"""Сохранение полной истории THINK / решений LLM / tool calls в файлы run."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent_desktop_constructor.app.core.config import resolve_runtime_path
from agent_desktop_constructor.app.llm.supervisor_models import SupervisorDecision
from agent_desktop_constructor.core.models.agent_spec import AgentSpec
from agent_desktop_constructor.core.models.runtime_state import (
    AgentRuntimeState,
    ToolCallRecord,
)

DEFAULT_TRACES_ROOT = "./data/run_traces"
MAX_TEXT_CHARS = 20_000
HEAVY_KEYS = {
    "screenshot_base64",
    "html",
    "page_html",
    "raw_html",
    "css",
    "styles_css",
}


class RunTranscriptLogger:
    """Пишет историю шагов агента в JSONL + читаемый Markdown."""

    def __init__(self, traces_root: Path | str | None = None) -> None:
        """Создать logger; корень по умолчанию — data/run_traces."""
        self._root = Path(
            resolve_runtime_path(str(traces_root or DEFAULT_TRACES_ROOT))
        )

    def ensure_paths(
        self,
        agent_spec: AgentSpec,
        state: AgentRuntimeState,
    ) -> dict[str, str]:
        """Создать файлы трассировки и вернуть их пути."""
        existing = state.variables.get("run_transcript_paths")
        if isinstance(existing, dict) and existing.get("jsonl"):
            return {str(k): str(v) for k, v in existing.items()}

        folder = self._root / _safe_id(agent_spec.agent_id) / _safe_id(state.run_id)
        folder.mkdir(parents=True, exist_ok=True)
        jsonl_path = folder / "transcript.jsonl"
        md_path = folder / "transcript.md"
        snapshot_path = folder / "transcript.json"

        if not md_path.exists():
            md_path.write_text(
                _markdown_header(agent_spec, state),
                encoding="utf-8",
            )
        if not snapshot_path.exists():
            snapshot_path.write_text(
                json.dumps(
                    {
                        "run_id": state.run_id,
                        "agent_id": agent_spec.agent_id,
                        "agent_name": agent_spec.name,
                        "goal": agent_spec.goal.model_dump(mode="json"),
                        "user_request": state.variables.get("user_request"),
                        "events": [],
                    },
                    ensure_ascii=False,
                    indent=2,
                    default=str,
                ),
                encoding="utf-8",
            )

        paths = {
            "folder": str(folder),
            "jsonl": str(jsonl_path),
            "markdown": str(md_path),
            "snapshot": str(snapshot_path),
        }
        state.variables["run_transcript_paths"] = paths
        state.variables["run_transcript_path"] = paths["markdown"]
        return paths

    def log_decision(
        self,
        agent_spec: AgentSpec,
        state: AgentRuntimeState,
        decision: SupervisorDecision,
        *,
        parse_error: str | None = None,
    ) -> None:
        """Записать THINK + решение LLM после ответа модели."""
        paths = self.ensure_paths(agent_spec, state)
        payload = {
            "ts": _now_iso(),
            "event": "llm_decision" if parse_error is None else "llm_parse_error",
            "step": state.step_counter,
            "status": state.status.value,
            "thought": (
                decision.thought.model_dump(mode="json")
                if decision.thought is not None
                else None
            ),
            "decision": decision.model_dump(mode="json"),
            "parse_error": parse_error,
            "goal_checklist": state.variables.get("goal_checklist"),
            "repeat_notes": list(state.variables.get("loop_repeat_notes") or [])[-5:],
        }
        self._append(paths, payload)
        self._append_markdown(
            paths["markdown"],
            _format_decision_md(payload),
        )

    def log_tool_result(
        self,
        agent_spec: AgentSpec,
        state: AgentRuntimeState,
        record: ToolCallRecord,
    ) -> None:
        """Записать результат исполнения инструмента (OBSERVE)."""
        paths = self.ensure_paths(agent_spec, state)
        payload = {
            "ts": _now_iso(),
            "event": "tool_result",
            "step": state.step_counter,
            "status": state.status.value,
            "tool_name": record.tool_name,
            "ok": record.ok,
            "error_type": record.error_type,
            "error_message": _clip(record.error_message),
            "input_data": _sanitize(record.input_data),
            "output_data": _sanitize(record.output_data),
        }
        self._append(paths, payload)
        self._append_markdown(paths["markdown"], _format_tool_md(payload))

    def log_run_status(
        self,
        agent_spec: AgentSpec,
        state: AgentRuntimeState,
        *,
        note: str | None = None,
    ) -> None:
        """Записать смену статуса run (finish/pause/fail)."""
        paths = self.ensure_paths(agent_spec, state)
        payload = {
            "ts": _now_iso(),
            "event": "run_status",
            "step": state.step_counter,
            "status": state.status.value,
            "note": note,
            "final_message": state.variables.get("final_message"),
            "errors": list(state.errors or [])[-10:],
            "criteria_evidence": state.variables.get("criteria_evidence"),
        }
        self._append(paths, payload)
        self._append_markdown(
            paths["markdown"],
            (
                f"\n## Статус: `{state.status.value}`\n\n"
                f"{note or ''}\n\n"
                f"**final_message:** {state.variables.get('final_message') or '—'}\n"
            ),
        )

    def log_event(
        self,
        agent_spec: AgentSpec,
        state: AgentRuntimeState,
        event: str,
        *,
        details: dict[str, Any] | None = None,
        note: str | None = None,
    ) -> None:
        """Записать произвольное событие цикла (waiting_llm, timeout, …)."""
        paths = self.ensure_paths(agent_spec, state)
        payload: dict[str, Any] = {
            "ts": _now_iso(),
            "event": event,
            "step": state.step_counter,
            "status": state.status.value,
            "note": note,
        }
        if details:
            payload["details"] = _sanitize(details)
        self._append(paths, payload)
        detail_text = ""
        if details:
            detail_text = "\n```json\n" + json.dumps(
                payload.get("details"),
                ensure_ascii=False,
                indent=2,
                default=str,
            ) + "\n```\n"
        self._append_markdown(
            paths["markdown"],
            f"\n### `{event}` (step {state.step_counter})\n\n"
            f"{note or ''}\n{detail_text}",
        )

    def _append(self, paths: dict[str, str], payload: dict[str, Any]) -> None:
        """Дописать событие в JSONL и обновить полный snapshot JSON."""
        line = json.dumps(payload, ensure_ascii=False, default=str)
        with open(paths["jsonl"], "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        self._update_snapshot(paths["snapshot"], payload)

    @staticmethod
    def _append_markdown(path: str, text: str) -> None:
        """Дописать человекочитаемый фрагмент в Markdown."""
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(text)
            if not text.endswith("\n"):
                handle.write("\n")

    @staticmethod
    def _update_snapshot(path: str, payload: dict[str, Any]) -> None:
        """Обновить агрегированный transcript.json (удобно открыть целиком)."""
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {"events": []}
        events = data.setdefault("events", [])
        if not isinstance(events, list):
            events = []
            data["events"] = events
        events.append(payload)
        data["updated_at"] = _now_iso()
        data["events_count"] = len(events)
        Path(path).write_text(
            json.dumps(data, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )


def _safe_id(value: str) -> str:
    """Оставить безопасный фрагмент пути."""
    cleaned = "".join(
        ch if ch.isalnum() or ch in {"-", "_", "."} else "_"
        for ch in (value or "unknown").strip()
    )
    return cleaned or "unknown"


def _now_iso() -> str:
    """UTC timestamp в ISO-формате."""
    return datetime.now(timezone.utc).isoformat()


def _clip(value: object | None, max_chars: int = MAX_TEXT_CHARS) -> object | None:
    """Обрезать длинные строки."""
    if value is None:
        return None
    text = str(value)
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"… [truncated {len(text) - max_chars} chars]"


def _sanitize(value: object) -> object:
    """Убрать тяжёлые поля (base64/html) из payload для файла трассировки."""
    if isinstance(value, dict):
        cleaned: dict[str, object] = {}
        for key, item in value.items():
            if key in HEAVY_KEYS:
                if isinstance(item, str):
                    cleaned[key] = f"[omitted {len(item)} chars]"
                else:
                    cleaned[key] = "[omitted]"
                continue
            cleaned[key] = _sanitize(item)
        return cleaned
    if isinstance(value, list):
        return [_sanitize(item) for item in value[:200]]
    if isinstance(value, str):
        return _clip(value)
    return value


def _markdown_header(agent_spec: AgentSpec, state: AgentRuntimeState) -> str:
    """Заголовок Markdown-трассировки."""
    return (
        f"# Трассировка run `{state.run_id}`\n\n"
        f"- **agent:** {agent_spec.name} (`{agent_spec.agent_id}`)\n"
        f"- **goal:** {agent_spec.goal.main_goal}\n"
        f"- **user_request:** {state.variables.get('user_request')}\n"
        f"- **started:** {_now_iso()}\n\n"
        "---\n"
    )


def _format_decision_md(payload: dict[str, Any]) -> str:
    """Markdown-блок для решения LLM."""
    thought = payload.get("thought") or {}
    decision = payload.get("decision") or {}
    tool_call = decision.get("tool_call") or {}
    lines = [
        f"\n## Шаг {payload.get('step')} — LLM decision ({payload.get('ts')})\n",
        "### THINK\n",
        f"- understanding: {thought.get('understanding') or '—'}\n",
        f"- missing_info: {thought.get('missing_info') or '—'}\n",
        f"- planned_actions: {thought.get('planned_actions') or []}\n",
        f"- chosen_tool: {thought.get('chosen_tool') or '—'}\n",
        f"- why: {thought.get('why') or '—'}\n",
        "\n### ACT / decision\n",
        f"- decision_type: `{decision.get('decision_type')}`\n",
        f"- reason: {decision.get('reason') or '—'}\n",
        f"- confidence: {decision.get('confidence')}\n",
    ]
    if tool_call:
        lines.extend(
            [
                f"- tool: `{tool_call.get('tool_name')}`\n",
                f"- tool_reason: {tool_call.get('reason') or '—'}\n",
                "```json\n",
                json.dumps(
                    _sanitize(tool_call.get("input_data") or {}),
                    ensure_ascii=False,
                    indent=2,
                    default=str,
                ),
                "\n```\n",
            ]
        )
    if decision.get("final_message"):
        lines.append(f"- final_message: {decision.get('final_message')}\n")
    if decision.get("criteria_evidence"):
        lines.append(
            "```json\n"
            + json.dumps(
                decision.get("criteria_evidence"),
                ensure_ascii=False,
                indent=2,
                default=str,
            )
            + "\n```\n"
        )
    if payload.get("parse_error"):
        lines.append(f"\n**parse_error:** {payload['parse_error']}\n")
    return "".join(lines)


def _format_tool_md(payload: dict[str, Any]) -> str:
    """Markdown-блок для результата инструмента."""
    status = "OK" if payload.get("ok") else "FAIL"
    body = {
        "error_type": payload.get("error_type"),
        "error_message": payload.get("error_message"),
        "output_data": payload.get("output_data"),
    }
    return (
        f"\n### OBSERVE — `{payload.get('tool_name')}` [{status}]\n\n"
        "```json\n"
        + json.dumps(body, ensure_ascii=False, indent=2, default=str)
        + "\n```\n"
    )
