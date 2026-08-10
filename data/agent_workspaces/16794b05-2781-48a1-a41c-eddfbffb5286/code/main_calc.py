import json, re
from datetime import datetime, date, timedelta

def load(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)

shipment = load('code/dump/ГРАФИК_ОТГРУЗОК_расширенный_2.json')
production = load('code/dump/График_производства_1.json')
detailed = load('code/dump/детальный.json')
customs = load('code/dump/ТАМОЖНЯ.json')

today = date(2026, 8, 6)

# ---------- 1) SHIPMENT ----------
shipment_items = []
for sheet_name, content in shipment.items():
    rows = content['rows']
    if len(rows) < 2:
        continue
    header = rows[1]
    date_cols = []
    for idx, h in enumerate(header):
        if isinstance(h, str) and re.match(r'^\d{4}-\d{2}-\d{2}', h):
            date_cols.append((idx, h[:10]))
    for r in rows[2:]:
        if not r or not r[0] or not isinstance(r[0], str):
            continue
        nom = r[0]
        ordered_qty = r[1] if len(r) > 1 else None
        log_msk = r[6] if len(r) > 6 else None
        log_rostov = r[7] if len(r) > 7 else None
        deliveries = []
        for idx, d in date_cols:
            if idx < len(r) and r[idx] not in (None, ''):
                try:
                    q = float(r[idx])
                except Exception:
                    continue
                if q > 0:
                    deliveries.append({'date': d, 'qty': q})
        if deliveries or ordered_qty:
            shipment_items.append({'sheet': sheet_name, 'nomenclature': nom, 'ordered_qty': ordered_qty,
                                    'logistics_msk': log_msk, 'logistics_rostov': log_rostov, 'deliveries': deliveries})

with open('code/dump/parsed_shipment.json', 'w', encoding='utf-8') as f:
    json.dump(shipment_items, f, ensure_ascii=False, indent=1)

# aggregate monthly receipts per nomenclature
receipts_monthly = {}
for it in shipment_items:
    nom = it['nomenclature']
    for d in it['deliveries']:
        month = d['date'][:7]
        receipts_monthly.setdefault(nom, {}).setdefault(month, 0)
        receipts_monthly[nom][month] += d['qty']

print('SHIPMENT: items=', len(shipment_items), 'unique_nom=', len(set(i['nomenclature'] for i in shipment_items)))

# ---------- 2) PRODUCTION (monthly) ----------
# find sheet with 'Наименования изделий' header, 3-level header structure
prod_result = {}
for sheet_name, content in production.items():
    rows = content['rows']
    header_row_idx = None
    for i, r in enumerate(rows):
        if r and isinstance(r[0], str) and 'Наименования' in r[0]:
            header_row_idx = i
            break
    if header_row_idx is None:
        continue
    # month row is header_row_idx, category row header_row_idx+1 maybe, plan/fact row +2
    month_row = rows[header_row_idx]
    cat_row = rows[header_row_idx+1] if header_row_idx+1 < len(rows) else []
    planfact_row = rows[header_row_idx+2] if header_row_idx+2 < len(rows) else []
    months = {}
    last_month = None
    for idx, v in enumerate(month_row):
        if isinstance(v, str) and v.strip() and idx > 1:
            last_month = v.strip()
        if last_month:
            months.setdefault(last_month, []).append(idx)
    items = []
    for r in rows[header_row_idx+3:]:
        if not r or not r[0] or not isinstance(r[0], str):
            continue
        item = {'name': r[0], 'months': {}}
        for month, idxs in months.items():
            item['months'][month] = {}
            for idx in idxs:
                cat = cat_row[idx] if idx < len(cat_row) else None
                pf = planfact_row[idx] if idx < len(planfact_row) else None
                val = r[idx] if idx < len(r) else None
                if val is not None:
                    key = f"{cat}|{pf}"
                    item['months'][month][key] = val
        items.append(item)
    prod_result[sheet_name] = {'items_count': len(items), 'sample': items[:3], 'months_found': list(months.keys())}

print('PRODUCTION sheets parsed:', {k: v['items_count'] for k, v in prod_result.items()})
for k, v in prod_result.items():
    print(k, 'months:', v['months_found'][:8])

with open('code/dump/parsed_production_debug.json', 'w', encoding='utf-8') as f:
    json.dump(prod_result, f, ensure_ascii=False, indent=1, default=str)

# ---------- 3) DETAILED (daily) ----------
det_result = {}
for sheet_name, content in detailed.items():
    rows = content['rows']
    # find header row with dates
    header_idx = None
    for i, r in enumerate(rows):
        if r and any(isinstance(c, str) and re.match(r'^\d{4}-\d{2}-\d{2}', c) for c in r):
            header_idx = i
            break
    if header_idx is None:
        continue
    header = rows[header_idx]
    date_cols = [(idx, c[:10]) for idx, c in enumerate(header) if isinstance(c, str) and re.match(r'^\d{4}-\d{2}-\d{2}', c)]
    stage_rows = []
    for r in rows[header_idx+1:]:
        if not r:
            continue
        row_label = None
        for c in r[:3]:
            if isinstance(c, str):
                row_label = c
                break
        stage_rows.append({'label': row_label, 'raw': r[:6]})
    det_result[sheet_name] = {'date_cols': date_cols[:10], 'n_date_cols': len(date_cols), 'stage_rows_sample': stage_rows[:15]}

print('DETAILED sheets:', {k: v['n_date_cols'] for k, v in det_result.items()})
with open('code/dump/parsed_detailed_debug.json', 'w', encoding='utf-8') as f:
    json.dump(det_result, f, ensure_ascii=False, indent=1, default=str)

# ---------- 4) CUSTOMS / Реестр Заказов ----------
cust_result = {}
for sheet_name, content in customs.items():
    rows = content['rows']
    header = rows[0] if rows else []
    cust_result[sheet_name] = {'header': header[:15], 'n_rows': len(rows)}

print('CUSTOMS sheets:', cust_result)
