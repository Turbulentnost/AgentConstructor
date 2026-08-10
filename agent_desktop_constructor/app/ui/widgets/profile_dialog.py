"""Диалог профиля: ФИО/подразделение read-only, email и аватарка редактируемые."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from agent_desktop_constructor.app.auth.client import (
    AuthClient,
    AuthClientError,
    AuthSession,
    save_session,
)


class ProfileDialog(QDialog):
    """Редактирование профиля текущего пользователя."""

    def __init__(self, session: AuthSession, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Мой профиль")
        self.resize(480, 320)
        self.session = session
        self._client = AuthClient(session.proxy_url or "")

        self.avatar_label = QLabel()
        self.avatar_label.setFixedSize(72, 72)
        self.avatar_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.avatar_label.setStyleSheet(
            "background:#2a2a4a; color:#c8cbff; border-radius:36px; font-weight:700;"
        )
        self._set_initials_avatar()

        upload_btn = QPushButton("Загрузить аватарку")
        upload_btn.clicked.connect(self._upload_avatar)

        avatar_row = QHBoxLayout()
        avatar_row.addWidget(self.avatar_label)
        avatar_row.addWidget(upload_btn)
        avatar_row.addStretch(1)

        self.name_edit = QLineEdit(session.user.display_name)
        self.name_edit.setReadOnly(True)
        self.dept_edit = QLineEdit(session.user.department)
        self.dept_edit.setReadOnly(True)
        self.email_edit = QLineEdit(session.user.email)

        form = QFormLayout()
        form.addRow("ФИО", self.name_edit)
        form.addRow("Подразделение", self.dept_edit)
        form.addRow("Email", self.email_edit)

        note = QLabel("ФИО и подразделение синхронизируются из 1С и недоступны для изменения.")
        note.setWordWrap(True)
        note.setStyleSheet("color:#8a8fa3;")

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Close
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Сохранить email")
        buttons.accepted.connect(self._save_email)
        buttons.rejected.connect(self.reject)

        root = QVBoxLayout(self)
        root.addLayout(avatar_row)
        root.addLayout(form)
        root.addWidget(note)
        root.addWidget(buttons)

        self._refresh_from_server()
        self._load_avatar()

    def _refresh_from_server(self) -> None:
        """Подтянуть ФИО/подразделение/email из API (после sync из 1С)."""
        try:
            user = self._client.me(self.session.access_token)
        except Exception:
            return
        self.session.user = user
        save_session(self.session)
        self.name_edit.setText(user.display_name)
        self.dept_edit.setText(user.department)
        self.email_edit.setText(user.email)

    def _set_initials_avatar(self) -> None:
        parts = [p for p in self.session.user.display_name.split() if p]
        initials = "".join(p[0] for p in parts[:2]).upper() or "?"
        self.avatar_label.setText(initials)
        self.avatar_label.setPixmap(QPixmap())

    def _load_avatar(self) -> None:
        if not self.session.user.has_avatar:
            return
        try:
            data = self._client.fetch_avatar(self.session.access_token)
        except Exception:
            return
        if not data:
            return
        pix = QPixmap()
        if pix.loadFromData(data):
            self.avatar_label.setPixmap(
                pix.scaled(
                    72,
                    72,
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            self.avatar_label.setText("")

    def _upload_avatar(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Выберите изображение",
            "",
            "Images (*.png *.jpg *.jpeg *.webp *.gif)",
        )
        if not path:
            return
        try:
            user = self._client.upload_avatar(self.session.access_token, Path(path))
            self.session.user = user
            save_session(self.session)
            self._load_avatar()
            QMessageBox.information(self, "Профиль", "Аватарка обновлена")
        except AuthClientError as exc:
            QMessageBox.critical(self, "Профиль", str(exc))

    def _save_email(self) -> None:
        email = self.email_edit.text().strip()
        try:
            user = self._client.patch_email(self.session.access_token, email)
            self.session.user = user
            save_session(self.session)
            QMessageBox.information(self, "Профиль", "Email сохранён")
            self.accept()
        except AuthClientError as exc:
            QMessageBox.critical(self, "Профиль", str(exc))
