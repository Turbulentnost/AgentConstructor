"""Vision-инструменты браузера: LLM управляет UI по скриншотам.

Инструменты только исполняют действие и возвращают свежий скриншот. Решение о
том, куда кликнуть, что ввести и куда перейти, принимает LLM, «видя» страницу
(скриншот прикладывается к её контексту в цикле выполнения). Никакого хардкода
сценариев — только примитивы взаимодействия с UI.
"""

from __future__ import annotations

from agent_desktop_constructor.core.models.tooling import (
    ToolCallResult,
    ToolDefinition,
    ToolExecutionMode,
    ToolSideEffectLevel,
)
from agent_desktop_constructor.tools.base import BaseTool
from agent_desktop_constructor.tools.registry import ToolRegistry
from agent_desktop_constructor.workers.browser_vision_worker import (
    BrowserVisionWorker,
    DEFAULT_VISION_PORT,
)
from agent_desktop_constructor.workers.browser_cdp_worker import (
    BrowserCdpError,
    BrowserLaunchConfig,
)
from agent_desktop_constructor.workers.browser_detect import (
    find_readable_browser,
    normalize_browser_id,
    resolve_browser_executable,
)


def _requested_browser_name(input_data: dict) -> str:
    """Достать browser_id/browser_name/browser из входных данных."""
    return str(
        input_data.get("browser_id")
        or input_data.get("browser_name")
        or input_data.get("browser")
        or ""
    ).strip()


class BrowserVisionWorkerProvider:
    """Выдаёт vision worker для выбранного Chromium-браузера."""

    def __init__(self, default_worker: BrowserVisionWorker) -> None:
        """Сохранить дефолтный worker и per-browser cache."""
        self._default_worker = default_worker
        self._by_browser: dict[str, BrowserVisionWorker] = {}
        self._active_key: str | None = None

    def get(self, input_data: dict) -> BrowserVisionWorker:
        """Вернуть worker для browser_id/name или последний активный."""
        name = _requested_browser_name(input_data)
        profile_options = _profile_options(input_data)
        inherited_session = _inherited_user_browser_session(input_data)
        inherited_session_used = False
        if inherited_session and not name and not _has_explicit_profile(input_data):
            name = str(inherited_session.get("browser_id") or "")
            profile_options = {
                "use_default_profile": True,
                "profile_name": None,
                "user_data_dir": None,
            }
            inherited_session_used = True
        if not name and not _has_explicit_profile(input_data):
            if self._active_key:
                return self._by_browser[self._active_key]
            return self._default_worker

        key = normalize_browser_id(name) if name else "default"
        if name and find_readable_browser(key) is None:
            raise BrowserCdpError(
                f"Браузер {name!r} не поддерживает vision/CDP. Проверь доступные "
                "Chromium-браузеры через browser.list_installed_browsers."
            )
        executable = resolve_browser_executable(key) if name else None
        if name and executable is None:
            raise BrowserCdpError(
                f"Браузер {name!r} не найден на устройстве. Сначала вызови "
                "browser.list_installed_browsers и выбери id из списка."
            )

        cache_key = _worker_cache_key(key, profile_options)
        worker = self._by_browser.get(cache_key)
        if worker is None:
            worker = BrowserVisionWorker(
                BrowserLaunchConfig(
                    port=DEFAULT_VISION_PORT + 1 + len(self._by_browser),
                    executable_path=executable,
                    browser_id=key,
                    **profile_options,
                )
            )
            self._by_browser[cache_key] = worker
        if inherited_session_used:
            worker.activate_os_fallback(
                url=str(inherited_session.get("url") or ""),
                command_args_summary=inherited_session.get("command_args_summary")
                if isinstance(inherited_session.get("command_args_summary"), list)
                else None,
            )
        self._active_key = cache_key
        return worker


class _BaseVisionTool(BaseTool):
    """Общая логика vision-инструментов: вызвать worker и нормализовать ошибку."""

    def __init__(
        self,
        definition: ToolDefinition,
        provider: BrowserVisionWorkerProvider,
    ) -> None:
        """Сохранить общий vision worker."""
        super().__init__(definition)
        self._provider = provider

    def _method_name(self) -> str:
        """Имя метода worker для этого инструмента."""
        raise NotImplementedError

    def execute(self, input_data: dict) -> ToolCallResult:
        """Выполнить действие vision worker и вернуть скриншот/состояние."""
        try:
            worker = self._provider.get(input_data)
            action = getattr(worker, self._method_name())
            output_data = action(input_data)
        except BrowserCdpError as exc:
            return ToolCallResult(
                ok=False,
                tool_name=self.definition.name,
                error_type="BROWSER_CDP_ERROR",
                error_message=str(exc),
                output_data=exc.output_data,
            )
        except Exception as exc:  # noqa: BLE001 - worker изолирует ошибки браузера
            return ToolCallResult(
                ok=False,
                tool_name=self.definition.name,
                error_type="BROWSER_VISION_ERROR",
                error_message=str(exc),
            )
        return ToolCallResult(
            ok=True,
            tool_name=self.definition.name,
            output_data=output_data,
        )


