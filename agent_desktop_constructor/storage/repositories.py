"""Репозитории локального SQLite-хранилища."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from agent_desktop_constructor.app.core.models.human_approval import (
    HumanApprovalRecord,
    HumanApprovalStatus,
)
from agent_desktop_constructor.app.core.models.run_events import AgentRunEvent
from agent_desktop_constructor.core.models.agent_spec import AgentSpec
from agent_desktop_constructor.core.models.runtime_state import (
    AgentRunStatus,
    AgentRuntimeState,
)
from agent_desktop_constructor.storage.entities import (
    AgentEntity,
    AgentRunEventEntity,
    AgentRunEntity,
    AuditLogEntity,
    HumanApprovalRequestEntity,
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


class RunEventRepository:
    """Репозиторий журнала событий выполнения агента."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        """Сохранить фабрику сессий."""
        self._session_factory = session_factory

    def add_event(self, event: AgentRunEvent) -> None:
        """Сохранить событие выполнения агента."""
        entity = AgentRunEventEntity(
            event_id=event.event_id,
            run_id=event.run_id,
            event_type=event.event_type.value,
            node_id=event.node_id,
            tool_name=event.tool_name,
            message=event.message,
            details_json=to_json_text(event.details),
            created_at=event.created_at,
        )
        with self._session_factory() as session:
            session.add(entity)
            session.commit()

    def list_events(self, run_id: str) -> list[AgentRunEvent]:
        """Вернуть события запуска в порядке создания."""
        with self._session_factory() as session:
            entities = session.scalars(
                select(AgentRunEventEntity)
                .where(AgentRunEventEntity.run_id == run_id)
                .order_by(AgentRunEventEntity.created_at, AgentRunEventEntity.id)
            ).all()
            return [self._to_event(entity) for entity in entities]

    def list_recent_events(self, limit: int = 100) -> list[AgentRunEvent]:
        """Вернуть последние события выполнения."""
        safe_limit = max(1, int(limit))
        with self._session_factory() as session:
            entities = session.scalars(
                select(AgentRunEventEntity)
                .order_by(
                    AgentRunEventEntity.created_at.desc(),
                    AgentRunEventEntity.id.desc(),
                )
                .limit(safe_limit)
            ).all()
            return [self._to_event(entity) for entity in entities]

    def delete_events_for_run(self, run_id: str) -> None:
        """Удалить события конкретного запуска."""
        with self._session_factory() as session:
            entities = session.scalars(
                select(AgentRunEventEntity).where(
                    AgentRunEventEntity.run_id == run_id
                )
            ).all()
            for entity in entities:
                session.delete(entity)
            session.commit()

    def _to_event(self, entity: AgentRunEventEntity) -> AgentRunEvent:
        """Восстановить AgentRunEvent из ORM entity."""
        try:
            details = from_json_text(entity.details_json)
        except ValueError as exc:
            raise ValueError(
                f"Некорректный details_json события {entity.event_id!r}: {exc}"
            ) from exc

        return AgentRunEvent.model_validate(
            {
                "event_id": entity.event_id,
                "run_id": entity.run_id,
                "event_type": entity.event_type,
                "node_id": entity.node_id,
                "tool_name": entity.tool_name,
                "message": entity.message,
                "details": details,
                "created_at": entity.created_at,
            }
        )


class HumanApprovalRepository:
    """Репозиторий очереди подтверждений человека."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        """Сохранить фабрику сессий."""
        self._session_factory = session_factory

    def create_request(self, record: HumanApprovalRecord) -> None:
        """Создать pending-запрос подтверждения."""
        with self._session_factory() as session:
            if session.get(HumanApprovalRequestEntity, record.approval_id) is not None:
                raise ValueError(
                    f"Запрос подтверждения {record.approval_id!r} уже существует"
                )

            entity = HumanApprovalRequestEntity(
                approval_id=record.approval_id,
                run_id=record.run_id,
                agent_id=record.agent_id,
                node_id=record.node_id,
                tool_name=record.tool_name,
                question=record.question,
                options_json=self._options_to_json(record.options),
                status=record.status.value,
                selected_option=record.selected_option,
                comment=record.comment,
                created_at=record.created_at,
                answered_at=record.answered_at,
            )
            session.add(entity)
            session.commit()

    def get_request(self, approval_id: str) -> HumanApprovalRecord:
        """Вернуть запрос подтверждения по approval_id."""
        with self._session_factory() as session:
            entity = session.get(HumanApprovalRequestEntity, approval_id)
            if entity is None:
                raise ValueError(
                    f"Запрос подтверждения с approval_id={approval_id!r} не найден"
                )
            return self._to_record(entity)

    def list_pending(self, agent_id: str | None = None) -> list[HumanApprovalRecord]:
        """Вернуть pending-запросы, при необходимости только для одного агента."""
        statement = (
            select(HumanApprovalRequestEntity)
            .where(HumanApprovalRequestEntity.status == HumanApprovalStatus.PENDING.value)
            .order_by(HumanApprovalRequestEntity.created_at)
        )
        if agent_id is not None:
            statement = statement.where(HumanApprovalRequestEntity.agent_id == agent_id)

        with self._session_factory() as session:
            entities = session.scalars(statement).all()
            return [self._to_record(entity) for entity in entities]

    def list_for_run(self, run_id: str) -> list[HumanApprovalRecord]:
        """Вернуть все запросы подтверждения конкретного запуска."""
        with self._session_factory() as session:
            entities = session.scalars(
                select(HumanApprovalRequestEntity)
                .where(HumanApprovalRequestEntity.run_id == run_id)
                .order_by(HumanApprovalRequestEntity.created_at)
            ).all()
            return [self._to_record(entity) for entity in entities]

    def answer_request(
        self,
        approval_id: str,
        status: HumanApprovalStatus,
        selected_option: str,
        comment: str | None = None,
    ) -> HumanApprovalRecord:
        """Зафиксировать решение человека по pending-запросу."""
        if status not in {HumanApprovalStatus.APPROVED, HumanApprovalStatus.REJECTED}:
            raise ValueError("status должен быть approved или rejected")
        if not selected_option.strip():
            raise ValueError("selected_option не должен быть пустым")

        with self._session_factory() as session:
            entity = session.get(HumanApprovalRequestEntity, approval_id)
            if entity is None:
                raise ValueError(
                    f"Запрос подтверждения с approval_id={approval_id!r} не найден"
                )
            self._ensure_pending(entity)
            entity.status = status.value
            entity.selected_option = selected_option
            entity.comment = comment
            entity.answered_at = utc_now()
            session.commit()
            session.refresh(entity)
            return self._to_record(entity)

    def cancel_request(
        self,
        approval_id: str,
        comment: str | None = None,
    ) -> HumanApprovalRecord:
        """Отменить pending-запрос подтверждения."""
        with self._session_factory() as session:
            entity = session.get(HumanApprovalRequestEntity, approval_id)
            if entity is None:
                raise ValueError(
                    f"Запрос подтверждения с approval_id={approval_id!r} не найден"
                )
            self._ensure_pending(entity)
            entity.status = HumanApprovalStatus.CANCELLED.value
            entity.comment = comment
            entity.answered_at = utc_now()
            session.commit()
            session.refresh(entity)
            return self._to_record(entity)

    def _to_record(self, entity: HumanApprovalRequestEntity) -> HumanApprovalRecord:
        """Восстановить HumanApprovalRecord из ORM entity."""
        return HumanApprovalRecord.model_validate(
            {
                "approval_id": entity.approval_id,
                "run_id": entity.run_id,
                "agent_id": entity.agent_id,
                "node_id": entity.node_id,
                "tool_name": entity.tool_name,
                "question": entity.question,
                "options": self._options_from_json(
                    entity.options_json,
                    entity.approval_id,
                ),
                "status": entity.status,
                "selected_option": entity.selected_option,
                "comment": entity.comment,
                "created_at": entity.created_at,
                "answered_at": entity.answered_at,
            }
        )

    def _ensure_pending(self, entity: HumanApprovalRequestEntity) -> None:
        """Проверить, что запрос ещё ожидает решения."""
        if entity.status != HumanApprovalStatus.PENDING.value:
            raise ValueError(
                f"Запрос подтверждения {entity.approval_id!r} уже обработан: "
                f"{entity.status}"
            )

    def _options_to_json(self, options: list[str]) -> str:
        """Сериализовать options без потери кириллицы."""
        return json.dumps(options, ensure_ascii=False)

    def _options_from_json(self, text: str, approval_id: str) -> list[str]:
        """Прочитать options_json с понятной ошибкой."""
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Некорректный options_json запроса {approval_id!r}: {exc.msg}"
            ) from exc
        if not isinstance(payload, list) or not all(
            isinstance(item, str) for item in payload
        ):
            raise ValueError(
                f"options_json запроса {approval_id!r} должен содержать список строк"
            )
        return payload


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
