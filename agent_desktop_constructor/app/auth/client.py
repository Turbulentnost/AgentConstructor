"""HTTP-клиент и локальная сессия пользователя."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx

from agent_desktop_constructor.app.core.config import resolve_runtime_path

DEFAULT_SESSION_PATH = resolve_runtime_path("data/session.json")


@dataclass
class AuthUser:
    """Профиль пользователя из /v1/auth/me."""

    onec_uid: str
    login: str
    display_name: str
    department: str = ""
    email: str = ""
    has_avatar: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AuthUser:
        return cls(
            onec_uid=str(data.get("onec_uid") or ""),
            login=str(data.get("login") or ""),
            display_name=str(data.get("display_name") or ""),
            department=str(data.get("department") or ""),
            email=str(data.get("email") or ""),
            has_avatar=bool(data.get("has_avatar")),
        )


@dataclass
class AuthSession:
    """Локально сохранённая сессия."""

    access_token: str
    user: AuthUser
    proxy_url: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "access_token": self.access_token,
            "proxy_url": self.proxy_url,
            "user": asdict(self.user),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AuthSession:
        return cls(
            access_token=str(data.get("access_token") or ""),
            proxy_url=str(data.get("proxy_url") or ""),
            user=AuthUser.from_dict(dict(data.get("user") or {})),
        )


class AuthClientError(RuntimeError):
    """Ошибка auth API."""


@dataclass
class AuthDirectoryUser:
    """Публичная запись пользователя для выбора на экране входа."""

    login: str
    display_name: str
    department: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AuthDirectoryUser:
        return cls(
            login=str(data.get("login") or ""),
            display_name=str(data.get("display_name") or data.get("login") or ""),
            department=str(data.get("department") or ""),
        )

    @property
    def label(self) -> str:
        name = self.display_name or self.login
        if self.department:
            return f"{name} — {self.department}"
        return name


class AuthClient:
    """Клиент к llm_proxy_service auth endpoints."""

    def __init__(self, proxy_base_url: str, *, timeout: float = 30.0) -> None:
        self.base_url = proxy_base_url.rstrip("/")
        self.timeout = timeout

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def list_users(self, query: str = "", *, limit: int = 500) -> list[AuthDirectoryUser]:
        """Загрузить каталог пользователей для экрана входа."""
        response = httpx.get(
            self._url("/v1/auth/users"),
            params={"q": query, "limit": limit},
            timeout=max(self.timeout, 60.0),
        )
        if response.status_code >= 400:
            raise AuthClientError(_error_detail(response))
        payload = response.json()
        warning = str(payload.get("warning") or "").strip()
        users = [
            AuthDirectoryUser.from_dict(item)
            for item in (payload.get("users") or [])
            if isinstance(item, dict)
        ]
        if warning and not users:
            raise AuthClientError(warning)
        return users

    def login(self, login: str, password: str) -> AuthSession:
        response = httpx.post(
            self._url("/v1/auth/login"),
            json={"login": login, "password": password},
            timeout=self.timeout,
        )
        if response.status_code >= 400:
            detail = _error_detail(response)
            raise AuthClientError(detail)
        payload = response.json()
        user = AuthUser.from_dict(dict(payload.get("user") or {}))
        return AuthSession(
            access_token=str(payload.get("access_token") or ""),
            user=user,
            proxy_url=self.base_url,
        )

    def me(self, token: str) -> AuthUser:
        response = httpx.get(
            self._url("/v1/auth/me"),
            headers={"Authorization": f"Bearer {token}"},
            timeout=self.timeout,
        )
        if response.status_code >= 400:
            raise AuthClientError(_error_detail(response))
        return AuthUser.from_dict(response.json())

    def patch_email(self, token: str, email: str) -> AuthUser:
        response = httpx.patch(
            self._url("/v1/auth/me"),
            headers={"Authorization": f"Bearer {token}"},
            json={"email": email},
            timeout=self.timeout,
        )
        if response.status_code >= 400:
            raise AuthClientError(_error_detail(response))
        return AuthUser.from_dict(response.json())

    def upload_avatar(self, token: str, file_path: Path) -> AuthUser:
        data = file_path.read_bytes()
        response = httpx.post(
            self._url("/v1/auth/me/avatar"),
            headers={"Authorization": f"Bearer {token}"},
            files={"file": (file_path.name, data)},
            timeout=max(self.timeout, 60.0),
        )
        if response.status_code >= 400:
            raise AuthClientError(_error_detail(response))
        payload = response.json()
        return AuthUser.from_dict(dict(payload.get("user") or {}))

    def fetch_avatar(self, token: str) -> bytes | None:
        response = httpx.get(
            self._url("/v1/auth/me/avatar"),
            headers={"Authorization": f"Bearer {token}"},
            timeout=self.timeout,
        )
        if response.status_code == 404:
            return None
        if response.status_code >= 400:
            raise AuthClientError(_error_detail(response))
        return response.content


def save_session(session: AuthSession, path: Path | None = None) -> Path:
    target = path or Path(DEFAULT_SESSION_PATH)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(session.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return target


def load_session(path: Path | None = None) -> AuthSession | None:
    target = path or Path(DEFAULT_SESSION_PATH)
    if not target.exists():
        return None
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        session = AuthSession.from_dict(data)
        if not session.access_token or not session.user.onec_uid:
            return None
        return session
    except Exception:
        return None


def clear_session(path: Path | None = None) -> None:
    target = path or Path(DEFAULT_SESSION_PATH)
    if target.exists():
        target.unlink()


def _error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
        detail = payload.get("detail") or payload.get("error")
        if isinstance(detail, dict):
            detail = detail.get("message") or detail
        if detail:
            text = str(detail)
            # Старый llm_proxy без auth-роутов отвечает FastAPI «Not Found».
            if response.status_code == 404 and text.strip().casefold() in {
                "not found",
                "404: not found",
            }:
                return (
                    "На LLM-прокси нет API входа (/v1/auth/login). "
                    "Перезапустите обновлённый llm_proxy_service с DATABASE_URL "
                    "и настройками 1С (см. llm_proxy_service/.env.example)."
                )
            return text
    except Exception:
        pass
    if response.status_code == 404:
        return (
            "На LLM-прокси нет API входа (/v1/auth/login). "
            "Перезапустите обновлённый llm_proxy_service."
        )
    return f"HTTP {response.status_code}: {response.text[:300]}"
