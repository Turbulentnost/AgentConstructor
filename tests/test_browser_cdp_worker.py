"""Unit-тесты BrowserCdpWorker без запуска реального браузера."""

from __future__ import annotations

import pytest

from agent_desktop_constructor.workers import browser_cdp_worker as cdp
from agent_desktop_constructor.workers.browser_cdp_worker import (
    BrowserCdpError,
    BrowserCdpWorker,
    BrowserLaunchConfig,
)


class FakeSession:
    """Минимальный fake CDP session."""

    def __enter__(self) -> "FakeSession":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def send(self, method: str, params: dict | None = None) -> dict:
        return {}

    def evaluate(self, expression: str):
        if "document.readyState" in expression:
            return "complete"
        if "wantedText" in expression:
            return {"href": "https://example.com/next", "text": "next"}
        if "Math.round(window.scrollY" in expression:
            return 900
        if "querySelectorAll('table')" in expression:
            return [{"index": 0, "caption": "Таблица", "rows": [["A", "B"]]}]
        if "document.title" in expression and "body.innerText" not in expression:
            return "Example"
        if "location.href" in expression and "body.innerText" not in expression:
            return "https://example.com"
        return {
            "url": "https://example.com",
            "title": "Example",
            "text": "Hello",
            "links": [{"text": "Next", "href": "https://example.com/next"}],
        }


def test_require_http_url_blocks_unsafe_scheme() -> None:
    """javascript/file/data URL блокируются."""
    with pytest.raises(BrowserCdpError):
        cdp._require_http_url("javascript:alert(1)")


def test_require_http_url_accepts_https() -> None:
    """https URL разрешён."""
    assert cdp._require_http_url("https://example.com") == "https://example.com"


def test_open_page_uses_session(monkeypatch: pytest.MonkeyPatch) -> None:
    """open_page возвращает snapshot через CDP session."""
    worker = BrowserCdpWorker()
    monkeypatch.setattr(worker, "_session_for_url", lambda url: FakeSession())

    result = worker.open_page({"url": "https://example.com", "max_chars": 100})

    assert result["title"] == "Example"
    assert result["links"][0]["href"] == "https://example.com/next"


def test_scroll_page_returns_scroll_position(monkeypatch: pytest.MonkeyPatch) -> None:
    """scroll_page возвращает scroll_y."""
    worker = BrowserCdpWorker()
    monkeypatch.setattr(worker, "_session_for_url", lambda url: FakeSession())

    result = worker.scroll_page({"url": "https://example.com", "pixels": 900})

    assert result["scroll_y"] == 900


def test_click_link_opens_found_link(monkeypatch: pytest.MonkeyPatch) -> None:
    """click_link находит ссылку по тексту."""
    worker = BrowserCdpWorker()
    monkeypatch.setattr(worker, "_session_for_url", lambda url: FakeSession())

    result = worker.click_link({"url": "https://example.com", "link_text": "Next"})

    assert result["url"] == "https://example.com"


def test_extract_table_returns_tables(monkeypatch: pytest.MonkeyPatch) -> None:
    """extract_table извлекает таблицы."""
    worker = BrowserCdpWorker()
    monkeypatch.setattr(worker, "_session_for_url", lambda url: FakeSession())

    result = worker.extract_table({"url": "https://example.com"})

    assert result["tables"][0]["rows"] == [["A", "B"]]


def test_default_cdp_automation_profile_is_stable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """Automation profile хранится стабильно между worker-ами и не в temp."""
    monkeypatch.setenv("AGENT_CONSTRUCTOR_BROWSER_PROFILE_ROOT", str(tmp_path))

    first = BrowserCdpWorker(BrowserLaunchConfig(browser_id="yandex"))
    second = BrowserCdpWorker(BrowserLaunchConfig(browser_id="yandex"))

    assert first._user_data_dir == second._user_data_dir
    assert first._user_data_dir == str(tmp_path / "cdp" / "yandex" / "automation")


