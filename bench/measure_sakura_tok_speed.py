"""
测量 Ollama 模型生成速度 (tok/s) 与 GPU 分层状态
"""
import requests
import json
import time

def test_model(model_name: str):
    prompt = (
        "将下面的日漫日文字幕翻译为高质量地道中文：\n"
        "1. 恵麻は私と夫のたった一人の娘だ。\n"
        "2. 私がいればと、娘はますます自由奔放に振る舞うようになっていた。\n"
        "3. 帰宅しないことが多く、仮に帰宅したとしても深夜ぼかり。\n"
        "4. 危ないからいきなり抱きつかないで拓斗。\n"
        "5. 次男の瑛斗は少し仏頂面だけど、ちゃんと挨拶を返してくれる。\n"
        "6. 晴斗『せゃあ仕事行ってくるから。おばあちとお願い』\n"
        "7. 拓斗の学校は、体育祭の振り替え休日だそうだ。\n"
        "8. 拓斗「オッケー！んじゃ、さっさとやっちまおうぜ!」\n"
        "9. 帰ってきた晴斗には、しばらくここで生活することは話してある。\n"
        "10. 孫にはそれぞれの悩みがある。"
    )
    url = "http://127.0.0.1:11434/api/generate"
    data = {
        "model": model_name,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.1,
            "top_p": 0.85
        }
    }
    print(f"正在向 {model_name} 发送请求并统计吞吐...")
    res = requests.post(url, json=data, timeout=120)
    if res.status_code != 200:
        print(f"请求失败: {res.text}")
        return None
    r_json = res.json()
    eval_count = r_json.get("eval_count", 0)
    eval_dur_ns = r_json.get("eval_duration", 1)
    prompt_count = r_json.get("prompt_eval_count", 0)
    prompt_dur_ns = r_json.get("prompt_eval_duration", 1)

    tok_per_sec = eval_count / (eval_dur_ns / 1e9) if eval_dur_ns > 0 else 0
    prompt_tok_per_sec = prompt_count / (prompt_dur_ns / 1e9) if prompt_dur_ns > 0 else 0

    print(f"模型: {model_name}")
    print(f"  Prompt tokens: {prompt_count} (耗时 {prompt_dur_ns/1e9:.2f}s, 吞吐 {prompt_tok_per_sec:.2f} tok/s)")
    print(f"  Generated tokens: {eval_count} (耗时 {eval_dur_ns/1e9:.2f}s, 吞吐 {tok_per_sec:.2f} tok/s)")
    return {
        "model": model_name,
        "eval_count": eval_count,
        "eval_tok_per_sec": tok_per_sec,
        "prompt_count": prompt_count,
        "prompt_tok_per_sec": prompt_tok_per_sec,
        "response": r_json.get("response", "")
    }

if __name__ == "__main__":
    import sys
    m = sys.argv[1] if len(sys.argv) > 1 else "sakura-14b:latest"
    out = test_model(m)
    if out:
        with open(f"bench/{m.replace(':', '_')}_speed.json", "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
