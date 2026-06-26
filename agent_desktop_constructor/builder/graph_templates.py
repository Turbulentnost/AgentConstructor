"""Шаблоны графов агентов для Builder-слоя."""

from __future__ import annotations

from enum import StrEnum

from agent_desktop_constructor.core.models.agent_spec import (
    AgentGraphNode,
    AgentGraphNodeType,
)


class AgentTemplateName(StrEnum):
    """Имена типовых шаблонов графов агентов."""

    TASK_CONTROL_AGENT = "task_control_agent"
    MEETING_AGENT = "meeting_agent"
    DOCUMENT_ANALYSIS_AGENT = "document_analysis_agent"
    GENERIC_AGENT = "generic_agent"


def _node(
    node_id: str,
    node_type: AgentGraphNodeType,
    title: str,
    description: str,
    *,
    tool_name: str | None = None,
    next_on_success: str | None = None,
    next_on_error: str | None = None,
    requires_human_approval: bool = False,
) -> AgentGraphNode:
    """Создать узел шаблона графа."""
    return AgentGraphNode(
        node_id=node_id,
        node_type=node_type,
        title=title,
        description=description,
        tool_name=tool_name,
        next_on_success=next_on_success,
        next_on_error=next_on_error,
        requires_human_approval=requires_human_approval,
    )


def build_task_control_graph() -> list[AgentGraphNode]:
    """Построить граф агента контроля поручений."""
    return [
        _node(
            "validate_request",
            AgentGraphNodeType.VALIDATION,
            "Проверить запрос пользователя",
            "Проверяет, можно ли запустить агента контроля поручений.",
            next_on_success="resolve_period",
            next_on_error="final_failed",
        ),
        _node(
            "resolve_period",
            AgentGraphNodeType.PLANNING,
            "Определить период анализа",
            "Определяет период анализа поручений. Если пользователь не указал период, используется значение по умолчанию.",
            next_on_success="read_mail",
            next_on_error="final_failed",
        ),
        _node(
            "read_mail",
            AgentGraphNodeType.TOOL_CALL,
            "Прочитать письма Outlook",
            "Ищет письма, которые могут содержать поручения.",
            tool_name="outlook.search_mail",
            next_on_success="read_calendar",
            next_on_error="read_calendar",
        ),
        _node(
            "read_calendar",
            AgentGraphNodeType.TOOL_CALL,
            "Прочитать календарь Outlook",
            "Ищет встречи, где могли быть даны поручения.",
            tool_name="outlook.read_calendar",
            next_on_success="read_tasks",
            next_on_error="read_tasks",
        ),
        _node(
            "read_tasks",
            AgentGraphNodeType.TOOL_CALL,
            "Прочитать задачи Outlook",
            "Получает существующие задачи пользователя.",
            tool_name="outlook.read_tasks",
            next_on_success="extract_task_candidates",
            next_on_error="extract_task_candidates",
        ),
        _node(
            "extract_task_candidates",
            AgentGraphNodeType.ANALYSIS,
            "Извлечь кандидаты в поручения",
            "Анализирует найденные письма, встречи и задачи, выделяет возможные поручения.",
            next_on_success="analyze_confidence",
            next_on_error="final_failed",
        ),
        _node(
            "analyze_confidence",
            AgentGraphNodeType.ROUTING,
            "Оценить уверенность",
            "Определяет, достаточно ли уверенности в найденных поручениях или нужно показать их человеку.",
            next_on_success="human_review_if_needed",
            next_on_error="human_review_if_needed",
        ),
        _node(
            "human_review_if_needed",
            AgentGraphNodeType.HUMAN_REVIEW,
            "Проверка человеком при необходимости",
            "Показывает пользователю спорные поручения, если уверенность низкая.",
            next_on_success="build_report",
            next_on_error="build_report",
            requires_human_approval=True,
        ),
        _node(
            "build_report",
            AgentGraphNodeType.TOOL_CALL,
            "Сформировать отчёт по поручениям",
            "Формирует итоговый отчёт по найденным поручениям.",
            tool_name="report.build_task_report",
            next_on_success="final",
            next_on_error="final_failed",
        ),
        _node(
            "final",
            AgentGraphNodeType.FINAL,
            "Завершить работу",
            "Агент успешно завершил работу.",
        ),
        _node(
            "final_failed",
            AgentGraphNodeType.FINAL,
            "Завершить с ошибкой",
            "Агент завершил работу из-за ошибки.",
        ),
    ]


