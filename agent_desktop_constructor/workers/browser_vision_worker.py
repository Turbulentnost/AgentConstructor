"""Vision-driven browser worker на Chrome DevTools Protocol.

В отличие от read-only BrowserCdpWorker, этот worker держит постоянную вкладку и
позволяет LLM управлять UI по скриншотам: делать снимок экрана, кликать по
координатам, вводить текст, нажимать клавиши, прокручивать и переходить по URL.
Каждое действие возвращает свежий скриншот (base64 PNG), чтобы LLM «видела»
результат и решала следующий шаг. Worker не принимает решений сам — он только
безопасно исполняет то, что решила LLM.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any
from urllib import error, request

from agent_desktop_constructor.workers.browser_cdp_worker import (
    BrowserCdpError,
    BrowserLaunchConfig,
    _CdpSession,
    _command_args_summary,
    _find_chromium_executable,
    _planned_command_args_summary,
    _profile_mode,
    _require_http_url,
    _resolved_profile_name,
    _resolve_user_data_dir,
)

DEFAULT_VISION_PORT = 9333
DEFAULT_VIEWPORT_WIDTH = 1280
DEFAULT_VIEWPORT_HEIGHT = 900
MAX_TEXT_LENGTH = 2000

# Виртуальные коды клавиш Windows для типовых спец-клавиш.
_SPECIAL_KEYS: dict[str, dict[str, Any]] = {
    "enter": {"key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13, "text": "\r"},
    "return": {"key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13, "text": "\r"},
    "tab": {"key": "Tab", "code": "Tab", "windowsVirtualKeyCode": 9},
    "escape": {"key": "Escape", "code": "Escape", "windowsVirtualKeyCode": 27},
    "esc": {"key": "Escape", "code": "Escape", "windowsVirtualKeyCode": 27},
    "backspace": {"key": "Backspace", "code": "Backspace", "windowsVirtualKeyCode": 8},
    "delete": {"key": "Delete", "code": "Delete", "windowsVirtualKeyCode": 46},
    "arrowdown": {"key": "ArrowDown", "code": "ArrowDown", "windowsVirtualKeyCode": 40},
    "arrowup": {"key": "ArrowUp", "code": "ArrowUp", "windowsVirtualKeyCode": 38},
    "arrowleft": {"key": "ArrowLeft", "code": "ArrowLeft", "windowsVirtualKeyCode": 37},
    "arrowright": {"key": "ArrowRight", "code": "ArrowRight", "windowsVirtualKeyCode": 39},
}


class BrowserVisionWorker:
    """Управляет постоянной вкладкой браузера по указаниям LLM (скриншоты + ввод)."""

    def __init__(self, config: BrowserLaunchConfig | None = None) -> None:
        """Создать worker с ленивым запуском видимого браузера."""
        self._config = config or BrowserLaunchConfig(port=DEFAULT_VISION_PORT)
        self._process: subprocess.Popen | None = None
        self._user_data_dir = _resolve_user_data_dir(
            self._config,
            profile_kind="vision",
        )
        self._profile_mode = _profile_mode(self._config)
        self._last_command_args_summary: list[str] = []
        self._page_ws_url: str | None = None

    def open(self, input_data: dict) -> dict:
        """Открыть URL в постоянной вкладке и вернуть скриншот."""
        url = _require_http_url(input_data.get("url"))
        with self._session() as session:
            self._navigate(session, url)
            return self._state_with_screenshot(session)

    def navigate(self, input_data: dict) -> dict:
        """Синоним open: перейти по URL и вернуть скриншот."""
        return self.open(input_data)

    def screenshot(self, input_data: dict) -> dict:
        """Сделать скриншот текущей вкладки (опционально сначала перейти на url)."""
        url = str(input_data.get("url") or "").strip()
        with self._session() as session:
            if url:
                self._navigate(session, _require_http_url(url))
            return self._state_with_screenshot(session)

    def click(self, input_data: dict) -> dict:
        """Кликнуть по координатам (x, y) и вернуть новый скриншот."""
        x = _require_number(input_data.get("x"), "x")
        y = _require_number(input_data.get("y"), "y")
        button = str(input_data.get("button") or "left").strip().casefold()
        with self._session() as session:
            session.send("Page.enable")
            session.send("Runtime.enable")
            for event_type in ("mousePressed", "mouseReleased"):
                session.send(
                    "Input.dispatchMouseEvent",
                    {
                        "type": event_type,
                        "x": x,
                        "y": y,
                        "button": button,
                        "clickCount": 1,
                    },
                )
            time.sleep(0.4)
            return self._state_with_screenshot(session)

    def type_text(self, input_data: dict) -> dict:
        """Ввести текст в текущий активный элемент и вернуть скриншот."""
        text = str(input_data.get("text") or "")
        if not text:
            raise BrowserCdpError("Для browser.type_text нужен непустой text.")
        if len(text) > MAX_TEXT_LENGTH:
            raise BrowserCdpError(
                f"text слишком длинный (>{MAX_TEXT_LENGTH} символов)."
            )
        with self._session() as session:
            session.send("Input.insertText", {"text": text})
            time.sleep(0.2)
            return self._state_with_screenshot(session)

    def press_key(self, input_data: dict) -> dict:
        """Нажать спец-клавишу (Enter/Tab/Escape/стрелки) и вернуть скриншот."""
        key_name = str(input_data.get("key") or "").strip().casefold()
        descriptor = _SPECIAL_KEYS.get(key_name)
        if descriptor is None:
            raise BrowserCdpError(
                "Поддерживаются клавиши: "
                + ", ".join(sorted({k for k in _SPECIAL_KEYS}))
            )
        with self._session() as session:
            session.send("Input.dispatchKeyEvent", {"type": "rawKeyDown", **descriptor})
            if "text" in descriptor:
                session.send("Input.dispatchKeyEvent", {"type": "char", **descriptor})
            session.send("Input.dispatchKeyEvent", {"type": "keyUp", **descriptor})
            time.sleep(0.3)
            return self._state_with_screenshot(session)

    def scroll(self, input_data: dict) -> dict:
        """Прокрутить нужный контейнер и вернуть скриншот с метриками прокрутки.

        Сама находит подходящую область прокрутки: если заданы x/y — берёт
        элемент под этой точкой и его ближайшего прокручиваемого родителя;
        иначе выбирает самый большой видимый прокручиваемый контейнер (например,
        список чатов), а если такого нет — прокручивает всю страницу. Работает
        по вертикали и по горизонтали и сообщает, сдвинулась ли страница и
        достигнут ли край.
        """
        direction = str(input_data.get("direction") or "down").strip().casefold()
        pixels = int(_require_number(input_data.get("pixels"), "pixels", default=700))
        has_point = input_data.get("x") is not None and input_data.get("y") is not None
        x = int(_require_number(input_data.get("x"), "x", default=0)) if has_point else -1
        y = int(_require_number(input_data.get("y"), "y", default=0)) if has_point else -1

        dx = 0
        dy = 0
        if direction in {"up", "вверх"}:
            dy = -pixels
        elif direction in {"left", "влево"}:
            dx = -pixels
        elif direction in {"right", "вправо"}:
            dx = pixels
        else:
            dy = pixels

        script = _SCROLL_SCRIPT_TEMPLATE.format(dx=dx, dy=dy, x=x, y=y)
        with self._session() as session:
            session.send("Runtime.enable")
            metrics = session.evaluate(script) or {}
            time.sleep(0.25)
            state = self._state_with_screenshot(session)
        if isinstance(metrics, dict):
            state.update(
                {
                    "scrolled": bool(metrics.get("scrolled")),
                    "scroll_top": metrics.get("scroll_top"),
                    "scroll_left": metrics.get("scroll_left"),
                    "scroll_height": metrics.get("scroll_height"),
                    "client_height": metrics.get("client_height"),
                    "at_bottom": bool(metrics.get("at_bottom")),
                    "at_top": bool(metrics.get("at_top")),
                    "scroll_target": metrics.get("target"),
                }
            )
        return state

    def _state_with_screenshot(self, session: _CdpSession) -> dict:
        """Собрать url/title/размеры и base64 PNG-скриншот текущей страницы."""
        session.send("Page.enable")
        session.send("Runtime.enable")
        result = session.send(
            "Page.captureScreenshot",
            {"format": "png", "captureBeyondViewport": False},
        )
        screenshot_base64 = str(result.get("data") or "")
        url = session.evaluate("location.href")
        title = session.evaluate("document.title")
        viewport = session.evaluate(
            "({w: window.innerWidth||0, h: window.innerHeight||0})"
        ) or {}
        return {
            "url": url,
            "title": title,
            "screenshot_base64": screenshot_base64,
            "screenshot_media_type": "image/png",
            "viewport_width": int(viewport.get("w") or DEFAULT_VIEWPORT_WIDTH),
            "viewport_height": int(viewport.get("h") or DEFAULT_VIEWPORT_HEIGHT),
            **self.profile_output(),
        }

    def profile_output(self) -> dict:
        """Вернуть безопасную диагностику режима профиля vision worker."""
        return {
            "profile_mode": self._profile_mode,
            "user_data_dir": self._user_data_dir or "",
            "used_default_profile": self._profile_mode == "default",
            "command_args_summary": self._last_command_args_summary
            or _planned_command_args_summary(self._config, self._user_data_dir),
        }

    def _session(self) -> _CdpSession:
        """Вернуть CDP session постоянной вкладки (запустив браузер при нужде)."""
        self._ensure_browser()
        websocket_url = self._ensure_page_ws_url()
        return _CdpSession(websocket_url, timeout_seconds=self._config.timeout_seconds)

    def _ensure_browser(self) -> None:
        """Подключиться к существующему CDP или запустить видимый Chromium."""
        if self._is_cdp_available():
            return
        executable = self._config.executable_path or _find_chromium_executable()
        if executable is None:
            raise BrowserCdpError(
                "Не найден Edge/Chrome/Chromium для vision browser worker."
            )
        command = [
            executable,
            f"--remote-debugging-port={self._config.port}",
            f"--window-size={DEFAULT_VIEWPORT_WIDTH},{DEFAULT_VIEWPORT_HEIGHT}",
        ]
        if self._user_data_dir:
            if self._profile_mode != "default":
                Path(self._user_data_dir).mkdir(parents=True, exist_ok=True)
            command.append(f"--user-data-dir={self._user_data_dir}")
        profile_name = _resolved_profile_name(self._config)
        if profile_name and (
            self._config.use_default_profile or self._config.user_data_dir
        ):
            command.append(f"--profile-directory={profile_name}")
        command.extend(
            [
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-popup-blocking",
                "about:blank",
            ]
        )
        self._last_command_args_summary = _command_args_summary(
            command,
            executable=executable,
        )
        self._process = subprocess.Popen(  # noqa: S603 - executable найден локально
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self._page_ws_url = None
        deadline = time.time() + self._config.timeout_seconds
        while time.time() < deadline:
            if self._is_cdp_available():
                return
            time.sleep(0.2)
        raise BrowserCdpError("Браузер запущен, но CDP endpoint не ответил.")

    def _ensure_page_ws_url(self) -> str:
        """Получить websocket постоянной вкладки, создав её один раз."""
        if self._page_ws_url and self._page_ws_alive(self._page_ws_url):
            return self._page_ws_url
        pages = self._get_json("/json/list")
        if isinstance(pages, list):
            for page in pages:
                if page.get("type") == "page" and page.get("webSocketDebuggerUrl"):
                    self._page_ws_url = str(page["webSocketDebuggerUrl"])
                    return self._page_ws_url
        payload = self._get_json("/json/new", method="PUT")
        websocket_url = payload.get("webSocketDebuggerUrl")
        if not websocket_url:
            raise BrowserCdpError("Не удалось создать вкладку для vision worker.")
        self._page_ws_url = str(websocket_url)
        return self._page_ws_url

    def _page_ws_alive(self, websocket_url: str) -> bool:
        """Проверить, что сохранённая вкладка ещё существует."""
        pages = self._get_json("/json/list")
        if not isinstance(pages, list):
            return False
        return any(page.get("webSocketDebuggerUrl") == websocket_url for page in pages)

    def _is_cdp_available(self) -> bool:
        """Проверить, отвечает ли CDP endpoint."""
        try:
            payload = self._get_json("/json/version")
        except Exception:
            return False
        return bool(payload.get("webSocketDebuggerUrl") or payload.get("Browser"))

    def _get_json(self, path: str, method: str = "GET") -> Any:
        """Прочитать JSON с локального CDP HTTP endpoint."""
        url = f"http://127.0.0.1:{self._config.port}{path}"
        http_request = request.Request(url, method=method)
        try:
            with request.urlopen(
                http_request,
                timeout=self._config.timeout_seconds,
            ) as response:
                return json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            raise BrowserCdpError(f"CDP HTTP {exc.code}: {url}") from exc
        except (error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise BrowserCdpError(f"CDP endpoint недоступен: {exc}") from exc

    def _navigate(self, session: _CdpSession, url: str) -> None:
        """Перейти на URL и дождаться загрузки DOM."""
        session.send("Page.enable")
        session.send("Runtime.enable")
        session.send("Page.navigate", {"url": _require_http_url(url)})
        deadline = time.time() + self._config.timeout_seconds
        while time.time() < deadline:
            ready_state = session.evaluate("document.readyState")
            if ready_state in {"interactive", "complete"}:
                time.sleep(0.4)
                return
            time.sleep(0.2)
        raise BrowserCdpError("Страница не загрузилась за timeout.")


# JS находит правильную область прокрутки и двигает её. Без хардкода конкретных
# сайтов: опирается только на CSS overflow и реальные размеры прокрутки.
_SCROLL_SCRIPT_TEMPLATE = """
(function() {{
  var dx = {dx}, dy = {dy}, px = {x}, py = {y};
  function scrollableAxis(el) {{
    if (!(el instanceof Element)) return {{y: false, x: false}};
    var s = getComputedStyle(el);
    var canY = (s.overflowY === 'auto' || s.overflowY === 'scroll')
      && el.scrollHeight > el.clientHeight + 2;
    var canX = (s.overflowX === 'auto' || s.overflowX === 'scroll')
      && el.scrollWidth > el.clientWidth + 2;
    return {{y: canY, x: canX}};
  }}
  function needAxis(a) {{ return (dy !== 0 && a.y) || (dx !== 0 && a.x); }}
  function fromPoint(x, y) {{
    var el = document.elementFromPoint(x, y);
    while (el && el !== document.body && el !== document.documentElement) {{
      if (needAxis(scrollableAxis(el))) return el;
      el = el.parentElement;
    }}
    return null;
  }}
  function largest() {{
    var best = null, bestArea = 0;
    var nodes = document.querySelectorAll('*');
    for (var i = 0; i < nodes.length; i++) {{
      var el = nodes[i];
      var a = scrollableAxis(el);
      if (!needAxis(a)) continue;
      var rect = el.getBoundingClientRect();
      if (rect.width < 60 || rect.height < 60) continue;
      if (rect.bottom < 0 || rect.top > (window.innerHeight || 0)) continue;
      var area = (el.scrollHeight - el.clientHeight) + (el.scrollWidth - el.clientWidth);
      if (area > bestArea) {{ bestArea = area; best = el; }}
    }}
    return best;
  }}
  var target = (px >= 0 && py >= 0) ? fromPoint(px, py) : largest();
  var usedWindow = false;
  if (!target) {{ target = document.scrollingElement || document.documentElement; usedWindow = true; }}
  var beforeTop = target.scrollTop, beforeLeft = target.scrollLeft;
  target.scrollTop = beforeTop + dy;
  target.scrollLeft = beforeLeft + dx;
  var afterTop = target.scrollTop, afterLeft = target.scrollLeft;
  var desc = (usedWindow ? 'window' : (target.tagName || '').toLowerCase());
  if (!usedWindow && target.className && typeof target.className === 'string') {{
    desc += '.' + target.className.trim().split(/\\s+/).slice(0, 2).join('.');
  }}
  return {{
    scrolled: (afterTop !== beforeTop) || (afterLeft !== beforeLeft),
    scroll_top: afterTop,
    scroll_left: afterLeft,
    scroll_height: target.scrollHeight,
    client_height: target.clientHeight,
    at_bottom: (afterTop + target.clientHeight) >= (target.scrollHeight - 2),
    at_top: afterTop <= 0,
    target: desc.slice(0, 60)
  }};
}})()
"""


def _require_number(value: object, name: str, default: float | None = None) -> float:
    """Привести значение к числу или вернуть понятную ошибку."""
    if value is None and default is not None:
        return float(default)
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise BrowserCdpError(f"Параметр {name} должен быть числом.") from exc
