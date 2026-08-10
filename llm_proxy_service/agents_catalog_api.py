"""REST API каталога опубликованных агентов, pins и сводок запусков."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from llm_proxy_service.agent_acl import user_can_access_agent
from llm_proxy_service.auth_api import get_current_user
from llm_proxy_service.db import get_session
from llm_proxy_service.models_catalog import (
    VALID_VISIBILITIES,
    VISIBILITY_PRIVATE,
    VISIBILITY_SELECTED,
    AgentRunSummaryEntity,
    SharedAgentDepartmentEntity,
    SharedAgentEntity,
    UserAgentPinEntity,
)
from llm_proxy_service.models_user import UserEntity

logger = logging.getLogger("llm_proxy.agents_catalog")

router = APIRouter(tags=["agents-catalog"])

_AGENT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _db_session() -> Session:
    try:
        return get_session()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Database is not configured") from exc


def _validate_agent_id(agent_id: str) -> str:
    cleaned = (agent_id or "").strip()
    if not cleaned or not _AGENT_ID_RE.fullmatch(cleaned):
        raise HTTPException(status_code=400, detail="Некорректный agent_id")
    return cleaned


class PublishAgentRequest(BaseModel):
    agent_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=256)
    description: str = ""
    short_description: str = ""
    agent_spec: dict[str, Any]
    visibility: str = VISIBILITY_PRIVATE
    departments: list[str] = Field(default_factory=list)
    image_object_key: str = ""

    @field_validator("visibility")
    @classmethod
    def _check_visibility(cls, value: str) -> str:
        cleaned = (value or "").strip().lower()
        if cleaned not in VALID_VISIBILITIES:
            raise ValueError(
                f"visibility должен быть одним из: {', '.join(sorted(VALID_VISIBILITIES))}"
            )
        return cleaned

    @field_validator("agent_id")
    @classmethod
    def _check_agent_id(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned or not _AGENT_ID_RE.fullmatch(cleaned):
            raise ValueError("Некорректный agent_id")
        return cleaned


class AccessPatchRequest(BaseModel):
    visibility: str
    departments: list[str] = Field(default_factory=list)

    @field_validator("visibility")
    @classmethod
    def _check_visibility(cls, value: str) -> str:
        cleaned = (value or "").strip().lower()
        if cleaned not in VALID_VISIBILITIES:
            raise ValueError(
                f"visibility должен быть одним из: {', '.join(sorted(VALID_VISIBILITIES))}"
            )
        return cleaned


class PinsPutRequest(BaseModel):
    agent_ids: list[str] = Field(default_factory=list)


class RunSummaryRequest(BaseModel):
    run_id: str = Field(min_length=1, max_length=128)
    agent_id: str = Field(min_length=1, max_length=128)
    status: str = Field(min_length=1, max_length=64)
    title: str = ""
    message: str = ""
    started_at: datetime | None = None
    finished_at: datetime | None = None

    @field_validator("agent_id")
    @classmethod
    def _check_agent_id(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned or not _AGENT_ID_RE.fullmatch(cleaned):
            raise ValueError("Некорректный agent_id")
        return cleaned


def _departments_for_agent(session: Session, agent_id: str) -> list[str]:
    rows = session.scalars(
        select(SharedAgentDepartmentEntity.department).where(
            SharedAgentDepartmentEntity.agent_id == agent_id
        )
    ).all()
    return [str(item) for item in rows if str(item).strip()]


def _replace_departments(
    session: Session,
    agent_id: str,
    departments: list[str],
) -> list[str]:
    session.execute(
        delete(SharedAgentDepartmentEntity).where(
            SharedAgentDepartmentEntity.agent_id == agent_id
        )
    )
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in departments:
        dept = str(item or "").strip()
        if not dept or dept in seen:
            continue
        seen.add(dept)
        cleaned.append(dept)
        session.add(
            SharedAgentDepartmentEntity(agent_id=agent_id, department=dept)
        )
    return cleaned


def _agent_card(
    agent: SharedAgentEntity,
    *,
    departments: list[str],
    pinned: bool = False,
    include_spec: bool = False,
) -> dict[str, Any]:
    card: dict[str, Any] = {
        "agent_id": agent.agent_id,
        "owner_onec_uid": agent.owner_onec_uid,
        "owner_department": agent.owner_department,
        "name": agent.name,
        "description": agent.description,
        "short_description": agent.short_description,
        "visibility": agent.visibility,
        "departments": departments,
        "image_object_key": agent.image_object_key,
        "has_image": bool(agent.image_object_key),
        "pinned": pinned,
        "created_at": agent.created_at.isoformat() if agent.created_at else None,
        "updated_at": agent.updated_at.isoformat() if agent.updated_at else None,
        "published_at": agent.published_at.isoformat() if agent.published_at else None,
    }
    if include_spec:
        try:
            card["agent_spec"] = json.loads(agent.agent_spec_json or "{}")
        except json.JSONDecodeError:
            card["agent_spec"] = {}
            card["agent_spec_error"] = "invalid_json"
    return card


def _ensure_access(
    session: Session,
    user: UserEntity,
    agent: SharedAgentEntity,
) -> list[str]:
    departments = _departments_for_agent(session, agent.agent_id)
    if not user_can_access_agent(user, agent, selected_departments=departments):
        raise HTTPException(status_code=404, detail="Агент не найден или недоступен")
    return departments


def _ensure_owner(user: UserEntity, agent: SharedAgentEntity) -> None:
    if agent.owner_onec_uid != user.onec_uid:
        raise HTTPException(status_code=403, detail="Только владелец может изменить агента")


@router.get("/v1/departments")
def list_departments(user: UserEntity = Depends(get_current_user)) -> dict[str, Any]:
    """Список отделов из app_users для UI выбора доступа."""
    _ = user
    session = _db_session()
    try:
        rows = session.scalars(
            select(UserEntity.department)
            .where(UserEntity.department != "")
            .distinct()
            .order_by(UserEntity.department)
        ).all()
        departments = sorted({str(item).strip() for item in rows if str(item).strip()})
        return {"departments": departments}
    finally:
        session.close()


@router.post("/v1/agents/catalog")
def publish_agent(
    body: PublishAgentRequest,
    user: UserEntity = Depends(get_current_user),
) -> dict[str, Any]:
    """Опубликовать или обновить своего агента в каталоге."""
    if body.visibility == VISIBILITY_SELECTED and not any(
        str(d).strip() for d in body.departments
    ):
        raise HTTPException(
            status_code=422,
            detail="Для visibility=selected укажите хотя бы один отдел",
        )

    session = _db_session()
    try:
        agent = session.get(SharedAgentEntity, body.agent_id)
        now = _utcnow()
        if agent is None:
            agent = SharedAgentEntity(
                agent_id=body.agent_id,
                owner_onec_uid=user.onec_uid,
                owner_department=(user.department or "").strip(),
                created_at=now,
                published_at=now,
            )
            session.add(agent)
        else:
            _ensure_owner(user, agent)

        agent.name = body.name.strip()
        agent.description = body.description or ""
        agent.short_description = (body.short_description or "")[:512]
        agent.agent_spec_json = json.dumps(body.agent_spec, ensure_ascii=False, default=str)
        agent.visibility = body.visibility
        agent.owner_department = (user.department or "").strip()
        if body.image_object_key:
            agent.image_object_key = body.image_object_key.strip()
        agent.updated_at = now
        agent.published_at = now

        departments: list[str] = []
        if body.visibility == VISIBILITY_SELECTED:
            departments = _replace_departments(session, body.agent_id, body.departments)
        else:
            _replace_departments(session, body.agent_id, [])

        # Автопин владельца
        existing_pin = session.scalar(
            select(UserAgentPinEntity).where(
                UserAgentPinEntity.onec_uid == user.onec_uid,
                UserAgentPinEntity.agent_id == body.agent_id,
            )
        )
        if existing_pin is None:
            session.add(
                UserAgentPinEntity(
                    onec_uid=user.onec_uid,
                    agent_id=body.agent_id,
                    pinned_at=now,
                )
            )

        session.commit()
        session.refresh(agent)
        return {
            "ok": True,
            "agent": _agent_card(agent, departments=departments, pinned=True),
        }
    except HTTPException:
        session.rollback()
        raise
    except Exception:
        session.rollback()
        logger.exception("publish_agent failed")
        raise
    finally:
        session.close()


@router.get("/v1/agents/catalog")
def list_catalog(
    include_spec: bool = Query(default=False),
    user: UserEntity = Depends(get_current_user),
) -> dict[str, Any]:
    """Список агентов, доступных текущему пользователю."""
    session = _db_session()
    try:
        agents = session.scalars(select(SharedAgentEntity)).all()
        pin_ids = set(
            session.scalars(
                select(UserAgentPinEntity.agent_id).where(
                    UserAgentPinEntity.onec_uid == user.onec_uid
                )
            ).all()
        )
        cards: list[dict[str, Any]] = []
        for agent in agents:
            departments = _departments_for_agent(session, agent.agent_id)
            if not user_can_access_agent(user, agent, selected_departments=departments):
                continue
            cards.append(
                _agent_card(
                    agent,
                    departments=departments,
                    pinned=agent.agent_id in pin_ids,
                    include_spec=include_spec,
                )
            )
        cards.sort(key=lambda item: (item.get("name") or "", item.get("agent_id") or ""))
        return {"agents": cards, "count": len(cards)}
    finally:
        session.close()


@router.get("/v1/agents/catalog/{agent_id}")
def get_catalog_agent(
    agent_id: str,
    user: UserEntity = Depends(get_current_user),
) -> dict[str, Any]:
    """Полный AgentSpec, если ACL позволяет."""
    safe_id = _validate_agent_id(agent_id)
    session = _db_session()
    try:
        agent = session.get(SharedAgentEntity, safe_id)
        if agent is None:
            raise HTTPException(status_code=404, detail="Агент не найден")
        departments = _ensure_access(session, user, agent)
        pinned = (
            session.scalar(
                select(UserAgentPinEntity.id).where(
                    UserAgentPinEntity.onec_uid == user.onec_uid,
                    UserAgentPinEntity.agent_id == safe_id,
                )
            )
            is not None
        )
        return {
            "agent": _agent_card(
                agent,
                departments=departments,
                pinned=pinned,
                include_spec=True,
            )
        }
    finally:
        session.close()


@router.patch("/v1/agents/catalog/{agent_id}/access")
def patch_access(
    agent_id: str,
    body: AccessPatchRequest,
    user: UserEntity = Depends(get_current_user),
) -> dict[str, Any]:
    """Сменить visibility (только владелец)."""
    safe_id = _validate_agent_id(agent_id)
    if body.visibility == VISIBILITY_SELECTED and not any(
        str(d).strip() for d in body.departments
    ):
        raise HTTPException(
            status_code=422,
            detail="Для visibility=selected укажите хотя бы один отдел",
        )
    session = _db_session()
    try:
        agent = session.get(SharedAgentEntity, safe_id)
        if agent is None:
            raise HTTPException(status_code=404, detail="Агент не найден")
        _ensure_owner(user, agent)
        agent.visibility = body.visibility
        agent.updated_at = _utcnow()
        departments: list[str] = []
        if body.visibility == VISIBILITY_SELECTED:
            departments = _replace_departments(session, safe_id, body.departments)
        else:
            _replace_departments(session, safe_id, [])
        session.commit()
        session.refresh(agent)
        return {"ok": True, "agent": _agent_card(agent, departments=departments)}
    except HTTPException:
        session.rollback()
        raise
    finally:
        session.close()


@router.delete("/v1/agents/catalog/{agent_id}")
def delete_catalog_agent(
    agent_id: str,
    user: UserEntity = Depends(get_current_user),
) -> dict[str, Any]:
    """Снять агента с каталога (только владелец)."""
    safe_id = _validate_agent_id(agent_id)
    session = _db_session()
    try:
        agent = session.get(SharedAgentEntity, safe_id)
        if agent is None:
            raise HTTPException(status_code=404, detail="Агент не найден")
        _ensure_owner(user, agent)
        session.execute(
            delete(SharedAgentDepartmentEntity).where(
                SharedAgentDepartmentEntity.agent_id == safe_id
            )
        )
        session.execute(
            delete(UserAgentPinEntity).where(UserAgentPinEntity.agent_id == safe_id)
        )
        session.delete(agent)
        session.commit()
        return {"ok": True, "agent_id": safe_id}
    except HTTPException:
        session.rollback()
        raise
    finally:
        session.close()


@router.get("/v1/agents/pins")
def list_pins(user: UserEntity = Depends(get_current_user)) -> dict[str, Any]:
    """Закреплённые агенты текущего пользователя (с метаданными, если ACL ок)."""
    session = _db_session()
    try:
        pins = session.scalars(
            select(UserAgentPinEntity)
            .where(UserAgentPinEntity.onec_uid == user.onec_uid)
            .order_by(UserAgentPinEntity.pinned_at.desc())
        ).all()
        agents: list[dict[str, Any]] = []
        agent_ids: list[str] = []
        for pin in pins:
            agent = session.get(SharedAgentEntity, pin.agent_id)
            if agent is None:
                continue
            departments = _departments_for_agent(session, agent.agent_id)
            if not user_can_access_agent(user, agent, selected_departments=departments):
                continue
            agent_ids.append(agent.agent_id)
            agents.append(
                _agent_card(agent, departments=departments, pinned=True)
            )
        return {"agent_ids": agent_ids, "agents": agents}
    finally:
        session.close()


@router.put("/v1/agents/pins")
def replace_pins(
    body: PinsPutRequest,
    user: UserEntity = Depends(get_current_user),
) -> dict[str, Any]:
    """Заменить набор закреплённых агентов (галочки в каталоге)."""
    session = _db_session()
    try:
        wanted: list[str] = []
        seen: set[str] = set()
        for raw in body.agent_ids:
            agent_id = _validate_agent_id(raw)
            if agent_id in seen:
                continue
            agent = session.get(SharedAgentEntity, agent_id)
            if agent is None:
                raise HTTPException(
                    status_code=404, detail=f"Агент не найден: {agent_id}"
                )
            departments = _ensure_access(session, user, agent)
            _ = departments
            seen.add(agent_id)
            wanted.append(agent_id)

        session.execute(
            delete(UserAgentPinEntity).where(
                UserAgentPinEntity.onec_uid == user.onec_uid
            )
        )
        now = _utcnow()
        for agent_id in wanted:
            session.add(
                UserAgentPinEntity(
                    onec_uid=user.onec_uid,
                    agent_id=agent_id,
                    pinned_at=now,
                )
            )
        session.commit()
        return {"ok": True, "agent_ids": wanted}
    except HTTPException:
        session.rollback()
        raise
    finally:
        session.close()


@router.post("/v1/agents/runs/summary")
def upsert_run_summary(
    body: RunSummaryRequest,
    user: UserEntity = Depends(get_current_user),
) -> dict[str, Any]:
    """Создать или обновить сводку запуска текущего пользователя."""
    session = _db_session()
    try:
        row = session.get(AgentRunSummaryEntity, body.run_id)
        now = _utcnow()
        if row is None:
            row = AgentRunSummaryEntity(
                run_id=body.run_id.strip(),
                agent_id=body.agent_id,
                onec_uid=user.onec_uid,
                status=body.status,
                title=(body.title or "")[:512],
                message=body.message or "",
                started_at=body.started_at or now,
                finished_at=body.finished_at,
                updated_at=now,
            )
            session.add(row)
        else:
            if row.onec_uid != user.onec_uid:
                raise HTTPException(status_code=403, detail="Чужая сводка запуска")
            row.agent_id = body.agent_id
            row.status = body.status
            row.title = (body.title or row.title or "")[:512]
            if body.message:
                row.message = body.message
            if body.started_at is not None:
                row.started_at = body.started_at
            if body.finished_at is not None:
                row.finished_at = body.finished_at
            row.updated_at = now
        session.commit()
        return {
            "ok": True,
            "run": {
                "run_id": row.run_id,
                "agent_id": row.agent_id,
                "status": row.status,
                "title": row.title,
                "message": row.message,
                "started_at": row.started_at.isoformat() if row.started_at else None,
                "finished_at": row.finished_at.isoformat() if row.finished_at else None,
            },
        }
    except HTTPException:
        session.rollback()
        raise
    finally:
        session.close()


@router.get("/v1/agents/runs/mine")
def list_my_runs(
    limit: int = Query(default=100, ge=1, le=500),
    user: UserEntity = Depends(get_current_user),
) -> dict[str, Any]:
    """История обращений текущего пользователя."""
    session = _db_session()
    try:
        rows = session.scalars(
            select(AgentRunSummaryEntity)
            .where(AgentRunSummaryEntity.onec_uid == user.onec_uid)
            .order_by(AgentRunSummaryEntity.started_at.desc())
            .limit(limit)
        ).all()
        runs = [
            {
                "run_id": row.run_id,
                "agent_id": row.agent_id,
                "status": row.status,
                "title": row.title,
                "message": row.message,
                "started_at": row.started_at.isoformat() if row.started_at else None,
                "finished_at": row.finished_at.isoformat() if row.finished_at else None,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            }
            for row in rows
        ]
        return {"runs": runs, "count": len(runs)}
    finally:
        session.close()
