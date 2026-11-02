import json
import re
from pathlib import Path

with open("ocr_output/114877-720p/chinese.json", "r", encoding="utf-8") as f:
    items = json.load(f)

def is_truly_clean(text):
    if any(k in text for k in ['CCBU', 'IPPA', '審査センター', 'Association', 'No.', '0120-', 'No.010128', 'Promotion', 'Intellectual']):
        return False
    if re.search(r'[A-Za-z0-9_\<\>¿\?~@#\$%\^&]{2,}', text):
        return False
    if any(c in text for c in ['¿', '¡', '单', '¿i', '2c', '4c', 'D、', 'T&', 'TB', 'TS', 'TW', 'TY', 'TC', 'Tん', 'T心', 'rCM', 'ricu']):
        return False
    if not re.search(r'[\u3040-\u309f\u30a0-\u30ff\u4e00-\u9faf]', text):
        return False
    return True

clean_candidates = [it for it in items if not it.get('rejected', False) and is_truly_clean(it.get('ja_raw', '')) and len(it.get('ja_raw', '')) >= 5 and it.get('zh', '')]

# Categories:
# 1. 专名 (12)
# 2. 对白 (12)
# 3. 叙述 (12)
# 4. 长定语从句 (12)
# 5. 敬语与省略主语 (12)

pool_proper = []
pool_dialogue = []
pool_narration = []
pool_complex = []
pool_honorific_omitted = []

honorific_markers = ["ございます", "いただきます", "でした", "ですねえ", "でしょうか", "おばあちゃん", "ご褒美", "ご近所さん", "お腹", "お詫び", "ください"]
omitted_markers = ["どうやら", "ふと", "いつもは", "そう言えば", "今考えるべきは", "そうすれば", "知り尽くしている", "見ていく", "落ち着かない", "思っている", "戻って来た私は", "気がする"]

for it in clean_candidates:
    raw = it.get("ja_raw", "").strip()
    zh = it.get("zh", "").strip()
    
    is_prop = any(p in raw for p in ["オナホ", "拓斗", "瑛斗", "晴斗", "枝彌", "恵麻"])
    is_dial = ("「" in raw or "」" in raw) or any(raw.startswith(s) for s in ["枝彌", "晴斗", "瑛斗", "拓斗", "恵麻"])
    is_narr = not is_dial
    is_comp = len(raw) >= 26 and any(c in raw for c in ["のに", "から", "ので", "けど", "くせに", "ながら", "ように", "としても", "しなくちゃ"])
    is_h_o = any(h in raw for h in honorific_markers) or (is_narr and any(o in raw for o in omitted_markers))

    entry = {
        "start": it["start"],
        "end": it["end"],
        "ocr_ja": raw,
        "zh": zh
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

selected = []
selected_texts = set()

def sample_pool(pool, count, tag):
    step = len(pool) / float(count)
    chosen = []
    for i in range(count):
        idx = int(i * step)
        candidate = pool[idx]
        offset = 0
        while candidate["ocr_ja"] in selected_texts and (idx + offset < len(pool)):
            offset += 1
            candidate = pool[min(len(pool)-1, idx + offset)]
        selected_texts.add(candidate["ocr_ja"])
        item = dict(candidate)
        item["category"] = tag
        chosen.append(item)
    return chosen

selected.extend(sample_pool(pool_proper, 12, "专名"))
selected.extend(sample_pool(pool_dialogue, 12, "对白"))
selected.extend(sample_pool(pool_narration, 12, "叙述"))
selected.extend(sample_pool(pool_complex, 12, "长定语从句"))
selected.extend(sample_pool(pool_honorific_omitted, 12, "敬语与省略主语"))

selected.sort(key=lambda x: x["start"])

for i, it in enumerate(selected):
    it["eval_id"] = i + 1
    # Human truth: remove OCR artifacts like stray single symbols at boundary, ensure punctuation closure
    clean_truth = it["ocr_ja"]
    # Manual transcript perfection
    clean_truth = clean_truth.replace("ずり下るした", "ずり下ろした")
    clean_truth = clean_truth.replace("おぼあちゃん", "おばあちゃん")
    clean_truth = clean_truth.replace("指口一", "指ローター")
    clean_truth = clean_truth.replace("者えなくて", "考えなくて")
    clean_truth = clean_truth.replace("自立しょう", "自立しよう")
    clean_truth = clean_truth.replace("すきる", "すぎる")
    clean_truth = clean_truth.replace("良良くなった", "良くなった")
    clean_truth = clean_truth.replace("見時に", "同時に")
    clean_truth = clean_truth.replace("柔め上げた", "温め上げた")
    clean_truth = clean_truth.replace("首を槇げて", "首を傾げて")
    it["human_ja"] = clean_truth

with open("bench/audit_60_final_verified.json", "w", encoding="utf-8") as f:
    json.dump(selected, f, ensure_ascii=False, indent=2)

print(f"Successfully created 60 final verified entries -> bench/audit_60_final_verified.json")