def build_meeting_agent_graph() -> list[AgentGraphNode]:
    """Построить граф агента по совещаниям."""
    return [
        _node(
            "validate_request",
            AgentGraphNodeType.VALIDATION,
            "Проверить запрос пользователя",
            "Проверяет, достаточно ли данных для работы с совещанием.",
            next_on_success="read_calendar",
            next_on_error="final_failed",
        ),
        _node(
            "read_calendar",
            AgentGraphNodeType.TOOL_CALL,
            "Прочитать календарь Outlook",
            "Ищет встречу или совещание в календаре пользователя.",
            tool_name="outlook.read_calendar",
            next_on_success="collect_meeting_context",
            next_on_error="final_failed",
        ),
        _node(
            "collect_meeting_context",
            AgentGraphNodeType.ANALYSIS,
            "Собрать контекст совещания",
            "Выделяет участников, тему, дату и доступные материалы совещания.",
            next_on_success="build_agenda_or_minutes",
            next_on_error="final_failed",
        ),
        _node(
            "build_agenda_or_minutes",
            AgentGraphNodeType.TOOL_CALL,
            "Подготовить повестку или протокол",
            "Формирует краткую повестку, итоги или протокол совещания.",
            tool_name="report.build_meeting_summary",
            next_on_success="final",
            next_on_error="final_failed",
        ),
        _node(
            "final",
            AgentGraphNodeType.FINAL,
            "Завершить работу",
            "Агент успешно завершил работу с совещанием.",
        ),
        _node(
            "final_failed",
            AgentGraphNodeType.FINAL,
            "Завершить с ошибкой",
            "Агент завершил работу с совещанием из-за ошибки.",
        ),
    ]


def build_document_analysis_graph() -> list[AgentGraphNode]:
    """Построить граф агента анализа документов СМК."""
    return [
        _node(
            "validate_request",
            AgentGraphNodeType.VALIDATION,
            "Проверить запрос пользователя",
            "Проверяет, можно ли запустить анализ документа.",
            next_on_success="resolve_document_source",
            next_on_error="final_failed",
        ),
        _node(
            "resolve_document_source",
            AgentGraphNodeType.PLANNING,
            "Определить источник документа",
            "Определяет, где искать документ для анализа.",
            next_on_success="search_document_file",
            next_on_error="final_failed",
        ),
        _node(
            "search_document_file",
            AgentGraphNodeType.TOOL_CALL,
            "Найти файл документа",
            "Ищет документ в файловой системе по доступным признакам.",
            tool_name="filesystem.search_files",
            next_on_success="read_document",
            next_on_error="final_failed",
        ),
        _node(
            "read_document",
            AgentGraphNodeType.TOOL_CALL,
            "Прочитать документ",
            "Ищет файл и извлекает текст документа.",
            tool_name="word.extract_text",
            next_on_success="search_related_documents",
            next_on_error="final_failed",
        ),
        _node(
            "search_related_documents",
            AgentGraphNodeType.TOOL_CALL,
            "Найти связанные документы",
            "Ищет связанные документы, регламенты и извещения.",
            tool_name="smk.search_documents",
            next_on_success="analyze_document",
            next_on_error="analyze_document",
        ),
        _node(
            "analyze_document",
            AgentGraphNodeType.ANALYSIS,
            "Проанализировать документ",
            "Анализирует содержание документа и возможное влияние изменений.",
            next_on_success="build_report",
            next_on_error="final_failed",
        ),
        _node(
            "build_report",
            AgentGraphNodeType.TOOL_CALL,
            "Сформировать отчёт по анализу",
            "Формирует отчёт по результатам анализа документа.",
            tool_name="report.build_document_analysis_report",
            next_on_success="human_review_if_needed",
            next_on_error="final_failed",
        ),
        _node(
            "human_review_if_needed",
            AgentGraphNodeType.HUMAN_REVIEW,
            "Проверка человеком при необходимости",
            "Показывает спорные выводы пользователю, если требуется проверка.",
            next_on_success="final",
            next_on_error="final",
            requires_human_approval=True,
        ),
        _node(
            "final",
            AgentGraphNodeType.FINAL,
            "Завершить работу",
            "Агент успешно завершил анализ документа.",
        ),
        _node(
            "final_failed",
            AgentGraphNodeType.FINAL,
            "Завершить с ошибкой",
            "Агент завершил анализ документа из-за ошибки.",
        ),
    ]


