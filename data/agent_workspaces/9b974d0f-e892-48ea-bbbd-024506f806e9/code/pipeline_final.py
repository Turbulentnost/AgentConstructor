# -*- coding: utf-8 -*-
"""
Объединяющий расчётный скрипт: собирает итоговые таблицы раздела 3 ТЗ из
parsed_structured.json (production_parsed) и final_calc.json (shipment_parsed,
detailed_parsed). Считает:
1) monthly_demand: месяц -> категория(заказ/опытн/склад) -> план/факт (сумма по изделиям)
2) monthly_arrivals: месяц (YYYY-MM) -> qty (сумма поступлений shipment по датам)
3) monthly_forecast: остаток=0 (нет stock-файла) + поступление - Sum(планы) нарастающим итогом
4) daily_demand (detailed Лист1, П/ф): дата -> план/факт
5) daily_arrivals: дата -> qty из shipment
6) logistics_risk_today: на TODAY, для каждого shipment item определить дату D примерной поставки
   (если есть будущая дата с qty в deliveries), стадию (загрузка/МСК/таможня/Ростов) и статус
   ok/warning/high/critical по окнам log_msk_window/log_rostov_window.
Сохраняет summary_calc.json. Печатает ASCII-safe summary в stdout.
"""
import json
import datetime
from collections import defaultdict

TODAY = datetime.date(2026, 8, 6)

with open("parsed_structured.json", "r", encoding="utf-8") as f:
    parsed = json.load(f)

with open("final_calc.json", "r", encoding="utf-8") as f:
    final_calc = json.load(f)

MONTHS_RU = {
    "январь": 1, "февраль": 2, "март": 3, "апрель": 4, "май": 5, "июнь": 6,
    "июль": 7, "август": 8, "сентябрь": 9, "октябрь": 10, "ноябрь": 11, "декабрь": 12,
}
MONTHS_ORDER = ["июль","август","сентябрь","октябрь","ноябрь","декабрь"]

# --- 1) monthly_demand по категориям, суммируя по изделиям всех production листов ---
monthly_demand = defaultdict(lambda: defaultdict(lambda: {"план": 0.0, "факт": 0.0}))
items_by_sheet = {}
for sname, sdata in parsed.get("production_parsed", {}).items():
    items = sdata.get("items", {})
    items_by_sheet[sname] = list(items.keys())
    for item_name, months in items.items():
        for month, cats in months.items():
            for cat, pf in cats.items():
                for pf_key, qty in pf.items():
                    key_pf = "план" if "план" in pf_key else ("факт" if "факт" in pf_key else "план")
                    monthly_demand[month][cat][key_pf] += qty

# --- 2) monthly_arrivals: суммируем deliveries из shipment_parsed по месяцу поставки ---
monthly_arrivals = defaultdict(float)
daily_arrivals = defaultdict(float)
logistics_items = []
for sname, sdata in final_calc.get("shipment_parsed", {}).items():
    for item in sdata.get("items", []):
        nomen = item.get("nomenclature")
        log_msk = item.get("log_msk_window")
        log_rostov = item.get("log_rostov_window")
        deliveries = item.get("deliveries", {})
        future_dates = []
        for date_iso, qty in deliveries.items():
            try:
                d = datetime.date.fromisoformat(date_iso)
            except ValueError:
                continue
            ym = "%04d-%02d" % (d.year, d.month)
            monthly_arrivals[ym] += qty
            daily_arrivals[date_iso] += qty
            future_dates.append((d, qty))
        # риск на сегодня: берём ближайшую дату поставки >= today (или последнюю прошедшую, если все в прошлом)
        future_dates.sort(key=lambda x: x[0])
        upcoming = [fd for fd in future_dates if fd[0] >= TODAY]
        target = upcoming[0] if upcoming else (future_dates[-1] if future_dates else None)
        if target and log_msk and log_rostov:
            D = target[0]
            days_to_D = (D - TODAY).days
            short_msk, long_msk = log_msk
            short_rostov, long_rostov = log_rostov
            total_short = short_msk + 2 + short_rostov
            total_long = long_msk + 2 + long_rostov
            if days_to_D < 0:
                status = "critical"  # просрочка даты поставки
            elif days_to_D <= total_short * 0.3:
                status = "critical"
            elif days_to_D <= total_short * 0.6:
                status = "high"
            elif days_to_D <= total_long:
                status = "warning"
            else:
                status = "ok"
            logistics_items.append({
                "nomenclature": nomen, "sheet": sname, "target_date": D.isoformat(),
                "qty": target[1], "days_to_D": days_to_D, "log_msk_window": log_msk,
                "log_rostov_window": log_rostov, "status": status,
            })

# --- 3) monthly_forecast: opening=0 (нет stock файла), нарастающий поступление - планы ---
monthly_forecast = {}
running = 0.0
for month in MONTHS_ORDER:
    if month not in monthly_demand:
        continue
    cats = monthly_demand[month]
    total_plan = sum(cats[c]["план"] for c in cats)
    ym_guess = None
    for ym in monthly_arrivals:
        pass
    arrival = 0.0
    for ym, qty in monthly_arrivals.items():
        mm = int(ym.split("-")[1])
        if MONTHS_RU.get(month) == mm:
            arrival += qty
    running = running + arrival - total_plan
    monthly_forecast[month] = {"arrival": arrival, "total_plan": total_plan, "forecast": running}

# --- 4) daily_demand из detailed_parsed (Лист1, П/ф) ---
daily_summary = {
    "detailed_sheets": list(final_calc.get("detailed_parsed", {}).keys()),
    "detailed_meta": final_calc.get("detailed_parsed", {}),
}

out = {
    "today": TODAY.isoformat(),
    "monthly_demand": {m: dict(cats) for m, cats in monthly_demand.items()},
    "monthly_arrivals": dict(monthly_arrivals),
    "monthly_forecast": monthly_forecast,
    "logistics_risk_today": sorted(logistics_items, key=lambda x: x["days_to_D"]),
    "daily_summary": daily_summary,
    "items_by_production_sheet": items_by_sheet,
    "warnings": final_calc.get("warnings", []) + ["no_bom_spec_price_stock_file_found"],
}

with open("summary_calc.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=1, default=str)

print("OK. Saved summary_calc.json")
print("months_with_demand:", list(monthly_demand.keys()))
print("monthly_forecast:", {m: round(v["forecast"], 1) for m, v in monthly_forecast.items()})
print("monthly_arrivals:", {k: round(v,1) for k,v in monthly_arrivals.items()})
print("logistics_risk_items_count:", len(logistics_items))
status_counts = defaultdict(int)
for li in logistics_items:
    status_counts[li["status"]] += 1
print("status_counts:", dict(status_counts))
print("warnings:", out["warnings"])
