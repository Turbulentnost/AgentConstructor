"""Промпты LLM-управляемого цикла агента (ReAct-style, без хардкода)."""

from __future__ import annotations

import json

from agent_desktop_constructor.app.llm.models import LLMImageContent, LLMMessage
from agent_desktop_constructor.app.llm.temporal_context import build_temporal_context
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
- Outlook и 1С работают только в режиме чтения. email.send заблокирован.
- Пароли/секреты нельзя запрашивать через LLM — для авторизации верни request_credentials.

Взаимодействие с UI сайтов (vision-режим):
- Если для задачи нужно не просто прочитать текст страницы, а взаимодействовать с
  интерфейсом (нажать кнопку, ввести текст, перейти по элементу, открыть раздел),
  используй vision-инструменты браузера: browser.navigate (открыть URL),
  browser.screenshot (обновить кадр), browser.click (клик по x,y),
  browser.type_text (ввод текста в активное поле), browser.press_key
  (enter/tab/escape/стрелки), browser.scroll (прокрутка).
- К твоему сообщению прикладывается АКТУАЛЬНЫЙ СКРИНШОТ текущей вкладки, если он
  есть. Определяй координаты клика по скриншоту в пикселях от левого-верхнего угла;
  размеры viewport указаны в screen_context.
- Действуй пошагово: сделай одно действие, посмотри на новый скриншот, реши следующее.
- Не вводи пароли, коды из SMS и 2FA — если сайт требует ручной вход, верни ask_human.
Ответ верни только JSON по схеме решения.
""".strip()

    allowed_tools = sorted(agent_spec.allowed_tool_names())
    tools_context = _available_tools_context(tools_catalog, allowed_tools)
    collected_data = _sanitize_collected_data(
        runtime_state.variables.get("tool_outputs", {})
    )
    last_screenshot = runtime_state.variables.get("last_screenshot")
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
        "temporal_context": build_temporal_context(),
        "user_request": runtime_state.variables.get("user_request"),
        "goal": agent_spec.goal.model_dump(mode="json"),
        "available_tools": tools_context,
        "executed_steps": executed_steps,
        "executed_actions": executed_signatures,
        "collected_data": collected_data,
        "repeat_notes": repeat_notes,
        "decision_schema": AGENT_LOOP_SCHEMA_DESCRIPTION,
    }
    if isinstance(last_screenshot, dict) and last_screenshot.get("base64"):
        user_payload["screen_context"] = {
            "has_screenshot": True,
            "url": last_screenshot.get("url"),
            "title": last_screenshot.get("title"),
            "viewport_width": last_screenshot.get("viewport_width"),
            "viewport_height": last_screenshot.get("viewport_height"),
            "note": (
                "К этому сообщению приложен скриншот текущей вкладки. Координаты "
                "для browser.click указывай в пикселях viewport по этому скриншоту."
            ),
        }
    user_prompt = (
        "Определи следующий безопасный шаг агента и верни JSON-решение. "
        "Инструменты выбирай сам, опираясь на их описание (description) и "
        "when_to_use в available_tools, на цель пользователя и на уже собранные "
        "данные (collected_data). Не полагайся на подсказки по конкретным задачам "
        "— их нет; сам реши, какой инструмент и с какими параметрами нужен сейчас. "
        "Для относительных дат ('сегодня', 'на этой неделе', 'за июнь') используй "
        "temporal_context; если input_data инструмента содержит дату, передавай её "
        "в формате YYYY-MM-DD.\n"
        + json.dumps(user_payload, ensure_ascii=False, indent=2, default=str)
    )
    user_images: list[LLMImageContent] = []
    if isinstance(last_screenshot, dict) and last_screenshot.get("base64"):
        user_images.append(
            LLMImageContent(
                base64_data=str(last_screenshot["base64"]),
                media_type=str(last_screenshot.get("media_type") or "image/png"),
            )
        )
    return [
        LLMMessage(role="system", content=system_prompt),
        LLMMessage(role="user", content=user_prompt, images=user_images),
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
                "input_schema": item.input_schema,
                "side_effect_level": item.side_effect_level.value,
                "requires_human_approval": item.requires_human_approval,
                "output_keys": sorted(
                    item.output_schema.get("properties", {}).keys()
                ),
            }
        )
    return context


def _sanitize_collected_data(collected_data: dict) -> dict:
    """Убрать тяжёлые base64-скриншоты из данных, отправляемых текстом в промпт."""
    if not isinstance(collected_data, dict):
        return collected_data
    sanitized: dict = {}
    for tool_name, output in collected_data.items():
        if isinstance(output, dict) and "screenshot_base64" in output:
            trimmed = {k: v for k, v in output.items() if k != "screenshot_base64"}
            trimmed["screenshot_captured"] = True
            sanitized[tool_name] = trimmed
        else:
            sanitized[tool_name] = output
    return sanitized


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
