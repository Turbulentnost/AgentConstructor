"""Rolling memory для agent-loop: recent steps + сжатые факты/артефакты.

Полная история tool_results остаётся в runtime/transcript на диске.
В LLM-промпт уходит только окно последних шагов и компактный run_memory.
"""

from __future__ import annotations

import json
import re
from typing import Any

from agent_desktop_constructor.core.models.runtime_state import (
    AgentRuntimeState,
    ToolCallRecord,
)

RUN_MEMORY_KEY = "run_memory"
PROMPT_PAYLOAD_CHARS_KEY = "prompt_payload_chars"
PROMPT_PAYLOAD_LIMIT_KEY = "prompt_payload_limit"

# Окно «свежих» шагов в промпте (и observation_history).
DEFAULT_RECENT_STEPS = 10
# При переполнении payload ужесточаем окно.
TIGHT_RECENT_STEPS = 6
# Мягкий лимит символов JSON user_payload (до сжатия картинки).
PROMPT_SOFT_LIMIT_CHARS = 90_000

_MAX_FACTS = 40
_MAX_ARTIFACTS = 30
_MAX_FAILURES = 12
_MAX_OPEN_QUESTIONS = 12
_FACT_MAX_CHARS = 240
_NOTE_MAX_CHARS = 200

_PATH_RE = re.compile(
    r"(?:[A-Za-z]:\\(?:[^\s\"']+)|(?:\.?/)?(?:[\w.-]+/)+[\w.-]+\.[\w]+)",
    re.UNICODE,
)
_SHEET_HINT_RE = re.compile(
    r"(?:sheet|лист|листы)\s*[:=]?\s*([^\n;|]{2,80})",
    re.IGNORECASE,
)


def ensure_run_memory(variables: dict[str, Any]) -> dict[str, Any]:
    """Вернуть нормализованный run_memory из variables (создать при отсутствии)."""
    raw = variables.get(RUN_MEMORY_KEY)
    memory = _normalize_memory(raw if isinstance(raw, dict) else {})
    variables[RUN_MEMORY_KEY] = memory
    return memory


def _normalize_memory(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "facts": _as_str_list(raw.get("facts"), _MAX_FACTS, _FACT_MAX_CHARS),
        "artifacts": _as_artifact_list(raw.get("artifacts")),
        "last_failures": _as_str_list(
            raw.get("last_failures"), _MAX_FAILURES, _FACT_MAX_CHARS
        ),
        "open_questions": _as_str_list(
            raw.get("open_questions"), _MAX_OPEN_QUESTIONS, _FACT_MAX_CHARS
        ),
        "compacted_steps": int(raw.get("compacted_steps") or 0),
    }


def _as_str_list(value: object, limit: int, max_chars: int) -> list[str]:
    if not isinstance(value, list):
        return []
    items: list[str] = []
    for item in value:
        text = " ".join(str(item or "").split())
        if not text:
            continue
        items.append(text[:max_chars])
    # Последние важнее — храним хвост.
    return items[-limit:]


