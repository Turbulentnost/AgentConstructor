"""Кэш AgentSpec из серверного каталога в локальный SQLite."""

from __future__ import annotations

from agent_desktop_constructor.app.auth.client import AuthSession
from agent_desktop_constructor.app.catalog.client import CatalogClient, CatalogClientError
from agent_desktop_constructor.app.core.services.agent_application_service import (
    AgentApplicationService,
)
from agent_desktop_constructor.core.models.agent_spec import AgentSpec


def ensure_local_agent_from_catalog(
    service: AgentApplicationService,
    session: AuthSession,
    agent_id: str,
) -> AgentSpec:
    """Скачать полный spec с сервера и сохранить локально для запуска."""
    client = CatalogClient.from_session(session)
    card = client.get_agent(session.access_token, agent_id)
    if not card.agent_spec:
        raise CatalogClientError("Сервер вернул агента без agent_spec")
    spec = AgentSpec.model_validate(card.agent_spec)
    service.save_agent(spec)
    return spec
