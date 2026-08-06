"""Unit-тесты BrowserVisionWorker без запуска реального браузера."""

from __future__ import annotations

import pytest

from agent_desktop_constructor.workers import browser_cdp_worker as cdp
from agent_desktop_constructor.workers import browser_vision_worker as vision_worker
from agent_desktop_constructor.workers.browser_cdp_worker import (
    BrowserCdpError,
    BrowserLaunchConfig,
)
from agent_desktop_constructor.workers.browser_vision_worker import (
    BrowserVisionWorker,
)


class FakeVisionSession:
    """Fake CDP session, записывающая отправленные команды."""

    def __init__(self, scroll_metrics: dict | None = None) -> None:
        self.sent: list[tuple[str, dict | None]] = []
        self.evaluated: list[str] = []
        self._scroll_metrics = scroll_metrics or {
            "scrolled": True,
            "scroll_top": 700,
            "scroll_height": 5000,
            "client_height": 900,
            "at_bottom": False,
            "at_top": False,
            "target": "div.chat-list",
        }

    def __enter__(self) -> "FakeVisionSession":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def send(self, method: str, params: dict | None = None) -> dict:
        self.sent.append((method, params))
        if method == "Page.captureScreenshot":
            return {"data": "SCREENSHOTB64"}
        return {}

    def evaluate(self, expression: str):
        self.evaluated.append(expression)
        if "scrollableAxis" in expression:
            return dict(self._scroll_metrics)
        if "outerHTML" in expression:
            full = "<html><head></head><body>" + ("x" * 120) + "</body></html>"
            max_chars = 50
            summary_chars = 20
            if "const maxChars =" in expression:
                try:
                    max_chars = int(expression.split("const maxChars =", 1)[1].split(";", 1)[0].strip())
                except ValueError:
                    pass
            if "const summaryChars =" in expression:
                try:
                    summary_chars = int(
                        expression.split("const summaryChars =", 1)[1].split(";", 1)[0].strip()
                    )
                except ValueError:
                    pass
            return {
                "url": "https://example.com/app",
                "title": "App",
                "html": full[:max_chars],
                "html_length": len(full),
                "truncated": len(full) > max_chars,
                "html_summary": full[:summary_chars],
            }
        if "location.href" in expression:
            return "https://example.com/app"
        if "document.title" in expression:
            return "App"
        if "innerWidth" in expression:
            return {"w": 1280, "h": 900}
        if "document.readyState" in expression:
            return "complete"
        return None


def _worker_with_fake(monkeypatch: pytest.MonkeyPatch) -> tuple[BrowserVisionWorker, FakeVisionSession]:
    worker = BrowserVisionWorker()
    session = FakeVisionSession()
    monkeypatch.setattr(worker, "_session", lambda: session)
    return worker, session


def test_screenshot_returns_base64(monkeypatch: pytest.MonkeyPatch) -> None:
    """screenshot возвращает base64 PNG и состояние страницы."""
    worker, _ = _worker_with_fake(monkeypatch)

    result = worker.screenshot({})

    assert result["screenshot_base64"] == "SCREENSHOTB64"
    assert result["screenshot_media_type"] == "image/png"
    assert result["url"] == "https://example.com/app"
    assert result["viewport_width"] == 1280
    assert result["profile_mode"] == "automation"
    assert result["used_default_profile"] is False


