# -*- coding: utf-8 -*-
import json

with open("headers_report_ascii.json", "r", encoding="utf-8") as f:
    data = json.load(f)

for fname, sheets in data.items():
    print("="*80)
    print("FILE:", fname.encode("ascii", "backslashreplace").decode("ascii"))
    if isinstance(sheets, dict) and "error" in sheets:
        print("  ERROR:", sheets["error"])
        continue
    for sname, sdata in sheets.items():
        print("-"*60)
        print("  SHEET:", sname.encode("ascii", "backslashreplace").decode("ascii"),
              "max_row=", sdata.get("max_row"), "max_col=", sdata.get("max_col"))
        for i, row in enumerate(sdata.get("header_preview", []), start=1):
            safe_row = [str(c).encode("ascii", "backslashreplace").decode("ascii") if c is not None else "" for c in row]
            print("    r%d:" % i, " | ".join(safe_row))
