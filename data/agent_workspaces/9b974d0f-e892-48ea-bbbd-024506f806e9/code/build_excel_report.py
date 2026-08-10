# -*- coding: utf-8 -*-
"""
Сборка итогового Excel-отчёта 'Агент закупок Авион' из summary_calc.json и
final_calc.json. Листы:
0-Роли файлов | 1-Предупреждения | 2-Произв.план (мес.) | 3-Дашборд логистики |
4-Сменное задание.
Сохраняет Отчет_Агент_закупок_Авион.xlsx в рабочей папке. Печатает ASCII-safe summary.
"""
import json
import datetime
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

TODAY = datetime.date(2026, 8, 6)

with open("summary_calc.json", "r", encoding="utf-8") as f:
    summary = json.load(f)

with open("final_calc.json", "r", encoding="utf-8") as f:
    final_calc = json.load(f)

RED = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")
YELLOW = PatternFill(start_color="FFEB9C", end_color="FFEB9C", fill_type="solid")
GREEN = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
BOLD = Font(bold=True)

wb = Workbook()

# --- Лист 0: Роли файлов ---
ws0 = wb.active
ws0.title = "0-Роли файлов"
ws0.append(["Файл", "Роль", "Почему"])
for c in ws0[1]:
    c.font = BOLD
roles_rows = [
    ("ГРАФИК ОТГРУЗОК (расширенный) 2.xlsx", "shipment_schedule", "Листы СС/СИ,СТ/СР,СРМ/НСУ2.1/Доп заказ: номенклатура + колонки дат поставки + логистика до МСК/МСК-Ростов + заказано"),
    ("ТАМОЖНЯ.xlsx", "shipment_schedule (доп.)", "Листы ТАМОЖНЯ / ИТЦ В РАБОТЕ / Реестр Заказов - позиции+таможня, но иная структура шапки, авто-парсинг не нашёл колонку 'Номенклатура' в первых строках"),
    ("График производства 1.xlsx", "production_schedule", "Листы 'Июнь выпуск Доп' / 'График до 20_12' / 'Лист3': Наименования изделий x месяцы, категории Заказ/Опытные/Склад, План/Факт"),
    ("детальный.xlsx", "detailed_production_schedule", "Лист1: дневная сетка с датами-колонками, стадии П/ф/ОТК/Склад"),
]
for r in roles_rows:
    ws0.append(list(r))
for col in ["A", "B", "C"]:
    ws0.column_dimensions[col].width = 45

# --- Лист 1: Предупреждения ---
ws1 = wb.create_sheet("1-Предупреждения")
ws1.append(["Предупреждение"])
ws1["A1"].font = BOLD
warn_texts = {
    "no_header_found: ТАМОЖНЯ.xlsx::ТАМОЖНЯ": "Лист 'ТАМОЖНЯ' файла ТАМОЖНЯ.xlsx не распарсен автоматически (нестандартная структура шапки без явной колонки 'Номенклатура' в первых строках) - позиции этого листа не вошли в расчёт поступлений/логистики.",
    "no_header_found: ТАМОЖНЯ.xlsx::ИТЦ В РАБОТЕ": "Лист 'ИТЦ В РАБОТЕ' файла ТАМОЖНЯ.xlsx не распарсен автоматически - не вошёл в расчёт.",
    "no_header_found: ТАМОЖНЯ.xlsx::Реестр Заказов": "Лист 'Реестр Заказов' файла ТАМОЖНЯ.xlsx не распарсен автоматически - не вошёл в расчёт.",
    "no_bom_spec_price_stock_file_found": "Среди 4 приложенных файлов НЕ найден отдельный файл со спецификацией BOM (материал-на-изделие), ценами/поставщиками или остатками материалов (stock). Из-за этого: (а) обеспеченность по изделиям (BOM-цепочка изделие->материал) не рассчитана; (б) план заказов по номенклатурам сформирован быть не может без данных остатков; (в) остаток материалов принят равным 0 во всех расчётах прогноза.",
}
for w in summary.get("warnings", []):
    ws1.append([warn_texts.get(w, w)])
ws1.column_dimensions["A"].width = 120

# --- Лист 2: Производственный план (мес.) - помесячная потребность/поступление/прогноз ---
ws2 = wb.create_sheet("2-Произв.план (мес.)")
months_order = ["июль","август","сентябрь","октябрь","ноябрь","декабрь"]
header = ["Категория"] + months_order
ws2.append(header)
for c in ws2[1]:
    c.font = BOLD
monthly_demand = summary.get("monthly_demand", {})
cats_seen = set()
for m, cats in monthly_demand.items():
    cats_seen.update(cats.keys())
