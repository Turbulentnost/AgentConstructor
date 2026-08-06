"""Тесты масштабирования vision-координат image → desktop."""

from __future__ import annotations

from agent_desktop_constructor.app.llm.supervisor_models import (
    SupervisorDecision,
    SupervisorDecisionType,
)
from agent_desktop_constructor.app.runtime.agent_loop_runtime import LLMAgentLoopRuntime
from agent_desktop_constructor.core.models.runtime_state import (
    AgentRunStatus,
    AgentRuntimeState,
)
from agent_desktop_constructor.tools.catalog_loader import load_tools_catalog
from agent_desktop_constructor.tools.gateway import ToolGateway
from agent_desktop_constructor.tools.registry import ToolRegistry


class _DummyPlanner:
    """Минимальный planner для конструктора runtime."""

    def decide(self, *args, **kwargs):
        return SupervisorDecision(
            decision_type=SupervisorDecisionType.FINISH_SUCCESS,
            reason="done",
            final_message="ok",
        )


def _runtime() -> LLMAgentLoopRuntime:
    registry = ToolRegistry()
    return LLMAgentLoopRuntime(
        tool_gateway=ToolGateway(registry),
        agent_loop_planner=_DummyPlanner(),  # type: ignore[arg-type]
        tools_catalog=load_tools_catalog(),
        tool_registry=registry,
    )


def test_scale_vision_coords_from_image_space() -> None:
    """Клик в пикселях сжатой картинки масштабируется в desktop."""
    runtime = _runtime()
    state = AgentRuntimeState(
        run_id="r1",
        agent_id="a1",
        status=AgentRunStatus.RUNNING,
        variables={
            "last_screenshot": {
                "image_width": 1280,
                "image_height": 384,
                "desktop_width": 3600,
                "desktop_height": 1080,
            }
        },
    )
    scaled = runtime._scale_vision_coords(
        state, "browser.click", {"x": 128, "y": 192, "button": "left"}
    )
    assert scaled["x"] == 360  # 128 * 3600/1280
    assert scaled["y"] == 540  # 192 * 1080/384
    assert scaled["_coord_space"] == "scaled_from_image"


def test_scale_vision_coords_keeps_desktop_space() -> None:
    """Если LLM уже дала desktop-координаты (больше image) — не масштабируем."""
    runtime = _runtime()
    state = AgentRuntimeState(
        run_id="r1",
        agent_id="a1",
        status=AgentRunStatus.RUNNING,
        variables={
            "last_screenshot": {
                "image_width": 1280,
                "image_height": 384,
                "desktop_width": 3600,
                "desktop_height": 1080,
            }
        },
    )
    scaled = runtime._scale_vision_coords(
        state, "browser.click", {"x": 330, "y": 770}
    )
    assert scaled["x"] == 330
    assert scaled["y"] == 770
    assert scaled["_coord_space"] == "desktop_as_reported"


def test_stash_screenshot_stores_image_and_desktop_sizes() -> None:
    """После сжатия last_screenshot хранит image_* и desktop_* раздельно."""
    runtime = _runtime()
    state = AgentRuntimeState(
        run_id="r1",
        agent_id="a1",
        status=AgentRunStatus.RUNNING,
        variables={},
    )
    # Минимальный валидный PNG 1x1.
    tiny_png_b64 = (
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8"
        "z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )
    trimmed = runtime._stash_screenshot(
        state,
        {
            "url": "https://example.com",
            "screenshot_base64": tiny_png_b64,
            "viewport_width": 3600,
            "viewport_height": 1080,
            "capture_mode": "virtual_desktop",
            "monitor_count": 2,
            "fallback_used": True,
            "cdp_available": False,
        },
    )
    shot = state.variables["last_screenshot"]
    assert shot["desktop_width"] == 3600
    assert shot["desktop_height"] == 1080
    assert shot["image_width"]
    assert shot["image_height"]
    assert trimmed["screenshot_captured"] is True
