import json

with open("ocr_output/114877-720p_old_1031_backup/japanese.json", "r", encoding="utf-8") as f:
    old_ja = json.load(f)
with open("ocr_output/114877-720p/japanese.json", "r", encoding="utf-8") as f:
    new_ja = json.load(f)

old_to_new = {}
for i, n in enumerate(new_ja):
    for j, o in enumerate(old_ja):
        inter = max(0, min(n["end"], o["end"]) - max(n["start"], o["start"]))
        if inter > 0.3:
            old_to_new.setdefault(j, []).append((i, n))

splits_old = {j: news for j, news in old_to_new.items() if len(news) > 1}
print(f"Total old segments split into >=2 new segments: {len(splits_old)}")

for count, (j, news) in enumerate(list(splits_old.items())[:8]):
    o = old_ja[j]
    print(f"\n--- Case {count+1} ---")
    print(f"Old [{o['start']:.2f}-{o['end']:.2f}]: {o['text']}")
    for ni, n in news:
        print(f"  New [{n['start']:.2f}-{n['end']:.2f}] (idx {ni}): {n['text']}")
