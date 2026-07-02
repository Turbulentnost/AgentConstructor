"""Тесты prompt builder-а LLM planner-а."""

from agent_desktop_constructor.app.llm.prompts import build_tool_planner_prompt


def _prompt_text() -> str:
    messages = build_tool_planner_prompt(
        user_request="Проверь Outlook и найди поручения",
        tools_context=(
            "Доступные инструменты:\n"
            "1. outlook.search_mail\n"
            "Уровень действия: read\n"
            "2. email.send\n"
            "Уровень действия: dangerous"
        ),
    )
    return "\n\n".join(message.content for message in messages)


def test_prompt_forbids_inventing_tool_names() -> None:
    """Prompt запрещает придумывать tool_name."""
    assert "Нельзя придумывать новые tool_name" in _prompt_text()


def test_prompt_contains_tools_catalog_context() -> None:
    """Prompt содержит ToolsCatalog context."""
    text = _prompt_text()

    assert "Доступные инструменты" in text
    assert "outlook.search_mail" in text


def test_prompt_contains_user_request() -> None:
    """Prompt содержит исходный user_request."""
    assert "Проверь Outlook и найди поручения" in _prompt_text()


def test_prompt_contains_current_date_context() -> None:
    """Prompt содержит текущую дату для grounding относительных дат."""
    text = _prompt_text()

    assert "Текущая дата выполнения:" in text
    assert "Текущая неделя:" in text
    assert "эта неделя" in text


def test_prompt_guides_calendar_and_birthday_search() -> None:
    """Prompt направляет LLM на календарь и поиск дней рождения в письмах."""
    text = _prompt_text()

    assert "outlook.read_calendar" in text
    assert "дни рождения" in text
    assert "folder=All" in text


def test_prompt_says_dangerous_requires_approval() -> None:
    """Prompt содержит правило о подтверждении dangerous/write."""
    assert "Все dangerous/write действия требуют подтверждения человека" in _prompt_text()


def test_prompt_forbids_executing_tools() -> None:
    """Prompt запрещает выполнять инструменты."""
    text = _prompt_text()

    assert "Ты не выполняешь инструменты" in text
    assert "Ты не вызываешь COM" in text
    assert "Ты не отправляешь письма" in text


def test_prompt_requires_json() -> None:
    """Prompt требует JSON-ответ."""
    text = _prompt_text()

    assert "Ответ верни только JSON" in text
    assert "Верни только JSON" in text
    assert '"selected_tools"' in text

