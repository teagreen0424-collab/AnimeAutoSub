import json
from pathlib import Path
from difflib import SequenceMatcher

old_ja_path = Path("ocr_output/114877-720p_old_1031_backup/japanese.json")
new_ja_path = Path("ocr_output/114877-720p/japanese.json")
old_zh_path = Path("ocr_output/114877-720p_old_1031_backup/chinese.json")
new_zh_path = Path("ocr_output/114877-720p/chinese.json")

with open(old_ja_path, "r", encoding="utf-8") as f:
    old_ja = json.load(f)
with open(new_ja_path, "r", encoding="utf-8") as f:
    new_ja = json.load(f)
with open(old_zh_path, "r", encoding="utf-8") as f:
    old_zh = json.load(f)
with open(new_zh_path, "r", encoding="utf-8") as f:
    new_zh = json.load(f)

print(f"Old: {len(old_ja)} ja, {len(old_zh)} zh")
print(f"New: {len(new_ja)} ja, {len(new_zh)} zh")

def get_overlap(s1, e1, s2, e2):
    inter = max(0, min(e1, e2) - max(s1, s2))
    union = max(e1, e2) - min(s1, s2)
    return inter, (inter / union if union > 0 else 0)

# Match each new segment to old segment(s)
new_matches = []
for i, n in enumerate(new_ja):
    n_s, n_e = n["start"], n["end"]
    best_old = []
    for j, o in enumerate(old_ja):
        inter, iou = get_overlap(n_s, n_e, o["start"], o["end"])
        if inter > 0.3: # at least 0.3s overlap
            best_old.append((j, inter, iou))
    new_matches.append({
        "new_idx": i,
        "new_seg": n,
        "new_zh": new_zh[i] if i < len(new_zh) else {},
        "matched_old": best_old
    })

# Classify new segments
purely_new = []
one_to_one = []
one_to_many_new = [] # multiple new match one old
old_matched_counts = {j: 0 for j in range(len(old_ja))}

for m in new_matches:
    matched = m["matched_old"]
    if not matched:
        purely_new.append(m)
    elif len(matched) == 1:
        old_idx = matched[0][0]
        old_matched_counts[old_idx] += 1
    else:
        # overlaps with multiple old segments
        for o in matched:
            old_matched_counts[o[0]] += 1

splits = []
for m in new_matches:
    matched = m["matched_old"]
    if len(matched) == 1:
        old_idx = matched[0][0]
        if old_matched_counts[old_idx] > 1:
            splits.append((m, old_idx))
        else:
            one_to_one.append((m, old_idx))

print(f"Classification of 839 new segments:")
print(f"  1-to-1 matched: {len(one_to_one)}")
print(f"  Purely new detected segments (no old overlap): {len(purely_new)}")
print(f"  Split segments (part of multi-new to 1-old): {len(splits)}")

# Analyze purely new segments
print("\nSample purely new detected segments:")
purely_new_samples = []
for m in purely_new[:10]:
    n = m["new_seg"]
    purely_new_samples.append({
        "time": f"{n['start']:.2f}-{n['end']:.2f}",
        "ja": n["text"],
        "zh": m["new_zh"].get("zh", "")
    })
    print(f"  [{n['start']:.2f}-{n['end']:.2f}] JA: {n['text']} -> ZH: {m['new_zh'].get('zh', '')}")

# Sample 20 representative comparisons across the video
sample_indices = [
    0, 10, 30, 50, 80, 120, 180, 240, 300, 360,
    420, 480, 540, 600, 660, 720, 760, 800, 820, 835
]

sample_20_comparisons = []
for idx in sample_indices:
    if idx < len(new_matches):
        m = new_matches[idx]
        n_seg = m["new_seg"]
        n_zh = m["new_zh"].get("zh", "")
        
        matched_old = m["matched_old"]
        if matched_old:
            best_old_idx = max(matched_old, key=lambda x: x[1])[0]
            o_seg = old_ja[best_old_idx]
            o_zh = old_zh[best_old_idx].get("zh", "")
        else:
            o_seg = {"start": 0, "end": 0, "text": "(None - 新增检出)"}
            o_zh = "(None - 新增检出)"
        
        sample_20_comparisons.append({
            "new_idx": idx,
            "time_range": f"{n_seg['start']:.2f}s - {n_seg['end']:.2f}s",
            "old_ja": o_seg.get("text", ""),
            "new_ja": n_seg.get("text", ""),
            "old_zh": o_zh,
            "new_zh": n_zh,
            "status": "improved/clean" if " " in o_seg.get("text", "") and " " not in n_seg.get("text", "") else "normal"
        })

report = {
    "total_old": len(old_ja),
    "total_new": len(new_ja),
    "diff_count": len(new_ja) - len(old_ja),
    "one_to_one_count": len(one_to_one),
    "purely_new_count": len(purely_new),
    "split_count": len(splits),
    "sample_purely_new": purely_new_samples,
    "sample_20_comparisons": sample_20_comparisons
}

with open("bench/w2_analysis_report.json", "w", encoding="utf-8") as f:
    json.dump(report, f, ensure_ascii=False, indent=2)

print("\nReport saved to bench/w2_analysis_report.json")
