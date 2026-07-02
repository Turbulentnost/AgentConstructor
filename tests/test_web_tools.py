"""Тесты read-only web tools."""

from __future__ import annotations

import json

from agent_desktop_constructor.tools.registry import ToolRegistry
from agent_desktop_constructor.tools.web_tools import (
    BrowserClickLinkTool,
    BrowserExtractTableTool,
    BrowserOpenPageTool,
    BrowserScrollPageTool,
    BrowserSearchWebTool,
    register_web_tools,
)


class FakeHTTPResponse:
    """Минимальный context manager для urllib response."""

    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def __enter__(self) -> "FakeHTTPResponse":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


def test_register_web_tools_registers_browser_search_web() -> None:
    """register_web_tools регистрирует все browser tools."""
    registry = ToolRegistry()

    register_web_tools(registry)

    assert registry.has_tool("browser.search_web")
    assert registry.has_tool("browser.open_page")
    assert registry.has_tool("browser.extract_table")
    assert registry.has_tool("browser.scroll_page")
    assert registry.has_tool("browser.click_link")


def test_browser_search_web_weather_uses_wttr(monkeypatch) -> None:
    """Погодный запрос возвращает структурированный read-only результат."""
    captured: dict = {}

    def fake_urlopen(http_request, timeout):
        captured["url"] = http_request.full_url
        return FakeHTTPResponse(
            {
                "nearest_area": [
                    {
                        "areaName": [{"value": "Moscow"}],
                        "country": [{"value": "Russia"}],
                    }
                ],
                "current_condition": [
                    {
                        "temp_C": "22",
                        "FeelsLikeC": "23",
                        "weatherDesc": [{"value": "Ясно"}],
                        "windspeedKmph": "9",
                        "humidity": "44",
                    }
                ],
                "weather": [
                    {
                        "date": "2026-07-02",
                        "mintempC": "17",
                        "maxtempC": "24",
                        "hourly": [
                            {
                                "weatherDesc": [{"value": "Переменная облачность"}],
                            }
                        ],
                    }
                ],
            }
        )

    monkeypatch.setattr(
        "agent_desktop_constructor.tools.web_tools.request.urlopen",
        fake_urlopen,
    )

    result = BrowserSearchWebTool().execute(
        {"query": "какая сегодня погода в Москве", "max_results": 2}
    )

    assert result.ok is True
    assert "wttr.in" in captured["url"]
    assert result.output_data is not None
    assert result.output_data["source"] == "wttr.in"
    assert "Температура: 22" in result.output_data["answer"]
    assert result.output_data["results"]


def test_browser_search_web_requires_query() -> None:
    """Пустой query не выполняет web-запрос."""
    result = BrowserSearchWebTool().execute({"query": ""})

    assert result.ok is False
    assert result.error_type == "INVALID_INPUT"


class FakeBrowserWorker:
    """Fake CDP worker для tool unit-тестов."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def open_page(self, input_data: dict) -> dict:
        self.calls.append(("open_page", input_data))
        return {"url": input_data["url"], "title": "T", "text": "Hello", "links": []}

    def extract_table(self, input_data: dict) -> dict:
        self.calls.append(("extract_table", input_data))
        return {"url": input_data["url"], "title": "T", "tables": [{"rows": [["A"]]}]}

    def scroll_page(self, input_data: dict) -> dict:
        self.calls.append(("scroll_page", input_data))
        return {"url": input_data["url"], "title": "T", "text": "After scroll", "scroll_y": 900}

    def click_link(self, input_data: dict) -> dict:
        self.calls.append(("click_link", input_data))
        return {"url": "https://example.com/next", "title": "Next", "text": "Next page"}


def test_browser_open_page_tool_uses_worker() -> None:
    """browser.open_page проксирует вызов в BrowserCdpWorker."""
    worker = FakeBrowserWorker()

    result = BrowserOpenPageTool(worker).execute({"url": "https://example.com"})

    assert result.ok is True
    assert result.output_data["text"] == "Hello"
    assert worker.calls == [("open_page", {"url": "https://example.com"})]


def test_browser_extract_table_tool_uses_worker() -> None:
    """browser.extract_table проксирует вызов в BrowserCdpWorker."""
    worker = FakeBrowserWorker()

    result = BrowserExtractTableTool(worker).execute(
        {"url": "https://example.com", "table_hint": "A"}
    )

    assert result.ok is True
    assert result.output_data["tables"][0]["rows"] == [["A"]]
    assert worker.calls == [
        ("extract_table", {"url": "https://example.com", "table_hint": "A"})
    ]


def test_browser_scroll_page_tool_uses_worker() -> None:
    """browser.scroll_page проксирует вызов в BrowserCdpWorker."""
    worker = FakeBrowserWorker()

    result = BrowserScrollPageTool(worker).execute(
        {"url": "https://example.com", "direction": "down"}
    )

    assert result.ok is True
    assert result.output_data["scroll_y"] == 900
    assert worker.calls == [
        ("scroll_page", {"url": "https://example.com", "direction": "down"})
    ]


def test_browser_click_link_tool_uses_worker() -> None:
    """browser.click_link проксирует вызов в BrowserCdpWorker."""
    worker = FakeBrowserWorker()

    result = BrowserClickLinkTool(worker).execute(
        {"url": "https://example.com", "link_text": "Next"}
    )

    assert result.ok is True
    assert result.output_data["url"] == "https://example.com/next"
    assert worker.calls == [
        ("click_link", {"url": "https://example.com", "link_text": "Next"})
    ]
