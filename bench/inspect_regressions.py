import json

with open("bench/audit_60_y2_y4_results.json", "r", encoding="utf-8") as f:
    data = json.load(f)

records = data.get("records", [])

regressions = []
improvements = []
equals = []

# PO 指出的退化：#15 (语义反转)、#34 (重复上一句译文)
# 我们仔细看看其他句子：
for r in records:
    eid = r["eval_id"]
    old = r["old_zh"]
    new = r["new_zh"]
    human = r["human_ja"]
    ocr = r["ocr_ja"]
    
    # 特别检查 #16:
    # Human: でもご褒美をと言いたいところだけど、今はまだ焦らしている。 (虽然很想说给你奖励，但现在还在吊他胃口)
    # Old: 虽然我想说要给他奖励，但现在还不能急。
    # New: 虽然很想说这是奖励，但现在还不能让她着急。 (焦らしている: 吊胃口/拖延，她/他省略)
    
    # 检查 #45:
    # Human: 自分が眠っているのか、起きているのかはまだあやふやで……
    # OCR:   息分が眠っているのか、起きているのかはまだあやふやで… (自分被识别成 息分)
    # Old:   我还没弄清楚自己是睡着了还是醒着… (Old猜对了 息分 -> 我)
    # New:   呼吸的频率是睡着了还是醒着了，还很模糊…… (New把息分按字面当成呼吸了)
    
    # 检查 #53:
    # Human: 晴斗「たぶん、俺が一番頑張ってると思うんだ。だから、うん」
    # OCR:   晴斗たぶん、俺が一番頑張ってると思うんだ。だから、うん」
    # Old:   晴斗我觉得，我应该是最努力的。所以，嗯
    # New:   晴斗大概，觉得我最努力了。所以，嗯」
    
    print(f"#{eid:02d}: old='{old}' | new='{new}'")