def build_generic_graph() -> list[AgentGraphNode]:
    """Построить минимальный универсальный граф агента."""
    return [
        _node(
            "validate_request",
            AgentGraphNodeType.VALIDATION,
            "Проверить запрос пользователя",
            "Проверяет, достаточно ли данных для запуска агента.",
            next_on_success="plan",
        ),
        _node(
            "plan",
            AgentGraphNodeType.PLANNING,
            "Составить план",
            "Определяет общий план выполнения запроса.",
            next_on_success="final",
        ),
        _node(
            "final",
            AgentGraphNodeType.FINAL,
            "Завершить работу",
            "Агент завершил работу.",
        ),
    ]


def get_graph_template(template_name: str) -> list[AgentGraphNode]:
    """Вернуть граф по имени шаблона или generic-граф для неизвестного имени."""
    template_builders = {
        AgentTemplateName.TASK_CONTROL_AGENT: build_task_control_graph,
        AgentTemplateName.MEETING_AGENT: build_meeting_agent_graph,
        AgentTemplateName.DOCUMENT_ANALYSIS_AGENT: build_document_analysis_graph,
        AgentTemplateName.GENERIC_AGENT: build_generic_graph,
    }

    try:
        normalized_name = AgentTemplateName(template_name)
    except ValueError:
        normalized_name = AgentTemplateName.GENERIC_AGENT

    return template_builders[normalized_name]()


def validate_graph_template(nodes: list[AgentGraphNode]) -> None:
    """Проверить структурную корректность шаблона графа."""
    if not nodes:
        raise ValueError("Шаблон графа не должен быть пустым")

    node_ids = [node.node_id for node in nodes]
    existing_node_ids = set(node_ids)
    if len(node_ids) != len(existing_node_ids):
        raise ValueError("node_id в шаблоне должны быть уникальными")

    has_final_node = any(node.node_type == AgentGraphNodeType.FINAL for node in nodes)
    if not has_final_node:
        raise ValueError("В шаблоне должен быть хотя бы один final-узел")

    for node in nodes:
        if node.node_type == AgentGraphNodeType.TOOL_CALL and not node.tool_name:
            raise ValueError(f"tool_call-узел {node.node_id!r} должен иметь tool_name")
        _validate_transition(node.node_id, "next_on_success", node.next_on_success, existing_node_ids)
        _validate_transition(node.node_id, "next_on_error", node.next_on_error, existing_node_ids)


def _validate_transition(
    node_id: str,
    field_name: str,
    target_node_id: str | None,
    existing_node_ids: set[str],
) -> None:
    """Проверить, что переход узла ссылается на существующий node_id."""
    if target_node_id is not None and target_node_id not in existing_node_ids:
        raise ValueError(
            f"Переход {field_name} узла {node_id!r} ссылается на неизвестный node_id: {target_node_id}"
        )
