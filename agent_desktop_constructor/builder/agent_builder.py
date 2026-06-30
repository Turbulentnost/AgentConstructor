"""Конструктор проверяемой спецификации агента из пользовательского запроса."""

from uuid import uuid4

from agent_desktop_constructor.app.llm.agent_plan_models import LLMAgentPlan
from agent_desktop_constructor.builder.data_requirements import DataRequirementAnalyzer
from agent_desktop_constructor.builder.graph_templates import (
    AgentTemplateName,
    get_graph_template,
)
from agent_desktop_constructor.builder.template_selector import TemplateSelector
from agent_desktop_constructor.core.models.agent_spec import (
    AgentActionLevel,
    AgentDataRequirement,
    AgentGraphNode,
    AgentGraphNodeType,
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

        if self._use_llm_planner:
            llm_plan = self._plan_with_llm(normalized_request)
            return self._build_from_llm_plan(normalized_request, llm_plan)

        template_name = self._template_selector.select_template(normalized_request)
        graph_nodes = get_graph_template(template_name)
        data_requirements = self._data_requirement_analyzer.analyze(
            normalized_request,
            template_name,
        )

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

    def _plan_with_llm(
        self,
        normalized_request: str,
    ) -> LLMAgentPlan:
        """Получить LLM AgentPlan и проверить tool_name через ToolsCatalog."""
        if self._llm_planner is None:
            raise ValueError("use_llm_planner=True требует llm_planner")

        planning_result = self._llm_planner.plan(normalized_request, self.tools_catalog)
        if not isinstance(planning_result, LLMAgentPlan):
            raise TypeError("llm_planner должен возвращать LLMAgentPlan")
        self._validate_llm_plan_tools(planning_result)
        return planning_result

    def _validate_llm_plan_tools(
        self,
        planning_result: LLMAgentPlan,
    ) -> None:
        """Повторно проверить все tool_name из LLMAgentPlan через ToolsCatalog."""
        tool_names = [tool.tool_name for tool in planning_result.selected_tools]
        tool_names.extend(
            step.tool_name
            for step in planning_result.steps
            if step.tool_name is not None
        )
        self.tools_catalog.validate_tool_names(tool_names)

    def _build_from_llm_plan(
        self,
        user_request: str,
        plan: LLMAgentPlan,
    ) -> AgentSpec:
        """Построить AgentSpec из LLM-плана без template tools/graph."""
        data_requirements = self._build_llm_plan_data_requirements(plan)
        graph_nodes = self._build_graph_nodes_from_llm_plan(plan)
        agent_spec = AgentSpec(
            agent_id=str(uuid4()),
            name=plan.agent_name,
            description=f"AgentSpec построен из LLM AgentPlan. Исходный запрос: {user_request}",
            goal=AgentGoal(
                main_goal=plan.goal,
                success_criteria=["Выполнен LLM-план по запросу пользователя"],
                forbidden_actions=[
                    "Не выполнять инструменты вне ToolsCatalog",
                    "Не выполнять dangerous/write действия без подтверждения человека",
                    "LLM не вызывает инструменты напрямую",
                ],
            ),
            data_requirements=data_requirements,
            tools=self._build_tools_from_llm_plan(plan),
            graph_nodes=graph_nodes,
            runtime_limits=AgentRuntimeLimits(),
        )
        validate_agent_spec_tools_against_catalog(agent_spec, self.tools_catalog)
        return agent_spec

    def _build_llm_plan_data_requirements(
        self,
        plan: LLMAgentPlan,
    ) -> list[AgentDataRequirement]:
        """Преобразовать missing_data LLM-плана в требования к данным."""
        requirements = [
            AgentDataRequirement(
                name=f"missing_data_{index}",
                description=missing_item,
                source_type="human",
                required=True,
                can_agent_find=False,
                default_value=None,
                ask_human_if_missing=True,
            )
            for index, missing_item in enumerate(plan.missing_data, start=1)
        ]
        if plan.needs_human:
            requirements.append(self._build_new_tool_or_human_requirement())
        return requirements

    def _build_tools_from_llm_plan(
        self,
        plan: LLMAgentPlan,
    ) -> list[AgentToolPermission]:
        """Создать AgentSpec tools строго из выбранных LLM tool_name."""
        ordered_tool_names: list[str] = []
        for planned_tool in plan.selected_tools:
            if planned_tool.tool_name not in ordered_tool_names:
                ordered_tool_names.append(planned_tool.tool_name)
        for step in plan.steps:
            if step.tool_name is not None and step.tool_name not in ordered_tool_names:
                ordered_tool_names.append(step.tool_name)
        return [
            self._build_tool_permission_from_catalog(tool_name)
            for tool_name in ordered_tool_names
        ]

    def _build_graph_nodes_from_llm_plan(
        self,
        plan: LLMAgentPlan,
    ) -> list[AgentGraphNode]:
        """Построить линейный безопасный граф из шагов LLM-плана."""
        nodes = [
            AgentGraphNode(
                node_id=step.step_id,
                node_type=self._node_type_from_llm_step(step.step_type, step.tool_name),
                title=step.title,
                description=step.description,
                tool_name=step.tool_name,
                next_on_success=self._next_success_for_llm_step(plan, index),
                next_on_error=(
                    None
                    if self._node_type_from_llm_step(step.step_type, step.tool_name)
                    == AgentGraphNodeType.FINAL
                    else "final_failed"
                ),
                requires_human_approval=False,
            )
            for index, step in enumerate(plan.steps)
        ]
        if not any(node.node_id == "final" for node in nodes):
            nodes.append(
                AgentGraphNode(
                    node_id="final",
                    node_type=AgentGraphNodeType.FINAL,
                    title="Завершить работу",
                    description="Агент успешно завершил LLM-план.",
                    tool_name=None,
                    next_on_success=None,
                    next_on_error=None,
                    requires_human_approval=False,
                )
            )
        if not any(node.node_id == "final_failed" for node in nodes):
            nodes.append(
                AgentGraphNode(
                    node_id="final_failed",
                    node_type=AgentGraphNodeType.FINAL,
                    title="Завершить с ошибкой",
                    description="Агент завершил LLM-план с ошибкой.",
                    tool_name=None,
                    next_on_success=None,
                    next_on_error=None,
                    requires_human_approval=False,
                )
            )
        return nodes

    def _next_success_for_llm_step(
        self,
        plan: LLMAgentPlan,
        index: int,
    ) -> str | None:
        """Рассчитать next_on_success для линейного LLM-графа."""
        step = plan.steps[index]
        node_type = self._node_type_from_llm_step(step.step_type, step.tool_name)
        if node_type == AgentGraphNodeType.FINAL:
            return None
        if index + 1 < len(plan.steps):
            return plan.steps[index + 1].step_id
        return "final"

    def _node_type_from_llm_step(
        self,
        step_type: str,
        tool_name: str | None,
    ) -> AgentGraphNodeType:
        """Преобразовать step_type LLM в AgentGraphNodeType."""
        if tool_name is not None:
            return AgentGraphNodeType.TOOL_CALL
        normalized = step_type.strip().casefold()
        mapping = {
            "validation": AgentGraphNodeType.VALIDATION,
            "planning": AgentGraphNodeType.PLANNING,
            "data_search": AgentGraphNodeType.DATA_SEARCH,
            "analysis": AgentGraphNodeType.ANALYSIS,
            "routing": AgentGraphNodeType.ROUTING,
            "human_review": AgentGraphNodeType.HUMAN_REVIEW,
            "final": AgentGraphNodeType.FINAL,
        }
        return mapping.get(normalized, AgentGraphNodeType.PLANNING)

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
                main_goal="Проанализировать совещания и помочь распланировать график",
                success_criteria=[
                    "Собраны совещания из календаря Outlook",
                    "Оценена плотность графика и перегруженные интервалы",
                    "Найдены свободные окна для фокус-работы",
                    "Сформированы рекомендации по планированию дня или недели",
                ],
                forbidden_actions=[
                    "Не отправлять приглашения без подтверждения человека",
                    "Не изменять календарь без подтверждения человека",
                    "Не создавать и не переносить события календаря автоматически",
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
                self._build_tool_permission_from_catalog("onec.search_tasks"),
                self._build_tool_permission_from_catalog("onec.get_task_card"),
                self._build_tool_permission_from_catalog(
                    "llm.extract_structured_facts"
                ),
                self._build_tool_permission_from_catalog("llm.analyze_collected_data"),
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
                self._build_tool_permission_from_catalog("llm.analyze_collected_data"),
                self._build_tool_permission_from_catalog(
                    "report.build_meeting_summary"
                ),
                self._build_tool_permission_from_catalog(
                    "report.build_schedule_recommendations"
                ),
                self._build_tool_permission_from_catalog("email.create_draft"),
                self._build_tool_permission_from_catalog("email.send", allowed=False),
            ]

        if template_name == AgentTemplateName.DOCUMENT_ANALYSIS_AGENT.value:
            return [
                self._build_tool_permission_from_catalog("filesystem.search_files"),
                self._build_tool_permission_from_catalog("word.extract_text"),
                self._build_tool_permission_from_catalog("smk.search_documents"),
                self._build_tool_permission_from_catalog("onec.search_documents"),
                self._build_tool_permission_from_catalog("onec.get_document_card"),
                self._build_tool_permission_from_catalog("browser.search_web"),
                self._build_tool_permission_from_catalog("browser.open_page"),
                self._build_tool_permission_from_catalog(
                    "llm.extract_structured_facts"
                ),
                self._build_tool_permission_from_catalog("llm.compare_sources"),
                self._build_tool_permission_from_catalog("llm.analyze_collected_data"),
                self._build_tool_permission_from_catalog(
                    "report.build_document_analysis_report"
                ),
                self._build_tool_permission_from_catalog(
                    "document.approve", allowed=False
                ),
            ]

        return [
            self._build_tool_permission_from_catalog("browser.search_web"),
            self._build_tool_permission_from_catalog("browser.open_page"),
            self._build_tool_permission_from_catalog("llm.generate_text"),
            self._build_tool_permission_from_catalog("llm.analyze_collected_data"),
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
