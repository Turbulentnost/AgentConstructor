"""Тесты сохранения предпочтений экрана входа."""

from __future__ import annotations

from agent_desktop_constructor.app.auth.login_prefs import (
    LoginPrefs,
    load_login_prefs,
    save_login_prefs,
)


def test_save_and_load_remembered_login(tmp_path) -> None:
    path = tmp_path / "login_prefs.json"
    save_login_prefs(LoginPrefs(remember=True, login="Иванов"), path=path)
    loaded = load_login_prefs(path)
    assert loaded.remember is True
    assert loaded.login == "Иванов"


def test_unremember_clears_login(tmp_path) -> None:
    path = tmp_path / "login_prefs.json"
    save_login_prefs(LoginPrefs(remember=False, login="Иванов"), path=path)
    loaded = load_login_prefs(path)
    assert loaded.remember is False
    assert loaded.login == ""
