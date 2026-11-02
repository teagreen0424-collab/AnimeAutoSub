import re
import json

with open('ocr_output/test_3min/subtitle.ass', 'r', encoding='utf-8') as f:
    lines = f.readlines()

masks = []
dialogues = []

mask_re = re.compile(r'Dialogue: 0,([^,]+),([^,]+),Mask,.*pos\((\d+),(\d+)\).*m 0 0 l (\d+) 0 l \5 (\d+) l 0 \6')
text_re = re.compile(r'Dialogue: 1,([^,]+),([^,]+),Default,.*\}\s*(.*)')

cur_mask = None
for l in lines:
    m = mask_re.search(l)
    if m:
        cur_mask = {
            'start': m.group(1),
            'end': m.group(2),
            'x': int(m.group(3)),
            'y': int(m.group(4)),
            'w': int(m.group(5)),
            'h': int(m.group(6)),
            'area': int(m.group(5)) * int(m.group(6)),
            'area_pct': round(int(m.group(5)) * int(m.group(6)) / (1280 * 720) * 100, 2)
        }
    t = text_re.search(l)
    if t and cur_mask:
        cur_mask['text'] = t.group(3)
        cur_mask['is_double'] = (r'\N' in t.group(3))
        masks.append(cur_mask)
        cur_mask = None

print(f"Total masks: {len(masks)}")
max_area = max(m['area'] for m in masks)
max_pct = max(m['area_pct'] for m in masks)
mean_area = sum(m['area'] for m in masks) / len(masks)
mean_pct = sum(m['area_pct'] for m in masks) / len(masks)
print(f"Max area: {max_area} px ({max_pct}%), Mean area: {mean_area:.1f} px ({mean_pct:.2f}%)")

over_limit = []
details = []
for idx, m in enumerate(masks):
    limit = 15.0 if m['is_double'] else 8.5
    exceeded = (m['area_pct'] > limit) or (m['area_pct'] > 16.0)
    item = {
        "idx": idx + 1,
        "start": m['start'],
        "end": m['end'],
        "w": m['w'],
        "h": m['h'],
        "area": m['area'],
        "area_pct": m['area_pct'],
        "limit_pct": limit,
        "is_double": m['is_double'],
        "exceeded": exceeded,
        "text": m['text']
    }
    details.append(item)
    if exceeded:
        over_limit.append(item)

with open('ocr_output/test_3min/mask_proportion_audit.json', 'w', encoding='utf-8') as f:
    json.dump({
        "total_masks": len(masks),
        "max_area": max_area,
        "max_pct": max_pct,
        "mean_area": round(mean_area, 1),
        "mean_pct": round(mean_pct, 2),
        "over_limit_count": len(over_limit),
        "over_limit_items": over_limit,
        "all_items": details
    }, f, ensure_ascii=False, indent=2)

print(f"Over limit count: {len(over_limit)}")
for item in over_limit:
    print(f"  [OVER] #{item['idx']} ({item['start']}~{item['end']}) {item['w']}x{item['h']}={item['area']} ({item['area_pct']}%, limit: {item['limit_pct']}%) text: {item['text'][:25]}")
