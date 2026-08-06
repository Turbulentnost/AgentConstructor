"""Экран входа по учётной записи 1С — в стиле основного приложения."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from agent_desktop_constructor.app.auth.client import (
    AuthClient,
    AuthClientError,
    AuthDirectoryUser,
    AuthSession,
    clear_session,
    save_session,
)
from agent_desktop_constructor.app.auth.login_prefs import (
    LoginPrefs,
    load_login_prefs,
    save_login_prefs,
)

_BG = "#0B0B14"
_CARD = "#161625"
_ACCENT = "#5856D6"
_TEXT = "#e8eaf2"
_MUTED = "#8a8fa3"
_BORDER = "#2a2a3d"
_INPUT_BG = "#0f0f1a"
_POPUP_MAX_HEIGHT = 260


class LoginDialog(QDialog):
    """Полноразмерный экран логина с выпадающим поиском пользователей."""

    authenticated = Signal()

    def __init__(self, proxy_url: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Конструктор ИИ-агентов")
        self.setModal(True)
        self.setMinimumSize(1280, 820)
        self.resize(1280, 820)
        self._proxy_url = proxy_url.rstrip("/")
        self.session: AuthSession | None = None
        self._prefs = load_login_prefs()
        self._all_users: list[AuthDirectoryUser] = []
        self._selected_login = ""
        self._suppress_popup = False
        self._users_load_started = False

        self.setObjectName("loginRoot")
        self.setStyleSheet(
            f"#loginRoot {{ background: {_BG}; }}"
            f"#loginCard {{ background: {_CARD}; border: 1px solid {_BORDER};"
            f"border-radius: 16px; }}"
            f"#loginBrand {{ color: {_TEXT}; font-size: 28px; font-weight: 800; }}"
            f"#loginTitle {{ color: {_TEXT}; font-size: 22px; font-weight: 800; }}"
            f"#loginHint {{ color: {_MUTED}; font-size: 13px; }}"
            f"#loginFieldLabel {{ color: {_MUTED}; font-size: 12px; font-weight: 600; }}"
            f"QLineEdit {{ background: {_INPUT_BG}; color: {_TEXT};"
            f"border: 1px solid {_BORDER}; border-radius: 10px; padding: 12px 14px;"
            f"font-size: 14px; selection-background-color: {_ACCENT}; }}"
            f"QLineEdit:focus {{ border: 1px solid {_ACCENT}; }}"
            f"#loginUsersPopup {{ background: {_INPUT_BG}; color: {_TEXT};"
            f"border: 1px solid {_BORDER}; border-radius: 10px; padding: 4px;"
            f"outline: none; font-size: 13px; }}"
            f"#loginUsersPopup::item {{ padding: 10px 12px; border-radius: 8px; }}"
            f"#loginUsersPopup::item:selected {{ background: {_ACCENT}; color: white; }}"
            f"#loginUsersPopup::item:hover {{ background: #22223a; }}"
            f"QCheckBox {{ color: {_MUTED}; font-size: 13px; spacing: 8px; }}"
            f"QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px;"
            f"border: 1px solid {_BORDER}; background: {_INPUT_BG}; }}"
            f"QCheckBox::indicator:checked {{ background: {_ACCENT}; border-color: {_ACCENT}; }}"
            f"#loginPrimary {{ background: {_ACCENT}; color: white; border: none;"
            f"border-radius: 12px; padding: 12px 22px; font-size: 14px; font-weight: 700; }}"
            "#loginPrimary:hover { background: #6a68e0; }"
            f"#loginSecondary {{ background: transparent; color: {_TEXT};"
            f"border: 1px solid {_BORDER}; border-radius: 12px; padding: 12px 22px;"
            f"font-size: 14px; font-weight: 600; }}"
            f"#loginSecondary:hover {{ border-color: {_MUTED}; }}"
            f"#loginStatus {{ color: {_MUTED}; font-size: 12px; }}"
            f"#loginLoadingTitle {{ color: {_TEXT}; font-size: 22px; font-weight: 800; }}"
            f"#loginLoadingHint {{ color: {_MUTED}; font-size: 14px; }}"
            f"QProgressBar {{ background: {_INPUT_BG}; border: 1px solid {_BORDER};"
            f"border-radius: 8px; height: 10px; text-align: center; }}"
            f"QProgressBar::chunk {{ background: {_ACCENT}; border-radius: 7px; }}"
        )

        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_login_page())
        self._stack.addWidget(self._build_loading_page())

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._stack)

        self._filter_timer = QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(120)
        self._filter_timer.timeout.connect(self._on_filter_timeout)

        self.login_edit.installEventFilter(self)
        self.login_edit.textChanged.connect(self._on_login_text_changed)

        if self._prefs.remember and self._prefs.login:
            self.password_edit.setFocus()
        else:
            self.login_edit.setFocus()

    def _build_login_page(self) -> QWidget:
        brand = QLabel("Конструктор ИИ-агентов")
        brand.setObjectName("loginBrand")
        brand.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        card = QFrame()
        card.setObjectName("loginCard")
        card.setMaximumWidth(560)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(32, 32, 32, 32)
        card_layout.setSpacing(12)

        title = QLabel("Вход")
        title.setObjectName("loginTitle")
        hint = QLabel(
            "Нажмите на поле поиска — появится список пользователей. "
            "Начните вводить ФИО/логин для фильтра, затем введите пароль 1С."
        )
        hint.setObjectName("loginHint")
        hint.setWordWrap(True)

        login_label = QLabel("Поиск: логин или ФИО")
        login_label.setObjectName("loginFieldLabel")
        self.login_edit = QLineEdit()
        self.login_edit.setPlaceholderText("Начните вводить фамилию или логин…")
        if self._prefs.remember and self._prefs.login:
            self.login_edit.setText(self._prefs.login)
            self._selected_login = self._prefs.login

        # Выпадающий список — отдельное popup-окно, не участвует в layout.
        self.users_list = QListWidget(self)
        self.users_list.setObjectName("loginUsersPopup")
        self.users_list.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.users_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.users_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.users_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.users_list.setMouseTracking(True)
        self.users_list.hide()
        self.users_list.itemClicked.connect(self._on_user_clicked)

        password_label = QLabel("Пароль")
        password_label.setObjectName("loginFieldLabel")
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_edit.setPlaceholderText("Пароль 1С")
        self.password_edit.returnPressed.connect(self._on_accept)
        self.password_edit.installEventFilter(self)

        self.remember_checkbox = QCheckBox("Запомнить пользователя")
        self.remember_checkbox.setChecked(self._prefs.remember)

        self.status_label = QLabel("Загрузка пользователей…")
        self.status_label.setObjectName("loginStatus")
        self.status_label.setWordWrap(True)

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        self.cancel_button = QPushButton("Выход")
        self.cancel_button.setObjectName("loginSecondary")
        self.cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_button.clicked.connect(self.reject)
        self.login_button = QPushButton("Войти")
        self.login_button.setObjectName("loginPrimary")
        self.login_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.login_button.clicked.connect(self._on_accept)
        buttons.addWidget(self.cancel_button)
        buttons.addStretch(1)
        buttons.addWidget(self.login_button)

        card_layout.addWidget(title)
        card_layout.addWidget(hint)
        card_layout.addSpacing(4)
        card_layout.addWidget(login_label)
        card_layout.addWidget(self.login_edit)
        card_layout.addWidget(password_label)
        card_layout.addWidget(self.password_edit)
        card_layout.addWidget(self.remember_checkbox)
        card_layout.addWidget(self.status_label)
        card_layout.addSpacing(8)
        card_layout.addLayout(buttons)

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.addStretch(1)
        layout.addWidget(brand)
        layout.addSpacing(20)
        layout.addWidget(card, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch(2)
        return page

    def _build_loading_page(self) -> QWidget:
        brand = QLabel("Конструктор ИИ-агентов")
        brand.setObjectName("loginBrand")
        brand.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        card = QFrame()
        card.setObjectName("loginCard")
        card.setMaximumWidth(480)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(36, 36, 36, 36)
        card_layout.setSpacing(14)

        self._loading_title = QLabel("Загрузка")
        self._loading_title.setObjectName("loginLoadingTitle")
        self._loading_title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self._loading_hint = QLabel("Подготовка интерфейса…")
        self._loading_hint.setObjectName("loginLoadingHint")
        self._loading_hint.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self._loading_hint.setWordWrap(True)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setTextVisible(False)
        self._progress.setFixedHeight(10)

        card_layout.addWidget(self._loading_title)
        card_layout.addWidget(self._loading_hint)
        card_layout.addSpacing(8)
        card_layout.addWidget(self._progress)

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.addStretch(1)
        layout.addWidget(brand)
        layout.addSpacing(20)
        layout.addWidget(card, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch(2)
        return page

    def show_login_form(self) -> None:
        """Показать форму входа."""
        self._stack.setCurrentIndex(0)
        self._hide_users_popup()
        if not self._users_load_started:
            QTimer.singleShot(0, self._load_users)

    def show_loading(self, message: str = "Загрузка приложения…") -> None:
        """Показать экран загрузки в том же окне (без закрытия)."""
        self._hide_users_popup()
        self._loading_hint.setText(message)
        self._stack.setCurrentIndex(1)

    def eventFilter(self, watched, event):  # noqa: N802
        if watched is self.login_edit:
            if event.type() in (
                QEvent.Type.MouseButtonPress,
                QEvent.Type.FocusIn,
            ):
                QTimer.singleShot(0, self._show_users_popup)
            elif event.type() == QEvent.Type.KeyPress and isinstance(event, QKeyEvent):
                if event.key() == Qt.Key.Key_Escape:
                    self._hide_users_popup()
                elif event.key() in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                    self._show_users_popup()
                    self._move_popup_selection(event.key() == Qt.Key.Key_Down)
                    return True
                elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    if self.users_list.isVisible() and self.users_list.currentItem():
                        self._on_user_clicked(self.users_list.currentItem())
                        return True
        if watched is self.password_edit and event.type() == QEvent.Type.FocusIn:
            self._hide_users_popup()
        return super().eventFilter(watched, event)

    def _load_users(self) -> None:
        if self._stack.currentIndex() != 0:
            return
        self._users_load_started = True
        if not self._proxy_url:
            self.status_label.setText("Не задан llm_proxy_url в настройках.")
            return
        self.status_label.setText("Загрузка пользователей из 1С…")
        try:
            client = AuthClient(self._proxy_url)
            self._all_users = client.list_users(limit=2000)
        except AuthClientError as exc:
            self._all_users = []
            self.status_label.setText(str(exc))
            return
        except Exception as exc:
            self._all_users = []
            self.status_label.setText(f"Не удалось загрузить пользователей: {exc}")
            return
        if self._all_users:
            self.status_label.setText(f"Найдено пользователей: {len(self._all_users)}")
        else:
            self.status_label.setText("Список пользователей пуст.")

    def _on_login_text_changed(self, _text: str) -> None:
        if self._suppress_popup:
            return
        self._selected_login = ""
        self._filter_timer.start()

    def _on_filter_timeout(self) -> None:
        self._apply_filter()
        if self.login_edit.hasFocus():
            self._show_users_popup()

    def _apply_filter(self) -> None:
        needle = " ".join(self.login_edit.text().strip().split()).casefold()
        self.users_list.clear()
        matched = 0
        for user in self._all_users:
            haystack = " ".join(
                [user.login, user.display_name, user.department]
            ).casefold()
            if needle and needle not in haystack:
                continue
            item = QListWidgetItem(user.label)
            item.setData(Qt.ItemDataRole.UserRole, user)
            self.users_list.addItem(item)
            matched += 1
        if self._all_users:
            if needle:
                self.status_label.setText(
                    f"Совпадений: {matched} из {len(self._all_users)}"
                )
            else:
                self.status_label.setText(
                    f"Найдено пользователей: {len(self._all_users)}"
                )

    def _popup_height(self) -> int:
        count = self.users_list.count()
        if count <= 0:
            return 0
        row = max(self.users_list.sizeHintForRow(0), 36)
        return min(_POPUP_MAX_HEIGHT, row * min(count, 7) + 10)

    def _show_users_popup(self) -> None:
        if self._suppress_popup or not self.login_edit.isEnabled():
            return
        if self._stack.currentIndex() != 0:
            return
        self._apply_filter()
        if self.users_list.count() == 0:
            self._hide_users_popup()
            return
        height = self._popup_height()
        width = max(self.login_edit.width(), 280)
        self.users_list.setFixedSize(width, height)
        below = self.login_edit.mapToGlobal(QPoint(0, self.login_edit.height() + 4))
        self.users_list.move(below)
        self.users_list.show()
        self.users_list.raise_()

    def _hide_users_popup(self) -> None:
        if self.users_list.isVisible():
            self.users_list.hide()

    def _move_popup_selection(self, down: bool) -> None:
        if self.users_list.count() == 0:
            return
        row = self.users_list.currentRow()
        if row < 0:
            row = 0 if down else self.users_list.count() - 1
        else:
            row = row + (1 if down else -1)
            row = max(0, min(self.users_list.count() - 1, row))
        self.users_list.setCurrentRow(row)

    def _on_user_clicked(self, item: QListWidgetItem) -> None:
        user = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(user, AuthDirectoryUser):
            return
        self._selected_login = user.login or user.display_name
        self._suppress_popup = True
        self.login_edit.blockSignals(True)
        self.login_edit.setText(user.display_name or user.login)
        self.login_edit.blockSignals(False)
        self._suppress_popup = False
        self._hide_users_popup()
        self.password_edit.setFocus()

    def _resolve_login(self) -> str:
        if self._selected_login.strip():
            return self._selected_login.strip()
        return self.login_edit.text().strip()

    def _on_accept(self) -> None:
        self._hide_users_popup()
        login = self._resolve_login()
        password = self.password_edit.text()
        if not login or not password:
            QMessageBox.warning(
                self,
                "Вход",
                "Выберите пользователя из списка (или введите ФИО/логин) и укажите пароль.",
            )
            return
        if not self._proxy_url:
            QMessageBox.critical(
                self,
                "Вход",
                "Не задан llm_proxy_url. Укажите его в настройках/settings.json.",
            )
            return

        self._set_busy(True)
        self.status_label.setText("Проверка учётной записи…")
        try:
            client = AuthClient(self._proxy_url)
            self.session = client.login(login, password)
            remember = self.remember_checkbox.isChecked()
            save_login_prefs(
                LoginPrefs(
                    remember=remember,
                    login=login if remember else "",
                )
            )
            if remember:
                save_session(self.session)
            else:
                clear_session()
        except AuthClientError as exc:
            self.status_label.setText("")
            QMessageBox.critical(self, "Ошибка входа", str(exc))
            return
        except Exception as exc:
            self.status_label.setText("")
            QMessageBox.critical(
                self,
                "Ошибка входа",
                f"Не удалось связаться с сервером:\n{exc}",
            )
            return
        finally:
            self._set_busy(False)

        # Не закрываем окно: показываем загрузку, пока стартует MainWindow.
        self.show_loading("Загрузка конструктора…")
        self.authenticated.emit()

    def _set_busy(self, busy: bool) -> None:
        self.login_button.setEnabled(not busy)
        self.cancel_button.setEnabled(not busy)
        self.login_edit.setEnabled(not busy)
        self.password_edit.setEnabled(not busy)
        self.remember_checkbox.setEnabled(not busy)
        if busy:
            self._hide_users_popup()
