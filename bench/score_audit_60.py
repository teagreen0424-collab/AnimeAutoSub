import json
import os

if not os.path.exists("bench/audit_60_z_results.json"):
    print("audit_60_z_results.json not found yet.")
    exit(0)

with open("bench/audit_60_z_results.json", "r", encoding="utf-8") as f:
    data = json.load(f)

records = data.get("records", [])
print(f"Loaded {len(records)} records.")

# 检查 #15, #33, #34
for r in records:
    eid = r["eval_id"]
    if eid in [15, 33, 34]:
        print(f"#{eid:02d}: {r['cleaned_ja']} -> {r['new_zh']}")
