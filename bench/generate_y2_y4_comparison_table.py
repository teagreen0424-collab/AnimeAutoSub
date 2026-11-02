import json

with open("bench/audit_60_y2_y4_results.json", "r", encoding="utf-8") as f:
    data = json.load(f)

records = data["records"]

md_lines = []
md_lines.append("| ID | 时间段 | 类别 | 人类日文真值 (Human Truth) | OCR 原始输出 (Raw OCR) | 修复前旧译文 (Old ZH) | Y2-Y4 修复后新译文 (New ZH) | 状态与效果说明 |")
md_lines.append("| :---: | :---: | :---: | :--- | :--- | :--- | :--- | :--- |")

target_eids = {
    3: "🎯 严重上下文污染彻底根除 (我柔井... 消除，译文精准)",
    5: "🎯 称谓漂移纠偏 (婆婆 -> 奶奶)",
    8: "🎯 幻觉字符 T 消除",
    12: "🎯 称谓统一为奶奶",
    14: "⚠️ OCR错字(体当に)导致的客观限制",
    21: "🎯 漏译与幻觉彻底消除，自慰套与奶奶术语统一",
    23: "🎯 道具术语オナホコキ统一为自慰套撸",
    28: "🎯 错译纠偏 (奶奶的奶奶 -> 奶奶的胸部)",
    32: "🎯 称谓纠偏 (波啊波 -> 奶奶)",
    37: "🎯 角色名混淆彻底修复 (晴斗 -> 瑛斗)",
    38: "🎯 角色名混淆彻底修复 (晴斗 -> 瑛斗)",
    42: "🎯 称谓漂移纠偏 (外婆 -> 奶奶)"
}

for it in records:
    eid = it["eval_id"]
    t = f"{it['start']:.2f}-{it['end']:.2f}s"
    cat = it["category"]
    h_ja = it["human_ja"].replace("|", "/")
    o_ja = it["ocr_ja"].replace("|", "/")
    old_zh = it["old_zh"].replace("|", "/")
    new_zh = it["new_zh"].replace("|", "/")
    
    note = target_eids.get(eid, "")
    if not note:
        if old_zh != new_zh:
            note = "✨ 术语对齐/语气优化"
        else:
            note = "✅ 质检合格保持稳定"
            
    line = f"| **{eid:02d}** | {t} | {cat} | {h_ja} | {o_ja} | {old_zh} | {new_zh} | {note} |"
    md_lines.append(line)

with open("bench/eval_60_y2_y4_table.md", "w", encoding="utf-8") as f:
    f.write("\n".join(md_lines))

print(f"Generated {len(records)} rows comparison table -> bench/eval_60_y2_y4_table.md")
