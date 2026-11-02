import requests
import json

# 15 在 60 句评测集中的前序 context 是什么？
# 让我们加载 audit_60_final_verified.json 中的前 15 句
with open("bench/audit_60_final_verified.json", "r", encoding="utf-8") as f:
    eval_set = json.load(f)

item15 = eval_set[14]
print("Item 15:", item15)

# 我们看一下在 rerun_60_eval_with_y2_y4 运行时，当时累积到 #15 的 context 是什么
with open("bench/audit_60_y2_y4_results.json", "r", encoding="utf-8") as f:
    res = json.load(f)

prev_items = [r for r in res.get("records", []) if r["eval_id"] < 15]
print(f"Prev items count: {len(prev_items)}")

raw_ocr15 = item15["ocr_ja"]

def test_15_prompt(desc, sys_p, ctx_pairs, prompt_style, text_to_trans):
    messages = [{"role": "system", "content": sys_p}]
    for c_ja, c_zh in ctx_pairs[-5:]:
        messages.append({"role": "user", "content": f"将下面的日文文本翻译成中文：{c_ja}"})
        messages.append({"role": "assistant", "content": c_zh})
    
    if prompt_style == "y4_dict":
        user_p = (
            "根据以下术语表（可以为空）：\n"
            "枝彌->枝弥 #角色名，奶奶\n"
            "拓斗->拓斗 #角色名，三男\n"
            "おばあちゃん->奶奶 #称谓，固定翻译为奶奶，禁止使用婆婆或外婆\n"
            "将下面的日文文本根据对应关系和备注翻译成中文：\n"
            + text_to_trans
        )
    elif prompt_style == "official_dict":
        user_p = (
            "根据以下字典翻译：\n"
            "枝彌->枝弥\n"
            "拓斗->拓斗\n"
            "おばあちゃん->奶奶\n"
            "将下面的日文文本翻译成中文："
            + text_to_trans
        )
    elif prompt_style == "no_dict":
        user_p = f"将下面的日文文本翻译成中文：{text_to_trans}"
    
    messages.append({"role": "user", "content": user_p})

    payload = {
        "model": "sakura-14b",
        "messages": messages,
        "temperature": 0.1,
        "top_p": 0.3,
        "stream": False,
        "options": {"num_predict": 512, "repeat_penalty": 1.10}
    }
    resp = requests.post("http://127.0.0.1:11434/v1/chat/completions", json=payload, timeout=30)
    out = resp.json()["choices"][0]["message"]["content"].strip()
    print(f"[{desc}] -> {out}")

# 测试 A: 原始 Y4 跑法 (带有 '誰がに')
test_15_prompt("A: Y4 dict + raw_ocr (誰がに)", 
               "你是一个轻小说翻译模型，可以流畅通顺地以日本轻小说的风格将日文翻译成简体中文，并联系上下文正确使用人称代词，不擅自添加原文中没有的代词。",
               [(r["ocr_ja"], r["new_zh"]) for r in prev_items if "□" not in r["new_zh"]],
               "y4_dict",
               raw_ocr15)

# 测试 B: Sakura 官方词典 + raw_ocr (誰がに)
test_15_prompt("B: Official dict + raw_ocr (誰がに)", 
               "你是一个轻小说翻译模型，可以流畅通顺地以日本轻小说的风格将日文翻译成简体中文，并联系上下文正确使用人称代词，不擅自添加原文中没有的代词。",
               [(r["ocr_ja"], r["new_zh"]) for r in prev_items if "□" not in r["new_zh"]],
               "official_dict",
               raw_ocr15)

# 测试 C: 修正 OCR 浊点误识 (誰がに -> 誰かに) + Sakura 官方词典
fixed_ocr15 = raw_ocr15.replace("誰がに", "誰かに")
test_15_prompt("C: Official dict + fixed_ocr (誰かに)", 
               "你是一个轻小说翻译模型，可以流畅通顺地以日本轻小说的风格将日文翻译成简体中文，并联系上下文正确使用人称代词，不擅自添加原文中没有的代词。",
               [(r["ocr_ja"], r["new_zh"]) for r in prev_items if "□" not in r["new_zh"]],
               "official_dict",
               fixed_ocr15)

# 测试 D: 无字典 + raw_ocr (誰がに)
test_15_prompt("D: No dict + raw_ocr (誰がに)", 
               "你是一个轻小说翻译模型，可以流畅通顺地以日本轻小说的风格将日文翻译成简体中文，并联系上下文正确使用人称代词，不擅自添加原文中没有的代词。",
               [(r["ocr_ja"], r["new_zh"]) for r in prev_items if "□" not in r["new_zh"]],
               "no_dict",
               raw_ocr15)
