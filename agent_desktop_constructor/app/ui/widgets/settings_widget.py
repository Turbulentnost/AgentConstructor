"""Страница настроек desktop UI."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from agent_desktop_constructor.app.core.app_mode import AppRunMode
from agent_desktop_constructor.app.core.config import AppConfig
from agent_desktop_constructor.app.core.settings import load_settings, save_settings
from agent_desktop_constructor.app.ui.helpers import show_error, show_info


class SettingsWidget(QWidget):
    """Редактор локальных настроек AppConfig."""

    def __init__(
        self,
        settings_path: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """Создать страницу настроек."""
        super().__init__(parent)
        self._settings_path = settings_path

        self.run_mode_combo = QComboBox()
        for mode in AppRunMode:
            self.run_mode_combo.addItem(mode.value, mode.value)

        self.database_path_edit = QLineEdit()
        self.choose_database_button = QPushButton("Выбрать файл")
        self.use_llm_planner_checkbox = QCheckBox()
        self.llm_base_url_edit = QLineEdit()
        self.llm_model_name_edit = QLineEdit()
        self.com_safe_mode_checkbox = QCheckBox()
        self.com_worker_timeout_spin = self._make_spinbox(1, 3600)
        self.outlook_mail_days_spin = self._make_spinbox(1, 3650)
        self.outlook_mail_max_results_spin = self._make_spinbox(1, 10000)
        self.outlook_calendar_days_forward_spin = self._make_spinbox(1, 3650)
        self.outlook_calendar_max_results_spin = self._make_spinbox(1, 10000)

        database_row = QHBoxLayout()
        database_row.addWidget(self.database_path_edit)
        database_row.addWidget(self.choose_database_button)

        form = QFormLayout()
        form.addRow("Режим запуска:", self.run_mode_combo)
        form.addRow("Путь к базе SQLite:", database_row)
        form.addRow("Использовать LLM Planner:", self.use_llm_planner_checkbox)
        form.addRow("LLM base_url:", self.llm_base_url_edit)
        form.addRow("LLM model_name:", self.llm_model_name_edit)
        form.addRow("COM safe mode:", self.com_safe_mode_checkbox)
        form.addRow("COM worker timeout:", self.com_worker_timeout_spin)
        form.addRow("Outlook mail days:", self.outlook_mail_days_spin)
        form.addRow("Outlook mail max results:", self.outlook_mail_max_results_spin)
        form.addRow(
            "Outlook calendar days forward:",
            self.outlook_calendar_days_forward_spin,
        )
        form.addRow(
            "Outlook calendar max results:",
            self.outlook_calendar_max_results_spin,
        )

        self.load_button = QPushButton("Загрузить")
        self.save_button = QPushButton("Сохранить")
        self.validate_button = QPushButton("Проверить настройки")
        self.reset_button = QPushButton("Сбросить по умолчанию")

        buttons = QHBoxLayout()
        buttons.addWidget(self.load_button)
        buttons.addWidget(self.save_button)
        buttons.addWidget(self.validate_button)
        buttons.addWidget(self.reset_button)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addLayout(buttons)

        self.choose_database_button.clicked.connect(self.choose_database_file)
        self.load_button.clicked.connect(self.load)
        self.save_button.clicked.connect(self.save)
        self.validate_button.clicked.connect(self.validate_settings)
        self.reset_button.clicked.connect(self.reset_defaults)
        self.set_config(AppConfig())

    def load(self) -> None:
        """Загрузить настройки из JSON."""
        try:
            self.set_config(load_settings(self._settings_path))
        except Exception as exc:
            show_error(self, "Ошибка загрузки настроек", exc)

    def save(self) -> None:
        """Сохранить настройки в JSON."""
        try:
            config = self.config_from_fields()
            self._validate_config(config)
            save_settings(config, self._settings_path)
        except Exception as exc:
            show_error(self, "Ошибка сохранения настроек", exc)
            return
        show_info(
            self,
            "Настройки сохранены",
            "Настройки сохранены. Перезапустите приложение, чтобы применить изменения.",
        )

    def validate_settings(self) -> None:
        """Выполнить только локальную проверку настроек."""
        try:
            config = self.config_from_fields()
            self._validate_config(config)
        except Exception as exc:
            show_error(self, "Настройки некорректны", exc)
            return
        show_info(self, "Настройки корректны", "Локальная проверка настроек пройдена.")

    def reset_defaults(self) -> None:
        """Сбросить поля на AppConfig() без сохранения."""
        self.set_config(AppConfig())

    def choose_database_file(self) -> None:
        """Выбрать путь к SQLite файлу."""
        selected, _ = QFileDialog.getSaveFileName(
            self,
            "Выберите файл SQLite",
            self.database_path_edit.text(),
            "SQLite DB (*.db);;All files (*.*)",
        )
        if selected:
            self.database_path_edit.setText(selected)

    def set_config(self, config: AppConfig) -> None:
        """Заполнить UI-поля из AppConfig."""
        index = self.run_mode_combo.findData(config.run_mode.value)
        self.run_mode_combo.setCurrentIndex(max(index, 0))
        self.database_path_edit.setText(config.database_path)
        self.use_llm_planner_checkbox.setChecked(config.use_llm_planner)
        self.llm_base_url_edit.setText(config.llm_base_url)
        self.llm_model_name_edit.setText(config.llm_model_name)
        self.com_safe_mode_checkbox.setChecked(config.com_safe_mode)
        self.com_worker_timeout_spin.setValue(config.com_worker_timeout_seconds)
        self.outlook_mail_days_spin.setValue(config.outlook_mail_days)
        self.outlook_mail_max_results_spin.setValue(config.outlook_mail_max_results)
        self.outlook_calendar_days_forward_spin.setValue(
            config.outlook_calendar_days_forward
        )
        self.outlook_calendar_max_results_spin.setValue(
            config.outlook_calendar_max_results
        )

    def config_from_fields(self) -> AppConfig:
        """Собрать AppConfig из UI-полей."""
        return AppConfig(
            run_mode=AppRunMode(self.run_mode_combo.currentData()),
            database_path=self.database_path_edit.text().strip(),
            use_llm_planner=self.use_llm_planner_checkbox.isChecked(),
            llm_base_url=self.llm_base_url_edit.text().strip(),
            llm_model_name=self.llm_model_name_edit.text().strip(),
            com_safe_mode=self.com_safe_mode_checkbox.isChecked(),
            com_worker_timeout_seconds=self.com_worker_timeout_spin.value(),
            outlook_mail_days=self.outlook_mail_days_spin.value(),
            outlook_mail_max_results=self.outlook_mail_max_results_spin.value(),
            outlook_calendar_days_forward=(
                self.outlook_calendar_days_forward_spin.value()
            ),
            outlook_calendar_max_results=self.outlook_calendar_max_results_spin.value(),
        )

    def _validate_config(self, config: AppConfig) -> None:
        """Локально проверить настройки без COM и HTTP."""
        if not config.database_path.strip():
            raise ValueError("database_path не должен быть пустым")
        if config.com_worker_timeout_seconds <= 0:
            raise ValueError("com_worker_timeout_seconds должен быть больше 0")
        if config.use_llm_planner:
            if not config.llm_base_url.strip():
                raise ValueError("llm_base_url не должен быть пустым для LLM Planner")
            if not config.llm_model_name.strip():
                raise ValueError("llm_model_name не должен быть пустым для LLM Planner")

    def _make_spinbox(self, minimum: int, maximum: int) -> QSpinBox:
        """Создать числовое поле."""
        spinbox = QSpinBox()
        spinbox.setRange(minimum, maximum)
        return spinbox

