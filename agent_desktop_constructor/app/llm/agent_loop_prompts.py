"""Промпты LLM-управляемого цикла агента (ReAct-style, без хардкода)."""

from __future__ import annotations

import json

from agent_desktop_constructor.app.llm.models import LLMMessage
from agent_desktop_constructor.core.models.agent_spec import AgentSpec
from agent_desktop_constructor.core.models.runtime_state import AgentRuntimeState
from agent_desktop_constructor.tools.catalog import ToolsCatalog

AGENT_LOOP_SCHEMA_DESCRIPTION = """
Верни только JSON-объект без Markdown:
{
  "decision_type": "call_tool | finish_success | finish_failed | ask_human | request_credentials",
  "reason": "почему ты выбрал это действие на основе цели и уже собранных данных",
  "tool_call": {
    "tool_name": "точное имя инструмента из списка доступных",
    "input_data": {"параметр": "значение"},
    "reason": "зачем нужен именно этот инструмент сейчас"
  },
  "final_message": "итоговый вывод для пользователя на основе собранных данных (для finish_success)",
  "human_question": null,
  "human_options": [],
  "confidence": 0.0,
  "warnings": []
}
""".strip()


def build_agent_loop_prompt(
    agent_spec: AgentSpec,
    runtime_state: AgentRuntimeState,
    tools_catalog: ToolsCatalog,
    executed_signatures: list[str],
    repeat_notes: list[str],
) -> list[LLMMessage]:
    """Собрать prompt одного шага LLM-управляемого цикла агента."""
    system_prompt = """
Ты — управляющий LLM ИИ-агента. Ты сам планируешь, как достичь цели пользователя.
После каждого результата инструмента ты решаешь следующий шаг.

Ты НЕ вызываешь инструменты напрямую и не пишешь код.
Ты возвращаешь только одно решение: вызвать инструмент, завершить успехом,
завершить ошибкой, спросить человека или запросить credentials.
Runtime сам безопасно исполнит инструмент через ToolGateway.

Правила:
- Выбирай tool_name только из списка доступных инструментов. Не выдумывай новые.
- НЕ повторяй уже выполненные действия с теми же параметрами (см. executed_actions).
- Смотри на результаты уже выполненных инструментов (collected_data) и решай:
  нужно ли собрать ещё данные другим инструментом или данных уже достаточно.
- Если собранных данных достаточно для цели — верни finish_success и сформулируй
  вывод (final_message) сам, на основе запроса пользователя и собранных данных.
  НЕ используй шаблонные или выдуманные факты — только реальные собранные данные.
- Если нужный инструмент недоступен или данных получить нельзя — finish_failed или ask_human.
- write/dangerous действия исполняются только с подтверждением человека.
- Outlook, 1С и браузер работают только в режиме чтения. email.send заблокирован.
- Пароли/секреты нельзя запрашивать через LLM — для авторизации 1С верни request_credentials.
Ответ верни только JSON по схеме решения.
""".strip()

    allowed_tools = sorted(agent_spec.allowed_tool_names())
    tools_context = _available_tools_context(tools_catalog, allowed_tools)
    collected_data = runtime_state.variables.get("tool_outputs", {})
    executed_steps = [
        {
            "tool_name": record.tool_name,
            "ok": record.ok,
            "error_type": record.error_type,
            "output_summary": _summarize_output(record.output_data),
        }
        for record in runtime_state.tool_results
    ]

    user_payload = {
        "user_request": runtime_state.variables.get("user_request"),
        "goal": agent_spec.goal.model_dump(mode="json"),
        "available_tools": tools_context,
        "executed_steps": executed_steps,
        "executed_actions": executed_signatures,
        "collected_data": collected_data,
        "repeat_notes": repeat_notes,
        "decision_schema": AGENT_LOOP_SCHEMA_DESCRIPTION,
    }
    user_prompt = (
        "Определи следующий безопасный шаг агента и верни JSON-решение.\n"
        + json.dumps(user_payload, ensure_ascii=False, indent=2, default=str)
    )
    return [
        LLMMessage(role="system", content=system_prompt),
        LLMMessage(role="user", content=user_prompt),
    ]


def _available_tools_context(
    tools_catalog: ToolsCatalog,
    allowed_tool_names: list[str],
) -> list[dict]:
    """Собрать компактное описание доступных агенту инструментов."""
    context: list[dict] = []
    for name in allowed_tool_names:
        if not tools_catalog.has_tool(name):
            continue
        item = tools_catalog.get_tool(name)
        context.append(
            {
                "tool_name": item.name,
                "description": item.description,
                "when_to_use": item.planner_hint,
                "side_effect_level": item.side_effect_level.value,
                "requires_human_approval": item.requires_human_approval,
                "output_keys": sorted(
                    item.output_schema.get("properties", {}).keys()
                ),
            }
        )
    return context


def _summarize_output(output_data: dict | None, max_chars: int = 600) -> str:
    """Сжать output_data инструмента до короткого текста для контекста LLM."""
    if not output_data:
        return "пустой результат"
    try:
        text = json.dumps(output_data, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = str(output_data)
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "…"
