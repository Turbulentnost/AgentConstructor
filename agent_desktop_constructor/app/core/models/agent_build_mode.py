"""Режимы построения и исполнения AgentSpec."""

from enum import StrEnum


class AgentBuildMode(StrEnum):
    """Стратегия участия LLM в жизненном цикле агента."""

    TEMPLATE_ONLY = "template_only"
    LLM_PLANNED = "llm_planned"
    LLM_SUPERVISED = "llm_supervised"

