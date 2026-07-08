"""Тесты read-only web tools."""

from __future__ import annotations

import json

from agent_desktop_constructor.tools.registry import ToolRegistry
from agent_desktop_constructor.tools.web_tools import (
    BrowserClickLinkTool,
    BrowserExtractTableTool,
    BrowserOpenBrowserTool,
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

    assert registry.has_tool("browser.list_installed_browsers")
    assert registry.has_tool("browser.open_browser")
    assert registry.has_tool("browser.search_web")
    assert registry.has_tool("browser.open_page")
    assert registry.has_tool("browser.extract_table")
    assert registry.has_tool("browser.scroll_page")
    assert registry.has_tool("browser.click_link")


def test_browser_list_installed_browsers_returns_detected(monkeypatch) -> None:
    """browser.list_installed_browsers возвращает найденные браузеры."""
    from agent_desktop_constructor.tools.web_tools import (
        BrowserListInstalledBrowsersTool,
    )

    fake_browsers = [
        {
            "name": "edge",
            "family": "chromium",
            "executable_path": "C:/edge/msedge.exe",
            "version": "122.0.0.0",
            "supports_cdp": True,
            "readable": True,
        },
        {
            "name": "firefox",
            "family": "gecko",
            "executable_path": "C:/ff/firefox.exe",
            "version": None,
            "supports_cdp": False,
            "readable": False,
        },
    ]
    monkeypatch.setattr(
        "agent_desktop_constructor.tools.web_tools.list_installed_browsers",
        lambda: fake_browsers,
    )

    result = BrowserListInstalledBrowsersTool().execute({})

    assert result.ok is True
    assert result.output_data["count"] == 2
    assert result.output_data["default_readable_browser"] == "edge"
    assert result.output_data["browsers"][0]["name"] == "edge"


def test_browser_open_browser_launches_specific_executable(monkeypatch) -> None:
    """browser.open_browser запускает выбранный executable, а не default browser."""
    captured: dict = {}

    class FakeProcess:
        pid = 1234

    def fake_popen(command, stdout, stderr):
        captured["command"] = command
        return FakeProcess()

    monkeypatch.setattr(
        "agent_desktop_constructor.tools.web_tools.resolve_browser_executable",
        lambda name: "C:/Users/me/AppData/Local/Yandex/YandexBrowser/Application/browser.exe"
        if name == "yandex"
        else None,
    )
    monkeypatch.setattr(
        "agent_desktop_constructor.tools.web_tools.subprocess.Popen",
        fake_popen,
    )
    monkeypatch.setattr(
        "agent_desktop_constructor.workers.browser_detect.os.name",
        "nt",
    )
    monkeypatch.setenv("LOCALAPPDATA", "C:/Users/me/AppData/Local")

    result = BrowserOpenBrowserTool().execute(
        {"browser_name": "яндекс", "url": "https://yandex.ru"}
    )

    assert result.ok is True
    assert result.output_data["browser_id"] == "yandex"
    assert captured["command"] == [
        "C:/Users/me/AppData/Local/Yandex/YandexBrowser/Application/browser.exe",
        "https://yandex.ru",
    ]
    assert not any(arg.startswith("--user-data-dir=") for arg in captured["command"])
    assert "--incognito" not in captured["command"]
    assert "--guest" not in captured["command"]
    assert result.output_data["profile_mode"] == "default"
    assert result.output_data["used_default_profile"] is True
    assert result.output_data["user_data_dir"] == (
        r"C:\Users\me\AppData\Local\Yandex\YandexBrowser\User Data"
    )
    assert "no --user-data-dir" in result.output_data["command_args_summary"]


def test_browser_open_browser_reports_available_when_not_found(monkeypatch) -> None:
    """Если браузер не найден, ошибка содержит доступные browser id."""
    monkeypatch.setattr(
        "agent_desktop_constructor.tools.web_tools.resolve_browser_executable",
        lambda name: None,
    )
    monkeypatch.setattr(
        "agent_desktop_constructor.tools.web_tools.list_installed_browsers",
        lambda: [{"id": "edge", "name": "edge", "path": "C:/edge/msedge.exe"}],
    )

    result = BrowserOpenBrowserTool().execute({"browser_id": "yandex"})

    assert result.ok is False
    assert result.error_type == "BROWSER_NOT_FOUND"
    assert "edge" in result.error_message
    assert result.output_data["available_browsers"][0]["id"] == "edge"


def test_browser_open_page_routes_to_specific_browser() -> None:
    """browser=... направляет вызов в worker конкретного браузера."""
    default_worker = FakeBrowserWorker()

    result = BrowserOpenPageTool(default_worker).execute(
        {"url": "https://example.com"}
    )

    assert result.ok is True
    assert default_worker.calls == [("open_page", {"url": "https://example.com"})]


def test_browser_open_page_rejects_non_cdp_browser() -> None:
    """Firefox (не Chromium) не поддерживает чтение через CDP — понятная ошибка."""
    result = BrowserOpenPageTool(FakeBrowserWorker()).execute(
        {"url": "https://example.com", "browser": "firefox"}
    )

    assert result.ok is False
    assert result.error_type == "BROWSER_CDP_ERROR"
    assert "firefox" in result.error_message.lower()


def test_browser_open_page_accepts_browser_id(monkeypatch) -> None:
    """browser_id=... тоже направляет CDP-вызов в выбранный браузер."""
    created: dict = {}

    class ProviderWorker(FakeBrowserWorker):
        pass

    def fake_worker(config):
        created["config"] = config
        return ProviderWorker()

    monkeypatch.setattr(
        "agent_desktop_constructor.tools.web_tools.find_readable_browser",
        lambda name: object() if name == "yandex" else None,
    )
    monkeypatch.setattr(
        "agent_desktop_constructor.tools.web_tools.resolve_browser_executable",
        lambda name: "C:/Yandex/browser.exe" if name == "yandex" else None,
    )
    monkeypatch.setattr(
        "agent_desktop_constructor.tools.web_tools.BrowserCdpWorker",
        fake_worker,
    )

    result = BrowserOpenPageTool(FakeBrowserWorker()).execute(
        {"url": "https://example.com", "browser_id": "яндекс"}
    )

    assert result.ok is True
    assert created["config"].executable_path == "C:/Yandex/browser.exe"
    assert created["config"].browser_id == "yandex"


def test_browser_open_page_accepts_explicit_default_profile(monkeypatch) -> None:
    """Параметры профиля передаются в CDP worker только явно."""
    created: dict = {}

    class ProviderWorker(FakeBrowserWorker):
        pass

    def fake_worker(config):
        created["config"] = config
        return ProviderWorker()

    monkeypatch.setattr(
        "agent_desktop_constructor.tools.web_tools.find_readable_browser",
        lambda name: object() if name == "chrome" else None,
    )
    monkeypatch.setattr(
        "agent_desktop_constructor.tools.web_tools.resolve_browser_executable",
        lambda name: "C:/Chrome/chrome.exe" if name == "chrome" else None,
    )
    monkeypatch.setattr(
        "agent_desktop_constructor.tools.web_tools.BrowserCdpWorker",
        fake_worker,
    )

    result = BrowserOpenPageTool(FakeBrowserWorker()).execute(
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


SAMPLE_DDG_HTML = """
<html><body>
<div class="result results_links results_links_deep web-result">
  <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fmoon&rut=x">
    Лунный календарь на 3 июля 2026
  </a>
  <a class="result__snippet" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fmoon">
    Благоприятные дни и фаза Луны на 3 июля 2026 года.
  </a>
</div>
<div class="result results_links results_links_deep web-result">
  <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.org%2Fhoroscope&rut=y">
    Гороскоп на 3 июля 2026
  </a>
  <a class="result__snippet">Астрологический прогноз на день.</a>
</div>
</body></html>
"""


def test_duckduckgo_html_parser_extracts_results() -> None:
    """Парсер SERP извлекает заголовки, сниппеты и раскодирует ссылки."""
    from agent_desktop_constructor.tools.web_tools import _DuckDuckGoHtmlParser

    parser = _DuckDuckGoHtmlParser()
    parser.feed(SAMPLE_DDG_HTML)
    results = parser.cleaned_results()

    assert len(results) == 2
    assert results[0]["title"] == "Лунный календарь на 3 июля 2026"
    assert results[0]["url"] == "https://example.com/moon"
    assert "Благоприятные дни" in results[0]["snippet"]
    assert results[1]["url"] == "https://example.org/horoscope"


def test_browser_search_web_returns_serp_results(monkeypatch) -> None:
    """Общий запрос возвращает реальные результаты SERP, даже без instant answer."""
    monkeypatch.setattr(
        "agent_desktop_constructor.tools.web_tools._read_text",
        lambda base_url, params=None: SAMPLE_DDG_HTML,
    )
    monkeypatch.setattr(
        "agent_desktop_constructor.tools.web_tools._read_json",
        lambda url: {"AbstractText": "", "RelatedTopics": []},
    )

    result = BrowserSearchWebTool().execute(
        {"query": "лунный календарь 3 июля 2026", "max_results": 5}
    )

    assert result.ok is True
    assert result.output_data["source"] == "duckduckgo"
    assert len(result.output_data["results"]) == 2
    assert result.output_data["results"][0]["url"] == "https://example.com/moon"
    assert result.output_data["answer"]


def test_browser_search_web_errors_when_no_results(monkeypatch) -> None:
    """Если и SERP, и instant answer пусты — возвращается понятная ошибка."""

    def raise_network(*args, **kwargs):
        raise RuntimeError("Не удалось выполнить web-поиск: network down")

    monkeypatch.setattr(
        "agent_desktop_constructor.tools.web_tools._read_text",
        raise_network,
    )
    monkeypatch.setattr(
        "agent_desktop_constructor.tools.web_tools._read_json",
        raise_network,
    )

    result = BrowserSearchWebTool().execute({"query": "что-то очень редкое"})

    assert result.ok is False
    assert result.error_type == "WEB_SEARCH_ERROR"


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
