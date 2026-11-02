import json

with open("bench/decoding_scan_results.json", "r", encoding="utf-8") as f:
    r = json.load(f)

recs = r["sentence_records"]
diff_ab = sum(1 for x in recs if x["config_a_zh"] != x["config_b_zh"])
diff_ac = sum(1 for x in recs if x["config_a_zh"] != x["config_c_zh"])
diff_bc = sum(1 for x in recs if x["config_b_zh"] != x["config_c_zh"])

print(f"Total sentences: {len(recs)}")
print(f"Config A vs Config B differences: {diff_ab} / 60")
print(f"Config A vs Config C differences: {diff_ac} / 60")
print(f"Config B vs Config C differences: {diff_bc} / 60")

print("\n--- Sample differences between configs ---")
count = 0
for x in recs:
    if x["config_a_zh"] != x["config_b_zh"] or x["config_a_zh"] != x["config_c_zh"]:
        print(f"#{x['eval_id']} [{x['category']}] JA: {x['ja']}")
        print(f"  A (T=0.1, top_p=0.3): {x['config_a_zh']}")
        print(f"  B (T=0.3, top_p=0.7): {x['config_b_zh']}")
        print(f"  C (T=0.05, top_p=0.2): {x['config_c_zh']}")
        print("-" * 50)
        count += 1
        if count >= 6:
            break
