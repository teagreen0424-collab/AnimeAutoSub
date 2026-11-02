import json

with open("ocr_output/114877-720p_old_1031_backup/japanese.json", "r", encoding="utf-8") as f:
    old_ja = json.load(f)
with open("ocr_output/114877-720p/japanese.json", "r", encoding="utf-8") as f:
    new_ja = json.load(f)

# Find IoU and overlap
old_to_news = {}
for j, o in enumerate(old_ja):
    matches = []
    for i, n in enumerate(new_ja):
        inter = max(0, min(n["end"], o["end"]) - max(n["start"], o["start"]))
        if inter > 0.3:
            matches.append((i, inter, n))
    old_to_news[j] = matches

new_to_olds = {}
for i, n in enumerate(new_ja):
    matches = []
    for j, o in enumerate(old_ja):
        inter = max(0, min(n["end"], o["end"]) - max(n["start"], o["start"]))
        if inter > 0.3:
            matches.append((j, inter, o))
    new_to_olds[i] = matches

# Categorize all 782 old segments
# 1. Matched to 0 new segments (Old segments dropped/unmatched)
dropped_old = [j for j, m in old_to_news.items() if len(m) == 0]

# 2. Split: Old matched to >= 2 new
split_old = [j for j, m in old_to_news.items() if len(m) >= 2]

# 3. Merged: Multiple old matched to the SAME new segment
# Look at new segments that have >= 2 old segments
merge_groups = {i: m for i, m in new_to_olds.items() if len(m) >= 2}
merged_old_indices = set()
for i, m in merge_groups.items():
    for j, inter, o in m:
        # if this old was only matched to this new segment
        if len(old_to_news[j]) == 1:
            merged_old_indices.add(j)

# 4. Strict 1-to-1: Old matched to 1 new, and that new matched ONLY to this old
strict_1to1_old = [j for j, m in old_to_news.items() if len(m) == 1 and len(new_to_olds[m[0][0]]) == 1]

# 5. Complex overlaps (e.g. partial bridge / multi-to-multi)
accounted = set(dropped_old) | set(split_old) | set(merged_old_indices) | set(strict_1to1_old)
remaining_old = [j for j in range(len(old_ja)) if j not in accounted]

print("=== 782 条旧字幕去向严格对账 ===")
print(f"总计旧字幕数: {len(old_ja)}")
print(f"1. 严格 1-to-1 完全对齐: {len(strict_1to1_old)}")
print(f"2. 1-to-N 拆分 (旧被拆成多句新): {len(split_old)}")
print(f"3. N-to-1 合并 (多个旧合并为 1 句新): {len(merged_old_indices)}")
print(f"4. 0 重叠丢弃 (旧版有，新版无): {len(dropped_old)}")
print(f"5. 复杂交叠/桥接: {len(remaining_old)}")
print(f"总和校验: {len(strict_1to1_old) + len(split_old) + len(merged_old_indices) + len(dropped_old) + len(remaining_old)} / 782")

print("\n--- 4. 详细查看 0 重叠丢弃的 6 句旧字幕 ---")
for j in dropped_old:
    o = old_ja[j]
    print(f"  Old #{j} [{o['start']:.2f}-{o['end']:.2f}s]: '{o['text']}'")

print("\n--- 3. 详细查看 N-to-1 合并的案例 ---")
for i, m in list(merge_groups.items())[:5]:
    n = new_ja[i]
    print(f"  New #{i} [{n['start']:.2f}-{n['end']:.2f}s]: '{n['text']}'")
    for j, inter, o in m:
        print(f"    <- Old #{j} [{o['start']:.2f}-{o['end']:.2f}s]: '{o['text']}'")
