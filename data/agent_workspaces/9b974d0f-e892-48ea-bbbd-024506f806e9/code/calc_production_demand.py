# -*- coding: utf-8 -*-
"""
Парсинг normalized_data.json: строит структурированные данные для расчётов:
- production_monthly: {изделие: {месяц: {категория(заказ/опытн/склад): {план, факт}}}}
- detailed_daily: {изделие: {дата(YYYY-MM-DD): {план, факт}}} только для стадии П/ф
- shipment_items: {номенклатура: {датапоставки: qty, лог_до_мск: (short,long), лог_мск_ростов:(short,long), заказано, остаток}}
Сохраняет parsed_structured.json. Печатает ASCII-safe summary в stdout.
"""
import json
import re
import datetime

with open("normalized_data.json", "r", encoding="utf-8") as f:
    norm = json.load(f)

MONTHS_RU = {
    "январь": 1, "февраль": 2, "март": 3, "апрель": 4, "май": 5, "июнь": 6,
    "июль": 7, "август": 8, "сентябрь": 9, "октябрь": 10, "ноябрь": 11, "декабрь": 12,
}

def norm_str(v):
    return str(v).strip().lower() if v is not None else ""

def find_header_row(rows, keywords, max_scan=10):
    for i, row in enumerate(rows[:max_scan]):
        joined = " ".join(norm_str(c) for c in row if c)
        if any(k in joined for k in keywords):
            return i
    return None

# --- 1. PRODUCTION SHEETS: помесячный план/факт по категориям ---
production_result = {}
for sname, sdata in norm.get("production_sheets", {}).items():
    rows = sdata.get("rows", [])
    if not rows:
        continue
    # ищем строку с названиями месяцев (row содержит несколько ru-месяцев)
    month_row_idx = None
    for i, row in enumerate(rows[:6]):
        month_hits = sum(1 for c in row if c and norm_str(c) in MONTHS_RU)
        if month_hits >= 2:
            month_row_idx = i
            break
    if month_row_idx is None:
        continue
    month_row = rows[month_row_idx]
    # строка ниже может содержать категории (заказ/опытн/склад), ниже неё план/факт
    cat_row = rows[month_row_idx + 1] if month_row_idx + 1 < len(rows) else []
    planfact_row = rows[month_row_idx + 2] if month_row_idx + 2 < len(rows) else []
    # определим карту колонка -> (месяц, категория, план_факт)
    col_map = {}
    current_month = None
    for c_idx, val in enumerate(month_row):
        vs = norm_str(val)
        if vs in MONTHS_RU:
            current_month = vs
        if current_month:
            cat = norm_str(cat_row[c_idx]) if c_idx < len(cat_row) else ""
            pf = norm_str(planfact_row[c_idx]) if c_idx < len(planfact_row) else ""
            col_map[c_idx] = (current_month, cat, pf)
    # находим начало данных изделий (после заголовков)
    data_start = month_row_idx + 3
    # определим колонку с наименованием изделия (обычно первая непустая текстовая колонка)
    item_col = 0
    items = {}
    for r in rows[data_start:]:
        if not r or not r[0]:
            continue
        item_name = str(r[0]).strip()
        if not item_name or item_name.lower().startswith("итог"):
            continue
        for c_idx, (month, cat, pf) in col_map.items():
            if c_idx >= len(r):
                continue
            val = r[c_idx]
            if val is None or val == "":
                continue
            try:
                qty = float(val)
            except (TypeError, ValueError):
                continue
            items.setdefault(item_name, {}).setdefault(month, {}).setdefault(
                cat if cat else "заказ", {}
            )[pf if pf else "план"] = qty
    production_result[sname] = {"items": items, "month_row_idx": month_row_idx}

# --- 2. DETAILED SHEETS: дневная потребность только стадия П/ф ---
detailed_result = {}
for sname, sdata in norm.get("detailed_sheets", {}).items():
    rows = sdata.get("rows", [])
    detailed_result[sname] = {"raw_rows_count": len(rows), "sample_first_rows": rows[:8]}

# --- 3. SHIPMENT SHEETS: даты поставки, логистика, заказано/остаток ---
shipment_result = {}
for sname, sdata in norm.get("shipment_sheets", {}).items():
    rows = sdata.get("rows", [])
    shipment_result[sname] = {"raw_rows_count": len(rows), "sample_first_rows": rows[:6]}

out = {
    "production_parsed": production_result,
    "detailed_preview": detailed_result,
    "shipment_preview": shipment_result,
}

with open("parsed_structured.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=1)

print("OK. Saved parsed_structured.json")
print("production_sheets_parsed:", list(production_result.keys()))
for sname, pdata in production_result.items():
    print("  ", sname, "-> items_count=", len(pdata["items"]))
print("detailed_sheets:", list(detailed_result.keys()))
print("shipment_sheets:", list(shipment_result.keys()))