def test_get_page_html_returns_truncated_html(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_page_html берёт outerHTML через Runtime.evaluate и обрезает по max_chars."""
    worker, session = _worker_with_fake(monkeypatch)

    result = worker.get_page_html({"max_chars": 40, "summary_chars": 100})

    assert result["url"] == "https://example.com/app"
    assert result["title"] == "App"
    assert result["html_length"] > 40
    assert result["truncated"] is True
    assert len(result["html"]) == 40
    assert len(result["html_summary"]) == 100
    assert result["cdp_available"] is True
    assert any("outerHTML" in expr for expr in session.evaluated)
    assert not any(method == "Page.captureScreenshot" for method, _ in session.sent)


def test_yandex_vision_default_profile_uses_real_user_data_dir(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """browser.navigate с use_default_profile не навязывает профиль Default."""
    captured: dict = {}

    class FakeProcess:
        pid = 4321

    monkeypatch.setattr(cdp.os, "name", "nt")
    monkeypatch.setenv("LOCALAPPDATA", "C:/Users/me/AppData/Local")
    worker = BrowserVisionWorker(
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

    monkeypatch.setattr(vision_worker.subprocess, "Popen", fake_popen)

    worker._ensure_browser()

    command = captured["command"]
    expected_user_data = r"C:\Users\me\AppData\Local\Yandex\YandexBrowser\User Data"
    assert f"--user-data-dir={expected_user_data}" in command
    assert not any(arg.startswith("--profile-directory=") for arg in command)
    assert not any("browser_profiles" in arg for arg in command)
    assert worker.profile_output()["profile_mode"] == "default"


def test_default_profile_navigate_falls_back_when_cdp_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Занятый штатный профиль открывается без CDP с явной диагностикой."""
    commands: list[list[str]] = []

    class FakeProcess:
        pid = 4321

    worker = BrowserVisionWorker(
        BrowserLaunchConfig(
            executable_path="C:/Chrome/chrome.exe",
            use_default_profile=True,
            timeout_seconds=0,
        )
    )
    monkeypatch.setattr(worker, "_is_cdp_available", lambda: False)
    monkeypatch.setattr(worker, "_desktop_screenshot", lambda: ("OSB64", 1600, 900))

    def fake_popen(command, stdout, stderr):
        commands.append(command)
        return FakeProcess()

    monkeypatch.setattr(vision_worker.subprocess, "Popen", fake_popen)

    result = worker.navigate({"url": "https://example.com"})

    assert result["url"] == "https://example.com"
    assert result["profile_mode"] == "default"
    assert result["cdp_available"] is False
    assert result["fallback_used"] is True
    assert result["fallback_reason"] == "default_profile_cdp_unavailable"
    assert result["screenshot_base64"] == "OSB64"
    assert result["viewport_width"] == 1600
    assert "OS fallback" in result["next_action_hint"]
    assert "automation profile" in result["next_action_hint"]
    assert len(commands) == 2
    assert commands[-1] == ["C:/Chrome/chrome.exe", "https://example.com"]


def test_default_profile_screenshot_uses_os_fallback_after_navigate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """После fallback-open screenshot больше не падает на CDP, а берёт экран ОС."""
    worker = BrowserVisionWorker(
        BrowserLaunchConfig(
            executable_path="C:/Chrome/chrome.exe",
            use_default_profile=True,
            timeout_seconds=0,
        )
    )
    monkeypatch.setattr(worker, "_is_cdp_available", lambda: False)
    monkeypatch.setattr(worker, "_desktop_screenshot", lambda: ("OSB64", 1366, 768))
    monkeypatch.setattr(
        vision_worker.subprocess,
        "Popen",
        lambda command, stdout, stderr: type("FakeProcess", (), {"pid": 123})(),
    )

    worker.navigate({"url": "https://example.com"})
    result = worker.screenshot({})

    assert result["screenshot_base64"] == "OSB64"
    assert result["screenshot_media_type"] == "image/png"
    assert result["cdp_available"] is False
    assert result["fallback_used"] is True
    assert result["fallback_reason"] == "default_profile_os_fallback"


def test_default_profile_os_fallback_click_and_type(monkeypatch: pytest.MonkeyPatch) -> None:
    """OS fallback позволяет продолжать UI-действия без CDP."""
    events: list[tuple] = []
    worker = BrowserVisionWorker(
        BrowserLaunchConfig(
            executable_path="C:/Chrome/chrome.exe",
            use_default_profile=True,
            timeout_seconds=0,
        )
    )
    worker._os_fallback_active = True
    worker._os_fallback_url = "https://example.com"
    monkeypatch.setattr(worker, "_desktop_screenshot", lambda: ("OSB64", 1366, 768))
    monkeypatch.setattr(
        worker,
        "_send_os_click",
        lambda x, y, button: events.append(("click", x, y, button)),
    )
    monkeypatch.setattr(
        worker,
        "_send_os_text",
        lambda text: events.append(("text", text)),
    )

    click_result = worker.click({"x": 10, "y": 20})
    type_result = worker.type_text({"text": "hello"})

    assert events == [("click", 10, 20, "left"), ("text", "hello")]
    assert click_result["screenshot_base64"] == "OSB64"
    assert type_result["fallback_used"] is True


def test_automation_profile_reports_cdp_available_under_mocked_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Automation profile остаётся CDP-режимом и отдаёт cdp_url."""
    worker = BrowserVisionWorker(BrowserLaunchConfig(port=9444, browser_id="chrome"))

    def fake_get_json(path, method="GET", *, timeout_seconds=None):
        assert path == "/json/version"
        return {"Browser": "Chrome/122"}

    monkeypatch.setattr(worker, "_get_json", fake_get_json)

    output = worker.profile_output()

    assert output["profile_mode"] == "automation"
    assert output["used_default_profile"] is False
    assert output["cdp_available"] is True
    assert output["cdp_url"] == "http://127.0.0.1:9444"
    assert output["fallback_used"] is False


def test_click_dispatches_mouse_events(monkeypatch: pytest.MonkeyPatch) -> None:
    """click отправляет mousePressed/mouseReleased по координатам и делает скриншот."""
    worker, session = _worker_with_fake(monkeypatch)

    result = worker.click({"x": 100, "y": 200})

    mouse_events = [p for m, p in session.sent if m == "Input.dispatchMouseEvent"]
    assert {e["type"] for e in mouse_events} == {"mousePressed", "mouseReleased"}
    assert mouse_events[0]["x"] == 100 and mouse_events[0]["y"] == 200
    assert result["screenshot_base64"] == "SCREENSHOTB64"


def test_type_text_uses_insert_text(monkeypatch: pytest.MonkeyPatch) -> None:
    """type_text отправляет Input.insertText с текстом."""
    worker, session = _worker_with_fake(monkeypatch)

    worker.type_text({"text": "привет"})

    inserts = [p for m, p in session.sent if m == "Input.insertText"]
    assert inserts and inserts[0]["text"] == "привет"


def test_type_text_requires_text(monkeypatch: pytest.MonkeyPatch) -> None:
    """Пустой text приводит к понятной ошибке."""
    worker, _ = _worker_with_fake(monkeypatch)

    with pytest.raises(BrowserCdpError):
        worker.type_text({"text": ""})


def test_press_key_enter(monkeypatch: pytest.MonkeyPatch) -> None:
    """press_key enter отправляет key-события с кодом 13."""
    worker, session = _worker_with_fake(monkeypatch)

    worker.press_key({"key": "enter"})

    key_events = [p for m, p in session.sent if m == "Input.dispatchKeyEvent"]
    assert key_events and key_events[0]["windowsVirtualKeyCode"] == 13


def test_press_key_unknown_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """Неизвестная клавиша отвергается."""
    worker, _ = _worker_with_fake(monkeypatch)

    with pytest.raises(BrowserCdpError):
        worker.press_key({"key": "f13"})


def test_scroll_targets_container_and_reports_metrics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """scroll ищет прокручиваемую область и возвращает метрики прокрутки."""
    worker, session = _worker_with_fake(monkeypatch)

    result = worker.scroll({"direction": "down", "pixels": 500})

    assert result["screenshot_base64"] == "SCREENSHOTB64"
    assert result["scrolled"] is True
    assert result["at_bottom"] is False
    assert result["scroll_target"] == "div.chat-list"
    # Использован скрипт поиска прокручиваемого контейнера, а не тупой window.scrollBy.
    assert any("scrollableAxis" in expr for expr in session.evaluated)


def test_scroll_reports_no_move_at_bottom(monkeypatch: pytest.MonkeyPatch) -> None:
    """Если область не сдвинулась, scroll честно сообщает scrolled=false/at_bottom."""
    worker = BrowserVisionWorker()
    session = FakeVisionSession(
        scroll_metrics={
            "scrolled": False,
            "scroll_top": 4100,
            "scroll_height": 5000,
            "client_height": 900,
            "at_bottom": True,
            "at_top": False,
            "target": "div.chat-list",
        }
    )
    monkeypatch.setattr(worker, "_session", lambda: session)

    result = worker.scroll({"direction": "down", "pixels": 500})

    assert result["scrolled"] is False
    assert result["at_bottom"] is True


def test_click_requires_numeric_coords(monkeypatch: pytest.MonkeyPatch) -> None:
    """Нечисловые координаты дают понятную ошибку."""
    worker, _ = _worker_with_fake(monkeypatch)

    with pytest.raises(BrowserCdpError):
        worker.click({"x": "left", "y": 10})


def test_os_fallback_screenshot_reports_virtual_desktop_meta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OS screenshot помечает capture_mode=virtual_desktop и размеры всего стола."""
    worker = BrowserVisionWorker(
        BrowserLaunchConfig(executable_path="C:/Chrome/chrome.exe", use_default_profile=True)
    )
    worker._os_fallback_active = True
    worker._os_fallback_url = "https://chat.deepseek.com"

    def fake_desktop_screenshot():
        worker._os_click_origin = (-1920, 0)
        worker._os_capture_meta = {
            "capture_mode": "virtual_desktop",
            "origin_x": -1920,
            "origin_y": 0,
            "monitor_count": 2,
            "engine": "win32",
            "width": 3840,
            "height": 1080,
        }
        return ("VDESKB64", 3840, 1080)

    monkeypatch.setattr(worker, "_desktop_screenshot", fake_desktop_screenshot)
    result = worker.screenshot({})

    assert result["screenshot_base64"] == "VDESKB64"
    assert result["capture_mode"] == "virtual_desktop"
    assert result["monitor_count"] == 2
    assert result["screen_origin_x"] == -1920
    assert result["screen_origin_y"] == 0
    assert result["viewport_width"] == 3840
    assert "virtual desktop" in result["warning"].casefold() or "монитор" in result[
        "warning"
    ].casefold()
    assert "virtual desktop" in result["next_action_hint"].casefold()


def test_os_click_applies_virtual_desktop_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Клик в координатах картинки сдвигается на origin virtual desktop."""
    worker = BrowserVisionWorker(
        BrowserLaunchConfig(executable_path="C:/Chrome/chrome.exe", use_default_profile=True)
    )
    worker._os_click_origin = (-1920, 100)
    positions: list[tuple[int, int]] = []

    class FakeWin32Api:
        @staticmethod
        def SetCursorPos(pos):
            positions.append(pos)

        @staticmethod
        def mouse_event(*_args):
            return None

    class FakeWin32Con:
        MOUSEEVENTF_LEFTDOWN = 2
        MOUSEEVENTF_LEFTUP = 4
        MOUSEEVENTF_RIGHTDOWN = 8
        MOUSEEVENTF_RIGHTUP = 16

    monkeypatch.setattr(vision_worker, "_is_windows", lambda: True)
    monkeypatch.setitem(__import__("sys").modules, "win32api", FakeWin32Api)
    monkeypatch.setitem(__import__("sys").modules, "win32con", FakeWin32Con)

    worker._send_os_click(50, 80, "left")

    assert positions == [(-1870, 180)]


def test_desktop_screenshot_prefers_browser_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_desktop_screenshot предпочитает окно браузера virtual desktop."""
    worker = BrowserVisionWorker()
    worker._os_fallback_url = "https://chat.deepseek.com"
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f"
        b"\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    monkeypatch.setattr(vision_worker, "_is_windows", lambda: True)
    monkeypatch.setattr(
        vision_worker,
        "capture_browser_window_png",
        lambda url_hint="", focus=True: (
            png,
            {
                "capture_mode": "browser_window",
                "origin_x": 100,
                "origin_y": 50,
                "monitor_count": 1,
                "engine": "win32_window",
                "width": 1200,
                "height": 800,
                "title": "DeepSeek",
            },
        ),
    )
    monkeypatch.setattr(
        vision_worker,
        "_capture_virtual_desktop_win32",
        lambda: (_ for _ in ()).throw(AssertionError("virtual must not run")),
    )

    b64, width, height = worker._desktop_screenshot()

    assert width == 1200 and height == 800
    assert worker._os_click_origin == (100, 50)
    assert worker._os_capture_meta["capture_mode"] == "browser_window"
    assert b64


def test_desktop_screenshot_falls_back_to_win32_virtual(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Если окно браузера не найдено — virtual desktop win32."""
    worker = BrowserVisionWorker()
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f"
        b"\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    monkeypatch.setattr(vision_worker, "_is_windows", lambda: True)
    monkeypatch.setattr(
        vision_worker,
        "capture_browser_window_png",
        lambda url_hint="", focus=True: None,
    )
    monkeypatch.setattr(
        vision_worker,
        "_capture_virtual_desktop_win32",
        lambda: (png, 3840, 1080, -1920, 0, 2, "win32"),
    )
    monkeypatch.setattr(
        vision_worker,
        "_capture_virtual_desktop_qt",
        lambda: (_ for _ in ()).throw(AssertionError("qt path must not run")),
    )

    _b64, width, height = worker._desktop_screenshot()

    assert width == 3840 and height == 1080
    assert worker._os_click_origin == (-1920, 0)
    assert worker._os_capture_meta["engine"] == "win32"


def test_os_click_focuses_browser_before_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OS click/type вызывают focus окна браузера перед действием."""
    events: list[str] = []
    worker = BrowserVisionWorker(
        BrowserLaunchConfig(executable_path="C:/Chrome/chrome.exe", use_default_profile=True)
    )
    worker._os_fallback_active = True
    worker._os_fallback_url = "https://chat.deepseek.com"
    monkeypatch.setattr(worker, "_desktop_screenshot", lambda: ("OSB64", 800, 600))
    monkeypatch.setattr(
        vision_worker,
        "focus_browser_window",
        lambda url: events.append(f"focus:{url}") or {"ok": True, "title": "DeepSeek"},
    )
    monkeypatch.setattr(
        vision_worker,
        "foreground_window_info",
        lambda: {"ok": True, "title": "DeepSeek"},
    )
    monkeypatch.setattr(
        worker,
        "_send_os_click",
        lambda x, y, button: events.append(f"click:{x},{y}"),
    )
    monkeypatch.setattr(
        worker,
        "_send_os_text",
        lambda text: events.append(f"text:{text}"),
    )

    click_result = worker.click({"x": 10, "y": 20})
    type_result = worker.type_text({"text": "hello"})

    assert events == [
        "focus:https://chat.deepseek.com",
        "click:10,20",
        "focus:https://chat.deepseek.com",
        "text:hello",
    ]
    assert click_result["focus_before_action"]["ok"] is True
    assert type_result["focused_window_after"]["title"] == "DeepSeek"