def _as_artifact_list(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    artifacts: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").strip()
        if not path or path in seen:
            continue
        seen.add(path)
        artifacts.append(
            {
                "path": path[:400],
                "kind": str(item.get("kind") or "file")[:64],
                "note": str(item.get("note") or "")[:_NOTE_MAX_CHARS],
            }
        )
    return artifacts[-_MAX_ARTIFACTS:]


def apply_memory_notes(variables: dict[str, Any], notes: object) -> dict[str, Any]:
    """Добавить memory_notes из решения LLM в facts."""
    memory = ensure_run_memory(variables)
    if not isinstance(notes, list):
        return memory
    for note in notes:
        text = " ".join(str(note or "").split())
        if not text:
            continue
        _append_unique(memory["facts"], text[:_FACT_MAX_CHARS], _MAX_FACTS)
    variables[RUN_MEMORY_KEY] = memory
    return memory


def update_run_memory_from_tool(
    variables: dict[str, Any],
    record: ToolCallRecord,
    *,
    step: int | None = None,
) -> dict[str, Any]:
    """Обновить run_memory по результату инструмента (эвристика)."""
    memory = ensure_run_memory(variables)
    tool = record.tool_name or "tool"
    step_label = step if step is not None else variables.get("step_counter")
    prefix = f"[{tool}@{step_label}]" if step_label is not None else f"[{tool}]"

    if not record.ok:
        err = (record.error_message or record.error_type or "ошибка").strip()
        _append_unique(
            memory["last_failures"],
            f"{prefix} {err}"[:_FACT_MAX_CHARS],
            _MAX_FAILURES,
        )
        variables[RUN_MEMORY_KEY] = memory
        return memory

    output = record.output_data if isinstance(record.output_data, dict) else {}
    for path, kind, note in _extract_artifacts(tool, output):
        _upsert_artifact(memory["artifacts"], path, kind, note)

    for fact in _extract_facts(tool, output):
        _append_unique(memory["facts"], f"{prefix} {fact}"[:_FACT_MAX_CHARS], _MAX_FACTS)

    # Успешный повтор того же tool может снять старые failure-записи того же tool.
    memory["last_failures"] = [
        item
        for item in memory["last_failures"]
        if f"[{tool}" not in item[: max(8, len(tool) + 2)]
    ][-_MAX_FAILURES:]

    variables[RUN_MEMORY_KEY] = memory
    return memory


def compact_overflow_steps_into_memory(
    state: AgentRuntimeState,
    *,
    recent_limit: int = DEFAULT_RECENT_STEPS,
) -> dict[str, Any]:
    """Для шагов старше окна увеличить compacted_steps (факты уже собраны по мере исполнения)."""
    memory = ensure_run_memory(state.variables)
    total = len(state.tool_results)
    overflow = max(0, total - max(1, recent_limit))
    if overflow > int(memory.get("compacted_steps") or 0):
        memory["compacted_steps"] = overflow
        # Короткий маркер, что старые шаги сжаты.
        _append_unique(
            memory["facts"],
            f"Сжато ранних шагов в память: {overflow}. Полный лог — в transcript/workspace.",
            _MAX_FACTS,
        )
    state.variables[RUN_MEMORY_KEY] = memory
    return memory


def build_executed_steps_for_prompt(
    tool_results: list[ToolCallRecord],
    *,
    recent_limit: int = DEFAULT_RECENT_STEPS,
    summary_chars_ok: int = 600,
    summary_chars_err: int = 1600,
) -> list[dict[str, Any]]:
    """Последние N шагов для промпта (не вся история)."""
    window = tool_results[-max(1, recent_limit) :]
    steps: list[dict[str, Any]] = []
    for record in window:
        steps.append(
            {
                "tool_name": record.tool_name,
                "ok": record.ok,
                "error_type": record.error_type,
                "error_message": (record.error_message or "")[:2000]
                if not record.ok
                else None,
                "output_summary": _summarize_output(
                    record.output_data,
                    max_chars=summary_chars_err if not record.ok else summary_chars_ok,
                ),
            }
        )
    return steps


def resolve_recent_limit(payload_chars: int | None = None) -> int:
    """Выбрать размер окна шагов с учётом давления на payload."""
    if payload_chars is not None and payload_chars > PROMPT_SOFT_LIMIT_CHARS:
        return TIGHT_RECENT_STEPS
    return DEFAULT_RECENT_STEPS


def estimate_payload_chars(payload: dict[str, Any]) -> int:
    """Оценить размер JSON payload в символах."""
    try:
        return len(json.dumps(payload, ensure_ascii=False, default=str))
    except (TypeError, ValueError):
        return len(str(payload))


def shrink_payload_if_needed(
    payload: dict[str, Any],
    *,
    soft_limit: int = PROMPT_SOFT_LIMIT_CHARS,
) -> dict[str, Any]:
    """При превышении лимита урезать тяжёлые блоки промпта."""
    chars = estimate_payload_chars(payload)
    if chars <= soft_limit:
        payload["_prompt_budget"] = {
            "chars": chars,
            "limit": soft_limit,
            "tightened": False,
        }
        return payload

    # 1) Ужесточить executed_steps / observation_history
    steps = payload.get("executed_steps")
    if isinstance(steps, list) and len(steps) > TIGHT_RECENT_STEPS:
        payload["executed_steps"] = steps[-TIGHT_RECENT_STEPS:]
        payload["executed_steps_note"] = (
            f"Окно шагов урезано до {TIGHT_RECENT_STEPS} из‑за размера контекста. "
            "Ранние шаги — в run_memory и на диске (transcript/workspace)."
        )

    history = payload.get("observation_history")
    if isinstance(history, list) and len(history) > TIGHT_RECENT_STEPS:
        payload["observation_history"] = history[-TIGHT_RECENT_STEPS:]

    # 2) Дожать summaries в recent steps
    for step in payload.get("executed_steps") or []:
        if not isinstance(step, dict):
            continue
        summary = step.get("output_summary")
        if isinstance(summary, str) and len(summary) > 320:
            step["output_summary"] = summary[:320] + "…"

    # 3) Урезать collected_data до ключей + коротких summary
    collected = payload.get("collected_data")
    if isinstance(collected, dict):
        compact: dict[str, Any] = {}
        for key, value in list(collected.items())[-12:]:
            if isinstance(value, dict):
                compact[key] = {
                    k: v
                    for k, v in value.items()
                    if k.endswith("_summary")
                    or k.endswith("_path")
                    or k in {"path", "filename", "ok", "sheet_names", "sheets"}
                }
                if not compact[key]:
                    text = _summarize_output(value, max_chars=220)
                    compact[key] = {"_summary": text}
            else:
                compact[key] = str(value)[:220]
        payload["collected_data"] = compact
        payload["collected_data_note"] = (
            "collected_data сжат из‑за лимита контекста; полные данные в workspace."
        )

    chars_after = estimate_payload_chars(payload)
    payload["_prompt_budget"] = {
        "chars": chars_after,
        "chars_before": chars,
        "limit": soft_limit,
        "tightened": True,
    }
    return payload


def _extract_artifacts(
    tool: str, output: dict[str, Any]
) -> list[tuple[str, str, str]]:
    found: list[tuple[str, str, str]] = []
    path_keys = (
        "path",
        "absolute_path",
        "filename",
        "file_path",
        "report_path",
        "output_path",
        "xlsx_path",
        "csv_path",
        "html_path",
        "css_path",
        "dump_dir",
    )
    for key in path_keys:
        value = output.get(key)
        if isinstance(value, str) and value.strip():
            kind = "report" if "report" in key or "report" in tool else "file"
            if value.lower().endswith((".xlsx", ".xls", ".csv")):
                kind = "spreadsheet"
            elif value.lower().endswith((".html", ".htm", ".css")):
                kind = "page_dump"
            elif value.lower().endswith((".py",)):
                kind = "code"
            elif value.lower().endswith((".txt", ".md", ".json")):
                kind = "report"
            found.append((value.strip(), kind, f"from {tool}.{key}"))

    # Вложенные пути в page_dumps / written files
    for key in ("files", "written", "outputs"):
        nested = output.get(key)
        if isinstance(nested, list):
            for item in nested[:20]:
                if isinstance(item, str) and item.strip():
                    found.append((item.strip(), "file", f"from {tool}.{key}"))
                elif isinstance(item, dict):
                    path = item.get("path") or item.get("filename")
                    if isinstance(path, str) and path.strip():
                        found.append((path.strip(), "file", f"from {tool}.{key}"))

    # Пути из stdout_summary
    for key in ("stdout_summary", "stdout", "message"):
        text = output.get(key)
        if isinstance(text, str):
            for match in _PATH_RE.findall(text)[:8]:
                found.append((match, "file", f"from {tool} text"))
    return found


def _extract_facts(tool: str, output: dict[str, Any]) -> list[str]:
    facts: list[str] = []
    sheets = output.get("sheet_names") or output.get("sheets")
    if isinstance(sheets, list) and sheets:
        names = ", ".join(str(x) for x in sheets[:20])
        facts.append(f"листы: {names}")
    elif isinstance(sheets, dict) and sheets:
        names = ", ".join(str(x) for x in list(sheets.keys())[:20])
        facts.append(f"листы: {names}")

    for key in ("rows", "row_count", "columns", "column_count", "bytes_written", "lines"):
        if key in output and output[key] is not None:
            facts.append(f"{key}={output[key]}")

    for key in ("stdout_summary", "message", "result_summary"):
        text = output.get(key)
        if isinstance(text, str) and text.strip():
            for match in _SHEET_HINT_RE.findall(text)[:3]:
                facts.append(f"sheet_hint: {match.strip()}")
            # Короткий снимок summary
            compact = " ".join(text.split())
            if compact:
                facts.append(compact[:180])
            break

    if tool.startswith("code.") and output.get("path"):
        facts.append(f"код/файл: {output.get('path')}")
    return facts[:8]


def _upsert_artifact(
    artifacts: list[dict[str, str]], path: str, kind: str, note: str
) -> None:
    for item in artifacts:
        if item.get("path") == path:
            item["kind"] = kind or item.get("kind") or "file"
            if note:
                item["note"] = note[:_NOTE_MAX_CHARS]
            return
    artifacts.append(
        {"path": path[:400], "kind": kind[:64], "note": note[:_NOTE_MAX_CHARS]}
    )
    if len(artifacts) > _MAX_ARTIFACTS:
        del artifacts[: len(artifacts) - _MAX_ARTIFACTS]


def _append_unique(items: list[str], value: str, limit: int) -> None:
    if not value:
        return
    if value in items:
        return
    # Не дублировать почти идентичный хвост
    for existing in items[-5:]:
        if value in existing or existing in value:
            return
    items.append(value)
    if len(items) > limit:
        del items[: len(items) - limit]


def _summarize_output(output_data: dict | None, max_chars: int = 600) -> str:
    if not output_data:
        return "пустой результат"
    try:
        text = json.dumps(output_data, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = str(output_data)
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "…"
