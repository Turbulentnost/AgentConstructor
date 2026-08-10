import json, re
from datetime import date

def load(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)

production = load('code/dump/График_производства_1.json')
detailed = load('code/dump/детальный.json')
customs = load('code/dump/ТАМОЖНЯ.json')

# Inspect production sheet 'График до 20_12' fully to find header structure
for sheet_name in ['График до 20_12','Июнь выпуск Доп']:
    content = production.get(sheet_name)
    if not content: continue
    rows = content['rows']
    print('=== PRODUCTION SHEET', sheet_name, 'rows:', len(rows))
    for i, r in enumerate(rows[:8]):
        r2 = list(r)
        while r2 and r2[-1] is None:
            r2.pop()
        print(i, r2[:20])

# detailed sheet full header rows
content = detailed.get('Лист1')
rows = content['rows']
print('=== DETAILED rows:', len(rows))
for i, r in enumerate(rows[:10]):
    r2 = list(r)
    while r2 and r2[-1] is None:
        r2.pop()
    print(i, r2[:20])

# Реестр Заказов sheet header
content = customs.get('Реестр Заказов')
if content:
    rows = content['rows']
    print('=== Реестр Заказов rows:', len(rows))
    for i, r in enumerate(rows[:5]):
        r2 = list(r)
        while r2 and r2[-1] is None:
            r2.pop()
        print(i, r2[:20])
