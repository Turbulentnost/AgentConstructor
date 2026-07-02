"""Read-only web tools для актуальной внешней информации."""

from __future__ import annotations

import json
from typing import Any
from urllib import error, parse, request

from agent_desktop_constructor.core.models.tooling import (
    ToolCallResult,
    ToolDefinition,
    ToolExecutionMode,
    ToolSideEffectLevel,
)
from agent_desktop_constructor.tools.base import BaseTool
from agent_desktop_constructor.tools.registry import ToolRegistry
from agent_desktop_constructor.workers.browser_cdp_worker import (
    BrowserCdpError,
    BrowserCdpWorker,
)

DEFAULT_MAX_RESULTS = 5
MAX_RESULTS = 10


class BrowserSearchWebTool(BaseTool):
    """Безопасный read-only поиск актуальной web-информации."""

    def __init__(self) -> None:
        """Создать инструмент browser.search_web."""
        super().__init__(
            ToolDefinition(
                name="browser.search_web",
                title="Поиск web-информации",
                description="Ищет актуальную информацию в интернете read-only.",
                side_effect_level=ToolSideEffectLevel.READ,
                execution_mode=ToolExecutionMode.EXTERNAL_API,
                requires_human_approval=False,
                timeout_seconds=20,
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "max_results": {"type": "integer"},
                        "allowed_domains": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                    "required": ["query"],
                },
                output_schema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "answer": {"type": "string"},
                        "results": {"type": "array"},
                        "source": {"type": "string"},
                    },
                },
            )
        )

    def execute(self, input_data: dict) -> ToolCallResult:
        """Выполнить web-поиск и вернуть структурированные результаты."""
        query = str(input_data.get("query") or "").strip()
        if not query:
            return ToolCallResult(
                ok=False,
                tool_name=self.definition.name,
                error_type="INVALID_INPUT",
                error_message="Для browser.search_web нужен непустой query.",
            )

        max_results = _clamp_int(
            input_data.get("max_results"),
            DEFAULT_MAX_RESULTS,
            1,
            MAX_RESULTS,
        )
        try:
            if _looks_like_weather_query(query):
                output_data = _search_weather(query, max_results)
            else:
                output_data = _search_duckduckgo(query, max_results)
        except Exception as exc:  # noqa: BLE001 - urllib возвращает разные ошибки
            return ToolCallResult(
                ok=False,
                tool_name=self.definition.name,
                error_type="WEB_SEARCH_ERROR",
                error_message=str(exc),
            )

        return ToolCallResult(
            ok=True,
            tool_name=self.definition.name,
            output_data=output_data,
        )


class BrowserOpenPageTool(BaseTool):
    """Открывает страницу через CDP и извлекает видимый текст/ссылки."""

    def __init__(self, worker: BrowserCdpWorker | None = None) -> None:
        """Создать инструмент browser.open_page."""
        super().__init__(
            ToolDefinition(
                name="browser.open_page",
                title="Чтение web-страницы",
                description="Открывает web-страницу read-only и извлекает текст.",
                side_effect_level=ToolSideEffectLevel.READ,
                execution_mode=ToolExecutionMode.BROWSER_WORKER,
                requires_human_approval=False,
                timeout_seconds=30,
                input_schema={
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "max_chars": {"type": "integer"},
                    },
                    "required": ["url"],
                },
                output_schema={
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "title": {"type": "string"},
                        "text": {"type": "string"},
                        "links": {"type": "array"},
                    },
                },
            )
        )
        self._worker = worker or BrowserCdpWorker()

    def execute(self, input_data: dict) -> ToolCallResult:
        """Открыть страницу через browser worker."""
        return _execute_browser_worker(self.definition.name, self._worker.open_page, input_data)


class BrowserExtractTableTool(BaseTool):
    """Извлекает таблицы со страницы через CDP."""

    def __init__(self, worker: BrowserCdpWorker | None = None) -> None:
        """Создать инструмент browser.extract_table."""
        super().__init__(
            ToolDefinition(
                name="browser.extract_table",
                title="Извлечение таблиц web-страницы",
                description="Извлекает таблицы с web-страницы read-only.",
                side_effect_level=ToolSideEffectLevel.READ,
                execution_mode=ToolExecutionMode.BROWSER_WORKER,
                requires_human_approval=False,
                timeout_seconds=30,
                input_schema={
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "table_hint": {"type": "string"},
                    },
                    "required": ["url"],
                },
                output_schema={
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "title": {"type": "string"},
                        "tables": {"type": "array"},
                    },
                },
            )
        )
        self._worker = worker or BrowserCdpWorker()

    def execute(self, input_data: dict) -> ToolCallResult:
        """Извлечь таблицы через browser worker."""
        return _execute_browser_worker(
            self.definition.name,
            self._worker.extract_table,
            input_data,
        )


