import json

with open("bench/audit_60_y2_y4_results.json", "r", encoding="utf-8") as f:
    res = json.load(f)

for i in range(29, 36):
    r = res["records"][i]
    print(f"#{r['eval_id']:02d}: JA='{r['ocr_ja']}' -> ZH='{r['new_zh']}'")
