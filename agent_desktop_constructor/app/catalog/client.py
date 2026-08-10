"""HTTP-клиент каталога агентов, pins и сводок запусков."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx

from agent_desktop_constructor.app.auth.client import AuthSession


class CatalogClientError(RuntimeError):
    """Ошибка API каталога агентов."""


@dataclass
class CatalogAgentCard:
    """Карточка агента из /v1/agents/catalog."""

    agent_id: str
    name: str
    description: str = ""
    short_description: str = ""
    visibility: str = "private"
    departments: list[str] = field(default_factory=list)
    owner_onec_uid: str = ""
    owner_department: str = ""
    pinned: bool = False
    has_image: bool = False
    agent_spec: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CatalogAgentCard:
        departments = data.get("departments") or []
        return cls(
            agent_id=str(data.get("agent_id") or ""),
            name=str(data.get("name") or ""),
            description=str(data.get("description") or ""),
            short_description=str(data.get("short_description") or ""),
            visibility=str(data.get("visibility") or "private"),
            departments=[str(item) for item in departments if str(item).strip()],
            owner_onec_uid=str(data.get("owner_onec_uid") or ""),
            owner_department=str(data.get("owner_department") or ""),
            pinned=bool(data.get("pinned")),
            has_image=bool(data.get("has_image")),
            agent_spec=data.get("agent_spec")
            if isinstance(data.get("agent_spec"), dict)
            else None,
        )


@dataclass
class RunSummary:
    """Сводка запуска из /v1/agents/runs/mine."""

    run_id: str
    agent_id: str
    status: str
    title: str = ""
    message: str = ""
    started_at: str | None = None
    finished_at: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RunSummary:
        return cls(
            run_id=str(data.get("run_id") or ""),
            agent_id=str(data.get("agent_id") or ""),
            status=str(data.get("status") or ""),
            title=str(data.get("title") or ""),
            message=str(data.get("message") or ""),
            started_at=data.get("started_at"),
            finished_at=data.get("finished_at"),
        )


class CatalogClient:
    """Клиент к llm_proxy agents catalog API."""

    def __init__(self, proxy_base_url: str, *, timeout: float = 30.0) -> None:
        self.base_url = proxy_base_url.rstrip("/")
        self.timeout = timeout

    @classmethod
    def from_session(cls, session: AuthSession) -> CatalogClient:
        if not session.proxy_url:
            raise CatalogClientError("В сессии нет proxy_url")
        return cls(session.proxy_url)

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def _headers(self, token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    def list_departments(self, token: str) -> list[str]:
        response = httpx.get(
            self._url("/v1/departments"),
            headers=self._headers(token),
            timeout=self.timeout,
        )
        if response.status_code >= 400:
            raise CatalogClientError(_error_detail(response))
        payload = response.json()
        return [str(item) for item in (payload.get("departments") or []) if str(item).strip()]

    def publish_agent(
        self,
        token: str,
        *,
        agent_id: str,
        name: str,
        description: str,
        short_description: str,
        agent_spec: dict[str, Any],
        visibility: str,
        departments: list[str] | None = None,
        image_object_key: str = "",
    ) -> CatalogAgentCard:
        response = httpx.post(
            self._url("/v1/agents/catalog"),
            headers=self._headers(token),
            json={
                "agent_id": agent_id,
                "name": name,
                "description": description,
                "short_description": short_description,
                "agent_spec": agent_spec,
                "visibility": visibility,
                "departments": departments or [],
                "image_object_key": image_object_key,
            },
            timeout=max(self.timeout, 60.0),
        )
        if response.status_code >= 400:
            raise CatalogClientError(_error_detail(response))
        payload = response.json()
        return CatalogAgentCard.from_dict(dict(payload.get("agent") or {}))

    def list_catalog(
        self, token: str, *, include_spec: bool = False
    ) -> list[CatalogAgentCard]:
        response = httpx.get(
            self._url("/v1/agents/catalog"),
            headers=self._headers(token),
            params={"include_spec": include_spec},
            timeout=self.timeout,
        )
        if response.status_code >= 400:
            raise CatalogClientError(_error_detail(response))
        payload = response.json()
        return [
            CatalogAgentCard.from_dict(item)
            for item in (payload.get("agents") or [])
            if isinstance(item, dict)
        ]

    def get_agent(self, token: str, agent_id: str) -> CatalogAgentCard:
        response = httpx.get(
            self._url(f"/v1/agents/catalog/{agent_id}"),
            headers=self._headers(token),
            timeout=self.timeout,
        )
        if response.status_code >= 400:
            raise CatalogClientError(_error_detail(response))
        payload = response.json()
        return CatalogAgentCard.from_dict(dict(payload.get("agent") or {}))

    def list_pins(self, token: str) -> list[CatalogAgentCard]:
        response = httpx.get(
            self._url("/v1/agents/pins"),
            headers=self._headers(token),
            timeout=self.timeout,
        )
        if response.status_code >= 400:
            raise CatalogClientError(_error_detail(response))
        payload = response.json()
        return [
            CatalogAgentCard.from_dict(item)
            for item in (payload.get("agents") or [])
            if isinstance(item, dict)
        ]

    def replace_pins(self, token: str, agent_ids: list[str]) -> list[str]:
        response = httpx.put(
            self._url("/v1/agents/pins"),
            headers=self._headers(token),
            json={"agent_ids": agent_ids},
            timeout=self.timeout,
        )
        if response.status_code >= 400:
            raise CatalogClientError(_error_detail(response))
        payload = response.json()
        return [str(item) for item in (payload.get("agent_ids") or [])]

    def upsert_run_summary(
        self,
        token: str,
        *,
        run_id: str,
        agent_id: str,
        status: str,
        title: str = "",
        message: str = "",
        started_at: datetime | str | None = None,
        finished_at: datetime | str | None = None,
    ) -> RunSummary:
        payload: dict[str, Any] = {
            "run_id": run_id,
            "agent_id": agent_id,
            "status": status,
            "title": title,
            "message": message,
        }
        if started_at is not None:
            payload["started_at"] = (
                started_at.isoformat()
                if isinstance(started_at, datetime)
                else started_at
            )
        if finished_at is not None:
            payload["finished_at"] = (
                finished_at.isoformat()
                if isinstance(finished_at, datetime)
                else finished_at
            )
        response = httpx.post(
            self._url("/v1/agents/runs/summary"),
            headers=self._headers(token),
            json=payload,
            timeout=self.timeout,
        )
        if response.status_code >= 400:
            raise CatalogClientError(_error_detail(response))
        body = response.json()
        return RunSummary.from_dict(dict(body.get("run") or {}))

    def list_my_runs(self, token: str, *, limit: int = 100) -> list[RunSummary]:
        response = httpx.get(
            self._url("/v1/agents/runs/mine"),
            headers=self._headers(token),
            params={"limit": limit},
            timeout=self.timeout,
        )
        if response.status_code >= 400:
            raise CatalogClientError(_error_detail(response))
        payload = response.json()
        return [
            RunSummary.from_dict(item)
            for item in (payload.get("runs") or [])
            if isinstance(item, dict)
        ]


def _error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
        detail = payload.get("detail") or payload.get("error")
        if isinstance(detail, list):
            return "; ".join(str(item) for item in detail)
        if detail:
            text = str(detail)
            if response.status_code == 404 and text.strip().casefold() in {
                "not found",
                "404: not found",
            }:
                return (
                    "На LLM-прокси нет API каталога агентов "
                    "(/v1/agents/catalog, /v1/agents/pins). "
                    "Перезапустите обновлённый llm_proxy_service "
                    "(с DATABASE_URL), затем войдите снова."
                )
            return text
    except Exception:
        pass
    if response.status_code == 404:
        return (
            "На LLM-прокси нет API каталога агентов. "
            "Перезапустите обновлённый llm_proxy_service."
        )
    return f"HTTP {response.status_code}: {response.text[:300]}"
