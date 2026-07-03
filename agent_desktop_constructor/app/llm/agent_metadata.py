"""Генерация человекочитаемой карточки агента при явном сохранении.

Когда пользователь нажимает «Сохранить», мы формируем короткое название,
краткое описание (одна строка) и развёрнутое описание (для чего агент, что он
делает и какие у него цели). По возможности используем LLM; при недоступности
или ошибке — детерминированный fallback из цели и инструментов агента.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from agent_desktop_constructor.app.llm.models import LLMMessage, LLMRequest
from agent_desktop_constructor.core.models.agent_spec import AgentSpec

_SYSTEM_PROMPT = (
    "Ты оформляешь карточку ИИ-агента для каталога. Верни ТОЛЬКО JSON-объект без "
    "Markdown вида {\"name\": ..., \"short_description\": ..., \"description\": ...}. "
    "name — короткое человекочитаемое название (до 50 символов, без кавычек). "
    "short_description — одно короткое предложение, что делает агент. "
    "description — 2-4 предложения: для чего этот агент, что он делает и какие у "
    "него цели. Пиши на языке запроса пользователя."
)


@dataclass(frozen=True)
class AgentMetadata:
    """Готовая карточка агента для сохранения."""

    name: str
    short_description: str
    description: str


class AgentMetadataGenerator:
    """Строит название/краткое/полное описание агента (LLM + fallback)."""

    def __init__(self, llm_client: object | None = None) -> None:
        """Создать генератор с необязательным LLM-клиентом."""
        self._llm_client = llm_client

    def generate(self, user_request: str, agent_spec: AgentSpec) -> AgentMetadata:
        """Сформировать метаданные карточки, не роняя сохранение при сбое LLM."""
        if self._llm_client is not None:
            try:
                return self._generate_via_llm(user_request, agent_spec)
            except Exception:
                pass
        return self._heuristic(user_request, agent_spec)

    def _generate_via_llm(
        self, user_request: str, agent_spec: AgentSpec
    ) -> AgentMetadata:
        """Запросить карточку у LLM и распарсить JSON-ответ."""
        payload = {
            "user_request": user_request or agent_spec.goal.main_goal,
            "main_goal": agent_spec.goal.main_goal,
            "success_criteria": agent_spec.goal.success_criteria,
            "tools": [tool.tool_name for tool in agent_spec.tools],
        }
        messages = [
            LLMMessage(role="system", content=_SYSTEM_PROMPT),
            LLMMessage(
                role="user",
                content=json.dumps(payload, ensure_ascii=False, default=str),
            ),
        ]
        config = getattr(self._llm_client, "config", None)
        response = self._llm_client.complete(
            LLMRequest(
                messages=messages,
                temperature=getattr(config, "temperature", 0.2),
                model_name=getattr(config, "model_name", None),
                response_format="json_object",
            )
        )
        data = _loads_first_json_object(response.content)
        name = _clean(data.get("name")) or agent_spec.name
        short_description = _clean(data.get("short_description")) or (
            agent_spec.goal.main_goal
        )
        description = _clean(data.get("description")) or agent_spec.description
        return AgentMetadata(
            name=name[:80],
            short_description=short_description[:200],
            description=description,
        )

    def _heuristic(self, user_request: str, agent_spec: AgentSpec) -> AgentMetadata:
        """Детерминированная карточка из цели и инструментов, без LLM."""
        goal = agent_spec.goal.main_goal.strip()
        name = agent_spec.name.strip() or goal[:50] or "Агент"
        short_description = goal or (user_request or "").strip() or agent_spec.description
        criteria = agent_spec.goal.success_criteria
        categories = sorted(
            {tool.tool_name.split(".")[0] for tool in agent_spec.tools if tool.tool_name}
        )
        parts = [f"Агент предназначен для: {goal}." if goal else ""]
        if criteria:
            parts.append("Критерии успеха: " + "; ".join(criteria[:3]) + ".")
        if categories:
            parts.append("Использует инструменты: " + ", ".join(categories) + ".")
        description = " ".join(part for part in parts if part) or agent_spec.description
        return AgentMetadata(
            name=name[:80],
            short_description=short_description[:200],
            description=description,
        )


def _clean(value: object) -> str:
    """Привести значение к обрезанной строке."""
    if value is None:
        return ""
    return str(value).strip()


def _loads_first_json_object(content: str) -> dict:
    """Распарсить JSON-объект, устойчиво к тексту вокруг."""
    text = (content or "").strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            parsed = json.loads(text[start : end + 1])
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
    return {}
