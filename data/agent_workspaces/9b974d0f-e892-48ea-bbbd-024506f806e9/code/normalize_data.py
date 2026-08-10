# -*- coding: utf-8 -*-
"""
Normalize-скрипт: читает raw_extracted_data.json (полный дамп всех листов 4 файлов)
и формирует нормализованные структуры данных по ролям, зафиксированным по ТЗ:

- shipment_schedule: 'ГРАФИК ОТГРУЗОК (расширенный) 2.xlsx' (листы CC/СИ,СТ/СР,СРМ/НСУ2.1/Доп заказ)
  + 'ТАМОЖНЯ.xlsx' листы 'ТАМОЖНЯ'/'ИТЦ В РАБОТЕ'/'Реестр Заказов'
- production_schedule: 'График производства 1.xlsx' (листы с версиями: 'Июнь выпуск Доп',
  'График до 20_12', 'Лист3' - берём 2 последние по 'Версия' в r1 если есть)
- detailed_production_schedule: 'детальный.xlsx' (Лист1)

Сохраняет normalized_data.json с ключами: shipment_sheets, production_sheets,
detailed_sheets - каждый содержит raw rows + заголовки, готовые к дальнейшему
парсингу расчётным скриптом. Печатает ASCII-safe summary в stdout.
"""
import json

SHIPMENT_FILE = "ГРАФИК ОТГРУЗОК (расширенный) 2.xlsx"
CUSTOMS_FILE = "ТАМОЖНЯ.xlsx"
PRODUCTION_FILE = "График производства 1.xlsx"
DETAILED_FILE = "детальный.xlsx"

CUSTOMS_SHIPMENT_SHEETS = ["ТАМОЖНЯ", "ИТЦ В РАБОТЕ", "Реестр Заказов"]

with open("raw_extracted_data.json", "r", encoding="utf-8") as f:
    raw = json.load(f)

files = raw.get("files", {})

result = {
    "roles": {
        SHIPMENT_FILE: "shipment_schedule (все листы)",
        CUSTOMS_FILE: "shipment_schedule (листы ТАМОЖНЯ/ИТЦ В РАБОТЕ/Реестр Заказов)",
        PRODUCTION_FILE: "production_schedule (версии в разных листах)",
        DETAILED_FILE: "detailed_production_schedule",
    },
    "shipment_sheets": {},
    "production_sheets": {},
    "detailed_sheets": {},
    "warnings": [],
}

# shipment_schedule из ГРАФИК ОТГРУЗОК
if SHIPMENT_FILE in files and "sheets" in files[SHIPMENT_FILE]:
    for sname, sdata in files[SHIPMENT_FILE]["sheets"].items():
        result["shipment_sheets"]["%s::%s" % (SHIPMENT_FILE, sname)] = sdata
else:
    result["warnings"].append("missing_shipment_file: %s" % SHIPMENT_FILE)

# shipment_schedule из ТАМОЖНЯ (только нужные листы)
if CUSTOMS_FILE in files and "sheets" in files[CUSTOMS_FILE]:
    for sname in CUSTOMS_SHIPMENT_SHEETS:
        if sname in files[CUSTOMS_FILE]["sheets"]:
            result["shipment_sheets"]["%s::%s" % (CUSTOMS_FILE, sname)] = files[CUSTOMS_FILE]["sheets"][sname]
        else:
            result["warnings"].append("missing_customs_sheet: %s" % sname)
else:
    result["warnings"].append("missing_customs_file: %s" % CUSTOMS_FILE)

# production_schedule
if PRODUCTION_FILE in files and "sheets" in files[PRODUCTION_FILE]:
    for sname, sdata in files[PRODUCTION_FILE]["sheets"].items():
        rows = sdata.get("rows", [])
        nonempty = sum(1 for r in rows if any(c is not None and str(c).strip() != "" for c in r))
        if nonempty > 2:  # пропускаем пустые технические листы типа Лист2
            result["production_sheets"][sname] = sdata
else:
    result["warnings"].append("missing_production_file: %s" % PRODUCTION_FILE)

# detailed_production_schedule
if DETAILED_FILE in files and "sheets" in files[DETAILED_FILE]:
    for sname, sdata in files[DETAILED_FILE]["sheets"].items():
        result["detailed_sheets"][sname] = sdata
else:
    result["warnings"].append("missing_detailed_file: %s" % DETAILED_FILE)

# явный поиск stock/prices/specification маркеров внутри имеющихся листов
no_stock_prices = True
for fname, fdata in files.items():
    if "sheets" not in fdata:
        continue
    for sname, sdata in fdata["sheets"].items():
        rows = sdata.get("rows", [])
        for row in rows[:3]:
            for c in row:
                if c and isinstance(c, str):
                    low = c.lower()
                    if "цена" in low or "поставщик" in low:
                        no_stock_prices = False
if no_stock_prices:
    result["warnings"].append("no_explicit_price_supplier_file_found")

with open("normalized_data.json", "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=1)

print("OK. Saved normalized_data.json")
print("shipment_sheets:", list(result["shipment_sheets"].keys()))
print("production_sheets:", list(result["production_sheets"].keys()))
print("detailed_sheets:", list(result["detailed_sheets"].keys()))
print("warnings:", result["warnings"])
