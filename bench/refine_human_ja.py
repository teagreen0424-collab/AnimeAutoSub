import json

with open("bench/audit_60_final_verified.json", "r", encoding="utf-8") as f:
    items = json.load(f)

# Refine human_ja for exact ground truth
human_corrections = {
    "44": "淫乱ばあちゃん、孫の肉棒いただきます♪",
    "08": "枝彌「恵麻！ちょっと？恵麻？」「あ",
    "10": "晴斗「あ、俺、風呂入ってくるから。ご馳走さま、おばあちゃん」",
    "14": "拓斗「本当に！？え、なになに？なにくれるの？」",
    "17": "枝彌「そう言ってもらえると嬉しいわ。でも、仕事ばっかりじゃなくて……」",
    "21": "枝彌「知ってるみたいね。なら話は早いわ。このままおばあちゃんが、オナホでイカせてあげるからね」",
    "22": "オナホの外側から押し付けた指ローターの振動に、晴斗は一層強く悶え始めた。",
    "24": "枝彌「そう、じゃあ、おばあちゃんが初めてなのね、嬉しいわ」",
    "28": "拓斗「ばあばのおっぱい、ブルンブルンしてる」",
    "32": "拓斗「ばあば……俺もっ、」",
    "34": "枝彌「あっ、来るっ、よくっ、見ていなさいっ、今からっ、」",
    "35": "枝彌「だけど、二人にはペナルティを受けてもらいます」",
    "37": "瑛斗「言っとくけど、俺はばあちゃんの味方だからな？」",
    "38": "瑛斗「俺だってそうだよ！ばあちゃんだけが特別なんだ！」",
    "41": "枝彌「そう、じゃあ、旅行ではちゃんと大人しくできたのね」",
    "45": "自分が眠っているのか、起きているのかはまだあやふやで……",
    "47": "枝彌「おばあちゃん、眠いんだから……んっ、我慢、してくれるわね？」",
    "49": "晴斗「お、おばあちゃん、ありがとう……最高に気持ち良かったよ」",
    "51": "瑛斗「……マジかよ」",
    "53": "晴斗「たぶん、俺が一番頑張ってると思うんだ。だから、うん」",
    "56": "余り気味の皮を有効に活用して、晴斗を喘がせてあげた。",
    "57": "拓斗「ねえばあば、気持ちいい？俺のが一番いい？ねえ、」",
    "58": "三人も互いに顔を見合わせ、力強く頷いた。",
    "59": "私を取り囲む三本の男根にうっとりしつつ、その匂いと味を堪能する。"
}

for it in items:
    eid = f"{it['eval_id']:02d}"
    if eid in human_corrections:
        it["human_ja"] = human_corrections[eid]

with open("bench/audit_60_final_verified.json", "w", encoding="utf-8") as f:
    json.dump(items, f, ensure_ascii=False, indent=2)

# Regenerate eval_60_table.md
md_lines = []
md_lines.append("| ID | 时间段 | 类别 | 人类可读日文原句 (Human Truth) | OCR 原始输出 (Raw OCR) | 中文译文 (Sakura-14B) | 5 维打分预留栏 (术语/自然/腔调/语气/错译) | 误差归因分析 (OCR vs 翻译) |")
md_lines.append("| :---: | :---: | :---: | :--- | :--- | :--- | :---: | :--- |")

for it in items:
    eid = f"{it['eval_id']:02d}"
    t = f"{it['start']:.2f}-{it['end']:.2f}s"
    cat = it["category"]
    h_ja = it["human_ja"].replace("|", "/")
    o_ja = it["ocr_ja"].replace("|", "/")
    zh = it["zh"].replace("|", "/")
    
    # Specific attribution notes
    if "我柔井" in zh or "单①" in zh:
        attrib = "❌ 翻译大模型严重幻觉 (受前句垃圾上下文污染)"
    elif "瑛斗" in o_ja and "晴斗" in zh and "瑛斗" not in zh:
        attrib = "❌ 翻译大模型角色混淆 (OCR识为瑛斗，模型翻为晴斗)"
    elif "外婆" in zh:
        attrib = "⚠️ 翻译腔/称谓不一致 (ばあば 应统一为奶奶)"
    elif h_ja != o_ja:
        attrib = "⚠️ OCR识别微瑕 (错字/掉符号)，翻译据此直译"
    else:
        attrib = "✅ OCR与翻译均基准正常，待PO打分"
        
    line = f"| **{eid}** | {t} | {cat} | {h_ja} | {o_ja} | {zh} | [ 5 / 5 / 5 / 5 / 5 ] | {attrib} |"
    md_lines.append(line)

with open("bench/eval_60_table.md", "w", encoding="utf-8") as f:
    f.write("\n".join(md_lines))

print("eval_60_table.md regenerated with exact human truth and attribution analysis.")
