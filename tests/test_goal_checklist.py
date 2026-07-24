"""Тесты чек-листа цели и finish-gate."""

from agent_desktop_constructor.app.llm.goal_checklist import (
    ChecklistItemStatus,
    apply_checklist_updates,
    build_goal_checklist,
    concrete_success_criteria_from_plan_steps,
    ensure_goal_checklist,
    is_generic_criterion,
    validate_finish_success,
)
from agent_desktop_constructor.builder.agent_builder import AgentBuilder


def test_generic_criterion_detection() -> None:
    assert is_generic_criterion("Выполнен LLM-план по запросу пользователя")
    assert not is_generic_criterion("Прочитан календарь Outlook за текущую неделю")


def test_concrete_criteria_from_plan_steps() -> None:
    criteria = concrete_success_criteria_from_plan_steps(
        ["Открыть календарь", "Сформировать вывод"],
        "распланировать неделю",
    )
    assert any("Открыть календарь" in item for item in criteria)
    assert any("собранные данные" in item.casefold() for item in criteria)


def test_build_goal_checklist_includes_plan_steps() -> None:
    agent_spec = AgentBuilder().build_from_request(
        "Посмотри совещания в Outlook и подскажи как распланировать график"
    )
    checklist = build_goal_checklist(agent_spec)
    kinds = {item.kind for item in checklist}
    assert "criterion" in kinds
    assert any(item.related_tool for item in checklist if item.kind == "plan_step")


def test_validate_finish_requires_evidence_or_done() -> None:
    agent_spec = AgentBuilder().build_from_request(
        "Посмотри совещания в Outlook и подскажи как распланировать график"
    )
    variables: dict = {}
    checklist = ensure_goal_checklist(agent_spec, variables)
    reject = validate_finish_success(
        checklist=checklist,
        criteria_evidence=None,
        final_message="Короткий итог без доказательств по цели агента.",
    )
    assert reject is not None

    ok = validate_finish_success(
        checklist=checklist,
        criteria_evidence=[
            {
                "criterion": item["text"],
                "evidence": "Данные инструмента подтверждают выполнение",
            }
            for item in checklist
            if item.get("kind") == "criterion"
        ],
        final_message="Итог с доказательствами по критериям цели.",
    )
    assert ok is None

    updated = apply_checklist_updates(
        checklist,
        [
            {
                "item_id": item["item_id"],
                "status": ChecklistItemStatus.DONE.value,
                "note": "закрыто",
            }
            for item in checklist
            if item.get("kind") == "criterion"
        ],
    )
    ok_done = validate_finish_success(
        checklist=updated,
        criteria_evidence=None,
        final_message="Итог после закрытия чек-листа критериями done.",
    )
    assert ok_done is None
