"""Правила доступа к опубликованным агентам по отделам."""

from __future__ import annotations

from llm_proxy_service.models_catalog import (
    VISIBILITY_ALL,
    VISIBILITY_DEPARTMENT,
    VISIBILITY_PRIVATE,
    VISIBILITY_SELECTED,
    SharedAgentEntity,
)
from llm_proxy_service.models_user import UserEntity


def user_can_see_department(user_department: str, target_department: str) -> bool:
    """Проверить доступ к отделу (сейчас — точное совпадение строк).

    Позже сюда войдёт оргструктура руководителей без смены visibility API.
    """
    user_dept = (user_department or "").strip()
    target_dept = (target_department or "").strip()
    if not user_dept or not target_dept:
        return False
    return user_dept == target_dept


def user_can_access_agent(
    user: UserEntity,
    agent: SharedAgentEntity,
    *,
    selected_departments: list[str] | None = None,
) -> bool:
    """Вернуть True, если пользователь может видеть/получить агента."""
    if user.onec_uid == agent.owner_onec_uid:
        return True

    visibility = (agent.visibility or VISIBILITY_PRIVATE).strip().lower()
    if visibility == VISIBILITY_PRIVATE:
        return False
    if visibility == VISIBILITY_ALL:
        return True
    if visibility == VISIBILITY_DEPARTMENT:
        return user_can_see_department(user.department, agent.owner_department)
    if visibility == VISIBILITY_SELECTED:
        departments = selected_departments or []
        user_dept = (user.department or "").strip()
        if not user_dept:
            return False
        return any(user_can_see_department(user_dept, dept) for dept in departments)
    return False
