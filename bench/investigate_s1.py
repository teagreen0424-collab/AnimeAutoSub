import re
import json
from pathlib import Path

ass_path = Path('ocr_output/test_3min/subtitle.ass')
ja_path = Path('ocr_output/test_3min/japanese.json')
zh_path = Path('ocr_output/test_3min/chinese.json')

with open(ja_path, encoding='utf-8') as f:
    ja_data = json.load(f)
with open(zh_path, encoding='utf-8') as f:
    zh_data = json.load(f)
with open(ass_path, encoding='utf-8') as f:
    ass_lines = f.readlines()

masks = []
for line in ass_lines:
    if line.startswith('Dialogue: 0') and 'Mask' in line:
        parts = line.strip().split(',', 9)
        start, end = parts[1], parts[2]
        m_pos = re.search(r'\\pos\((\d+),(\d+)\)', parts[9])
        m_box = re.search(r'm 0 0 l (\d+) 0 l \1 (\d+) l 0 \2', parts[9])
        if m_pos and m_box:
            x0, y0 = int(m_pos.group(1)), int(m_pos.group(2))
            w, h = int(m_box.group(1)), int(m_box.group(2))
            masks.append({'start': start, 'end': end, 'x0': x0, 'y0': y0, 'w': w, 'h': h, 'area': w*h})

print(f"Total masks: {len(masks)}")
exceeding = [m for m in masks if m['area'] > 120000]
print(f"Exceeding 120,000 px: {len(exceeding)} / {len(masks)}")

for i, m in enumerate(exceeding):
    idx = masks.index(m)
    ja = ja_data[idx] if idx < len(ja_data) else {}
    zh = zh_data[idx] if idx < len(zh_data) else {}
    raw_box = ja.get('box', [])
    raw_w = raw_box[2] - raw_box[0] if len(raw_box) == 4 else 0
    raw_h = raw_box[3] - raw_box[1] if len(raw_box) == 4 else 0
    raw_area = raw_w * raw_h
    print(f"\n--- [Exceeding #{i+1}] Index {idx} ---")
    print(f"Time: {m['start']} -> {m['end']}")
    print(f"Mask Size: {m['w']}x{m['h']} = {m['area']} px (Screen %: {m['area']/(1280*720)*100:.2f}%)")
    print(f"Raw Det Box: {raw_box} (w={raw_w}, h={raw_h}, area={raw_area})")
    print(f"JA: {ja.get('text')}")
    print(f"ZH: {zh.get('zh')}")
