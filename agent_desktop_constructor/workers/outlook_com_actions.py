"""Низкоуровневые безопасные действия Outlook через COM."""

from __future__ import annotations

import importlib
import re
import sys
from datetime import datetime, timedelta
from typing import Any

from agent_desktop_constructor.workers import com_availability
from agent_desktop_constructor.workers.outlook_com_errors import (
    ComUnavailableError,
    DangerousOutlookActionBlockedError,
    OutlookAccessError,
    OutlookComError,
)

INBOX_FOLDER_ID = 6
CALENDAR_FOLDER_ID = 9
DEFAULT_FOLDER = "Inbox"
CALENDAR_FOLDER = "Calendar"
DEFAULT_DAYS = 7
DEFAULT_DAYS_FORWARD = 7
DEFAULT_MAX_RESULTS = 50
DEFAULT_CALENDAR_MAX_RESULTS = 20
MAX_DAYS = 30
MAX_RESULTS = 50
DEFAULT_MAIL_MAX_SCAN_ITEMS = 200
DEFAULT_CALENDAR_MAX_SCAN_ITEMS = 300
MAX_SCAN_ITEMS = 500
BODY_PREVIEW_LIMIT = 500
CALENDAR_BODY_PREVIEW_LIMIT = 300


def _log_progress(message: str) -> None:
    """Записать COM progress-сообщение в stderr, не загрязняя stdout JSON."""
    print(f"[COM_DIAG] {message}", file=sys.stderr, flush=True)


def _load_pywin32_modules():
    """Загрузить pywin32-модули только внутри worker/action слоя."""
    if not com_availability.is_windows():
        raise ComUnavailableError("COM доступен только на Windows")

    try:
        pythoncom = importlib.import_module("pythoncom")
        win32com_client = importlib.import_module("win32com.client")
    except ImportError as exc:
        raise ComUnavailableError("pywin32 не установлен") from exc
    except Exception as exc:
        raise ComUnavailableError(f"pywin32 недоступен: {exc}") from exc

    return pythoncom, win32com_client


def _safe_str(value: Any) -> str:
    """Безопасно привести COM-значение к строке."""
    if value is None:
        return ""
    try:
        return str(value)
    except Exception:
        return ""


def _matches_query(subject: str, body: str, query: str | None) -> bool:
    """Проверить, подходит ли письмо под простой query с поддержкой OR."""
    if query is None or not query.strip():
        return True

    haystack = f"{subject}\n{body}".casefold()
    terms = [
        term.strip().casefold()
        for term in re.split(r"\s+OR\s+", query, flags=re.IGNORECASE)
        if term.strip()
    ]
    if not terms:
        return True

    return any(term in haystack for term in terms)