def test_cdp_launch_uses_stable_profile_and_does_not_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """CDP launch создаёт стабильный профиль и не удаляет каталог профиля."""
    captured: dict = {}
    cleanup_calls: list[str] = []

    class FakeProcess:
        pid = 4321

    monkeypatch.setenv("AGENT_CONSTRUCTOR_BROWSER_PROFILE_ROOT", str(tmp_path))
    worker = BrowserCdpWorker(
        BrowserLaunchConfig(
            executable_path="C:/Chrome/chrome.exe",
            browser_id="chrome",
            timeout_seconds=1,
        )
    )
    checks = iter([False, True])
    monkeypatch.setattr(worker, "_is_cdp_available", lambda: next(checks))

    def fake_popen(command, stdout, stderr):
        captured["command"] = command
        return FakeProcess()

    monkeypatch.setattr(
        cdp.subprocess,
        "Popen",
        fake_popen,
    )
    monkeypatch.setattr(
        cdp.shutil,
        "rmtree",
        lambda path, *args, **kwargs: cleanup_calls.append(str(path)),
    )

    worker._ensure_browser()

    command = captured["command"]
    assert f"--user-data-dir={tmp_path / 'cdp' / 'chrome' / 'automation'}" in command
    assert cleanup_calls == []


def test_yandex_use_default_profile_uses_real_user_data_dir(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Yandex default profile использует штатный User Data, а не automation dir."""
    captured: dict = {}

    class FakeProcess:
        pid = 4321

    monkeypatch.setattr(cdp.os, "name", "nt")
    monkeypatch.setenv("LOCALAPPDATA", "C:/Users/me/AppData/Local")
    worker = BrowserCdpWorker(
        BrowserLaunchConfig(
            executable_path="C:/Program Files (x86)/Yandex/YandexBrowser/Application/browser.exe",
            browser_id="yandex",
            use_default_profile=True,
            timeout_seconds=1,
        )
    )
    checks = iter([False, True])
    monkeypatch.setattr(worker, "_is_cdp_available", lambda: next(checks))

    def fake_popen(command, stdout, stderr):
        captured["command"] = command
        return FakeProcess()

    monkeypatch.setattr(cdp.subprocess, "Popen", fake_popen)

    worker._ensure_browser()

    command = captured["command"]
    expected_user_data = r"C:\Users\me\AppData\Local\Yandex\YandexBrowser\User Data"
    assert f"--user-data-dir={expected_user_data}" in command
    assert "--profile-directory=Default" in command
    assert not any("AgentConstructor" in arg for arg in command)
    assert worker.profile_output()["profile_mode"] == "default"
    assert worker.profile_output()["used_default_profile"] is True


def test_use_default_profile_omits_user_data_dir_and_allows_profile_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Штатный профиль используется только при явном use_default_profile."""
    captured: dict = {}

    class FakeProcess:
        pid = 4321

    worker = BrowserCdpWorker(
        BrowserLaunchConfig(
            executable_path="C:/Chrome/chrome.exe",
            use_default_profile=True,
            profile_name="Profile 1",
            timeout_seconds=1,
        )
    )
    checks = iter([False, True])
    monkeypatch.setattr(worker, "_is_cdp_available", lambda: next(checks))

    def fake_popen(command, stdout, stderr):
        captured["command"] = command
        return FakeProcess()

    monkeypatch.setattr(
        cdp.subprocess,
        "Popen",
        fake_popen,
    )

    worker._ensure_browser()

    command = captured["command"]
    assert not any(arg.startswith("--user-data-dir=") for arg in command)
    assert "--profile-directory=Profile 1" in command


def test_explicit_user_data_dir_is_passed_to_command(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """Кастомный user_data_dir попадает в команду только при явном указании."""
    captured: dict = {}
    custom_profile = tmp_path / "custom-profile"

    class FakeProcess:
        pid = 4321

    worker = BrowserCdpWorker(
        BrowserLaunchConfig(
            executable_path="C:/Chrome/chrome.exe",
            user_data_dir=str(custom_profile),
            profile_name="Profile 2",
            timeout_seconds=1,
        )
    )
    checks = iter([False, True])
    monkeypatch.setattr(worker, "_is_cdp_available", lambda: next(checks))

    def fake_popen(command, stdout, stderr):
        captured["command"] = command
        return FakeProcess()

    monkeypatch.setattr(
        cdp.subprocess,
        "Popen",
        fake_popen,
    )

    worker._ensure_browser()

    command = captured["command"]
    assert f"--user-data-dir={custom_profile}" in command
    assert "--profile-directory=Profile 2" in command
