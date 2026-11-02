import json

with open("bench/audit_60_final_verified.json", "r", encoding="utf-8") as f:
    items = json.load(f)

for it in items[:6]:
    print(f"#{it['eval_id']:02d} [{it['category']}] ({it['start']:.2f}s-{it['end']:.2f}s)")
    print(f"  HUMAN: {it['human_ja']}")
    print(f"  OCR  : {it['ocr_ja']}")
    print(f"  ZH   : {it['zh']}")
