import json

with open('work_ko_1080p_ocr/ocr_raw.json', 'r', encoding='utf-8') as f:
    ocr = json.load(f)

print(f"--- OCR Raw Total {len(ocr)} ---")
for idx, o in enumerate(ocr):
    print(f"OCR #{idx:02d}: [{o['start']} - {o['end']}] {o['text']}")
