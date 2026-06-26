"""Конструктор проверяемой спецификации агента из пользовательского запроса."""

from uuid import uuid4

from agent_desktop_constructor.app.llm.models import LLMPlanningResult
from agent_desktop_constructor.builder.data_requirements import DataRequirementAnalyzer
from agent_desktop_constructor.builder.graph_templates import (
    AgentTemplateName,
    get_graph_template,
)
from agent_desktop_constructor.builder.template_selector import TemplateSelector
from agent_desktop_constructor.core.models.agent_spec import (
    AgentActionLevel,
    AgentDataRequirement,
    AgentGoal,
    AgentRuntimeLimits,
    AgentSpec,
    AgentToolPermission,
)
from agent_desktop_constructor.core.models.tooling import ToolSideEffectLevel
from agent_desktop_constructor.tools.catalog import (
    ToolsCatalog,
    validate_agent_spec_tools_against_catalog,
)
from agent_desktop_constructor.tools.catalog_loader import load_tools_catalog


class AgentBuilder:
    """Собирает AgentSpec из текста пользователя без исполнения агента."""

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

    def __init__(
        self,
        template_selector: TemplateSelector | None = None,
        data_requirement_analyzer: DataRequirementAnalyzer | None = None,
        tools_catalog: ToolsCatalog | None = None,
        llm_planner: object | None = None,
        use_llm_planner: bool = False,
    ) -> None:
        """Создать AgentBuilder с переданными или дефолтными зависимостями."""
        self._template_selector = template_selector or TemplateSelector()
        self._data_requirement_analyzer = (
            data_requirement_analyzer or DataRequirementAnalyzer()
        )
        self.tools_catalog = tools_catalog or load_tools_catalog()
        self._llm_planner = llm_planner
        self._use_llm_planner = use_llm_planner

    def build_from_request(self, user_request: str) -> AgentSpec:
        """Построить валидный AgentSpec из пользовательского запроса."""
        normalized_request = user_request.strip()
        if not normalized_request:
            raise ValueError("user_request не должен быть пустым")

        template_name = self._template_selector.select_template(normalized_request)
        llm_planning_result = self._plan_with_llm_if_enabled(
            normalized_request,
            template_name,
        )
        graph_nodes = get_graph_template(template_name)
        data_requirements = self._data_requirement_analyzer.analyze(
            normalized_request,
            template_name,
        )
        if (
            llm_planning_result is not None
            and llm_planning_result.needs_human_or_new_tool
        ):
            data_requirements.append(self._build_new_tool_or_human_requirement())

        agent_spec = AgentSpec(
            agent_id=str(uuid4()),
            name=self._build_agent_name(template_name, normalized_request),
            description=self._build_agent_description(
                template_name,
                normalized_request,
            ),
            goal=self._build_goal(normalized_request, template_name),
            data_requirements=data_requirements,
            tools=self._build_tools(template_name, normalized_request),
            graph_nodes=graph_nodes,
            runtime_limits=self._build_runtime_limits(template_name),
        )
        validate_agent_spec_tools_against_catalog(agent_spec, self.tools_catalog)
        return agent_spec

    def _plan_with_llm_if_enabled(
        self,
        normalized_request: str,
        template_name: str,
    ) -> LLMPlanningResult | None:
        """Получить LLM-подсказку, не доверяя ей построение AgentSpec."""
        if not self._use_llm_planner:
            return None
        if self._llm_planner is None:
            raise ValueError("use_llm_planner=True требует llm_planner")

        planning_result = self._llm_planner.plan(normalized_request, template_name)
        self._validate_llm_selected_tools(planning_result)
        return planning_result

    def _validate_llm_selected_tools(
        self,
        planning_result: LLMPlanningResult,
    ) -> None:
        """Повторно проверить tool_name из LLMPlanningResult через ToolsCatalog."""
        self.tools_catalog.validate_tool_names(
            [tool.tool_name for tool in planning_result.selected_tools]
        )

    def _build_new_tool_or_human_requirement(self) -> AgentDataRequirement:
        """Добавить требование, если LLM считает, что нужен человек или новый tool."""
        return AgentDataRequirement(
            name="new_tool_or_human_needed",
            description=(
                "Модель считает, что подходящего инструмента нет или нужно участие "
                "человека."
            ),
            source_type="human",
            required=True,
            can_agent_find=False,
            default_value=None,
            ask_human_if_missing=True,
        )

    def _build_goal(self, user_request: str, template_name: str) -> AgentGoal:
        """Сформировать цель агента для выбранного шаблона."""
        if template_name == AgentTemplateName.TASK_CONTROL_AGENT.value:
            return AgentGoal(
                main_goal="Найти поручения в Outlook и сформировать отчёт",
                success_criteria=[
                    "Проверены доступные источники поручений",
                    "Найдены кандидаты в поручения",
                    "Сформирован отчёт по поручениям",
                    "Спорные поручения переданы человеку на проверку при необходимости",
                ],
                forbidden_actions=[
                    "Не отправлять письма без подтверждения человека",
                    "Не удалять письма",
                    "Не изменять календарь без подтверждения человека",
                    "Не создавать задачи без подтверждения человека",
                ],
            )

        if template_name == AgentTemplateName.MEETING_AGENT.value:
            return AgentGoal(
                main_goal="Подготовить материалы по совещанию",
                success_criteria=[
                    "Найдена встреча или период встреч",
                    "Собран контекст совещания",
                    "Сформирована сводка, повестка или протокол",
                ],
                forbidden_actions=[
                    "Не отправлять приглашения без подтверждения человека",
                    "Не изменять календарь без подтверждения человека",
                ],
            )

        if template_name == AgentTemplateName.DOCUMENT_ANALYSIS_AGENT.value:
            return AgentGoal(
                main_goal="Проанализировать документ и подготовить отчёт",
                success_criteria=[
                    "Определён документ для анализа",
                    "Извлечён текст документа",
                    "Найдены связанные документы при необходимости",
                    "Сформирован отчёт анализа",
                ],
                forbidden_actions=[
                    "Не изменять утверждённые документы",
                    "Не утверждать документы",
                    "Не запускать согласование без подтверждения человека",
                ],
            )

        return AgentGoal(
            main_goal=user_request,
            success_criteria=["Сформирован результат по запросу пользователя"],
            forbidden_actions=[
                "Не выполнять опасные действия без подтверждения человека"
            ],
        )

    def _build_tools(
        self,
        template_name: str,
        user_request: str,
    ) -> list[AgentToolPermission]:
        """Подобрать разрешения инструментов для выбранного шаблона."""
        if template_name == AgentTemplateName.TASK_CONTROL_AGENT.value:
            return [
                self._build_tool_permission_from_catalog("outlook.search_mail"),
                self._build_tool_permission_from_catalog("outlook.read_calendar"),
                self._build_tool_permission_from_catalog("outlook.read_tasks"),
                self._build_tool_permission_from_catalog("report.build_task_report"),
                self._build_tool_permission_from_catalog("email.create_draft"),
                self._build_tool_permission_from_catalog(
                    "email.send",
                    allowed=self._has_send_intent(user_request),
                ),
            ]

        if template_name == AgentTemplateName.MEETING_AGENT.value:
            return [
                self._build_tool_permission_from_catalog("outlook.read_calendar"),
                self._build_tool_permission_from_catalog(
                    "report.build_meeting_summary"
                ),
                self._build_tool_permission_from_catalog("email.create_draft"),
                self._build_tool_permission_from_catalog("email.send", allowed=False),
            ]

        if template_name == AgentTemplateName.DOCUMENT_ANALYSIS_AGENT.value:
            return [
                self._build_tool_permission_from_catalog("filesystem.search_files"),
                self._build_tool_permission_from_catalog("word.extract_text"),
                self._build_tool_permission_from_catalog("smk.search_documents"),
                self._build_tool_permission_from_catalog(
                    "report.build_document_analysis_report"
                ),
                self._build_tool_permission_from_catalog(
                    "document.approve", allowed=False
                ),
            ]

        return [
            self._build_tool_permission_from_catalog("llm.generate_text"),
        ]

    def _build_runtime_limits(self, template_name: str) -> AgentRuntimeLimits:
        """Сформировать runtime limits для выбранного шаблона."""
        if template_name == AgentTemplateName.TASK_CONTROL_AGENT.value:
            return AgentRuntimeLimits(
                max_steps=20,
                max_tool_calls=30,
                max_retries_per_tool=2,
                low_confidence_threshold=0.65,
            )
        if template_name == AgentTemplateName.MEETING_AGENT.value:
            return AgentRuntimeLimits(
                max_steps=15,
                max_tool_calls=20,
                max_retries_per_tool=2,
                low_confidence_threshold=0.65,
            )
        if template_name == AgentTemplateName.DOCUMENT_ANALYSIS_AGENT.value:
            return AgentRuntimeLimits(
                max_steps=25,
                max_tool_calls=40,
                max_retries_per_tool=2,
                low_confidence_threshold=0.7,
            )
        return AgentRuntimeLimits()

    def _build_agent_name(self, template_name: str, user_request: str) -> str:
        """Сформировать русское имя агента."""
        if template_name == AgentTemplateName.TASK_CONTROL_AGENT.value:
            return "Агент контроля поручений"
        if template_name == AgentTemplateName.MEETING_AGENT.value:
            return "Агент по совещаниям"
        if template_name == AgentTemplateName.DOCUMENT_ANALYSIS_AGENT.value:
            return "Агент анализа документов"
        return "Универсальный агент"

    def _build_agent_description(self, template_name: str, user_request: str) -> str:
        """Сформировать русское описание агента с исходным запросом."""
        if template_name == AgentTemplateName.TASK_CONTROL_AGENT.value:
            summary = (
                "Автоматически проверяет доступные источники, выделяет поручения "
                "и формирует отчёт."
            )
        elif template_name == AgentTemplateName.MEETING_AGENT.value:
            summary = (
                "Помогает подготовить материалы по встрече, повестку, сводку "
                "или протокол."
            )
        elif template_name == AgentTemplateName.DOCUMENT_ANALYSIS_AGENT.value:
            summary = (
                "Анализирует документ, ищет связанные материалы и формирует отчёт."
            )
        else:
            summary = "Выполняет общий пользовательский запрос в рамках AgentSpec."
        return f"{summary} Исходный запрос: {user_request}"

    def _has_send_intent(self, user_request: str) -> bool:
        """Определить намерение отправить результат по тексту запроса."""
        normalized_request = user_request.strip().casefold()
        return any(
            keyword in normalized_request for keyword in self._SEND_INTENT_KEYWORDS
        )

    def _tool(
        self,
        tool_name: str,
        action_level: AgentActionLevel,
        *,
        requires_human_approval: bool = False,
        allowed: bool = True,
    ) -> AgentToolPermission:
        """Создать разрешение инструмента для AgentSpec с проверкой по каталогу."""
        catalog_tool = self.tools_catalog.get_tool(tool_name)
        catalog_action_level = self._action_level_from_side_effect(
            catalog_tool.side_effect_level
        )
        if action_level != catalog_action_level:
            raise ValueError(
                f"action_level для {tool_name!r} должен быть "
                f"{catalog_action_level.value!r} из каталога"
            )
        if requires_human_approval != catalog_tool.requires_human_approval:
            raise ValueError(
                f"requires_human_approval для {tool_name!r} должен быть "
                f"{catalog_tool.requires_human_approval!r} из каталога"
            )
        return AgentToolPermission(
            tool_name=tool_name,
            action_level=action_level,
            requires_human_approval=requires_human_approval,
            allowed=allowed,
        )

    def _build_tool_permission_from_catalog(
        self,
        tool_name: str,
        allowed: bool = True,
    ) -> AgentToolPermission:
        """Создать разрешение инструмента на основе единого каталога."""
        catalog_tool = self.tools_catalog.get_tool(tool_name)
        return AgentToolPermission(
            tool_name=catalog_tool.name,
            action_level=self._action_level_from_side_effect(
                catalog_tool.side_effect_level
            ),
            requires_human_approval=catalog_tool.requires_human_approval,
            allowed=allowed,
        )

    def _action_level_from_side_effect(
        self,
        side_effect_level: ToolSideEffectLevel,
    ) -> AgentActionLevel:
        """Преобразовать риск инструмента из каталога в permission AgentSpec."""
        return AgentActionLevel(side_effect_level.value)
