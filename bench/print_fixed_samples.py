import json

with open("bench/audit_60_y2_y4_results.json", "r", encoding="utf-8") as f:
    d = json.load(f)

for it in d["records"]:
    eid = it["eval_id"]
    if eid in [8, 12, 14, 21, 23, 28, 32, 37, 38, 42, 44, 57]:
        print(f"#{eid:02d} [{it['category']}]")
        print(f"  HUMAN: {it['human_ja']}")
        print(f"  OCR  : {it['ocr_ja']}")
        print(f"  Old  : {it['old_zh']}")
        print(f"  New  : {it['new_zh']}")
        print("-" * 50)
