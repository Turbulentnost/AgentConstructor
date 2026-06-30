"""Тесты LLMAnalyzeCollectedDataTool."""

from agent_desktop_constructor.app.llm.errors import LLMConnectionError
from agent_desktop_constructor.app.llm.models import LLMResponse
from agent_desktop_constructor.app.tools.llm_analysis_tools import (
    LLMAnalyzeCollectedDataTool,
)
from agent_desktop_constructor.core.models.llm_config import LLMConfig
from agent_desktop_constructor.core.models.tooling import (
    ToolExecutionMode,
    ToolSideEffectLevel,
)


class FakeLLMClient:
    """Fake LLM client для analysis tool."""

    def __init__(self, error: Exception | None = None) -> None:
        self.config = LLMConfig()
        self.error = error
        self.last_request = None

    def complete(self, request):
        """Вернуть JSON analysis или ошибку."""
        self.last_request = request
        if self.error is not None:
            raise self.error
        return LLMResponse(
            content='{"summary":"ok","findings":["f"],"risks":["r"],"recommendations":["x"],"confidence":0.9}'
        )


def test_llm_analysis_tool_definition() -> None:
    """LLM analysis tool имеет правильный definition."""
    tool = LLMAnalyzeCollectedDataTool(FakeLLMClient())

    assert tool.definition.name == "llm.analyze_collected_data"
    assert tool.definition.execution_mode == ToolExecutionMode.LLM
    assert tool.definition.side_effect_level == ToolSideEffectLevel.CREATE_DRAFT


def test_llm_analysis_tool_uses_collected_data() -> None:
    """Runtime передаёт tool_outputs в LLM analysis tool."""
    client = FakeLLMClient()
    tool = LLMAnalyzeCollectedDataTool(client)

    result = tool.execute(
        {
            "agent_goal": {"main_goal": "Планировать график"},
            "tool_outputs": {"outlook.read_calendar": {"events": [{"id": "e1"}]}},
        }
    )

    assert result.ok is True
    assert result.output_data is not None
    assert result.output_data["summary"] == "ok"
    assert client.last_request is not None
    prompt_text = "\n".join(message.content for message in client.last_request.messages)
    assert "outlook.read_calendar" in prompt_text


def test_llm_analysis_tool_returns_error_when_llm_unavailable() -> None:
    """Если LLM недоступна, tool не роняет Runtime."""
    tool = LLMAnalyzeCollectedDataTool(FakeLLMClient(LLMConnectionError("offline")))

    result = tool.execute({})

    assert result.ok is False
    assert result.error_type == "LLM_CONNECTION_ERROR"

