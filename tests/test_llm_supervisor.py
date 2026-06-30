"""Тесты LLMSupervisor без реального HTTP."""

import pytest

from agent_desktop_constructor.app.llm.models import LLMResponse
from agent_desktop_constructor.app.llm.supervisor import LLMSupervisor
from agent_desktop_constructor.core.models.llm_config import LLMConfig
from agent_desktop_constructor.core.models.runtime_state import (
    AgentRunStatus,
    AgentRuntimeState,
)
from agent_desktop_constructor.builder.agent_builder import AgentBuilder
from agent_desktop_constructor.tools.catalog_loader import load_tools_catalog


class FakeLLMClient:
    """Fake LLM client для Supervisor."""

    def __init__(self, content: str) -> None:
        self.config = LLMConfig()
        self.content = content
        self.complete_called = False

    def complete(self, request):
        """Вернуть fake response."""
        self.complete_called = True
        return LLMResponse(content=self.content, raw={"fake": True})


def test_llm_supervisor_returns_decision() -> None:
    """LLMSupervisor возвращает SupervisorDecision."""
    client = FakeLLMClient(
        '{"decision_type":"continue_to_next","reason":"ok","confidence":0.7}'
    )
    supervisor = LLMSupervisor(client, load_tools_catalog())
    agent_spec = AgentBuilder().build_from_request("Найди совещания")

    decision = supervisor.decide(
        agent_spec,
        AgentRuntimeState(
            run_id="run-1",
            agent_id=agent_spec.agent_id,
            status=AgentRunStatus.RUNNING,
        ),
        None,
        None,
    )

    assert client.complete_called is True
    assert decision.decision_type == "continue_to_next"


def test_llm_supervisor_rejects_invented_tool() -> None:
    """LLM Supervisor не принимает invented.tool."""
    client = FakeLLMClient(
        """
        {
          "decision_type":"call_additional_tool",
          "reason":"Нужен tool",
          "tool_call":{"tool_name":"invented.tool","input_data":{},"reason":"x"}
        }
        """
    )
    supervisor = LLMSupervisor(client, load_tools_catalog())
    agent_spec = AgentBuilder().build_from_request("Найди совещания")

    with pytest.raises(ValueError, match="invented.tool"):
        supervisor.decide(
            agent_spec,
            AgentRuntimeState(
                run_id="run-1",
                agent_id=agent_spec.agent_id,
                status=AgentRunStatus.RUNNING,
            ),
            None,
            None,
        )

