"""Тесты расширенных правил LLM Planner prompt."""

from agent_desktop_constructor.app.llm.prompts import build_tool_planner_prompt


def prompt_text() -> str:
    """Собрать prompt text с расширенным catalog context."""
    messages = build_tool_planner_prompt(
        user_request="Найди документ в 1С, проверь web и проанализируй данные",
        tools_context=(
            "Доступные инструменты:\n"
            "1. browser.search_web\n"
            "2. onec.search_documents\n"
            "3. llm.analyze_collected_data"
        ),
    )
    return "\n\n".join(message.content for message in messages)


def test_prompt_forbids_inventing_tool_names() -> None:
    """LLM Planner prompt запрещает придумывать tool_name."""
    assert "Нельзя придумывать новые tool_name" in prompt_text()


def test_prompt_explains_browser_tools() -> None:
    """Prompt объясняет, когда использовать browser tools."""
    text = prompt_text()

    assert "Если нужны данные из браузера" in text
    assert "browser.search_web" in text
    assert "browser.open_page" in text


def test_prompt_explains_onec_tools() -> None:
    """Prompt объясняет, когда использовать 1C tools."""
    text = prompt_text()

    assert "Если нужны данные из 1С" in text
    assert "onec.search_documents" in text
    assert "onec.get_task_card" in text
    assert "1С работает только в read-only режиме" in text


def test_prompt_explains_llm_analytics_tools() -> None:
    """Prompt объясняет, когда использовать LLM analytics tools."""
    text = prompt_text()

    assert "llm.analyze_collected_data" in text
    assert "llm.compare_sources" in text
    assert "llm.extract_structured_facts" in text


def test_prompt_forbids_browser_write_actions() -> None:
    """Prompt запрещает действия на сайтах."""
    text = prompt_text()

    assert "Запрещено отправлять формы" in text
    assert "нажимать кнопки подтверждения" in text

