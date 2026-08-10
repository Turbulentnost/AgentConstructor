# -*- coding: utf-8 -*-
"""Печатает inspect_report.txt в UTF-8 без искажений кодировки."""
import sys

with open("inspect_report.txt", "r", encoding="utf-8") as f:
    text = f.read()

sys.stdout.reconfigure(encoding="utf-8")
print(text)
