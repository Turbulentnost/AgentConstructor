"""Менеджер контекста агента.

Менеджер не зависит от Qt или storage: он читает/пишет сериализуемый snapshot
в `AgentRuntimeState.variables`, а runtime и UI используют готовые метрики.
"""

from __future__ import annotations

import json
from typing import Any

from agent_desktop_constructor.app.context.models import (
    AgentContextSnapshot,
    ContextBudget,
    ContextEntry,
    ContextSection,
    ContextUsage,
)
from agent_desktop_constructor.core.models.agent_spec import AgentSpec
from agent_desktop_constructor.core.models.runtime_state import (
    AgentRuntimeState,
    ToolCallRecord,
)

CONTEXT_SNAPSHOT_KEY = "context_snapshot"


class AgentContextManager:
    """Собирает, ограничивает и сериализует контекст агента."""

    def __init__(self, budget: ContextBudget | None = None) -> None:
        """Создать manager с бюджетом контекста."""
        self.budget = budget or ContextBudget()

    def restore_from_state(self, state: AgentRuntimeState) -> AgentContextSnapshot:
        """Вернуть snapshot из state или пересобрать минимальный снимок."""
        raw = state.variables.get(CONTEXT_SNAPSHOT_KEY)
        if isinstance(raw, dict):
            try:
                snapshot = AgentContextSnapshot.model_validate(raw)
                snapshot.usage = self.calculate_usage(snapshot)
                return snapshot
            except Exception:
                pass
        snapshot = AgentContextSnapshot()
        self.record_run_context(snapshot, state)
        for record in state.tool_results[-8:]:
            self.record_tool_result(snapshot, record)
        if state.pending_human_approval is not None:
            self.record_pause_state(snapshot, state)
        return self.compact_context(snapshot)

    def save_to_state(
        self,
        state: AgentRuntimeState,
        snapshot: AgentContextSnapshot,
    ) -> AgentContextSnapshot:
        """Сжать snapshot и сохранить его в variables."""
        compacted = self.compact_context(snapshot)
        state.variables[CONTEXT_SNAPSHOT_KEY] = compacted.model_dump(mode="json")
        return compacted

    def update_state_context(
        self,
        state: AgentRuntimeState,
        *,
        agent_spec: AgentSpec | None = None,
    ) -> AgentContextSnapshot:
        """Пересобрать/обновить snapshot по текущему runtime state."""
        snapshot = self.restore_from_state(state)
        if agent_spec is not None:
            self.record_creation_context(snapshot, agent_spec, state)
        self.record_run_context(snapshot, state)
        if state.pending_human_approval is not None or state.status.value.startswith(
            "paused"
        ):
            self.record_pause_state(snapshot, state)
        return self.save_to_state(state, snapshot)

    def record_creation_context(
        self,
        snapshot: AgentContextSnapshot,
        agent_spec: AgentSpec,
        state: AgentRuntimeState,
    ) -> None:
        """Записать контекст создания агента."""
        self._upsert(
            snapshot,
            ContextSection.CREATION,
            "agent",
            {
                "agent_id": agent_spec.agent_id,
                "name": agent_spec.name,
                "goal": agent_spec.goal.model_dump(mode="json"),
                "tools": [tool.tool_name for tool in agent_spec.tools],
                "runtime_limits": agent_spec.runtime_limits.model_dump(mode="json"),
            },
            priority=90,
        )
        user_request = state.variables.get("user_request")
        if user_request:
            self._upsert(
                snapshot,
                ContextSection.CREATION,
                "user_request",
                user_request,
                priority=100,
            )
        attached_files = state.variables.get("attached_files")
        if attached_files:
            self._upsert(
                snapshot,
                ContextSection.CREATION,
                "attached_files",
                attached_files,
                priority=80,
            )

    def record_run_context(
        self,
        snapshot: AgentContextSnapshot,
        state: AgentRuntimeState,
    ) -> None:
        """Записать текущий контекст выполнения."""
        self._upsert(
            snapshot,
            ContextSection.RUN,
            "state",
            {
                "run_id": state.run_id,
                "agent_id": state.agent_id,
                "status": state.status.value,
                "current_node_id": state.current_node_id,
                "step_counter": state.step_counter,
                "tool_call_counter": state.tool_call_counter,
                "errors": state.errors[-5:],
            },
            priority=100,
        )
        if decisions := state.variables.get("loop_decisions"):
            self._upsert(
                snapshot,
                ContextSection.RUN,
                "recent_loop_decisions",
                decisions[-8:] if isinstance(decisions, list) else decisions,
                priority=80,
            )
        if repeat_notes := state.variables.get("loop_repeat_notes"):
            self._upsert(
                snapshot,
                ContextSection.RUN,
                "repeat_notes",
                repeat_notes[-5:] if isinstance(repeat_notes, list) else repeat_notes,
                priority=70,
            )

    def record_run_event(
        self,
        snapshot: AgentContextSnapshot,
        event: dict[str, Any],
    ) -> None:
        """Добавить событие выполнения в контекст."""
        entries = snapshot.entries(ContextSection.EVENTS)
        entries.append(self._entry(f"event_{len(entries) + 1}", event, priority=50))

    def record_tool_result(
        self,
        snapshot: AgentContextSnapshot,
        record: ToolCallRecord,
    ) -> None:
        """Добавить результат инструмента."""
        value = {
            "tool_name": record.tool_name,
            "ok": record.ok,
            "input_summary": self._summarize(record.input_data, 600),
            "output_summary": self._summarize(record.output_data, 1200),
            "error_type": record.error_type,
            "error_message": record.error_message,
        }
        self._upsert(
            snapshot,
            ContextSection.TOOL_RESULTS,
            f"{record.tool_name}_{len(snapshot.entries(ContextSection.TOOL_RESULTS)) + 1}",
            value,
            priority=90 if record.ok else 100,
        )

    def record_pause_state(
        self,
        snapshot: AgentContextSnapshot,
        state: AgentRuntimeState,
    ) -> None:
        """Записать состояние паузы/ожидания человека."""
        approval = state.pending_human_approval
        value: dict[str, Any] = {
            "status": state.status.value,
            "credential_request_reason": state.variables.get(
                "credential_request_reason"
            ),
            "pending_loop_tool": state.variables.get("pending_loop_tool"),
            "human_plan_ahead": state.variables.get("human_plan_ahead"),
        }
        if approval is not None:
            value["approval"] = approval.model_dump(mode="json")
        self._upsert(snapshot, ContextSection.PAUSE, "pause_state", value, priority=100)

    def record_agent_call_context(
        self,
        snapshot: AgentContextSnapshot,
        call_context: dict[str, Any],
    ) -> None:
        """Записать контекст вызова одного агента другим."""
        self._upsert(
            snapshot,
            ContextSection.AGENT_CALL,
            "agent_call",
            call_context,
            priority=80,
        )

    def record_user_history(
        self,
        snapshot: AgentContextSnapshot,
        state: AgentRuntimeState,
    ) -> None:
        """Записать историю взаимодействия с пользователем."""
        history = {
            "human_responses": state.variables.get("human_responses", []),
            "human_decisions": state.variables.get("human_decisions", []),
        }
        self._upsert(
            snapshot,
            ContextSection.USER_HISTORY,
            "interaction_history",
            history,
            priority=80,
        )

    def build_llm_context(
        self,
        *,
        agent_spec: AgentSpec,
        runtime_state: AgentRuntimeState,
    ) -> dict[str, Any]:
        """Собрать компактный контекст для LLM prompt."""
        snapshot = self.update_state_context(runtime_state, agent_spec=agent_spec)
        sections: dict[str, list[dict[str, Any]]] = {}
        for section, entries in snapshot.sections.items():
            sections[section.value] = [
                {
                    "key": entry.key,
                    "summary": entry.summary,
                    "value": entry.value,
                    "truncated": entry.truncated,
                    "size_chars": entry.size_chars,
                }
                for entry in entries
            ]
        return {
            "version": snapshot.version,
            "sections": sections,
            "usage": snapshot.usage.model_dump(mode="json") if snapshot.usage else None,
        }

    def compact_context(
        self,
        snapshot: AgentContextSnapshot,
    ) -> AgentContextSnapshot:
        """Ограничить snapshot по бюджетам секций и общему бюджету."""
        compacted = AgentContextSnapshot(version=snapshot.version)
        for section, entries in snapshot.sections.items():
            section_limit = self.budget.limit_for(section)
            used = 0
            ordered = sorted(entries, key=lambda item: item.priority, reverse=True)
            kept: list[ContextEntry] = []
            for entry in ordered:
                normalized = self._limit_entry(entry)
                if used + normalized.size_chars > section_limit:
                    if not kept:
                        kept.append(self._truncate_entry(normalized, section_limit))
                    continue
                kept.append(normalized)
                used += normalized.size_chars
            compacted.sections[section] = kept
        self._enforce_total_budget(compacted)
        compacted.usage = self.calculate_usage(compacted)
        return compacted

    def _enforce_total_budget(self, snapshot: AgentContextSnapshot) -> None:
        """Удалить наименее приоритетные записи, если общий бюджет превышен."""
        while True:
            total = sum(
                entry.size_chars
                for entries in snapshot.sections.values()
                for entry in entries
            )
            if total <= self.budget.max_total_chars:
                return
            candidate: tuple[ContextSection, int, ContextEntry] | None = None
            for section, entries in snapshot.sections.items():
                for index, entry in enumerate(entries):
                    current = (section, index, entry)
                    if candidate is None or entry.priority < candidate[2].priority:
                        candidate = current
            if candidate is None:
                return
            section, index, _entry = candidate
            del snapshot.sections[section][index]

    def calculate_usage(self, snapshot: AgentContextSnapshot) -> ContextUsage:
        """Посчитать заполнение бюджета по разделам."""
        section_chars: dict[ContextSection, int] = {}
        section_percent: dict[ContextSection, float] = {}
        total = 0
        for section in ContextSection:
            chars = sum(entry.size_chars for entry in snapshot.sections.get(section, []))
            section_chars[section] = chars
            total += chars
            limit = self.budget.limit_for(section)
            section_percent[section] = round((chars / limit) * 100, 2) if limit else 0.0
        total_percent = round((total / self.budget.max_total_chars) * 100, 2)
        return ContextUsage(
            total_chars=total,
            total_limit=self.budget.max_total_chars,
            total_percent=min(total_percent, 100.0),
            section_chars=section_chars,
            section_percent=section_percent,
        )

    def _upsert(
        self,
        snapshot: AgentContextSnapshot,
        section: ContextSection,
        key: str,
        value: object,
        *,
        priority: int,
    ) -> None:
        entries = snapshot.entries(section)
        entry = self._entry(key, value, priority=priority)
        for index, existing in enumerate(entries):
            if existing.key == key:
                entries[index] = entry
                return
        entries.append(entry)

    def _entry(self, key: str, value: object, *, priority: int) -> ContextEntry:
        text = self._serialize(value)
        truncated = len(text) > self.budget.max_entry_chars
        stored_value = value
        if truncated:
            stored_value = text[: self.budget.max_entry_chars] + "…"
        summary = self._summarize(value, 700)
        return ContextEntry(
            key=key,
            value=stored_value,
            summary=summary,
            priority=priority,
            size_chars=min(len(text), self.budget.max_entry_chars),
            truncated=truncated,
        )

    def _limit_entry(self, entry: ContextEntry) -> ContextEntry:
        if entry.size_chars <= self.budget.max_entry_chars:
            return entry
        return self._truncate_entry(entry, self.budget.max_entry_chars)

    def _truncate_entry(self, entry: ContextEntry, limit: int) -> ContextEntry:
        text = self._serialize(entry.value)
        limited = text[: max(limit, 0)] + ("…" if len(text) > limit else "")
        return entry.model_copy(
            update={
                "value": limited,
                "summary": self._summarize(limited, 700),
                "size_chars": min(len(text), limit),
                "truncated": len(text) > limit,
            }
        )

    @staticmethod
    def _serialize(value: object) -> str:
        try:
            return json.dumps(value, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            return str(value)

    def _summarize(self, value: object, max_chars: int) -> str:
        text = self._serialize(value)
        if len(text) <= max_chars:
            return text
        return text[:max_chars] + "…"
