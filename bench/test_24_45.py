import requests
import json

def test_single(prompt, ocr_text):
    resp = requests.post("http://127.0.0.1:11434/v1/chat/completions", json={
        "model": "sakura-14b",
        "messages": [
            {"role": "system", "content": "你是一个轻小说翻译模型，可以流畅通顺地以日本轻小说的风格将日文翻译成简体中文，并联系上下文正确使用人称代词，不擅自添加原文中没有的代词。"},
            {"role": "user", "content": f"根据以下字典翻译：\n枝彌->枝弥\n将下面的日文文本翻译成中文：{ocr_text}"}
        ],
        "temperature": 0.1,
        "top_p": 0.3
    }, timeout=30)
    print(f"[{ocr_text}] -> {resp.json()['choices'][0]['message']['content']}")

test_single("24", "枝彌「そう、女の人とこういうことするの初めてな")
test_single("45", "息分が眠っているのか、起きているのかはまだあやふやで…")
