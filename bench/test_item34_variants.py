import requests
import json

system_prompt_y4 = (
    "你是一个轻小说翻译模型，可以流畅通顺地以日本轻小说的风格将日文翻译成简体中文，"
    "并联系上下文正确使用人称代词，不擅自添加原文中没有的代词。"
    "遇到 OCR 明显损毁或无法识别的噪点字符（如带有孤立字母数字如 T、2C、片假名混拉丁等），"
    "请用「□」占位或保留原文，严禁胡乱猜测脑补填充。"
)

system_prompt_orig = (
    "你是一个轻小说翻译模型，可以流畅通顺地以日本轻小说的风格将日文翻译成简体中文，"
    "并联系上下文正确使用人称代词，不擅自添加原文中没有的代词。"
)

context_queue = [
    ('枝彌「おばあちゃんのために、ありがとう……さあ好きに味わって」', '枝弥「为了奶奶，谢谢你……来吧，尽情享受吧」'),
    ('リビングに戻って来た私は、テーブルに座った。', '我回到客厅，坐在桌子旁。'),
    ('拓头ぼあぼ……俺もっ、', '拓头奶奶……我也要'),
    ('これがオナニーじゃなく、セックスでで得られていたら最高なのに。', '如果这不是自慰，而是通过性交得到的快感，那就太棒了。')
]

ocr_text = '枝彌あっ来るつ、よくっ、見ていなさいっ、今がらっ、'

def test_config(name, sys_prompt, ctx, user_prompt):
    messages = [{"role": "system", "content": sys_prompt}]
    for c_ja, c_zh in ctx:
        messages.append({"role": "user", "content": f"将下面的日文文本翻译成中文：{c_ja}"})
        messages.append({"role": "assistant", "content": c_zh})
    messages.append({"role": "user", "content": user_prompt})
    
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
    print(f"[{name}] -> {out}")

# 1. 原始 Y4 带全部 4 句 context + 字典
user_p_dict = "根据以下术语表（可以为空）：\n枝彌->枝弥 #角色名，奶奶\n将下面的日文文本根据对应关系和备注翻译成中文：\n枝彌あっ来るつ、よくっ、見ていなさいっ、今がらっ、"
test_config("1. Y4 + 4 context + dict", system_prompt_y4, context_queue, user_p_dict)

# 2. 原版 prompt (无占位符说明) + 4 context + 字典
test_config("2. Orig sys + 4 context + dict", system_prompt_orig, context_queue, user_p_dict)

# 3. Sakura 官方字典格式
user_p_official_dict = "根据以下字典翻译：\n枝彌->枝弥\n将下面的日文文本翻译成中文：枝彌あっ来るつ、よくっ、見ていなさいっ、今がらっ、"
test_config("3. Official dict + 4 context", system_prompt_orig, context_queue, user_p_official_dict)

# 4. Y4 sys + 无 context + 字典
test_config("4. Y4 sys + NO context + dict", system_prompt_y4, [], user_p_dict)

# 5. Y4 sys + 仅保留前 1 句 context + 字典
test_config("5. Y4 sys + 1 context + dict", system_prompt_y4, context_queue[-1:], user_p_dict)

# 6. Y4 sys + 仅保留前 2 句 context + 字典
test_config("6. Y4 sys + 2 context + dict", system_prompt_y4, context_queue[-2:], user_p_dict)