for cat in sorted(cats_seen):
    row_plan = ["%s - План" % cat]
    row_fact = ["%s - Факт" % cat]
    for m in months_order:
        cats = monthly_demand.get(m, {})
        vals = cats.get(cat, {})
        row_plan.append(vals.get("план", 0))
        row_fact.append(vals.get("факт", 0))
    ws2.append(row_plan)
    ws2.append(row_fact)
ws2.append([])
ws2.append(["Ожидаемое поступление (сумма по датам shipment)"] + [
    summary.get("monthly_arrivals", {}).get("2026-%02d" % {"июль":7,"август":8,"сентябрь":9,"октябрь":10,"ноябрь":11,"декабрь":12}[m], 0)
    for m in months_order
])
row_forecast = ["Прогноз остатка (нарастающий, только планы)"]
forecast_data = summary.get("monthly_forecast", {})
for m in months_order:
    v = forecast_data.get(m, {}).get("forecast", None)
    row_forecast.append(v if v is not None else "")
ws2.append(row_forecast)
fr_row_idx = ws2.max_row
for col_idx, m in enumerate(months_order, start=2):
    v = forecast_data.get(m, {}).get("forecast", None)
    if v is not None and v < 0:
        ws2.cell(row=fr_row_idx, column=col_idx).fill = RED
ws2.column_dimensions["A"].width = 45
for col in "BCDEFG":
    ws2.column_dimensions[col].width = 14

# --- Лист 3: Дашборд логистики (риски на сегодня) ---
ws3 = wb.create_sheet("3-Дашборд логистики")
ws3.append(["Номенклатура", "Лист-источник", "Дата поставки D", "Кол-во", "Дней до D", "Окно МСК (short-long)", "Окно Ростов (short-long)", "Статус"])
for c in ws3[1]:
    c.font = BOLD
risk_items = summary.get("logistics_risk_today", [])
for it in risk_items:
    row = [
        it.get("nomenclature"), it.get("sheet"), it.get("target_date"), it.get("qty"),
        it.get("days_to_D"), str(it.get("log_msk_window")), str(it.get("log_rostov_window")),
        it.get("status"),
    ]
    ws3.append(row)
    r_idx = ws3.max_row
    status = it.get("status")
    fill = {"critical": RED, "high": RED, "warning": YELLOW, "ok": GREEN}.get(status)
    if fill:
        ws3.cell(row=r_idx, column=8).fill = fill
for col, w in zip("ABCDEFGH", [40, 35, 16, 10, 10, 20, 20, 12]):
    ws3.column_dimensions[col].width = w

status_counts = {}
for it in risk_items:
    status_counts[it.get("status")] = status_counts.get(it.get("status"), 0) + 1

# --- Лист 4: Сменное задание ---
ws4 = wb.create_sheet("4-Сменное задание")
ws4.append(["Дата: %s" % TODAY.isoformat()])
ws4.append(["Критично: %d | Высокий риск: %d | Предупреждение: %d | ОК: %d" % (
    status_counts.get("critical", 0), status_counts.get("high", 0),
    status_counts.get("warning", 0), status_counts.get("ok", 0))])
ws4.append([])
ws4.append(["Приоритет", "Проблема", "Что сделать", "Номенклатура", "Кол-во", "Срок (дата D)", "Дней до D"])
for c in ws4[4]:
    c.font = BOLD
urgent = [it for it in risk_items if it.get("status") in ("critical", "high")]
urgent_sorted = sorted(urgent, key=lambda x: x.get("days_to_D", 9999))
for it in urgent_sorted:
    priority = "Срочно" if it.get("status") == "critical" else "Высокий"
    problem = "Просрочка/риск поставки" if it.get("days_to_D", 0) < 0 else "Вход в окно логистического риска"
    action = "Проверить статус отгрузки, ускорить логистику/таможню"
    ws4.append([priority, problem, action, it.get("nomenclature"), it.get("qty"), it.get("target_date"), it.get("days_to_D")])
    r_idx = ws4.max_row
    ws4.cell(row=r_idx, column=1).fill = RED if priority == "Срочно" else YELLOW
for col, w in zip("ABCDEFG", [12, 30, 40, 40, 10, 14, 10]):
    ws4.column_dimensions[col].width = w

out_name = "Отчет_Агент_закупок_Авион.xlsx"
wb.save(out_name)

print("OK. Saved", out_name)
print("sheets:", wb.sheetnames)
print("risk_items_total:", len(risk_items), "status_counts:", status_counts)
print("urgent_tasks_count:", len(urgent_sorted))
