# -*- coding: utf-8 -*-
"""
Финальный расчётный скрипт: парсит normalized_data.json (shipment_sheets, detailed_sheets)
и parsed_structured.json (production_parsed) для выполнения расчётов раздела 3 ТЗ:
1) Помесячная потребность материала (заглушка без BOM -> пока по изделиям, BOM свяжем позже)
2) Парсинг shipment: даты поставки (колонки-даты) -> qty по номенклатуре по календарным месяцам и дням
3) Логистические окна: 'Логистика до МСК' и 'Логистика МСК-Ростов' вида '7-14 к.д.' -> (short,long)
4) Парсинг detailed (дневная сетка, стадия П/ф) -> план/факт по дням
Сохраняет final_calc.json. Печатает ASCII-safe summary в stdout.
"""
import json
import re
import datetime

with open("normalized_data.json", "r", encoding="utf-8") as f:
    norm = json.load(f)

with open("parsed_structured.json", "r", encoding="utf-8") as f:
    parsed = json.load(f)

def norm_str(v):
    return str(v).strip() if v is not None else ""

def parse_logistics_window(val):
    """'7-14 к.д.' -> (7, 14); None если не распарсилось."""
    if not val:
        return None
    s = str(val)
    m = re.search(r"(\d+)\s*-\s*(\d+)", s)
    if m:
        return (int(m.group(1)), int(m.group(2)))
    m2 = re.search(r"(\d+)", s)
    if m2:
        n = int(m2.group(1))
        return (n, n)
    return None

def parse_date_cell(v):
    if v is None:
        return None
    if isinstance(v, str):
        # ISO datetime string from json dump
        m = re.match(r"(\d{4}-\d{2}-\d{2})", v)
        if m:
            try:
                return datetime.date.fromisoformat(m.group(1))
            except ValueError:
                return None
    return None

# --- Парсинг shipment_sheets: находим строку-шапку с колонками-датами ---
shipment_parsed = {}
warnings = []
for sname, sdata in norm.get("shipment_sheets", {}).items():
    rows = sdata.get("rows", [])
    if not rows:
        continue
    # ищем строку заголовка с 'Номенклатура' и колонки логистики
    header_idx = None
    for i, row in enumerate(rows[:5]):
        joined = " ".join(norm_str(c).lower() for c in row if c)
        if "номенклатур" in joined:
            header_idx = i
            break
    if header_idx is None:
        warnings.append("no_header_found: %s" % sname)
        continue
    header = rows[header_idx]
    # найдём индексы ключевых колонок
    col_idx = {"nomen": None, "zakazano": None, "log_msk": None, "log_rostov": None, "date_cols": []}
    for c_idx, h in enumerate(header):
        hs = norm_str(h).lower()
        if "номенклатур" in hs and col_idx["nomen"] is None:
            col_idx["nomen"] = c_idx
        elif "заказано" in hs or ("кол-во" in hs and "заказ" in hs):
            col_idx["zakazano"] = c_idx
        elif "мск" in hs and "ростов" not in hs:
            col_idx["log_msk"] = c_idx
        elif "ростов" in hs:
            col_idx["log_rostov"] = c_idx
    # колонки-даты: пробуем распарсить сам заголовок ячейки как дату (ISO строка)
    for c_idx, h in enumerate(header):
        d = parse_date_cell(h)
        if d:
            col_idx["date_cols"].append((c_idx, d.isoformat()))
    items = []
    for r in rows[header_idx + 1:]:
        if not r or col_idx["nomen"] is None or col_idx["nomen"] >= len(r):
            continue
        nomen = norm_str(r[col_idx["nomen"]])
        if not nomen:
            continue
        item = {"nomenclature": nomen, "deliveries": {}}
        if col_idx["zakazano"] is not None and col_idx["zakazano"] < len(r):
            item["zakazano"] = r[col_idx["zakazano"]]
        if col_idx["log_msk"] is not None and col_idx["log_msk"] < len(r):
            item["log_msk_window"] = parse_logistics_window(r[col_idx["log_msk"]])
        if col_idx["log_rostov"] is not None and col_idx["log_rostov"] < len(r):
            item["log_rostov_window"] = parse_logistics_window(r[col_idx["log_rostov"]])
        for c_idx, date_iso in col_idx["date_cols"]:
            if c_idx < len(r) and r[c_idx] not in (None, ""):
                try:
                    qty = float(r[c_idx])
                    item["deliveries"][date_iso] = qty
                except (TypeError, ValueError):
                    pass
        items.append(item)
    shipment_parsed[sname] = {"header_idx": header_idx, "col_idx": col_idx, "items_count": len(items), "items": items}

# --- Парсинг detailed_sheets: дневная сетка, стадия П/ф ---
detailed_parsed = {}
for sname, sdata in norm.get("detailed_sheets", {}).items():
    rows = sdata.get("rows", [])
    if not rows:
        continue
    # ищем строку заголовка с датами
    header_idx = None
    date_cols = []
    for i, row in enumerate(rows[:6]):
        found = []
        for c_idx, v in enumerate(row):
            d = parse_date_cell(v)
            if d:
                found.append((c_idx, d.isoformat()))
        if len(found) >= 3:
            header_idx = i
            date_cols = found
            break
    stage_rows = []
    if header_idx is not None:
        for r in rows[header_idx + 1:]:
            if not r:
                continue
            joined = " ".join(norm_str(c).lower() for c in r[:3] if c)
            if "п/ф" in joined or "пф" in joined:
                stage_rows.append(r)
    detailed_parsed[sname] = {
        "header_idx": header_idx,
        "date_cols_count": len(date_cols),
        "date_cols_sample": date_cols[:5],
        "pf_stage_rows_count": len(stage_rows),
    }

out = {
    "shipment_parsed": shipment_parsed,
    "detailed_parsed": detailed_parsed,
    "production_parsed_ref": list(parsed.get("production_parsed", {}).keys()),
    "warnings": warnings,
}

with open("final_calc.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=1, default=str)

print("OK. Saved final_calc.json")
print("shipment_parsed sheets:", list(shipment_parsed.keys()))
for sname, sp in shipment_parsed.items():
    print("  ", sname, "-> items=", sp["items_count"], "date_cols=", len(sp["col_idx"]["date_cols"]))
print("detailed_parsed sheets:", list(detailed_parsed.keys()))
for sname, dp in detailed_parsed.items():
    print("  ", sname, "-> header_idx=", dp["header_idx"], "date_cols=", dp["date_cols_count"], "pf_rows=", dp["pf_stage_rows_count"])
print("warnings:", warnings)
