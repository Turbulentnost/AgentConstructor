"""Unit-тесты BrowserCdpWorker без запуска реального браузера."""

from __future__ import annotations

import pytest

from agent_desktop_constructor.workers import browser_cdp_worker as cdp
from agent_desktop_constructor.workers.browser_cdp_worker import (
    BrowserCdpError,
    BrowserCdpWorker,
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
