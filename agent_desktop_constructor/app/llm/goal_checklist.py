"""Чек-лист цели для LLM agent-loop: критерии успеха и шаги плана."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, field_validator

from agent_desktop_constructor.core.models.agent_spec import (
    AgentGraphNodeType,
    AgentSpec,
)

TOOL_OUTPUT_HISTORY_LIMIT = 12
GENERIC_CRITERIA_MARKERS = (
    "выполнен llm-план",
    "сформирован результат по запросу",
    "задача выполнена",
)


class ChecklistItemStatus(StrEnum):
    """Статус пункта чек-листа цели."""

    PENDING = "pending"
    DONE = "done"
    BLOCKED = "blocked"


class GoalChecklistItem(BaseModel):
    """Один пункт цели: критерий успеха или шаг плана."""

    item_id: str
    kind: str  # criterion | plan_step | data_requirement
    text: str
    status: ChecklistItemStatus = ChecklistItemStatus.PENDING
    required: bool = True
    related_tool: str | None = None

    @field_validator("item_id", "text", "kind")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        """Проверить, что текстовое поле заполнено."""
        if not value.strip():
            raise ValueError("Поле чек-листа не должно быть пустым")
        return value


class CriteriaEvidence(BaseModel):
    """Доказательство, что критерий успеха выполнен."""

    criterion: str
    evidence: str

    @field_validator("criterion", "evidence")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        """Проверить, что evidence заполнен."""
        if not value.strip():
            raise ValueError("criterion/evidence не должны быть пустыми")
        return value.strip()


class ChecklistUpdate(BaseModel):
    """Обновление статуса пункта чек-листа от LLM."""

    item_id: str
    status: ChecklistItemStatus
    note: str = ""

    @field_validator("item_id")
    @classmethod
    def validate_item_id(cls, value: str) -> str:
        """Проверить item_id."""
        if not value.strip():
            raise ValueError("item_id не должен быть пустым")
        return value.strip()


def is_generic_criterion(text: str) -> bool:
    """Шаблонный критерий, который почти не проверяет реальную цель."""
    normalized = " ".join(text.casefold().split())
    return any(marker in normalized for marker in GENERIC_CRITERIA_MARKERS)


def build_goal_checklist(agent_spec: AgentSpec) -> list[GoalChecklistItem]:
    """Собрать чек-лист из success_criteria, tool-шагов графа и data_requirements."""
    items: list[GoalChecklistItem] = []
    criteria = list(agent_spec.goal.success_criteria or [])
    concrete = [c for c in criteria if not is_generic_criterion(c)]
    source_criteria = concrete or criteria
    for index, criterion in enumerate(source_criteria):
        items.append(
            GoalChecklistItem(
                item_id=f"criterion_{index + 1}",
                kind="criterion",
                text=criterion.strip(),
                required=True,
            )
        )

    plan_index = 0
    for node in agent_spec.graph_nodes:
        if node.node_type != AgentGraphNodeType.TOOL_CALL:
            continue
        if not node.tool_name:
            continue
        plan_index += 1
        title = (node.title or node.tool_name).strip()
        items.append(
            GoalChecklistItem(
                item_id=f"plan_step_{plan_index}",
                kind="plan_step",
                text=title,
                required=False,
                related_tool=node.tool_name,
            )
        )

    for index, requirement in enumerate(agent_spec.data_requirements):
        if not requirement.required:
            continue
        items.append(
            GoalChecklistItem(
                item_id=f"data_{index + 1}",
                kind="data_requirement",
                text=f"{requirement.name}: {requirement.description}",
                required=bool(requirement.ask_human_if_missing or requirement.required),
            )
        )

    return items


def ensure_goal_checklist(
    agent_spec: AgentSpec,
    variables: dict,
) -> list[dict]:
    """Инициализировать goal_checklist в variables при первом заходе."""
    existing = variables.get("goal_checklist")
    if isinstance(existing, list) and existing:
        return existing
    checklist = [item.model_dump(mode="json") for item in build_goal_checklist(agent_spec)]
    variables["goal_checklist"] = checklist
    return checklist


def apply_checklist_updates(
    checklist: list[dict],
    updates: list[ChecklistUpdate] | list[dict] | None,
) -> list[dict]:
    """Применить обновления статусов к чек-листу."""
    if not updates:
        return checklist
    by_id = {
        str(item.get("item_id")): dict(item)
        for item in checklist
        if isinstance(item, dict)
    }
    order = [str(item.get("item_id")) for item in checklist if isinstance(item, dict)]
    for raw in updates:
        if isinstance(raw, ChecklistUpdate):
            update = raw
        elif isinstance(raw, dict):
            try:
                update = ChecklistUpdate.model_validate(raw)
            except Exception:
                continue
        else:
            continue
        item = by_id.get(update.item_id)
        if item is None:
            continue
        item["status"] = update.status.value
        if update.note.strip():
            item["note"] = update.note.strip()
        by_id[update.item_id] = item
    return [by_id[item_id] for item_id in order if item_id in by_id]


def append_tool_output_history(
    variables: dict,
    tool_name: str,
    output_data: object,
    *,
    ok: bool,
    error_message: str | None = None,
    step: int | None = None,
    limit: int = TOOL_OUTPUT_HISTORY_LIMIT,
) -> None:
    """Добавить результат инструмента в кольцевой буфер истории наблюдений."""
    history = variables.setdefault("tool_output_history", [])
    if not isinstance(history, list):
        history = []
        variables["tool_output_history"] = history
    history.append(
        {
            "step": step,
            "tool_name": tool_name,
            "ok": ok,
            "error_message": error_message,
            "output": output_data,
        }
    )
    del history[:-limit]


def validate_finish_success(
    *,
    checklist: list[dict],
    criteria_evidence: list[CriteriaEvidence] | list[dict] | None,
    final_message: str | None,
) -> str | None:
    """Вернуть текст причины отказа finish_success или None если можно завершать."""
    if not (final_message or "").strip():
        return "finish_success требует непустой final_message."

    evidence_items: list[CriteriaEvidence] = []
    for raw in criteria_evidence or []:
        if isinstance(raw, CriteriaEvidence):
            evidence_items.append(raw)
        elif isinstance(raw, dict):
            try:
                evidence_items.append(CriteriaEvidence.model_validate(raw))
            except Exception:
                continue

    required_criteria = [
        item
        for item in checklist
        if isinstance(item, dict)
        and item.get("kind") == "criterion"
        and item.get("required", True)
    ]
    if not required_criteria:
        if evidence_items:
            return None
        if len((final_message or "").strip()) < 20:
            return (
                "Нет success_criteria в чек-листе: для finish_success нужен "
                "развёрнутый final_message (≥20 символов) или criteria_evidence."
            )
        return None

    pending_required = [
        item
        for item in required_criteria
        if str(item.get("status") or ChecklistItemStatus.PENDING)
        != ChecklistItemStatus.DONE
    ]

    if not evidence_items and pending_required:
        pending_text = "; ".join(
            str(item.get("text") or item.get("item_id")) for item in pending_required[:5]
        )
        return (
            "Нельзя finish_success: не закрыты критерии цели и нет criteria_evidence. "
            f"Открыто: {pending_text}. Верни criteria_evidence по каждому критерию "
            "или обнови goal_checklist (checklist_updates) в status=done."
        )

    if evidence_items:
        if len(evidence_items) >= len(required_criteria):
            return None
        if pending_required:
            return (
                "criteria_evidence не покрывает все обязательные критерии. "
                f"Нужно evidence для {len(required_criteria)} критериев, "
                f"получено {len(evidence_items)}."
            )
    return None


def concrete_success_criteria_from_plan_steps(
    step_titles: list[str],
    goal: str,
) -> list[str]:
    """Построить конкретные критерии успеха из шагов плана вместо шаблона."""
    criteria: list[str] = []
    for title in step_titles:
        cleaned = title.strip()
        if cleaned:
            criteria.append(f"Выполнен шаг: {cleaned}")
    if not criteria:
        criteria.append(f"Получен проверяемый результат по цели: {goal.strip()}")
    criteria.append(
        "Итоговый ответ пользователю опирается на собранные данные инструментов"
    )
    return criteria
