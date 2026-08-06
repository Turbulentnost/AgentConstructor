"""Клиент аутентификации desktop → llm_proxy_service."""

from agent_desktop_constructor.app.auth.client import AuthClient, AuthSession, AuthUser

__all__ = ["AuthClient", "AuthSession", "AuthUser"]
