"""Тесты vision-инструментов браузера и мультимодального промпта цикла."""

from __future__ import annotations

from agent_desktop_constructor.app.llm.agent_loop_prompts import (
    build_agent_loop_prompt,
    _sanitize_collected_data,
)
from agent_desktop_constructor.builder.agent_builder import AgentBuilder
from agent_desktop_constructor.core.models.runtime_state import (
    AgentRunStatus,
    AgentRuntimeState,
)
from agent_desktop_constructor.tools.browser_vision_tools import (
    BrowserNavigateTool,
    BrowserScreenshotTool,
    BrowserVisionWorkerProvider,
    register_browser_vision_tools,
)
from agent_desktop_constructor.tools.catalog_loader import load_tools_catalog
from agent_desktop_constructor.tools.registry import ToolRegistry
from agent_desktop_constructor.workers.browser_cdp_worker import BrowserCdpError


class FakeVisionWorker:
    """Fake worker: возвращает фиктивный скриншот или бросает ошибку."""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[str, dict]] = []
        self.os_fallback: dict | None = None

    def _act(self, name: str, input_data: dict) -> dict:
        self.calls.append((name, input_data))
        if self.fail:
            raise BrowserCdpError("нет браузера")
        return {"url": "https://x", "title": "t", "screenshot_base64": "IMG"}

    def navigate(self, i): return self._act("navigate", i)
    def screenshot(self, i): return self._act("screenshot", i)
    def get_page_html(self, i):
        self.calls.append(("get_page_html", i))
        if self.fail:
            raise BrowserCdpError("нет браузера")
        return {
            "url": "https://x",
            "title": "t",
            "html": "<html><body>hi</body></html>",
            "html_length": 28,
            "truncated": False,
            "html_summary": "<html><body>hi</body></html>",
        }
    def click(self, i): return self._act("click", i)
    def type_text(self, i): return self._act("type_text", i)
    def press_key(self, i): return self._act("press_key", i)
    def scroll(self, i): return self._act("scroll", i)
    def activate_os_fallback(self, **kwargs):
        self.os_fallback = kwargs


def test_vision_tool_returns_screenshot() -> None:
    """browser.click возвращает ok с output от worker."""
    registry = ToolRegistry()
    worker = FakeVisionWorker()
    register_browser_vision_tools(registry, worker=worker)

    result = registry.get("browser.click").execute({"x": 5, "y": 6})

    assert result.ok is True
    assert result.output_data["screenshot_base64"] == "IMG"
    assert worker.calls[0][0] == "click"


def test_get_page_html_tool_returns_html() -> None:
    """browser.get_page_html возвращает html/summary без скриншота."""
    registry = ToolRegistry()
    worker = FakeVisionWorker()
    register_browser_vision_tools(registry, worker=worker)

    result = registry.get("browser.get_page_html").execute({"max_chars": 1000})

    assert result.ok is True
    assert result.output_data["html"].startswith("<html>")
    assert result.output_data["html_length"] == 28
    assert result.output_data["truncated"] is False
    assert "html_summary" in result.output_data
    assert worker.calls[0][0] == "get_page_html"


def test_sanitize_collected_data_strips_html() -> None:
    """Сырой html убирается из текстовых collected_data, summary остаётся."""
    sanitized = _sanitize_collected_data(
        {
            "browser.get_page_html": {
                "url": "u",
                "html": "<html>" + ("x" * 5000) + "</html>",
                "html_length": 5013,
                "truncated": True,
                "html_summary": "<html>preview",
            }
        }
    )
    assert "html" not in sanitized["browser.get_page_html"]
    assert sanitized["browser.get_page_html"]["html_captured"] is True
    assert sanitized["browser.get_page_html"]["html_summary"] == "<html>preview"
    assert sanitized["browser.get_page_html"]["html_length"] == 5013



def test_vision_tool_normalizes_error() -> None:
    """Ошибка worker превращается в ToolCallResult с ok=False."""
    registry = ToolRegistry()
    register_browser_vision_tools(registry, worker=FakeVisionWorker(fail=True))

    result = registry.get("browser.screenshot").execute({})

    assert result.ok is False
    assert result.error_type == "BROWSER_CDP_ERROR"


