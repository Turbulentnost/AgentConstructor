import json, os

files = {
    'shipment': 'code/dump/ГРАФИК_ОТГРУЗОК_расширенный_2.json',
    'production': 'code/dump/График_производства_1.json',
    'detailed': 'code/dump/детальный.json',
    'customs': 'code/dump/ТАМОЖНЯ.json',
}

for label, path in files.items():
    print('='*20, label, path)
    with open(path, encoding='utf-8') as f:
        data = json.load(f)
    for sheet, content in data.items():
        rows = content['rows']
        print(f'--- sheet: {sheet!r} max_row={content["max_row"]} max_col={content["max_col"]}')
        for r in rows[:6]:
            # trim trailing None
            while r and r[-1] is None:
                r = r[:-1]
            print(r[:15])
        print()
