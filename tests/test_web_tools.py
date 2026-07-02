"""Тесты read-only web tools."""

from __future__ import annotations

import json

from agent_desktop_constructor.tools.registry import ToolRegistry
from agent_desktop_constructor.tools.web_tools import (
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
    """register_web_tools регистрирует browser.search_web."""
    registry = ToolRegistry()

    register_web_tools(registry)

    assert registry.has_tool("browser.search_web")


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
