"""Страница создания агента."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QHBoxLayout,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from agent_desktop_constructor.app.core.bootstrap import ApplicationContainer
from agent_desktop_constructor.app.ui.helpers import (
    format_json_preview,
    set_table_rows,
    show_error,
    show_info,
)
from agent_desktop_constructor.core.models.agent_spec import AgentSpec


class AgentCreateWidget(QWidget):
    """Создаёт preview AgentSpec и сохраняет агента через service-слой."""

    def __init__(
        self,
        container: ApplicationContainer,
        parent: QWidget | None = None,
    ) -> None:
        """Создать страницу создания агента."""
        super().__init__(parent)
        self._container = container
        self._preview_agent: AgentSpec | None = None

        self.request_edit = QTextEdit()
        self.request_edit.setPlaceholderText("Опишите, какого агента нужно создать...")
        self.preview_button = QPushButton("Предпросмотр")
        self.validate_button = QPushButton("Проверить агента")
        self.save_button = QPushButton("Сохранить")
        self.validate_run_button = QPushButton("Собрать, проверить и запустить")
        self.clear_button = QPushButton("Очистить")
        self.tabs = QTabWidget()
        self.general_output = QTextEdit()
        self.general_output.setReadOnly(True)
        self.data_table = QTableWidget()
        self.tools_table = QTableWidget()
        self.graph_table = QTableWidget()
        self.json_output = QTextEdit()
        self.json_output.setReadOnly(True)
        for table in [self.data_table, self.tools_table, self.graph_table]:
            table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.tabs.addTab(self.general_output, "Общее")
        self.tabs.addTab(self.data_table, "Данные")
        self.tabs.addTab(self.tools_table, "Инструменты")
        self.tabs.addTab(self.graph_table, "Граф")
        self.tabs.addTab(self.json_output, "JSON")

        buttons = QHBoxLayout()
        buttons.addWidget(self.preview_button)
        buttons.addWidget(self.validate_button)
        buttons.addWidget(self.save_button)
        buttons.addWidget(self.validate_run_button)
        buttons.addWidget(self.clear_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self.request_edit)
        layout.addLayout(buttons)
        layout.addWidget(self.tabs)

        self.preview_button.clicked.connect(self.build_preview)
        self.validate_button.clicked.connect(self.validate_agent)
        self.save_button.clicked.connect(self.save_agent)
        self.validate_run_button.clicked.connect(self.create_validate_and_run)
        self.clear_button.clicked.connect(self.clear)

    def build_preview(self) -> None:
        """Построить AgentSpec preview без сохранения и запуска."""
        user_request = self.request_edit.toPlainText().strip()
        if not user_request:
            show_error(self, "Пустой запрос", "Введите запрос для создания агента.")
            return

        try:
            self._preview_agent = self._container.agent_service.build_preview(
                user_request
            )
        except Exception as exc:
            show_error(self, "Ошибка предпросмотра", exc)
            return

        self._render_preview(self._preview_agent)

    def save_agent(self) -> None:
        """Сохранить preview или создать и сохранить агента из запроса."""
        user_request = self.request_edit.toPlainText().strip()
        if not user_request and self._preview_agent is None:
            show_error(self, "Пустой запрос", "Введите запрос для создания агента.")
            return

        try:
            if self._preview_agent is not None:
                agent_spec = self._preview_agent
                self._container.agent_service.save_agent(agent_spec)
            else:
                agent_spec = self._container.agent_service.create_agent_from_request(
                    user_request,
                    save=True,
                )
                self._preview_agent = agent_spec
                self._render_preview(agent_spec)
        except Exception as exc:
            show_error(self, "Ошибка сохранения агента", exc)
            return

        show_info(self, "Агент сохранён", f"Агент сохранён: {agent_spec.agent_id}")

    def validate_agent(self) -> None:
        """Построить preview и выполнить пробную проверку агента."""
        user_request = self.request_edit.toPlainText().strip()
        if not user_request and self._preview_agent is None:
            show_error(self, "Пустой запрос", "Введите запрос для создания агента.")
            return

        try:
            if self._preview_agent is None:
                self._preview_agent = self._container.agent_service.build_preview(
                    user_request
                )
                self._render_preview(self._preview_agent)
            validation = self._container.agent_service.validate_agent(
                self._preview_agent,
                user_request,
            )
        except Exception as exc:
            show_error(self, "Ошибка проверки агента", exc)
            return

        self.general_output.setPlainText(
            self._format_general(self._preview_agent)
            + "\n\n"
            + self._format_validation(validation)
        )
        show_info(self, "Проверка агента", validation.summary)

    def create_validate_and_run(self) -> None:
        """Собрать, проверить и запустить агента при успешной проверке."""
        user_request = self.request_edit.toPlainText().strip()
        if not user_request:
            show_error(self, "Пустой запрос", "Введите запрос для создания агента.")
            return

        try:
            agent_spec, validation, state = (
                self._container.agent_service.create_validate_and_run_once(user_request)
            )
            self._preview_agent = agent_spec
            self._render_preview(agent_spec)
        except Exception as exc:
            show_error(self, "Ошибка проверки и запуска", exc)
            return

        self.general_output.setPlainText(
            self._format_general(agent_spec) + "\n\n" + self._format_validation(validation)
        )
        if state is None:
            show_info(self, "Агент не запущен", validation.summary)
            return
        show_info(
            self,
            "Агент запущен",
            f"Проверка пройдена, run_id={state.run_id}, status={state.status.value}",
        )

    def clear(self) -> None:
        """Очистить запрос и preview."""
        self._preview_agent = None
        self.request_edit.clear()
        self.general_output.clear()
        self.json_output.clear()
        set_table_rows(self.data_table, [], self._data_headers())
        set_table_rows(self.tools_table, [], self._tool_headers())
        set_table_rows(self.graph_table, [], self._graph_headers())

    def _render_preview(self, agent_spec: AgentSpec) -> None:
        """Показать AgentSpec во вкладках."""
        self.general_output.setPlainText(self._format_general(agent_spec))
        set_table_rows(
            self.data_table,
            [
                [
                    item.name,
                    item.description,
                    item.required,
                    item.can_agent_find,
                    item.default_value,
                    item.ask_human_if_missing,
                ]
                for item in agent_spec.data_requirements
            ],
            self._data_headers(),
        )
        set_table_rows(
            self.tools_table,
            [
                [
                    tool.tool_name,
                    tool.action_level.value,
                    tool.requires_human_approval,
                    tool.allowed,
                ]
                for tool in agent_spec.tools
            ],
            self._tool_headers(),
        )
        set_table_rows(
            self.graph_table,
            [
                [
                    node.node_id,
                    node.node_type.value,
                    node.title,
                    node.tool_name,
                    node.next_on_success,
                    node.next_on_error,
                ]
                for node in agent_spec.graph_nodes
            ],
            self._graph_headers(),
        )
        self.json_output.setPlainText(
            format_json_preview(agent_spec.model_dump(mode="json"), max_chars=12000)
        )

    def _format_general(self, agent_spec: AgentSpec) -> str:
        """Сформировать общую вкладку AgentSpec."""
        lines = [
            f"Название: {agent_spec.name}",
            f"agent_id: {agent_spec.agent_id}",
            f"Описание: {agent_spec.description}",
            "",
            f"Цель: {agent_spec.goal.main_goal}",
            "Критерии успеха:",
            *[f"- {item}" for item in agent_spec.goal.success_criteria],
            "Запрещённые действия:",
            *[f"- {item}" for item in agent_spec.goal.forbidden_actions],
        ]
        return "\n".join(lines)

    def _format_validation(self, validation) -> str:
        """Сформировать текст результата пробной проверки."""
        lines = [
            "Проверка агента:",
            f"status: {validation.status.value}",
            f"run_id: {validation.run_id}",
            f"summary: {validation.summary}",
            "",
            "Итоговый вывод:",
            validation.final_message or "Итоговый вывод пока не сформирован.",
            "",
            "errors:",
            *[f"- {item}" for item in validation.errors],
            "critical_errors:",
            *[f"- {item}" for item in validation.critical_errors],
            "warnings:",
            *[f"- {item}" for item in validation.warnings],
            "suggested_fixes:",
            *[f"- {item}" for item in validation.suggested_fixes],
        ]
        if validation.tool_result_checks:
            lines.extend(["", "Проверка обязательных инструментов:"])
            for check in validation.tool_result_checks:
                lines.extend(
                    [
                        f"- tool_name: {check.get('tool_name')}",
                        f"  node_id: {check.get('node_id')}",
                        f"  critical: {check.get('critical')}",
                        f"  error_type: {check.get('error_type')}",
                        f"  error_message: {check.get('error_message')}",
                        f"  recommendation: {check.get('recommendation')}",
                    ]
                )
        if validation.output_data:
            lines.extend(
                [
                    "",
                    "Структурированный результат:",
                    format_json_preview(validation.output_data, max_chars=4000),
                ]
            )
        return "\n".join(lines)

    def _data_headers(self) -> list[str]:
        """Вернуть заголовки таблицы data requirements."""
        return [
            "name",
            "description",
            "required",
            "can_agent_find",
            "default_value",
            "ask_human_if_missing",
        ]

    def _tool_headers(self) -> list[str]:
        """Вернуть заголовки таблицы tools."""
        return ["tool_name", "action_level", "requires_human_approval", "allowed"]

    def _graph_headers(self) -> list[str]:
        """Вернуть заголовки таблицы graph."""
        return [
            "node_id",
            "node_type",
            "title",
            "tool_name",
            "next_on_success",
            "next_on_error",
        ]