_SCREENSHOT_OUTPUT = {
    "type": "object",
    "properties": {
        "url": {"type": "string"},
        "title": {"type": "string"},
        "screenshot_base64": {"type": "string"},
        "viewport_width": {"type": "integer"},
        "viewport_height": {"type": "integer"},
        "profile_mode": {"type": "string"},
        "user_data_dir": {"type": "string"},
        "used_default_profile": {"type": "boolean"},
        "command_args_summary": {"type": "array"},
        "cdp_available": {"type": "boolean"},
        "cdp_url": {"type": "string"},
        "fallback_used": {"type": "boolean"},
        "fallback_reason": {"type": "string"},
        "next_action_hint": {"type": "string"},
        "warning": {"type": "string"},
    },
}

_BROWSER_INPUT_PROPERTIES = {
    "browser_id": {"type": "string"},
    "browser_name": {"type": "string"},
    "browser": {"type": "string"},
    "use_default_profile": {"type": "boolean"},
    "allow_open_browser_fallback": {"type": "boolean"},
    "allow_os_fallback": {"type": "boolean"},
    "profile_name": {"type": "string"},
    "user_data_dir": {"type": "string"},
}


def _bool_input(value: object) -> bool:
    """Разобрать bool-флаг из JSON-like input."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "yes", "да", "истина"}
    return bool(value)


def _profile_options(input_data: dict) -> dict[str, object]:
    """Вытащить явные настройки профиля для vision worker."""
    return {
        "use_default_profile": _bool_input(input_data.get("use_default_profile")),
        "profile_name": str(input_data.get("profile_name") or "").strip() or None,
        "user_data_dir": str(input_data.get("user_data_dir") or "").strip() or None,
    }


def _has_explicit_profile(input_data: dict) -> bool:
    """Проверить, просил ли caller не дефолтный automation worker."""
    return any(
        key in input_data and input_data.get(key) not in {None, "", False}
        for key in ("use_default_profile", "profile_name", "user_data_dir")
    )


def _inherited_user_browser_session(input_data: dict) -> dict | None:
    """Найти в tool_outputs уже открытый обычный браузер с пользовательским профилем."""
    tool_outputs = input_data.get("tool_outputs")
    if not isinstance(tool_outputs, dict):
        return None
    for tool_name in ("browser.open_browser", "browser.navigate"):
        output = tool_outputs.get(tool_name)
        if not isinstance(output, dict):
            continue
        browser_id = str(output.get("browser_id") or output.get("browser_name") or "").strip()
        if not browser_id:
            continue
        if output.get("used_default_profile") is True or output.get("profile_mode") == "default":
            if output.get("cdp_available") is False or tool_name == "browser.open_browser":
                return output
    return None


def _worker_cache_key(browser_id: str, profile_options: dict[str, object]) -> str:
    """Стабильный cache key для browser/profile worker."""
    return "|".join(
        [
            browser_id,
            f"default={bool(profile_options.get('use_default_profile'))}",
            f"profile={profile_options.get('profile_name') or ''}",
            f"data={profile_options.get('user_data_dir') or ''}",
        ]
    )


class BrowserNavigateTool(_BaseVisionTool):
    """Открыть URL в управляемой вкладке и вернуть скриншот."""

    def __init__(self, provider: BrowserVisionWorkerProvider) -> None:
        """Создать инструмент browser.navigate."""
        super().__init__(
            ToolDefinition(
                name="browser.navigate",
                title="Открыть страницу в браузере (UI)",
                description=(
                    "Открывает URL в управляемой вкладке браузера и возвращает "
                    "скриншот страницы. По умолчанию использует стабильный "
                    "automation-профиль; use_default_profile/profile_name/"
                    "user_data_dir применяются только при явном указании. Если "
                    "штатный профиль уже открыт без CDP, может открыть URL обычным "
                    "браузером и перейти в OS fallback: cdp_available=false, "
                    "но screenshot/click/type_text продолжат работать по видимому экрану."
                ),
                side_effect_level=ToolSideEffectLevel.CREATE_DRAFT,
                execution_mode=ToolExecutionMode.BROWSER_WORKER,
                requires_human_approval=False,
                timeout_seconds=40,
                input_schema={
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        **_BROWSER_INPUT_PROPERTIES,
                    },
                    "required": ["url"],
                },
                output_schema=_SCREENSHOT_OUTPUT,
            ),
            provider,
        )

    def _method_name(self) -> str:
        return "navigate"


class BrowserScreenshotTool(_BaseVisionTool):
    """Сделать скриншот текущей вкладки для анализа LLM."""

    def __init__(self, provider: BrowserVisionWorkerProvider) -> None:
        """Создать инструмент browser.screenshot."""
        super().__init__(
            ToolDefinition(
                name="browser.screenshot",
                title="Скриншот страницы браузера",
                description=(
                    "Делает скриншот текущей вкладки браузера (base64 PNG), чтобы "
                    "LLM видела UI и решила следующее действие. Если штатный профиль "
                    "открыт без CDP после fallback, делает скриншот видимого экрана."
                ),
                side_effect_level=ToolSideEffectLevel.READ,
                execution_mode=ToolExecutionMode.BROWSER_WORKER,
                requires_human_approval=False,
                timeout_seconds=40,
                input_schema={
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        **_BROWSER_INPUT_PROPERTIES,
                    },
                },
                output_schema=_SCREENSHOT_OUTPUT,
            ),
            provider,
        )

    def _method_name(self) -> str:
        return "screenshot"


_PAGE_HTML_OUTPUT = {
    "type": "object",
    "properties": {
        "url": {"type": "string"},
        "title": {"type": "string"},
        "html": {"type": "string"},
        "html_length": {"type": "integer"},
        "truncated": {"type": "boolean"},
        "html_summary": {"type": "string"},
        "profile_mode": {"type": "string"},
        "user_data_dir": {"type": "string"},
        "used_default_profile": {"type": "boolean"},
        "command_args_summary": {"type": "array"},
        "cdp_available": {"type": "boolean"},
        "cdp_url": {"type": "string"},
        "fallback_used": {"type": "boolean"},
        "fallback_reason": {"type": "string"},
        "next_action_hint": {"type": "string"},
        "warning": {"type": "string"},
    },
}


class BrowserGetPageHtmlTool(_BaseVisionTool):
    """Получить HTML-код текущей вкладки через CDP."""

    def __init__(self, provider: BrowserVisionWorkerProvider) -> None:
        """Создать инструмент browser.get_page_html."""
        super().__init__(
            ToolDefinition(
                name="browser.get_page_html",
                title="HTML текущей страницы браузера",
                description=(
                    "Возвращает HTML текущей вкладки (document.documentElement.outerHTML) "
                    "через CDP: url, title, html (с лимитом), html_length, truncated, "
                    "html_summary. Нужен для структуры DOM, селекторов, текста форм и "
                    "скрытого контента — не заменяет screenshot для визуального UI."
                ),
                side_effect_level=ToolSideEffectLevel.READ,
                execution_mode=ToolExecutionMode.BROWSER_WORKER,
                requires_human_approval=False,
                timeout_seconds=40,
                input_schema={
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "max_chars": {"type": "integer"},
                        "summary_chars": {"type": "integer"},
                        **_BROWSER_INPUT_PROPERTIES,
                    },
                },
                output_schema=_PAGE_HTML_OUTPUT,
            ),
            provider,
        )

    def _method_name(self) -> str:
        return "get_page_html"


class BrowserClickTool(_BaseVisionTool):
    """Кликнуть по координатам на странице (координаты определяет LLM по скриншоту)."""

    def __init__(self, provider: BrowserVisionWorkerProvider) -> None:
        """Создать инструмент browser.click."""
        super().__init__(
            ToolDefinition(
                name="browser.click",
                title="Клик по координатам в браузере",
                description=(
                    "Кликает по координатам (x, y) со скриншота и возвращает новый "
                    "скриншот. В CDP-режиме координаты viewport; в OS fallback после "
                    "штатного профиля — координаты видимого экрана."
                ),
                side_effect_level=ToolSideEffectLevel.CREATE_DRAFT,
                execution_mode=ToolExecutionMode.BROWSER_WORKER,
                requires_human_approval=False,
                timeout_seconds=40,
                input_schema={
                    "type": "object",
                    "properties": {
                        "x": {"type": "number"},
                        "y": {"type": "number"},
                        "button": {"type": "string"},
                        **_BROWSER_INPUT_PROPERTIES,
                    },
                    "required": ["x", "y"],
                },
                output_schema=_SCREENSHOT_OUTPUT,
            ),
            provider,
        )

    def _method_name(self) -> str:
        return "click"


class BrowserTypeTextTool(_BaseVisionTool):
    """Ввести текст в активный элемент страницы и вернуть скриншот."""

    def __init__(self, provider: BrowserVisionWorkerProvider) -> None:
        """Создать инструмент browser.type_text."""
        super().__init__(
            ToolDefinition(
                name="browser.type_text",
                title="Ввод текста в браузере",
                description=(
                    "Вводит текст в текущий активный элемент (сначала кликни в поле "
                    "через browser.click) и возвращает скриншот. В OS fallback "
                    "вставляет текст в активное окно через clipboard."
                ),
                side_effect_level=ToolSideEffectLevel.CREATE_DRAFT,
                execution_mode=ToolExecutionMode.BROWSER_WORKER,
                requires_human_approval=False,
                timeout_seconds=40,
                input_schema={
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        **_BROWSER_INPUT_PROPERTIES,
                    },
                    "required": ["text"],
                },
                output_schema=_SCREENSHOT_OUTPUT,
            ),
            provider,
        )

    def _method_name(self) -> str:
        return "type_text"


class BrowserPressKeyTool(_BaseVisionTool):
    """Нажать спец-клавишу (Enter/Tab/Escape/стрелки) и вернуть скриншот."""

    def __init__(self, provider: BrowserVisionWorkerProvider) -> None:
        """Создать инструмент browser.press_key."""
        super().__init__(
            ToolDefinition(
                name="browser.press_key",
                title="Нажатие клавиши в браузере",
                description=(
                    "Нажимает спец-клавишу (enter, tab, escape, backspace, стрелки) "
                    "в браузере и возвращает скриншот. В OS fallback нажимает клавишу "
                    "в активном окне."
                ),
                side_effect_level=ToolSideEffectLevel.CREATE_DRAFT,
                execution_mode=ToolExecutionMode.BROWSER_WORKER,
                requires_human_approval=False,
                timeout_seconds=40,
                input_schema={
                    "type": "object",
                    "properties": {
                        "key": {"type": "string"},
                        **_BROWSER_INPUT_PROPERTIES,
                    },
                    "required": ["key"],
                },
                output_schema=_SCREENSHOT_OUTPUT,
            ),
            provider,
        )

    def _method_name(self) -> str:
        return "press_key"


class BrowserScrollTool(_BaseVisionTool):
    """Прокрутить управляемую вкладку и вернуть скриншот."""

    def __init__(self, provider: BrowserVisionWorkerProvider) -> None:
        """Создать инструмент browser.scroll."""
        super().__init__(
            ToolDefinition(
                name="browser.scroll",
                title="Прокрутка браузера (UI)",
                description=(
                    "Прокручивает текущую вкладку вверх/вниз и возвращает скриншот. "
                    "В OS fallback прокручивает активное окно системным wheel-событием."
                ),
                side_effect_level=ToolSideEffectLevel.CREATE_DRAFT,
                execution_mode=ToolExecutionMode.BROWSER_WORKER,
                requires_human_approval=False,
                timeout_seconds=40,
                input_schema={
                    "type": "object",
                    "properties": {
                        "direction": {"type": "string"},
                        "pixels": {"type": "integer"},
                        **_BROWSER_INPUT_PROPERTIES,
                    },
                },
                output_schema=_SCREENSHOT_OUTPUT,
            ),
            provider,
        )

    def _method_name(self) -> str:
        return "scroll"


def register_browser_vision_tools(
    registry: ToolRegistry,
    *,
    skip_existing: bool = False,
    worker: BrowserVisionWorker | None = None,
) -> None:
    """Зарегистрировать vision-инструменты браузера с общим worker."""
    provider = BrowserVisionWorkerProvider(worker or BrowserVisionWorker())
    tools = [
        BrowserNavigateTool(provider),
        BrowserScreenshotTool(provider),
        BrowserGetPageHtmlTool(provider),
        BrowserClickTool(provider),
        BrowserTypeTextTool(provider),
        BrowserPressKeyTool(provider),
        BrowserScrollTool(provider),
    ]
    for tool in tools:
        if skip_existing and registry.has_tool(tool.definition.name):
            continue
        registry.register(tool)
