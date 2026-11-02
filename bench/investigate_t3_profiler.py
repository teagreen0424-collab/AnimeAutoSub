"""
T3 专项剖析：translate_one 深度分段计时与 Session 复用性能分析
============================================================
测量项：
1. Fresh requests.post (无 session) vs Reused Session (有 session)
2. HTTP 分段拆分：
   - 连接与等待首字节 (TTFB: 包含网络握手 + Ollama Prompt Prefill + 第一个 Token 生成)
   - 流式内容接收耗时 (Content Download / Streaming)
   - 响应解析与正则后处理耗时 (Post-processing)
3. 解释 Chain A 154 句中 214 秒的完整去向
"""

import sys
import time
import json
import re
import requests
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# System prompt
SAKURA_SYSTEM_PROMPT = (
    "你是一个轻小说翻译模型，可以流畅通顺地以日本轻小说的风格将日文翻译成简体中文，"
    "并联系上下文正确使用人称代词，不擅自添加原文中没有的代词。"
)

OLLAMA_API_URL = "http://localhost:11434/v1/chat/completions"

with open(PROJECT_ROOT / "output/408309-1080p/japanese.json", encoding="utf-8") as f:
    ja_a = json.load(f)

def profile_translation_calls(sentences, use_session=True, n_samples=20):
    mode_name = "Reused Session" if use_session else "Fresh requests.post"
    print(f"\n>>> 正在剖析 [{mode_name}] ({n_samples} 句)...")
    
    session = requests.Session() if use_session else None
    
    records = []
    history = []
    
    for i in range(min(n_samples, len(sentences))):
        text = sentences[i]["text"]
        messages = [{"role": "system", "content": SAKURA_SYSTEM_PROMPT}]
        for h_ja, h_zh in history[-5:]:
            messages.append({"role": "user", "content": f"将下面的日文文本翻译成中文：{h_ja}"})
            messages.append({"role": "assistant", "content": h_zh})
        messages.append({"role": "user", "content": f"将下面的日文文本翻译成中文：{text}"})

        payload = {
            "model": "sakura-14b",
            "messages": messages,
            "temperature": 0.1,
            "top_p": 0.3,
            "stream": True  # 启用流式以便精确测量 TTFB 与接收耗时
        }

        t_start = time.time()
        
        # 1. 发起请求并等待首字节 (TTFB)
        client = session if use_session else requests
        resp = client.post(OLLAMA_API_URL, json=payload, stream=True, timeout=60)
        t_ttfb = time.time()
        ttfb_s = t_ttfb - t_start

        # 2. 接收全部流式数据
        chunks = []
        for line in resp.iter_lines():
            if line:
                chunks.append(line.decode("utf-8"))
        t_recv = time.time()
        recv_s = t_recv - t_ttfb

        # 3. 解析与后处理
        # 拼接 SSE 事件
        full_text = ""
        for c in chunks:
            if c.startswith("data: ") and c != "data: [DONE]":
                try:
                    data = json.loads(c[6:])
                    delta = data["choices"][0].get("delta", {}).get("content", "")
                    full_text += delta
                except Exception:
                    pass
        
        clean_text = re.sub(r'^(翻译结果[：:]\s*|中文[：:]\s*)', '', full_text.strip())
        t_end = time.time()
        post_s = t_end - t_recv
        total_s = t_end - t_start

        history.append((text, clean_text))
        records.append({
            "idx": i + 1,
            "ttfb_s": ttfb_s,
            "recv_s": recv_s,
            "post_s": post_s,
            "total_s": total_s,
            "chars": len(clean_text)
        })
        print(f"  [{i+1:02d}] total={total_s:.2f}s (TTFB={ttfb_s:.2f}s, recv={recv_s:.2f}s, post={post_s*1000:.1f}ms) -> {clean_text[:15]}")

    import numpy as np
    mean_total = np.mean([r["total_s"] for r in records])
    mean_ttfb = np.mean([r["ttfb_s"] for r in records])
    mean_recv = np.mean([r["recv_s"] for r in records])
    mean_post = np.mean([r["post_s"] for r in records])

    print(f"--- [{mode_name}] 均值统计 ---")
    print(f"Mean Total: {mean_total:.3f}s / 句")
    print(f"  ├── TTFB (连接握手+Prompt Prefill+首Token): {mean_ttfb:.3f}s ({mean_ttfb/mean_total*100:.1f}%)")
    print(f"  ├── Content Stream Recv (Token流式生成接收): {mean_recv:.3f}s ({mean_recv/mean_total*100:.1f}%)")
    print(f"  └── Post-processing (正则清洗与解析):        {mean_post*1000:.1f}ms ({mean_post/mean_total*100:.1f}%)")
    
    return {
        "mode": mode_name,
        "mean_total_s": float(mean_total),
        "mean_ttfb_s": float(mean_ttfb),
        "mean_recv_s": float(mean_recv),
        "mean_post_s": float(mean_post),
        "samples": records
    }

res_fresh = profile_translation_calls(ja_a, use_session=False, n_samples=10)
res_session = profile_translation_calls(ja_a, use_session=True, n_samples=10)

with open(PROJECT_ROOT / "bench/t3_timing_profile.json", "w", encoding="utf-8") as f:
    json.dump({"fresh_requests": res_fresh, "reused_session": res_session}, f, indent=2, ensure_ascii=False)
