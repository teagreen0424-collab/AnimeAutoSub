import json

with open("bench/audit_60_y2_y4_results.json", "r", encoding="utf-8") as f:
    data = json.load(f)

records = data.get("records", [])

print(f"Total records: {len(records)}")

for r in records:
    eid = r["eval_id"]
    old_zh = r["old_zh"]
    new_zh = r["new_zh"]
    human_ja = r["human_ja"]
    ocr_ja = r["ocr_ja"]
    cat = r["category"]
    
    # Check differences
    if old_zh != new_zh:
        print(f"--- #{eid:02d} [{cat}] ---")
        print(f"Human: {human_ja}")
        print(f"OCR  : {ocr_ja}")
        print(f"Old  : {old_zh}")
        print(f"New  : {new_zh}")
