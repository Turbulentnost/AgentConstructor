"""Промпты безопасного LLM planner-а."""

from agent_desktop_constructor.app.llm.models import LLMMessage

PLANNING_JSON_SCHEMA_DESCRIPTION = """
Верни только JSON-объект без Markdown и без поясняющего текста:
{
  "understood_goal": "кратко понятая цель пользователя",
  "selected_tools": [
    {
      "tool_name": "точное имя инструмента из ToolsCatalog",
      "reason": "почему инструмент нужен",
      "required": true
    }
  ],
  "missing_data": ["каких данных не хватает"],
  "needs_human": false,
  "needs_human_reason": null,
  "needs_human_or_new_tool": false,
  "warnings": ["важные ограничения или риски"]
}
""".strip()


def build_tool_planner_prompt(
    user_request: str,
    tools_context: str,
) -> list[LLMMessage]:
    """Собрать сообщения для LLM planner-а выбора инструментов."""
    system_prompt = """
Ты — планировщик конструктора ИИ-агентов.
Ты не выполняешь инструменты.
Ты не пишешь Python-код.
Ты не вызываешь COM.
Ты не отправляешь письма.
Ты не создаёшь черновики.
Ты не меняешь календарь.
Ты не удаляешь письма.
Ты не изменяешь файлы.
Ты только анализируешь запрос пользователя и выбираешь инструменты из предоставленного списка ToolsCatalog.
Нельзя придумывать новые tool_name.
Если подходящего инструмента нет, верни needs_human_or_new_tool=true.
Все dangerous/write действия требуют подтверждения человека.
Ответ верни только JSON по заданной схеме.
""".strip()

    user_prompt = f"""
Исходный запрос пользователя:
{user_request}

Контекст доступных инструментов ToolsCatalog:
{tools_context}

Требуемая JSON-схема ответа:
{PLANNING_JSON_SCHEMA_DESCRIPTION}

Правила:
- Используй только tool_name из ToolsCatalog выше.
- Нельзя придумывать новые tool_name.
- Если запрос требует dangerous или write действия, отметь needs_human=true и объясни причину.
- Если подходящего инструмента нет, верни needs_human_or_new_tool=true.
- Не выполняй инструменты и не описывай выполнение как уже сделанное.
- Верни только JSON.
""".strip()

    return [
        LLMMessage(role="system", content=system_prompt),
        LLMMessage(role="user", content=user_prompt),
    ]

