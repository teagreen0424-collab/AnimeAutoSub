import json

with open("bench/audit_60_final_verified.json", "r", encoding="utf-8") as f:
    items = json.load(f)

md_lines = []
md_lines.append("| ID | 时间段 | 类别 | 人类可读日文原句 (Human Truth) | OCR 原始输出 (Raw OCR) | 中文译文 (Sakura-14B) | 5 维打分预留栏 (术语/自然/腔调/语气/错译) | 误差归因 |")
md_lines.append("| :---: | :---: | :---: | :--- | :--- | :--- | :---: | :---: |")

for it in items:
    eid = f"{it['eval_id']:02d}"
    t = f"{it['start']:.2f}-{it['end']:.2f}s"
    cat = it["category"]
    h_ja = it["human_ja"].replace("|", "/")
    o_ja = it["ocr_ja"].replace("|", "/")
    zh = it["zh"].replace("|", "/")
    
    # Simple attribution baseline hint
    if h_ja != o_ja and zh:
        attrib = "OCR微瑕 / 翻译跟读"
    elif "我柔井" in zh or "单①" in zh:
        attrib = "大模型上下文污染"
    else:
        attrib = "待PO打分"
        
    line = f"| **{eid}** | {t} | {cat} | {h_ja} | {o_ja} | {zh} | [ 5 / 5 / 5 / 5 / 5 ] | {attrib} |"
    md_lines.append(line)

with open("bench/eval_60_table.md", "w", encoding="utf-8") as f:
    f.write("\n".join(md_lines))

print(f"Generated {len(items)} rows markdown table -> bench/eval_60_table.md")
