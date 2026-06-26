"""Эвристический выбор шаблона графа по текстовому запросу пользователя."""

from agent_desktop_constructor.builder.graph_templates import AgentTemplateName


class TemplateSelector:
    """Выбирает шаблон агента простыми правилами без вызова LLM."""

    _TASK_CONTROL_KEYWORDS = (
        "поруч",
        "задач",
        "контрол",
        "исполн",
        "просроч",
    )
    _MEETING_KEYWORDS = (
        "совещ",
        "встреч",
        "протокол",
        "повестк",
    )
    _DOCUMENT_ANALYSIS_KEYWORDS = (
        "документ",
        "нд",
        "извещение",
        "анализ влияния",
        "смк",
        "регламент",
    )

    def select_template(self, user_request: str) -> str:
        """Выбрать имя шаблона по тексту пользовательского запроса."""
        normalized_request = user_request.strip().casefold()
        if not normalized_request:
            raise ValueError("user_request не должен быть пустым")

        if self._contains_any(normalized_request, self._TASK_CONTROL_KEYWORDS):
            return AgentTemplateName.TASK_CONTROL_AGENT.value
        if self._contains_any(normalized_request, self._MEETING_KEYWORDS):
            return AgentTemplateName.MEETING_AGENT.value
        if self._contains_any(normalized_request, self._DOCUMENT_ANALYSIS_KEYWORDS):
            return AgentTemplateName.DOCUMENT_ANALYSIS_AGENT.value
        return AgentTemplateName.GENERIC_AGENT.value

    def _contains_any(self, text: str, keywords: tuple[str, ...]) -> bool:
        """Проверить наличие любого ключевого слова в тексте."""
        return any(keyword in text for keyword in keywords)
