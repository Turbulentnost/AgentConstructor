"""Unit-тесты ACL каталога агентов."""

from __future__ import annotations

from llm_proxy_service.agent_acl import (
    user_can_access_agent,
    user_can_see_department,
)
from llm_proxy_service.models_catalog import (
    VISIBILITY_ALL,
    VISIBILITY_DEPARTMENT,
    VISIBILITY_PRIVATE,
    VISIBILITY_SELECTED,
    SharedAgentEntity,
)
from llm_proxy_service.models_user import UserEntity


def _user(uid: str, department: str) -> UserEntity:
    return UserEntity(
        onec_uid=uid,
        login=uid,
        display_name=uid,
        department=department,
        password_data=b"",
    )


def _agent(
    owner: str,
    *,
    visibility: str,
    owner_department: str = "ИТ",
) -> SharedAgentEntity:
    return SharedAgentEntity(
        agent_id="agent-1",
        owner_onec_uid=owner,
        owner_department=owner_department,
        name="Test",
        visibility=visibility,
        agent_spec_json="{}",
    )


def test_owner_always_sees_private() -> None:
    user = _user("u1", "ИТ")
    agent = _agent("u1", visibility=VISIBILITY_PRIVATE)
    assert user_can_access_agent(user, agent)


def test_other_user_cannot_see_private() -> None:
    user = _user("u2", "ИТ")
    agent = _agent("u1", visibility=VISIBILITY_PRIVATE)
    assert not user_can_access_agent(user, agent)


def test_department_visibility_same_dept() -> None:
    user = _user("u2", "ИТ")
    agent = _agent("u1", visibility=VISIBILITY_DEPARTMENT, owner_department="ИТ")
    assert user_can_access_agent(user, agent)


def test_department_visibility_other_dept() -> None:
    user = _user("u2", "Бухгалтерия")
    agent = _agent("u1", visibility=VISIBILITY_DEPARTMENT, owner_department="ИТ")
    assert not user_can_access_agent(user, agent)


def test_department_empty_user_dept_denied() -> None:
    user = _user("u2", "")
    agent = _agent("u1", visibility=VISIBILITY_DEPARTMENT, owner_department="ИТ")
    assert not user_can_access_agent(user, agent)


def test_all_visibility() -> None:
    user = _user("u2", "Бухгалтерия")
    agent = _agent("u1", visibility=VISIBILITY_ALL)
    assert user_can_access_agent(user, agent)


def test_selected_departments() -> None:
    user = _user("u2", "Сектор ИИ")
    agent = _agent("u1", visibility=VISIBILITY_SELECTED)
    assert user_can_access_agent(
        user, agent, selected_departments=["Сектор ИИ", "ИТ"]
    )
    assert not user_can_access_agent(
        user, agent, selected_departments=["Бухгалтерия"]
    )


def test_user_can_see_department_match() -> None:
    assert user_can_see_department("ИТ", "ИТ")
    assert not user_can_see_department("ИТ", "Бухгалтерия")
    assert not user_can_see_department("", "ИТ")