class BrowserScrollPageTool(BaseTool):
    """Прокручивает страницу через CDP и возвращает видимый текст."""

    def __init__(self, worker: BrowserCdpWorker | None = None) -> None:
        """Создать инструмент browser.scroll_page."""
        super().__init__(
            ToolDefinition(
                name="browser.scroll_page",
                title="Прокрутка web-страницы",
                description="Прокручивает web-страницу read-only.",
                side_effect_level=ToolSideEffectLevel.READ,
                execution_mode=ToolExecutionMode.BROWSER_WORKER,
                requires_human_approval=False,
                timeout_seconds=30,
                input_schema={
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "direction": {"type": "string"},
                        "pixels": {"type": "integer"},
                        "max_chars": {"type": "integer"},
                    },
                    "required": ["url"],
                },
                output_schema={
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "title": {"type": "string"},
                        "text": {"type": "string"},
                        "scroll_y": {"type": "integer"},
                    },
                },
            )
        )
        self._worker = worker or BrowserCdpWorker()

    def execute(self, input_data: dict) -> ToolCallResult:
        """Прокрутить страницу через browser worker."""
        return _execute_browser_worker(
            self.definition.name,
            self._worker.scroll_page,
            input_data,
        )


class BrowserClickLinkTool(BaseTool):
    """Переходит по безопасной http/https ссылке через CDP."""

    def __init__(self, worker: BrowserCdpWorker | None = None) -> None:
        """Создать инструмент browser.click_link."""
        super().__init__(
            ToolDefinition(
                name="browser.click_link",
                title="Переход по ссылке web-страницы",
                description="Открывает найденную ссылку read-only.",
                side_effect_level=ToolSideEffectLevel.READ,
                execution_mode=ToolExecutionMode.BROWSER_WORKER,
                requires_human_approval=False,
                timeout_seconds=30,
                input_schema={
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "link_text": {"type": "string"},
                        "href": {"type": "string"},
                        "max_chars": {"type": "integer"},
                    },
                    "required": ["url"],
                },
                output_schema={
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "title": {"type": "string"},
                        "text": {"type": "string"},
                        "links": {"type": "array"},
                    },
                },
            )
        )
        self._worker = worker or BrowserCdpWorker()

    def execute(self, input_data: dict) -> ToolCallResult:
        """Перейти по ссылке через browser worker."""
        return _execute_browser_worker(
            self.definition.name,
            self._worker.click_link,
            input_data,
        )


def register_web_tools(
    registry: ToolRegistry,
    *,
    skip_existing: bool = False,
    worker: BrowserCdpWorker | None = None,
) -> None:
    """Зарегистрировать read-only web tools."""
    browser_worker = worker or BrowserCdpWorker()
    tools = [
        BrowserSearchWebTool(),
        BrowserOpenPageTool(browser_worker),
        BrowserExtractTableTool(browser_worker),
        BrowserScrollPageTool(browser_worker),
        BrowserClickLinkTool(browser_worker),
    ]
    for tool in tools:
        if skip_existing and registry.has_tool(tool.definition.name):
            continue
        registry.register(tool)


def _execute_browser_worker(tool_name: str, action, input_data: dict) -> ToolCallResult:
    """Выполнить browser worker action и нормализовать ошибку в ToolCallResult."""
    try:
        output_data = action(input_data)
    except BrowserCdpError as exc:
        return ToolCallResult(
            ok=False,
            tool_name=tool_name,
            error_type="BROWSER_CDP_ERROR",
            error_message=str(exc),
        )
    except Exception as exc:  # noqa: BLE001 - worker изолирует внешние browser ошибки
        return ToolCallResult(
            ok=False,
            tool_name=tool_name,
            error_type="BROWSER_TOOL_ERROR",
            error_message=str(exc),
        )
    return ToolCallResult(ok=True, tool_name=tool_name, output_data=output_data)



