import json

with open("bench/audit_60_y2_y4_results.json", "r", encoding="utf-8") as f:
    data = json.load(f)

items = data.get("records", [])

for item in items:
    eid = item["eval_id"]
    if eid in [15, 33, 34]:
        print(f"=== #{eid} ===")
        print("human_ja:", item["human_ja"])
        print("ocr_ja:  ", item["ocr_ja"])
        print("old_zh:  ", item["old_zh"])
        print("new_zh:  ", item["new_zh"])