def search_mail(input_data: dict) -> dict:
    """Безопасно прочитать письма Outlook из Inbox без изменений в Outlook."""
    _log_progress("step=load_pywin32 start")
    folder = _safe_str(input_data.get("folder") or DEFAULT_FOLDER)
    if folder.casefold() != DEFAULT_FOLDER.casefold():
        raise OutlookComError("UNSUPPORTED_FOLDER: поддерживается только Inbox")

    days = _clamp_int(input_data.get("days"), DEFAULT_DAYS, 1, MAX_DAYS)
    max_results = _clamp_int(
        input_data.get("max_results"),
        DEFAULT_MAX_RESULTS,
        1,
        MAX_RESULTS,
    )
    max_scan_items = _clamp_int(
        input_data.get("max_scan_items"),
        DEFAULT_MAIL_MAX_SCAN_ITEMS,
        1,
        MAX_SCAN_ITEMS,
    )
    query = input_data.get("query")

    pythoncom, win32com_client = _load_pywin32_modules()
    _log_progress("step=load_pywin32 ok")
    com_initialized = False
    try:
        _log_progress("step=co_initialize start")
        pythoncom.CoInitialize()
        com_initialized = True
        _log_progress("step=co_initialize ok")

        _log_progress("step=dispatch_outlook start")
        outlook = win32com_client.Dispatch("Outlook.Application")
        _log_progress("step=dispatch_outlook ok")
        _log_progress("step=get_namespace start")
        namespace = outlook.GetNamespace("MAPI")
        _log_progress("step=get_namespace ok")
        _log_progress("step=get_inbox start")
        inbox = namespace.GetDefaultFolder(INBOX_FOLDER_ID)
        _log_progress("step=get_inbox ok")
        _log_progress("step=get_items start")
        messages = inbox.Items
        _log_progress("step=get_items ok")
        _log_progress("step=sort_items start")
        messages.Sort("[ReceivedTime]", True)
        _log_progress("step=sort_items ok")

        cutoff = datetime.now() - timedelta(days=days)
        results = []
        scanned_count = 0
        _log_progress("step=iterate_items start")
        for message in messages:
            scanned_count += 1
            if scanned_count > max_scan_items:
                break

            subject = _safe_str(getattr(message, "Subject", ""))
            sender = _safe_str(getattr(message, "SenderName", ""))
            received_time = getattr(message, "ReceivedTime", None)
            received_at = _safe_str(received_time)
            body = _safe_str(getattr(message, "Body", ""))
            entry_id = _safe_str(getattr(message, "EntryID", ""))

            if _is_older_than_cutoff(received_time, cutoff):
                continue
            if not _matches_query(subject, body, _safe_str(query) if query else None):
                continue

            results.append(
                {
                    "entry_id": entry_id,
                    "subject": subject,
                    "sender": sender,
                    "received_at": received_at,
                    "body_preview": body[:BODY_PREVIEW_LIMIT],
                }
            )
            if len(results) >= max_results:
                break

        _log_progress("step=done ok")
        return {
            "messages": results,
            "count": len(results),
            "scanned_count": scanned_count,
            "source": "outlook_com",
            "folder": DEFAULT_FOLDER,
        }
    except OutlookComError:
        raise
    except Exception as exc:
        raise OutlookAccessError(f"Ошибка доступа к Outlook или MAPI: {exc}") from exc
    finally:
        if com_initialized:
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass


def read_calendar(input_data: dict) -> dict:
    """Безопасно прочитать ближайшие события Outlook Calendar без изменений."""
    _log_progress("step=load_pywin32 start")
    days_forward = _clamp_int(
        input_data.get("days_forward"),
        DEFAULT_DAYS_FORWARD,
        1,
        MAX_DAYS,
    )
    max_results = _clamp_int(
        input_data.get("max_results"),
        DEFAULT_CALENDAR_MAX_RESULTS,
        1,
        MAX_RESULTS,
    )
    max_scan_items = _clamp_int(
        input_data.get("max_scan_items"),
        DEFAULT_CALENDAR_MAX_SCAN_ITEMS,
        1,
        MAX_SCAN_ITEMS,
    )

    pythoncom, win32com_client = _load_pywin32_modules()
    _log_progress("step=load_pywin32 ok")
    com_initialized = False
    try:
        _log_progress("step=co_initialize start")
        pythoncom.CoInitialize()
        com_initialized = True
        _log_progress("step=co_initialize ok")

        _log_progress("step=dispatch_outlook start")
        outlook = win32com_client.Dispatch("Outlook.Application")
        _log_progress("step=dispatch_outlook ok")
        _log_progress("step=get_namespace start")
        namespace = outlook.GetNamespace("MAPI")
        _log_progress("step=get_namespace ok")
        _log_progress("step=get_calendar start")
        calendar = namespace.GetDefaultFolder(CALENDAR_FOLDER_ID)
        _log_progress("step=get_calendar ok")
        _log_progress("step=get_items start")
        items = calendar.Items
        _log_progress("step=get_items ok")
        _log_progress("step=include_recurrences start")
        items.IncludeRecurrences = True
        _log_progress("step=include_recurrences ok")
        _log_progress("step=sort_items start")
        items.Sort("[Start]")
        _log_progress("step=sort_items ok")

        start_at = datetime.now()
        end_at = start_at + timedelta(days=days_forward)
        restricted_items = _restrict_calendar_items(items, start_at, end_at)

        events = []
        checked_count = 0
        _log_progress("step=iterate_items start")
        for event in restricted_items:
            checked_count += 1
            if checked_count > max_scan_items:
                break

            event_start = getattr(event, "Start", None)
            event_end = getattr(event, "End", None)
            if not _is_within_range(event_start, start_at, end_at):
                continue

            body = _safe_str(getattr(event, "Body", ""))
            events.append(
                {
                    "entry_id": _safe_str(getattr(event, "EntryID", "")),
                    "subject": _safe_str(getattr(event, "Subject", "")),
                    "start": _safe_str(event_start),
                    "end": _safe_str(event_end),
                    "location": _safe_str(getattr(event, "Location", "")),
                    "organizer": _safe_str(getattr(event, "Organizer", "")),
                    "required_attendees": _safe_str(
                        getattr(event, "RequiredAttendees", "")
                    ),
                    "optional_attendees": _safe_str(
                        getattr(event, "OptionalAttendees", "")
                    ),
                    "body_preview": body[:CALENDAR_BODY_PREVIEW_LIMIT],
                }
            )
            if len(events) >= max_results:
                break

        _log_progress("step=done ok")
        return {
            "events": events,
            "count": len(events),
            "scanned_count": checked_count,
            "source": "outlook_com",
            "folder": CALENDAR_FOLDER,
        }
    except OutlookComError:
        raise
    except Exception as exc:
        raise OutlookAccessError(f"Ошибка доступа к Outlook Calendar: {exc}") from exc
    finally:
        if com_initialized:
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass


def send_mail_disabled(input_data: dict) -> dict:
    """Всегда заблокировать отправку писем в безопасном режиме."""
    raise DangerousOutlookActionBlockedError(
        "Отправка писем через Outlook COM отключена в безопасном режиме"
    )


def create_draft_disabled(input_data: dict) -> dict:
    """Всегда заблокировать создание черновиков в безопасном режиме."""
    raise DangerousOutlookActionBlockedError(
        "Создание черновиков через Outlook COM пока отключено в безопасном режиме"
    )


def _clamp_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    """Привести числовой параметр к безопасному диапазону."""
    try:
        parsed_value = int(value)
    except (TypeError, ValueError):
        parsed_value = default
    return max(minimum, min(maximum, parsed_value))


def _is_older_than_cutoff(received_time: Any, cutoff: datetime) -> bool:
    """Проверить дату письма, не падая на нестандартных COM-типах времени."""
    if received_time is None:
        return False

    try:
        if hasattr(received_time, "replace"):
            comparable_time = received_time.replace(tzinfo=None)
        else:
            comparable_time = received_time
        return comparable_time < cutoff
    except Exception:
        return False


def _is_within_range(value: Any, start_at: datetime, end_at: datetime) -> bool:
    """Проверить, что COM-дата попадает в безопасный диапазон чтения."""
    if value is None:
        return False
    try:
        if hasattr(value, "replace"):
            comparable_value = value.replace(tzinfo=None)
        else:
            comparable_value = value
        return start_at <= comparable_value <= end_at
    except Exception:
        return False


def _restrict_calendar_items(items: Any, start_at: datetime, end_at: datetime) -> Any:
    """Безопасно ограничить календарные элементы через Restrict или fallback."""
    restriction = (
        "[Start] >= '"
        + start_at.strftime("%m/%d/%Y %I:%M %p")
        + "' AND [Start] <= '"
        + end_at.strftime("%m/%d/%Y %I:%M %p")
        + "'"
    )
    try:
        return items.Restrict(restriction)
    except Exception:
        return items