def _search_weather(query: str, max_results: int) -> dict:
    """Получить погодные данные через wttr.in в JSON-формате."""
    location = _extract_weather_location(query)
    encoded_location = parse.quote(location, safe="")
    url = f"https://wttr.in/{encoded_location}?format=j1&lang=ru"
    payload = _read_json(url)
    current = (payload.get("current_condition") or [{}])[0]
    nearest_area = (payload.get("nearest_area") or [{}])[0]
    area_name = _first_value(nearest_area.get("areaName")) or location or "текущая локация"
    country = _first_value(nearest_area.get("country"))
    description = _first_value(current.get("weatherDesc"))
    answer_parts = [
        f"Локация: {area_name}" + (f", {country}" if country else ""),
        f"Температура: {current.get('temp_C', '—')} °C",
        f"Ощущается как: {current.get('FeelsLikeC', '—')} °C",
        f"Условия: {description or '—'}",
        f"Ветер: {current.get('windspeedKmph', '—')} км/ч",
        f"Влажность: {current.get('humidity', '—')}%",
    ]
    forecast_items = payload.get("weather") or []
    results = [
        {
            "title": "Текущая погода",
            "snippet": "; ".join(answer_parts),
            "url": "https://wttr.in/",
            "source": "wttr.in",
        }
    ]
    for item in forecast_items[: max(0, max_results - 1)]:
        hourly = item.get("hourly") or []
        noon = hourly[len(hourly) // 2] if hourly else {}
        results.append(
            {
                "title": f"Прогноз на {item.get('date', 'дату')}",
                "snippet": (
                    f"Мин: {item.get('mintempC', '—')} °C; "
                    f"макс: {item.get('maxtempC', '—')} °C; "
                    f"днём: {_first_value(noon.get('weatherDesc')) or '—'}"
                ),
                "url": "https://wttr.in/",
                "source": "wttr.in",
            }
        )
    return {
        "query": query,
        "answer": "\n".join(answer_parts),
        "results": results[:max_results],
        "source": "wttr.in",
    }


def _search_duckduckgo(query: str, max_results: int) -> dict:
    """Получить краткие результаты через DuckDuckGo Instant Answer API."""
    params = parse.urlencode(
        {
            "q": query,
            "format": "json",
            "no_html": "1",
            "skip_disambig": "1",
        }
    )
    payload = _read_json(f"https://api.duckduckgo.com/?{params}")
    results: list[dict[str, str]] = []
    abstract = str(payload.get("AbstractText") or "").strip()
    abstract_url = str(payload.get("AbstractURL") or "").strip()
    heading = str(payload.get("Heading") or query).strip()
    if abstract:
        results.append(
            {
                "title": heading,
                "snippet": abstract,
                "url": abstract_url,
                "source": "duckduckgo",
            }
        )
    for item in _flatten_related_topics(payload.get("RelatedTopics") or []):
        if len(results) >= max_results:
            break
        text = str(item.get("Text") or "").strip()
        if not text:
            continue
        results.append(
            {
                "title": text.split(" - ", 1)[0][:120],
                "snippet": text,
                "url": str(item.get("FirstURL") or ""),
                "source": "duckduckgo",
            }
        )
    answer = abstract or str(payload.get("Answer") or "").strip()
    return {
        "query": query,
        "answer": answer,
        "results": results[:max_results],
        "source": "duckduckgo",
    }


def _read_json(url: str) -> dict[str, Any]:
    """Прочитать JSON по URL с user-agent и понятной ошибкой."""
    http_request = request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "AgentConstructor/1.0 read-only",
        },
        method="GET",
    )
    try:
        with request.urlopen(http_request, timeout=20) as response:
            raw = response.read()
    except error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code} при web-поиске") from exc
    except (error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"Не удалось выполнить web-поиск: {exc}") from exc
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("Web endpoint вернул невалидный JSON") from exc


def _looks_like_weather_query(query: str) -> bool:
    """Проверить, что запрос похож на запрос о погоде."""
    lowered = query.casefold()
    return any(marker in lowered for marker in ["погода", "weather", "температура"])


def _extract_weather_location(query: str) -> str:
    """Выделить локацию из простого погодного запроса или оставить авто-локацию."""
    lowered = query.casefold()
    for marker in [" в ", " во ", " для "]:
        if marker in lowered:
            location = query[lowered.rindex(marker) + len(marker) :].strip(" ?.!")
            if location:
                return location
    return ""


def _flatten_related_topics(items: list) -> list[dict]:
    """Развернуть RelatedTopics DuckDuckGo с вложенными группами."""
    flattened: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if "Topics" in item and isinstance(item["Topics"], list):
            flattened.extend(_flatten_related_topics(item["Topics"]))
        else:
            flattened.append(item)
    return flattened


def _first_value(items: object) -> str:
    """Достать value из wttr.in массива вида [{'value': '...'}]."""
    if isinstance(items, list) and items and isinstance(items[0], dict):
        return str(items[0].get("value") or "").strip()
    return ""


def _clamp_int(value: object, default: int, minimum: int, maximum: int) -> int:
    """Привести числовой параметр к безопасному диапазону."""
    try:
        parsed_value = int(value)
    except (TypeError, ValueError):
        parsed_value = default
    return max(minimum, min(maximum, parsed_value))
