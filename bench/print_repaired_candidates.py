import json

with open("bench/audit_60_repaired_raw.json", "r", encoding="utf-8") as f:
    items = json.load(f)

for it in items:
    print(f"#{it['eval_id']:02d} [{it['category']}] ({it['start']:.2f}s - {it['end']:.2f}s)")
    print(f"  OCR: {it['ocr_ja']}")
    print(f"  ZH : {it['zh']}")
