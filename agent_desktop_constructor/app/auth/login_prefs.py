"""Локальные настройки экрана входа (запомнить логин)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from agent_desktop_constructor.app.core.config import resolve_runtime_path

DEFAULT_PREFS_PATH = resolve_runtime_path("data/login_prefs.json")


@dataclass
class LoginPrefs:
    """Сохранённые предпочтения логина."""

    remember: bool = False
    login: str = ""

    def to_dict(self) -> dict:
        return {"remember": self.remember, "login": self.login}

    @classmethod
    def from_dict(cls, data: dict) -> LoginPrefs:
        return cls(
            remember=bool(data.get("remember")),
            login=str(data.get("login") or "").strip(),
        )


def load_login_prefs(path: Path | None = None) -> LoginPrefs:
    target = path or Path(DEFAULT_PREFS_PATH)
    if not target.exists():
        return LoginPrefs()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        return LoginPrefs.from_dict(data if isinstance(data, dict) else {})
    except Exception:
        return LoginPrefs()


def save_login_prefs(prefs: LoginPrefs, path: Path | None = None) -> Path:
    target = path or Path(DEFAULT_PREFS_PATH)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = prefs.to_dict()
    if not prefs.remember:
        payload["login"] = ""
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return target
