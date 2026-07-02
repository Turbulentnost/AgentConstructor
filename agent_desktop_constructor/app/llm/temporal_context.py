"""Единый временной контекст для LLM prompts."""

from __future__ import annotations

from datetime import date, timedelta


def build_temporal_context() -> dict[str, str]:
    """Вернуть текущую дату и границы недели для grounding относительных дат."""
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)
    return {
        "current_date": today.isoformat(),
        "current_week_start": week_start.isoformat(),
        "current_week_end": week_end.isoformat(),
        "timezone_note": "Используй локальную дату компьютера пользователя.",
        "relative_date_rule": (
            "Все относительные даты в запросе пользователя вычисляй от current_date. "
            "'сегодня' = current_date; 'эта неделя' = current_week_start..current_week_end. "
            "Не придумывай даты из прошлого или будущего, если пользователь их не указал явно."
        ),
    }


def build_temporal_context_text() -> str:
    """Вернуть человекочитаемый временной контекст для текстовых prompts."""
    context = build_temporal_context()
    return "\n".join(
        [
            f"Текущая дата выполнения: {context['current_date']}",
            (
                "Текущая неделя: "
                f"{context['current_week_start']} .. {context['current_week_end']}"
            ),
            f"Правило относительных дат: {context['relative_date_rule']}",
        ]
    )
