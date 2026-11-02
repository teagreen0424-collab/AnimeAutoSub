import json
import re
from pathlib import Path

zh_path = Path("ocr_output/114877-720p/chinese.json")
with open(zh_path, "r", encoding="utf-8") as f:
    items = json.load(f)

# Categories
# 1. 含专名 (Proper names: 枝彌, 晴斗, 瑛斗, 拓斗, 恵麻, オナホ, IPPA, CCBU)
# 2. 对白 (Dialogue: speaker tags or opening quotes)
# 3. 叙述 (Narration: first-person/third-person monologue, no quotes, no speaker)
# 4. 长句 (Long sentences: len(ja) >= 30)
# 5. 短句 (Short sentences: 3 <= len(ja) <= 10)

proper_names = ["枝彌", "晴斗", "瑛斗", "拓斗", "恵麻", "オナホ", "IPPA", "CCBU"]

pool_proper = []
pool_dialogue = []
pool_narration = []
pool_long = []
pool_short = []

for idx, it in enumerate(items):
    if it.get("rejected", False):
        continue
    ja = it.get("ja", "").strip()
    zh = it.get("zh", "").strip()
    if not ja or not zh:
        continue
    
    # Classify
    is_prop = any(p in ja for p in ["オナホ", "IPPA", "CCBU", "拓斗", "瑛斗", "晴斗", "枝彌", "恵麻"])
    is_dial = ("「" in ja or "」" in ja)
    is_narr = not is_dial and not any(s in ja[:5] for s in ["枝彌", "晴斗", "瑛斗", "拓斗", "恵麻"])
    is_long = len(ja) >= 30
    is_short = 3 <= len(ja) <= 10

    item_dict = {
        "full_idx": idx,
        "start": it["start"],
        "end": it["end"],
        "ja_raw": it.get("ja_raw", ja),
        "ja": ja,
        "zh_baseline": zh,
        "box": it.get("box", [])
    }

    if is_prop:
        pool_proper.append(item_dict)
    if is_dial:
        pool_dialogue.append(item_dict)
    if is_narr:
        pool_narration.append(item_dict)
    if is_long:
        pool_long.append(item_dict)
    if is_short:
        pool_short.append(item_dict)

print(f"Pool sizes: Proper={len(pool_proper)}, Dialogue={len(pool_dialogue)}, Narration={len(pool_narration)}, Long={len(pool_long)}, Short={len(pool_short)}")

selected = []
selected_indices = set()

def sample_from_pool(pool, count, tag):
    step = len(pool) / float(count)
    chosen = []
    for i in range(count):
        idx = int(i * step)
        candidate = pool[idx]
        offset = 0
        while candidate["full_idx"] in selected_indices and (idx + offset < len(pool)):
            offset += 1
            candidate = pool[min(len(pool)-1, idx + offset)]
        selected_indices.add(candidate["full_idx"])
        item = dict(candidate)
        item["category"] = tag
        chosen.append(item)
    return chosen

selected.extend(sample_from_pool(pool_proper, 12, "含专名"))
selected.extend(sample_from_pool(pool_dialogue, 12, "对白"))
selected.extend(sample_from_pool(pool_narration, 12, "叙述"))
selected.extend(sample_from_pool(pool_long, 12, "长句"))
selected.extend(sample_from_pool(pool_short, 12, "短句"))

# Sort by timestamp
selected.sort(key=lambda x: x["start"])

# Re-index 1..60
for i, item in enumerate(selected):
    item["eval_id"] = i + 1

output_path = Path("bench/audit_60_sentences.json")
with open(output_path, "w", encoding="utf-8") as f:
    json.dump(selected, f, ensure_ascii=False, indent=2)

print(f"Successfully selected {len(selected)} sentences across 5 categories -> {output_path}")
