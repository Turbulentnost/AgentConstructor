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
)
from agent_desktop_constructor.workers.browser_cdp_worker import BrowserCdpError


class _BaseVisionTool(BaseTool):
    """Общая логика vision-инструментов: вызвать worker и нормализовать ошибку."""

    def __init__(self, definition: ToolDefinition, worker: BrowserVisionWorker) -> None:
        """Сохранить общий vision worker."""
        super().__init__(definition)
        self._worker = worker

    def _method_name(self) -> str:
        """Имя метода worker для этого инструмента."""
        raise NotImplementedError

    def execute(self, input_data: dict) -> ToolCallResult:
        """Выполнить действие vision worker и вернуть скриншот/состояние."""
        action = getattr(self._worker, self._method_name())
        try:
            output_data = action(input_data)
        except BrowserCdpError as exc:
            return ToolCallResult(
                ok=False,
                tool_name=self.definition.name,
                error_type="BROWSER_CDP_ERROR",
                error_message=str(exc),
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
    },
}


class BrowserNavigateTool(_BaseVisionTool):
    """Открыть URL в управляемой вкладке и вернуть скриншот."""

    def __init__(self, worker: BrowserVisionWorker) -> None:
        """Создать инструмент browser.navigate."""
        super().__init__(
            ToolDefinition(
                name="browser.navigate",
                title="Открыть страницу в браузере (UI)",
                description="Открывает URL в управляемой вкладке браузера и возвращает скриншот страницы.",
                side_effect_level=ToolSideEffectLevel.CREATE_DRAFT,
                execution_mode=ToolExecutionMode.BROWSER_WORKER,
                requires_human_approval=False,
                timeout_seconds=40,
                input_schema={
                    "type": "object",
                    "properties": {"url": {"type": "string"}},
                    "required": ["url"],
                },
                output_schema=_SCREENSHOT_OUTPUT,
            ),
            worker,
        )

    def _method_name(self) -> str:
        return "navigate"


class BrowserScreenshotTool(_BaseVisionTool):
    """Сделать скриншот текущей вкладки для анализа LLM."""

    def __init__(self, worker: BrowserVisionWorker) -> None:
        """Создать инструмент browser.screenshot."""
        super().__init__(
            ToolDefinition(
                name="browser.screenshot",
                title="Скриншот страницы браузера",
                description="Делает скриншот текущей вкладки браузера (base64 PNG), чтобы LLM видела UI и решила следующее действие.",
                side_effect_level=ToolSideEffectLevel.READ,
                execution_mode=ToolExecutionMode.BROWSER_WORKER,
                requires_human_approval=False,
                timeout_seconds=40,
                input_schema={
                    "type": "object",
                    "properties": {"url": {"type": "string"}},
                },
                output_schema=_SCREENSHOT_OUTPUT,
            ),
            worker,
        )

    def _method_name(self) -> str:
        return "screenshot"


class BrowserClickTool(_BaseVisionTool):
    """Кликнуть по координатам на странице (координаты определяет LLM по скриншоту)."""

    def __init__(self, worker: BrowserVisionWorker) -> None:
        """Создать инструмент browser.click."""
        super().__init__(
            ToolDefinition(
                name="browser.click",
                title="Клик по координатам в браузере",
                description="Кликает по координатам (x, y) в пикселях viewport текущей вкладки и возвращает новый скриншот. Координаты бери со скриншота.",
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
                    },
                    "required": ["x", "y"],
                },
                output_schema=_SCREENSHOT_OUTPUT,
            ),
            worker,
        )

    def _method_name(self) -> str:
        return "click"


class BrowserTypeTextTool(_BaseVisionTool):
    """Ввести текст в активный элемент страницы и вернуть скриншот."""

    def __init__(self, worker: BrowserVisionWorker) -> None:
        """Создать инструмент browser.type_text."""
        super().__init__(
            ToolDefinition(
                name="browser.type_text",
                title="Ввод текста в браузере",
                description="Вводит текст в текущий активный элемент (сначала кликни в поле через browser.click) и возвращает скриншот.",
                side_effect_level=ToolSideEffectLevel.CREATE_DRAFT,
                execution_mode=ToolExecutionMode.BROWSER_WORKER,
                requires_human_approval=False,
                timeout_seconds=40,
                input_schema={
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                    "required": ["text"],
                },
                output_schema=_SCREENSHOT_OUTPUT,
            ),
            worker,
        )

    def _method_name(self) -> str:
        return "type_text"


class BrowserPressKeyTool(_BaseVisionTool):
    """Нажать спец-клавишу (Enter/Tab/Escape/стрелки) и вернуть скриншот."""

    def __init__(self, worker: BrowserVisionWorker) -> None:
        """Создать инструмент browser.press_key."""
        super().__init__(
            ToolDefinition(
                name="browser.press_key",
                title="Нажатие клавиши в браузере",
                description="Нажимает спец-клавишу (enter, tab, escape, backspace, стрелки) в браузере и возвращает скриншот.",
                side_effect_level=ToolSideEffectLevel.CREATE_DRAFT,
                execution_mode=ToolExecutionMode.BROWSER_WORKER,
                requires_human_approval=False,
                timeout_seconds=40,
                input_schema={
                    "type": "object",
                    "properties": {"key": {"type": "string"}},
                    "required": ["key"],
                },
                output_schema=_SCREENSHOT_OUTPUT,
            ),
            worker,
        )

    def _method_name(self) -> str:
        return "press_key"


class BrowserScrollTool(_BaseVisionTool):
    """Прокрутить управляемую вкладку и вернуть скриншот."""

    def __init__(self, worker: BrowserVisionWorker) -> None:
        """Создать инструмент browser.scroll."""
        super().__init__(
            ToolDefinition(
                name="browser.scroll",
                title="Прокрутка браузера (UI)",
                description="Прокручивает текущую вкладку вверх/вниз и возвращает скриншот.",
                side_effect_level=ToolSideEffectLevel.CREATE_DRAFT,
                execution_mode=ToolExecutionMode.BROWSER_WORKER,
                requires_human_approval=False,
                timeout_seconds=40,
                input_schema={
                    "type": "object",
                    "properties": {
                        "direction": {"type": "string"},
                        "pixels": {"type": "integer"},
                    },
                },
                output_schema=_SCREENSHOT_OUTPUT,
            ),
            worker,
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
    vision_worker = worker or BrowserVisionWorker()
    tools = [
        BrowserNavigateTool(vision_worker),
        BrowserScreenshotTool(vision_worker),
        BrowserClickTool(vision_worker),
        BrowserTypeTextTool(vision_worker),
        BrowserPressKeyTool(vision_worker),
        BrowserScrollTool(vision_worker),
    ]
    for tool in tools:
        if skip_existing and registry.has_tool(tool.definition.name):
            continue
        registry.register(tool)
