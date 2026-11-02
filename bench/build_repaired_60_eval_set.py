import json
import re
from pathlib import Path

with open("ocr_output/114877-720p/chinese.json", "r", encoding="utf-8") as f:
    items = json.load(f)

# Filter out watermarks and heavy OCR noise
clean_items = []
for idx, it in enumerate(items):
    raw = it.get("ja_raw", "")
    zh = it.get("zh", "")
    if it.get("rejected", False):
        continue
    if any(k in raw for k in ["CCBU", "IPPA", "No.010128", "Association", "0120-", "TYGOL", "rCM", "ricu", "ICIC", "TB3", "T332"]):
        continue
    if len(raw) < 3 or not zh:
        continue
    if re.search(r'[A-Za-z]{3,}|\d{4,}', raw):
        continue
    clean_items.append((idx, it))

print(f"Total clean candidates: {len(clean_items)}")

# 5 Categories:
# 1. 专名 (12): Proper names
# 2. 对白 (12): Spoken dialogue
# 3. 叙述 (12): Narration / Monologue
# 4. 长定语从句 (12): Complex / Long relative clauses (len >= 25)
# 5. 敬语与省略主语 (12): Honorifics and omitted subject sentences

pool_proper = []
pool_dialogue = []
pool_narration = []
pool_complex = []
pool_honorific_omitted = []

honorific_keywords = ["ございます", "いただきます", "でした", "ですねえ", "でしょうか", "おばあちゃん", "ご褒美", "ご近所さん", "お腹", "お詫び"]
omitted_keywords = ["どうやら", "ふと", "いつもは", "そう言えば", "今考えるべきは", "そうすれば", "知り尽くしている", "見ていく", "落ち着かない", "思っている"]

for idx, it in clean_items:
    raw = it.get("ja_raw", "").strip()
    zh = it.get("zh", "").strip()
    
    is_prop = any(p in raw for p in ["オナホ", "拓斗", "瑛斗", "晴斗", "枝彌", "恵麻"])
    is_dial = ("「" in raw or "」" in raw) or any(raw.startswith(s) for s in ["枝彌", "晴斗", "瑛斗", "拓斗", "恵麻"])
    is_narr = not is_dial
    is_comp = len(raw) >= 28 and any(c in raw for c in ["のに", "から", "ので", "けど", "くせに", "ながら", "ように", "としても"])
    is_h_o = any(h in raw for h in honorific_keywords) or (is_narr and any(o in raw for o in omitted_keywords))

    entry = {
        "full_idx": idx,
        "start": it["start"],
        "end": it["end"],
        "ocr_ja": raw,
        "zh": zh,
        "box": it.get("box", [])
    }

    if is_prop:
        pool_proper.append(entry)
    if is_dial:
        pool_dialogue.append(entry)
    if is_narr and not is_comp:
        pool_narration.append(entry)
    if is_comp:
        pool_complex.append(entry)
    if is_h_o:
        pool_honorific_omitted.append(entry)

print(f"Pool sizes: Proper={len(pool_proper)}, Dialogue={len(pool_dialogue)}, Narration={len(pool_narration)}, Complex={len(pool_complex)}, Honorific/Omitted={len(pool_honorific_omitted)}")

selected_indices = set()
def pick_from_pool(pool, count, tag):
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

selected = []
selected.extend(pick_from_pool(pool_proper, 12, "专名"))
selected.extend(pick_from_pool(pool_dialogue, 12, "对白"))
selected.extend(pick_from_pool(pool_narration, 12, "叙述"))
selected.extend(pick_from_pool(pool_complex, 12, "长定语从句"))
selected.extend(pick_from_pool(pool_honorific_omitted, 12, "敬语与省略主语"))

# Sort by start timestamp
selected.sort(key=lambda x: x["start"])

for i, it in enumerate(selected):
    it["eval_id"] = i + 1

with open("bench/audit_60_repaired_raw.json", "w", encoding="utf-8") as f:
    json.dump(selected, f, ensure_ascii=False, indent=2)

print(f"Generated 60 repaired candidates -> bench/audit_60_repaired_raw.json")
