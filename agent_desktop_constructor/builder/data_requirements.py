"""Анализ требований к данным для построения AgentSpec."""

from agent_desktop_constructor.builder.graph_templates import AgentTemplateName
from agent_desktop_constructor.core.models.agent_spec import AgentDataRequirement


class DataRequirementAnalyzer:
    """Определяет data_requirements по запросу пользователя и шаблону агента."""

    _SEND_INTENT_KEYWORDS = (
        "отправь",
        "отправлять",
        "пришли",
        "выслать",
        "отчёт руководителю",
        "отчет руководителю",
        "по почте",
        "на почту",
        "email",
        "e-mail",
    )

    def analyze(
        self,
        user_request: str,
        template_name: str,
    ) -> list[AgentDataRequirement]:
        """Вернуть требования к данным для выбранного шаблона агента."""
        normalized_request = self._normalize_request(user_request)
        if not normalized_request:
            raise ValueError("user_request не должен быть пустым")

        normalized_template_name = template_name.strip()
        if not normalized_template_name:
            raise ValueError("template_name не должен быть пустым")

        try:
            template = AgentTemplateName(normalized_template_name)
        except ValueError:
            template = AgentTemplateName.GENERIC_AGENT

        if template == AgentTemplateName.TASK_CONTROL_AGENT:
            return self._requirements_for_task_control(normalized_request)
        if template == AgentTemplateName.MEETING_AGENT:
            return self._requirements_for_meeting_agent(normalized_request)
        if template == AgentTemplateName.DOCUMENT_ANALYSIS_AGENT:
            return self._requirements_for_document_analysis(normalized_request)
        return self._requirements_for_generic(normalized_request)

    def _normalize_request(self, user_request: str) -> str:
        """Нормализовать пользовательский запрос для эвристического анализа."""
        return user_request.strip().casefold()

    def _has_send_intent(self, normalized_request: str) -> bool:
        """Определить, просит ли пользователь отправить результат."""
        return any(keyword in normalized_request for keyword in self._SEND_INTENT_KEYWORDS)

    def _requirements_for_task_control(
        self,
        normalized_request: str,
    ) -> list[AgentDataRequirement]:
        """Вернуть требования к данным для агента контроля поручений."""
        has_send_intent = self._has_send_intent(normalized_request)
        return [
            AgentDataRequirement(
                name="analysis_period",
                description="Период, за который агент должен анализировать поручения.",
                source_type="user_or_default",
                required=True,
                can_agent_find=False,
                default_value="последние 7 дней",
                ask_human_if_missing=False,
            ),
            AgentDataRequirement(
                name="mail_source",
                description="Источник писем для поиска поручений.",
                source_type="outlook",
                required=True,
                can_agent_find=True,
                default_value="Outlook Inbox",
                ask_human_if_missing=False,
            ),
            AgentDataRequirement(
                name="calendar_source",
                description="Источник календаря для поиска встреч, где могли появиться поручения.",
                source_type="outlook_calendar",
                required=False,
                can_agent_find=True,
                default_value="Outlook Calendar",
                ask_human_if_missing=False,
            ),
            AgentDataRequirement(
                name="task_source",
                description="Источник существующих задач пользователя.",
                source_type="outlook_tasks",
                required=False,
                can_agent_find=True,
                default_value="Outlook Tasks",
                ask_human_if_missing=False,
            ),
            AgentDataRequirement(
                name="report_format",
                description="Формат итогового отчёта по поручениям.",
                source_type="user_or_default",
                required=True,
                can_agent_find=False,
                default_value="таблица + краткая сводка",
                ask_human_if_missing=False,
            ),
            AgentDataRequirement(
                name="report_recipient",
                description="Получатель отчёта, если пользователь хочет отправить отчёт по почте.",
                source_type="user",
                required=False,
                can_agent_find=False,
                default_value=None,
                ask_human_if_missing=has_send_intent,
            ),
            AgentDataRequirement(
                name="include_attachments",
                description="Нужно ли анализировать вложения писем при поиске поручений.",
                source_type="user_or_default",
                required=False,
                can_agent_find=False,
                default_value="false",
                ask_human_if_missing=False,
            ),
        ]

    def _requirements_for_meeting_agent(
        self,
        normalized_request: str,
    ) -> list[AgentDataRequirement]:
        """Вернуть требования к данным для агента по совещаниям."""
        return [
            AgentDataRequirement(
                name="meeting_period",
                description="Период поиска встреч",
                source_type="user_or_default",
                required=True,
                can_agent_find=False,
                default_value="сегодня",
                ask_human_if_missing=False,
            ),
            AgentDataRequirement(
                name="calendar_source",
                description="Источник календаря",
                source_type="outlook_calendar",
                required=True,
                can_agent_find=True,
                default_value="Outlook Calendar",
                ask_human_if_missing=False,
            ),
            AgentDataRequirement(
                name="meeting_identifier",
                description="Конкретная встреча или тема встречи",
                source_type="user",
                required=False,
                can_agent_find=True,
                default_value=None,
                ask_human_if_missing=False,
            ),
            AgentDataRequirement(
                name="output_format",
                description="Формат результата: повестка, протокол или сводка",
                source_type="user_or_default",
                required=True,
                can_agent_find=False,
                default_value="краткая сводка",
                ask_human_if_missing=False,
            ),
        ]

    def _requirements_for_document_analysis(
        self,
        normalized_request: str,
    ) -> list[AgentDataRequirement]:
        """Вернуть требования к данным для агента анализа документов."""
        return [
            AgentDataRequirement(
                name="document_source",
                description="Документ или папка, которые нужно проанализировать",
                source_type="file_or_knowledge_base",
                required=True,
                can_agent_find=True,
                default_value=None,
                ask_human_if_missing=True,
            ),
            AgentDataRequirement(
                name="analysis_goal",
                description="Цель анализа документа",
                source_type="user_or_default",
                required=True,
                can_agent_find=False,
                default_value="общий анализ документа",
                ask_human_if_missing=False,
            ),
            AgentDataRequirement(
                name="related_documents_source",
                description="Источник связанных документов",
                source_type="knowledge_base",
                required=False,
                can_agent_find=True,
                default_value="база знаний СМК",
                ask_human_if_missing=False,
            ),
            AgentDataRequirement(
                name="report_format",
                description="Формат отчёта по анализу документа",
                source_type="user_or_default",
                required=True,
                can_agent_find=False,
                default_value="структурированный отчёт",
                ask_human_if_missing=False,
            ),
        ]

    def _requirements_for_generic(
        self,
        normalized_request: str,
    ) -> list[AgentDataRequirement]:
        """Вернуть минимальные требования к данным для универсального агента."""
        return [
            AgentDataRequirement(
                name="user_goal",
                description="Цель, которую пользователь поставил агенту",
                source_type="user",
                required=True,
                can_agent_find=False,
                default_value=normalized_request,
                ask_human_if_missing=False,
            ),
            AgentDataRequirement(
                name="output_format",
                description="Формат результата",
                source_type="user_or_default",
                required=False,
                can_agent_find=False,
                default_value="текстовый ответ",
                ask_human_if_missing=False,
            ),
        ]
