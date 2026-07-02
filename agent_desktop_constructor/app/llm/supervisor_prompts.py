"""Промпты LLM Supervisor для безопасного управления выполнением."""

from __future__ import annotations

import json

from agent_desktop_constructor.app.core.models.run_events import AgentRunEvent
from agent_desktop_constructor.app.llm.models import LLMMessage
from agent_desktop_constructor.app.llm.temporal_context import build_temporal_context
from agent_desktop_constructor.core.models.agent_spec import AgentSpec
from agent_desktop_constructor.core.models.runtime_state import (
    AgentRuntimeState,
    ToolCallRecord,
)

SUPERVISOR_JSON_SCHEMA_DESCRIPTION = """
Верни только JSON-объект без Markdown:
{
  "decision_type": "continue_to_next | call_tool | retry_tool | ask_human | request_credentials | finish_success | finish_failed",
  "reason": "почему выбрано это решение",
  "next_node_id": null,
  "tool_call": {
    "tool_name": "точное имя инструмента из ToolsCatalog",
    "input_data": {},
    "reason": "почему нужен этот дополнительный инструмент"
  },
  "human_question": null,
  "human_options": [],
  "graph_patch": null,
  "final_message": null,
  "confidence": 0.0,
  "warnings": []
}
""".strip()


def build_supervisor_prompt(
    agent_spec: AgentSpec,
    runtime_state: AgentRuntimeState,
    latest_event: AgentRunEvent | None,
    latest_tool_result: ToolCallRecord | None,
    tools_context: str,
) -> list[LLMMessage]:
    """Собрать prompt для LLM Supervisor."""
    system_prompt = """
Ты — LLM Supervisor выполнения ИИ-агента.
Ты не вызываешь инструменты напрямую.
Ты не работаешь с COM напрямую.
Ты не открываешь Outlook, 1С или браузер напрямую.
Ты не отправляешь письма.
Ты не изменяешь Outlook.
Ты не пишешь в 1С.
Ты не нажимаешь кнопки подтверждения в браузере.
Ты не выполняешь произвольный код.
Ты анализируешь состояние агента, результат последнего инструмента и выбираешь следующее решение.
Ты можешь выбирать только инструменты из ToolsCatalog.
Ты не можешь придумывать tool_name.
Если подходящего инструмента нет — попроси человека или предложи request/replan через безопасное решение.
Все write/dangerous действия требуют HumanApproval.
Outlook, 1С и Browser сейчас работают только read-only.
email.send заблокирован safe_mode.
Пароли и секреты нельзя просить через LLM-контекст. Если нужна авторизация 1С — верни request_credentials.
Ответ верни только JSON по схеме SupervisorDecision.
""".strip()

    user_payload = {
        "temporal_context": build_temporal_context(),
        "agent_spec": agent_spec.model_dump(mode="json"),
        "runtime_state": runtime_state.model_dump(mode="json"),
        "latest_event": latest_event.model_dump(mode="json") if latest_event else None,
        "latest_tool_result": (
            latest_tool_result.model_dump(mode="json") if latest_tool_result else None
        ),
        "available_tools_context": tools_context,
        "current_goal": agent_spec.goal.model_dump(mode="json"),
        "user_request": runtime_state.variables.get("user_request"),
        "tool_outputs": runtime_state.variables.get("tool_outputs", {}),
        "supervisor_decision_schema": SUPERVISOR_JSON_SCHEMA_DESCRIPTION,
        "hard_forbidden": [
            "отправка писем",
            "изменение Outlook",
            "запись в 1С",
            "нажатие кнопок подтверждения в браузере",
            "выполнение произвольного кода",
            "придумывание инструментов вне ToolsCatalog",
        ],
    }
    user_prompt = (
        "Проанализируй состояние выполнения агента и верни следующее безопасное "
        "решение SupervisorDecision. Для относительных дат используй temporal_context; "
        "если tool input_data содержит дату, передавай её как YYYY-MM-DD.\n"
        + json.dumps(user_payload, ensure_ascii=False, indent=2)
    )
    return [
        LLMMessage(role="system", content=system_prompt),
        LLMMessage(role="user", content=user_prompt),
    ]

