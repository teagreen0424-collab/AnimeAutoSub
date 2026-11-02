import json
import time
import requests
import numpy as np

OLLAMA_API = "http://localhost:11434/api/chat"
MODEL = "sakura-14b"

with open('output/408309-1080p/japanese.json', encoding='utf-8') as f:
    ja_a = json.load(f)
with open('ocr_output/test_3min/japanese.json', encoding='utf-8') as f:
    ja_b = json.load(f)

# System prompt
SYS_PROMPT = (
    "你是一个轻小说翻译模型，可以流畅通顺地以日本轻小说的风格将日文翻译成简体中文，"
    "并联系上下文正确使用人称代词，不擅自添加原文中没有的代词。"
)

def benchmark_stream(sentences, name, n_samples=15):
    print(f"\n>>> Benchmarking {name} ({n_samples} sentences)...")
    prompt_tokens_list = []
    eval_tokens_list = []
    prompt_eval_sec_list = []
    eval_sec_list = []
    total_sec_list = []

    history = []
    for i in range(min(n_samples, len(sentences))):
        text = sentences[i]["text"]
        messages = [{"role": "system", "content": SYS_PROMPT}]
        # context 5 lines
        for h_ja, h_zh in history[-5:]:
            messages.append({"role": "user", "content": f"将下面的日文文本翻译成中文：{h_ja}"})
            messages.append({"role": "assistant", "content": h_zh})
        messages.append({"role": "user", "content": f"将下面的日文文本翻译成中文：{text}"})

        payload = {
            "model": MODEL,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": 0.1,
                "top_p": 0.3
            }
        }
        r = requests.post(OLLAMA_API, json=payload, timeout=60).json()
        
        p_count = r.get("prompt_eval_count", 0)
        e_count = r.get("eval_count", 0)
        p_sec = r.get("prompt_eval_duration", 0) / 1e9
        e_sec = r.get("eval_duration", 0) / 1e9
        t_sec = r.get("total_duration", 0) / 1e9
        content = r.get("message", {}).get("content", "").strip()

        prompt_tokens_list.append(p_count)
        eval_tokens_list.append(e_count)
        prompt_eval_sec_list.append(p_sec)
        eval_sec_list.append(e_sec)
        total_sec_list.append(t_sec)

        history.append((text, content))
        print(f"  [{i+1:02d}] total={t_sec:.2f}s (prompt_eval={p_sec:.2f}s for {p_count} tok, eval={e_sec:.2f}s for {e_count} tok) -> {content[:15]}")

    print(f"--- Summary for {name} ---")
    print(f"Mean Total Time: {np.mean(total_sec_list):.3f}s / sentence")
    print(f"Mean Prompt Tokens: {np.mean(prompt_tokens_list):.1f} tokens, Eval Duration: {np.mean(prompt_eval_sec_list):.3f}s")
    print(f"Mean Gen Tokens: {np.mean(eval_tokens_list):.1f} tokens, Gen Duration: {np.mean(eval_sec_list):.3f}s")
    speed_gen = np.sum(eval_tokens_list) / np.sum(eval_sec_list)
    print(f"Generation Speed: {speed_gen:.1f} tokens/s (or {1/speed_gen*1000:.1f} ms/token)")
    return {
        "name": name,
        "mean_total_s": float(np.mean(total_sec_list)),
        "mean_prompt_tokens": float(np.mean(prompt_tokens_list)),
        "mean_prompt_s": float(np.mean(prompt_eval_sec_list)),
        "mean_gen_tokens": float(np.mean(eval_tokens_list)),
        "mean_gen_s": float(np.mean(eval_sec_list)),
        "tokens_per_sec": float(speed_gen)
    }

res_a = benchmark_stream(ja_a, "Chain A (Speech)", 15)
res_b = benchmark_stream(ja_b, "Chain B (OCR Subtitles)", 15)

with open('bench/s3_ollama_profile.json', 'w', encoding='utf-8') as f:
    json.dump({"chain_a": res_a, "chain_b": res_b}, f, indent=2, ensure_ascii=False)
