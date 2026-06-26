"""Репозитории локального SQLite-хранилища."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from agent_desktop_constructor.core.models.agent_spec import AgentSpec
from agent_desktop_constructor.core.models.runtime_state import (
    AgentRunStatus,
    AgentRuntimeState,
)
from agent_desktop_constructor.storage.entities import (
    AgentEntity,
    AgentRunEntity,
    AuditLogEntity,
    ToolCallLogEntity,
)


FINAL_RUN_STATUSES = {
    AgentRunStatus.COMPLETED,
    AgentRunStatus.FAILED,
    AgentRunStatus.CANCELLED,
}


def utc_now() -> datetime:
    """Вернуть текущее UTC-время для обновления записей."""
    return datetime.now(timezone.utc)


def to_json_text(model_or_dict: BaseModel | dict[str, Any]) -> str:
    """Сериализовать Pydantic-модель или dict в JSON-текст без потери кириллицы."""
    if isinstance(model_or_dict, BaseModel):
        payload = model_or_dict.model_dump(mode="json")
    elif isinstance(model_or_dict, dict):
        payload = model_or_dict
    else:
        raise ValueError("to_json_text принимает только Pydantic-модель или dict")

    return json.dumps(payload, ensure_ascii=False)


def from_json_text(text: str) -> dict[str, Any]:
    """Прочитать JSON-текст и вернуть dict с понятной ошибкой при проблеме."""
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Некорректный JSON: {exc.msg}") from exc

    if not isinstance(payload, dict):
        raise ValueError("JSON должен содержать объект")
    return payload


class AgentRepository:
    """Репозиторий для сохранения и загрузки AgentSpec."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        """Сохранить фабрику сессий."""
        self._session_factory = session_factory

    def save_agent(self, agent_spec: AgentSpec) -> None:
        """Создать или обновить запись агента."""
        now = utc_now()
        agent_spec_json = to_json_text(agent_spec)

        with self._session_factory() as session:
            entity = session.get(AgentEntity, agent_spec.agent_id)
            if entity is None:
                entity = AgentEntity(
                    agent_id=agent_spec.agent_id,
                    name=agent_spec.name,
                    description=agent_spec.description,
                    agent_spec_json=agent_spec_json,
                    created_at=now,
                    updated_at=now,
                )
                session.add(entity)
            else:
                entity.name = agent_spec.name
                entity.description = agent_spec.description
                entity.agent_spec_json = agent_spec_json
                entity.updated_at = now
            session.commit()

    def get_agent(self, agent_id: str) -> AgentSpec:
        """Загрузить AgentSpec по agent_id."""
        with self._session_factory() as session:
            entity = session.get(AgentEntity, agent_id)
            if entity is None:
                raise ValueError(f"Агент с agent_id={agent_id!r} не найден")
            return AgentSpec.model_validate(from_json_text(entity.agent_spec_json))

    def list_agents(self) -> list[AgentSpec]:
        """Вернуть все сохраненные AgentSpec."""
        with self._session_factory() as session:
            entities = session.scalars(
                select(AgentEntity).order_by(AgentEntity.created_at)
            ).all()
            return [
                AgentSpec.model_validate(from_json_text(entity.agent_spec_json))
                for entity in entities
            ]


class AgentRunRepository:
    """Репозиторий для состояния конкретных запусков агента."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        """Сохранить фабрику сессий."""
        self._session_factory = session_factory

    def create_run(
        self,
        agent_spec: AgentSpec,
        initial_state: AgentRuntimeState,
    ) -> None:
        """Создать запись запуска агента с начальным состоянием."""
        now = utc_now()
        with self._session_factory() as session:
            entity = AgentRunEntity(
                run_id=initial_state.run_id,
                agent_id=agent_spec.agent_id,
                status=initial_state.status.value,
                current_node_id=initial_state.current_node_id,
                state_json=to_json_text(initial_state),
                created_at=now,
                updated_at=now,
                finished_at=self._finished_at_for_status(initial_state.status),
            )
            session.add(entity)
            session.commit()

    def save_state(self, run_id: str, state: AgentRuntimeState) -> None:
        """Сохранить полное состояние существующего запуска."""
        with self._session_factory() as session:
            entity = session.get(AgentRunEntity, run_id)
            if entity is None:
                raise ValueError(f"Запуск с run_id={run_id!r} не найден")

            entity.status = state.status.value
            entity.current_node_id = state.current_node_id
            entity.state_json = to_json_text(state)
            entity.updated_at = utc_now()
            self._set_finished_at_if_needed(entity, state.status)
            session.commit()

    def get_state(self, run_id: str) -> AgentRuntimeState:
        """Загрузить состояние запуска по run_id."""
        with self._session_factory() as session:
            entity = session.get(AgentRunEntity, run_id)
            if entity is None:
                raise ValueError(f"Запуск с run_id={run_id!r} не найден")
            return AgentRuntimeState.model_validate(from_json_text(entity.state_json))

    def list_runs(self, agent_id: str) -> list[AgentRuntimeState]:
        """Вернуть состояния запусков конкретного агента."""
        with self._session_factory() as session:
            entities = session.scalars(
                select(AgentRunEntity)
                .where(AgentRunEntity.agent_id == agent_id)
                .order_by(AgentRunEntity.created_at)
            ).all()
            return [
                AgentRuntimeState.model_validate(from_json_text(entity.state_json))
                for entity in entities
            ]

    def update_status(self, run_id: str, status: AgentRunStatus) -> None:
        """Обновить только статус запуска и timestamp."""
        with self._session_factory() as session:
            entity = session.get(AgentRunEntity, run_id)
            if entity is None:
                raise ValueError(f"Запуск с run_id={run_id!r} не найден")

            state = AgentRuntimeState.model_validate(from_json_text(entity.state_json))
            state.status = status
            entity.status = status.value
            entity.state_json = to_json_text(state)
            entity.updated_at = utc_now()
            self._set_finished_at_if_needed(entity, status)
            session.commit()

    def _finished_at_for_status(self, status: AgentRunStatus) -> datetime | None:
        """Вернуть finished_at для финального статуса."""
        if status in FINAL_RUN_STATUSES:
            return utc_now()
        return None

    def _set_finished_at_if_needed(
        self,
        entity: AgentRunEntity,
        status: AgentRunStatus,
    ) -> None:
        """Установить finished_at один раз при переходе в финальный статус."""
        if status in FINAL_RUN_STATUSES and entity.finished_at is None:
            entity.finished_at = utc_now()


class ToolCallLogRepository:
    """Репозиторий журнала вызовов инструментов."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        """Сохранить фабрику сессий."""
        self._session_factory = session_factory

    def add_tool_call(
        self,
        run_id: str,
        tool_name: str,
        input_data: dict,
        output_data: dict | None,
        ok: bool,
        error_type: str | None = None,
        error_message: str | None = None,
    ) -> None:
        """Сохранить отдельный вызов инструмента."""
        entity = ToolCallLogEntity(
            run_id=run_id,
            tool_name=tool_name,
            input_json=to_json_text(input_data),
            output_json=to_json_text(output_data) if output_data is not None else None,
            ok=ok,
            error_type=error_type,
            error_message=error_message,
        )
        with self._session_factory() as session:
            session.add(entity)
            session.commit()

    def list_tool_calls(self, run_id: str) -> list[dict[str, Any]]:
        """Вернуть журнал вызовов инструментов для запуска."""
        with self._session_factory() as session:
            entities = session.scalars(
                select(ToolCallLogEntity)
                .where(ToolCallLogEntity.run_id == run_id)
                .order_by(ToolCallLogEntity.id)
            ).all()
            return [
                {
                    "id": entity.id,
                    "run_id": entity.run_id,
                    "tool_name": entity.tool_name,
                    "input_data": from_json_text(entity.input_json),
                    "output_data": (
                        from_json_text(entity.output_json)
                        if entity.output_json is not None
                        else None
                    ),
                    "ok": entity.ok,
                    "error_type": entity.error_type,
                    "error_message": entity.error_message,
                    "created_at": entity.created_at.isoformat(),
                }
                for entity in entities
            ]


class AuditLogRepository:
    """Репозиторий общего журнала действий приложения."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        """Сохранить фабрику сессий."""
        self._session_factory = session_factory

    def add_log(
        self,
        action: str,
        details: dict,
        run_id: str | None = None,
    ) -> None:
        """Сохранить событие аудита."""
        entity = AuditLogEntity(
            run_id=run_id,
            action=action,
            details_json=to_json_text(details),
        )
        with self._session_factory() as session:
            session.add(entity)
            session.commit()

    def list_logs(self, run_id: str | None = None) -> list[dict[str, Any]]:
        """Вернуть события аудита, при необходимости только для одного запуска."""
        statement = select(AuditLogEntity).order_by(AuditLogEntity.id)
        if run_id is not None:
            statement = statement.where(AuditLogEntity.run_id == run_id)

        with self._session_factory() as session:
            entities = session.scalars(statement).all()
            return [
                {
                    "id": entity.id,
                    "run_id": entity.run_id,
                    "action": entity.action,
                    "details": from_json_text(entity.details_json),
                    "created_at": entity.created_at.isoformat(),
                }
                for entity in entities
            ]
