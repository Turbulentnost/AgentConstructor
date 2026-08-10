# -*- coding: utf-8 -*-
"""
Читает raw_extracted_data.json и печатает в stdout ASCII-safe (ensure_ascii=True)
JSON с заголовками (первые N строк) каждого листа каждого файла - чтобы избежать
mojibake при просмотре кириллицы через консоль.
"""
import json

HEADER_ROWS = 6
MAX_COLS = 40

with open("raw_extracted_data.json", "r", encoding="utf-8") as f:
    data = json.load(f)

result = {}
for fname, fdata in data.get("files", {}).items():
    if "error" in fdata:
        result[fname] = {"error": fdata["error"]}
        continue
    sheets_out = {}
    for sname, sdata in fdata.get("sheets", {}).items():
        rows = sdata.get("rows", [])
        header_preview = []
        for r in rows[:HEADER_ROWS]:
            header_preview.append(r[:MAX_COLS])
        sheets_out[sname] = {
            "max_row": sdata.get("max_row"),
            "max_col": sdata.get("max_col"),
            "header_preview": header_preview,
        }
    result[fname] = sheets_out

with open("headers_report_ascii.json", "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=True, indent=1)

print("Saved ASCII-safe headers report to headers_report_ascii.json")
print("Files:", list(result.keys()))
for fname, sheets in result.items():
    if isinstance(sheets, dict) and "error" in sheets:
        continue
    print(fname, "-> sheets:", list(sheets.keys()))
