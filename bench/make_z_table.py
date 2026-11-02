import json

with open("bench/audit_60_scored_final.json", "r", encoding="utf-8") as f:
    data = json.load(f)

records = data["records"]

md_lines = []
md_lines.append("# 全 60 句质量审计打分与修复明细表 (统一全量口径)\n")
md_lines.append(f"**评测汇总**: 总句数 60 | **可用率 (5+4分)**: **{data['usable_pct']}%** (55/60) | **不可用率 (1-2分)**: **{data['unusable_pct']}%** (4/60) | **边际率 (3分)**: **{data['marginal_pct']}%** (1/60)\n")
md_lines.append("| ID | 分类 | 日文真值 (Human) / OCR 提取 | 旧版译文 (Baseline 7B) | 新版译文 (Sakura 14B + Z修复) | 得分 | 评级与判定理由 |")
md_lines.append("|:---:|:---:|:---|:---|:---|:---:|:---|")

for r in records:
    eid = r["eval_id"]
    cat = r["category"]
    human = r["human_ja"]
    ocr = r["ocr_ja"]
    old = r["old_zh"]
    new = r["new_zh"]
    score = r["score"]
    reason = r["reason"]
    
    # 格式化
    score_tag = f"**{score}分**"
    if score >= 4:
        score_tag = f"🟢 **{score}分**"
    elif score == 3:
        score_tag = f"🟡 **{score}分**"
    else:
        score_tag = f"🔴 **{score}分**"
        
    ja_cell = f"**真值**: {human}<br>**OCR**: {ocr}"
    
    # 转义 markdown 管道符
    old_clean = old.replace("|", "\\|")
    new_clean = new.replace("|", "\\|")
    ja_cell = ja_cell.replace("|", "\\|")
    
    md_lines.append(f"| #{eid:02d} | {cat} | {ja_cell} | {old_clean} | {new_clean} | {score_tag} | {reason} |")

with open("bench/eval_60_z_table.md", "w", encoding="utf-8") as f:
    f.write("\n".join(md_lines))

print("Saved table to bench/eval_60_z_table.md")