def test_vision_navigate_passes_explicit_profile_options(monkeypatch) -> None:
    """browser.navigate передаёт профиль в worker только при явном указании."""
    created: dict = {}

    class ProviderWorker(FakeVisionWorker):
        pass

    def fake_worker(config):
        created["config"] = config
        return ProviderWorker()

    monkeypatch.setattr(
        "agent_desktop_constructor.tools.browser_vision_tools.find_readable_browser",
        lambda name: object() if name == "chrome" else None,
    )
    monkeypatch.setattr(
        "agent_desktop_constructor.tools.browser_vision_tools.resolve_browser_executable",
        lambda name: "C:/Chrome/chrome.exe" if name == "chrome" else None,
    )
    monkeypatch.setattr(
        "agent_desktop_constructor.tools.browser_vision_tools.BrowserVisionWorker",
        fake_worker,
    )
    provider = BrowserVisionWorkerProvider(FakeVisionWorker())

    result = BrowserNavigateTool(provider).execute(
        {
            "url": "https://example.com",
            "browser_id": "chrome",
            "use_default_profile": True,
            "profile_name": "Profile 1",
        }
    )

    assert result.ok is True
    assert created["config"].use_default_profile is True
    assert created["config"].profile_name == "Profile 1"
    assert created["config"].user_data_dir is None


def test_vision_tool_inherits_open_browser_user_session(monkeypatch) -> None:
    """После browser.open_browser vision tools наследуют browser/default profile."""
    created: dict = {}

    class ProviderWorker(FakeVisionWorker):
        pass

    def fake_worker(config):
        created["config"] = config
        worker = ProviderWorker()
        created["worker"] = worker
        return worker

    monkeypatch.setattr(
        "agent_desktop_constructor.tools.browser_vision_tools.find_readable_browser",
        lambda name: object() if name == "edge" else None,
    )
    monkeypatch.setattr(
        "agent_desktop_constructor.tools.browser_vision_tools.resolve_browser_executable",
        lambda name: "C:/Edge/msedge.exe" if name == "edge" else None,
    )
    monkeypatch.setattr(
        "agent_desktop_constructor.tools.browser_vision_tools.BrowserVisionWorker",
        fake_worker,
    )
    provider = BrowserVisionWorkerProvider(FakeVisionWorker())

    result = BrowserScreenshotTool(provider).execute(
        {
            "tool_outputs": {
                "browser.open_browser": {
                    "browser_id": "edge",
                    "url": "https://vk.com/im",
                    "profile_mode": "default",
                    "used_default_profile": True,
                    "cdp_available": False,
                    "command_args_summary": [
                        "<browser_executable>",
                        "https://vk.com/im",
                    ],
                }
            }
        }
    )

    assert result.ok is True
    assert created["config"].browser_id == "edge"
    assert created["config"].use_default_profile is True
    assert created["worker"].os_fallback["url"] == "https://vk.com/im"


def test_sanitize_collected_data_strips_base64() -> None:
    """Тяжёлый скриншот убирается из текстовых collected_data."""
    sanitized = _sanitize_collected_data(
        {"browser.click": {"url": "u", "screenshot_base64": "HUGE"}}
    )
    assert "screenshot_base64" not in sanitized["browser.click"]
    assert sanitized["browser.click"]["screenshot_captured"] is True


def test_loop_prompt_attaches_screenshot_image() -> None:
    """Последний скриншот из state попадает как image в user-сообщение."""
    catalog = load_tools_catalog()
    spec = AgentBuilder().build_from_request("Открой сайт и кликни кнопку в браузере")
    state = AgentRuntimeState(
        run_id="r1",
        agent_id=spec.agent_id,
        status=AgentRunStatus.RUNNING,
        variables={
            "user_request": "открой сайт",
            "last_screenshot": {
                "base64": "IMGDATA",
                "media_type": "image/png",
                "viewport_width": 1280,
                "viewport_height": 900,
            },
        },
    )

    messages = build_agent_loop_prompt(spec, state, catalog, [], [])

    user_message = messages[-1]
    assert user_message.images
    assert user_message.images[0].base64_data == "IMGDATA"
    assert "screen_context" in user_message.content
