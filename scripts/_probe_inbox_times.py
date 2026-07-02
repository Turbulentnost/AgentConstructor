"""Диагностика ReceivedTime писем Inbox in-process."""

from __future__ import annotations

import importlib
from datetime import datetime, timedelta

pythoncom = importlib.import_module("pythoncom")
win32com_client = importlib.import_module("win32com.client")

pythoncom.CoInitialize()
try:
    outlook = win32com_client.Dispatch("Outlook.Application")
    ns = outlook.GetNamespace("MAPI")
    inbox = ns.GetDefaultFolder(6)
    items = inbox.Items
    print("inbox count:", items.Count)
    items.Sort("[ReceivedTime]", True)
    now = datetime.now()
    print("now:", now)
    shown = 0
    for message in items:
        cls = getattr(message, "Class", None)
        rt = getattr(message, "ReceivedTime", None)
        rt_naive = None
        cmp = None
        try:
            rt_naive = rt.replace(tzinfo=None) if hasattr(rt, "replace") else rt
            cmp = rt_naive < (now - timedelta(days=365))
        except Exception as exc:  # noqa: BLE001
            cmp = f"ERR:{exc}"
        print(f"class={cls} received={rt!r} naive={rt_naive!r} older_than_365={cmp}")
        shown += 1
        if shown >= 8:
            break
finally:
    pythoncom.CoUninitialize()
