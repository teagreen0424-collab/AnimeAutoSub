import requests

raw_ocr15 = '枝彌「ええそうよ。誰がに言っちゃダメよ？おばあちゃんと拓斗の秘密。いいわね?」'

def test_raw(model_name, prompt):
    resp = requests.post("http://127.0.0.1:11434/v1/chat/completions", json={
        "model": model_name,
        "messages": [
            {"role": "system", "content": "你是一个轻小说翻译模型，可以流畅通顺地以日本轻小说的风格将日文翻译成简体中文，并联系上下文正确使用人称代词，不擅自添加原文中没有的代词。"},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.1,
        "top_p": 0.3
    }, timeout=30)
    print(f"[{model_name}] -> {resp.json()['choices'][0]['message']['content']}")

test_raw("sakura-14b", f"将下面的日文文本翻译成中文：{raw_ocr15}")
test_raw("sakura:latest", f"将下面的日文文本翻译成中文：{raw_ocr15}")
