"""Тесты парсинга ответов CatalogClient без сети."""

from __future__ import annotations

from agent_desktop_constructor.app.catalog.client import CatalogAgentCard, RunSummary


def test_catalog_agent_card_from_dict() -> None:
    card = CatalogAgentCard.from_dict(
        {
            "agent_id": "a1",
            "name": "Agent",
            "description": "d",
            "short_description": "s",
            "visibility": "selected",
            "departments": ["ИТ", ""],
            "pinned": True,
            "agent_spec": {"agent_id": "a1"},
        }
    )
    assert card.agent_id == "a1"
    assert card.pinned is True
    assert card.departments == ["ИТ"]
    assert card.agent_spec == {"agent_id": "a1"}


def test_run_summary_from_dict() -> None:
    run = RunSummary.from_dict(
        {
            "run_id": "r1",
            "agent_id": "a1",
            "status": "failed",
            "title": "T",
            "message": "err",
            "started_at": "2026-01-01T00:00:00+00:00",
        }
    )
    assert run.run_id == "r1"
    assert run.status == "failed"
    assert run.finished_at is None
