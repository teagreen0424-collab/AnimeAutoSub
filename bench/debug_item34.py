import json
import requests
import re
from pathlib import Path

# Load audit 60 sentences
with open("bench/audit_60_final_verified.json", "r", encoding="utf-8") as f:
    eval_set = json.load(f)

# Load Y3 glossary
with open("glossary/anime_production.json", "r", encoding="utf-8") as f:
    glossary_data = json.load(f)
glossary = {k: v for k, v in glossary_data.items() if not k.startswith("_")}

notes = {
    "瑛斗": "角色名，次男，请勿与晴斗混淆",
    "晴斗": "角色名，长男",
    "拓斗": "角色名，三男",
    "枝彌": "角色名，奶奶",
    "枝弥": "角色名，奶奶",
    "恵麻": "角色名，女儿",
    "おばあちゃん": "称谓，固定翻译为奶奶，禁止使用婆婆或外婆",
    "ばあちゃん": "称谓，固定翻译为奶奶",
    "ばあば": "称谓，固定翻译为奶奶，禁止音译为波啊波或外婆",
    "オナホ": "道具名，固定翻译为自慰套，禁止使用飞机杯",
    "オナホコキ": "自慰套撸",
}

system_prompt = (
    "你是一个轻小说翻译模型，可以流畅通顺地以日本轻小说的风格将日文翻译成简体中文，"
    "并联系上下文正确使用人称代词，不擅自添加原文中没有的代词。"
    "遇到 OCR 明显损毁或无法识别的噪点字符（如带有孤立字母数字如 T、2C、片假名混拉丁等），"
    "请用「□」占位或保留原文，严禁胡乱猜测脑补填充。"
)

# Context up to #33:
context_queue = [
    ('枝彌「おばあちゃんのために、ありがとう……さあ好きに味わって」', '枝弥「为了奶奶，谢谢你……来吧，尽情享受吧」'),
    ('リビングに戻って来た私は、テーブルに座った。', '我回到客厅，坐在桌子旁。'),
    ('拓头ぼあぼ……俺もっ、', '拓头奶奶……我也要'),
    ('これがオナニーじゃなく、セックスでで得られていたら最高なのに。', '如果这不是自慰，而是通过性交得到的快感，那就太棒了。')
]

ocr_text = '枝彌あっ来るつ、よくっ、見ていなさいっ、今がらっ、'

matched_glossary = {k: v for k, v in glossary.items() if k in ocr_text}
dict_lines = []
for k, v in matched_glossary.items():
    n = notes.get(k, "")
    dict_lines.append(f"{k}->{v} #{n}" if n else f"{k}->{v}")

user_prompt = (
    "根据以下术语表（可以为空）：\n"
    + "\n".join(dict_lines)
    + "\n将下面的日文文本根据对应关系和备注翻译成中文：\n"
    + ocr_text
)

messages = [{"role": "system", "content": system_prompt}]
for c_ja, c_zh in context_queue:
    messages.append({"role": "user", "content": f"将下面的日文文本翻译成中文：{c_ja}"})
    messages.append({"role": "assistant", "content": c_zh})
messages.append({"role": "user", "content": user_prompt})

print("Messages sent to Ollama:")
print(json.dumps(messages, ensure_ascii=False, indent=2))

payload = {
    "model": "sakura-14b",
    "messages": messages,
    "temperature": 0.1,
    "top_p": 0.3,
    "stream": False,
    "options": {
        "num_predict": 512,
        "repeat_penalty": 1.10
    }
}

resp = requests.post("http://127.0.0.1:11434/v1/chat/completions", json=payload, timeout=30)
print("Response status:", resp.status_code)
print("Response text:", resp.json()["choices"][0]["message"]["content"])
