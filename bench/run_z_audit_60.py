import json
import time
import re
import requests
from pathlib import Path

# 1. 加载 60 句验证评测集
with open("bench/audit_60_final_verified.json", "r", encoding="utf-8") as f:
    eval_set = json.load(f)

print(f"Loaded {len(eval_set)} evaluation sentences.")

# 2. 加载术语表
glossary_path = Path("glossary/anime_production.json")
with open(glossary_path, "r", encoding="utf-8") as f:
    glossary_data = json.load(f)
glossary = {k: v for k, v in glossary_data.items() if not k.startswith("_")}
print(f"Loaded {len(glossary)} glossary terms: {list(glossary.keys())}")

# 3. 系统提示词
system_prompt = (
    "你是一个轻小说翻译模型，可以流畅通顺地以日本轻小说的风格将日文翻译成简体中文，"
    "并联系上下文正确使用人称代词，不擅自添加原文中没有的代词。"
)

session = requests.Session()
api_url = "http://127.0.0.1:11434/v1/chat/completions"

def clean_ocr_text(raw_text: str) -> str:
    """与 pipeline_ocr.py 保持完全同步的清洗与助词误识纠偏"""
    t = raw_text
    # 修复常见 OCR 助词浊点误识 (Z3)
    t = re.sub(r'誰がに', '誰かに', t)
    # 去除末尾悬空未闭合的符号与空白
    t = re.sub(r'[\s「」\[\]&]+$', '', t).strip()
    return t

def call_ollama(text: str, ctx_pairs: list, term_dict: dict) -> str:
    matched = {k: v for k, v in term_dict.items() if k in text}
    if matched:
        dict_lines = [f"{k}->{v}" for k, v in matched.items()]
        user_prompt = (
            "根据以下字典翻译：\n"
            + "\n".join(dict_lines)
            + "\n将下面的日文文本翻译成中文："
            + text
        )
    else:
        user_prompt = f"将下面的日文文本翻译成中文：{text}"

    messages = [{"role": "system", "content": system_prompt}]
    for c_ja, c_zh in ctx_pairs[-5:]:
        messages.append({"role": "user", "content": f"将下面的日文文本翻译成中文：{c_ja}"})
        messages.append({"role": "assistant", "content": c_zh})
    messages.append({"role": "user", "content": user_prompt})

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

    for attempt in range(3):
        try:
            resp = session.post(api_url, json=payload, timeout=60)
            if resp.status_code == 200:
                out = resp.json()["choices"][0]["message"]["content"].strip()
                out = re.sub(r'^(翻译结果[：:]\s*|中文[：:]\s*)', '', out)
                return out
            time.sleep(1)
        except Exception:
            time.sleep(1)
    return text

context_queue = []
results = []
prev_ja = ""
prev_zh = ""

t0 = time.time()
print("=== 开始执行 Z 阶段重跑与强校验 (全 60 句) ===")

for i, item in enumerate(eval_set):
    eid = item["eval_id"]
    ocr_raw = item["ocr_ja"]
    human_ja = item["human_ja"]
    old_zh = item["zh"]
    
    cleaned_ja = clean_ocr_text(ocr_raw)
    
    t_start = time.time()
    # 执行模型翻译
    zh = call_ollama(cleaned_ja, context_queue, glossary)
    
    # Z2 强断言与防重复降级自愈：
    if prev_zh and zh == prev_zh and cleaned_ja != prev_ja:
        print(f"  ⚠ [Z2 拦截触发] #{eid:02d} 与上句译文完全相同！触发独立重跑降级自愈...")
        zh_retry = call_ollama(cleaned_ja, [], glossary)
        assert zh_retry != prev_zh, f"Z2 断言失败: 源文本 [{cleaned_ja}] 重试后依然输出重复译文 [{zh_retry}]"
        print(f"  ✓ [Z2 自愈成功] 独立重试后译文: '{zh_retry}'")
        zh = zh_retry
        
    dt = time.time() - t_start
    
    # 断言相邻不同原文译文不同
    if prev_zh and cleaned_ja != prev_ja:
        assert zh != prev_zh, f"断言失败: #{eid:02d} 译文与前一句完全重复！"
        
    # 上下文管理 (仅 pristine 入队)
    is_pristine = (
        not re.search(r'[A-Za-z0-9_\<\>¿\?~@#\$%\^&]{2,}', cleaned_ja) and
        len(zh) >= 2 and
        "我柔井" not in zh and
        "单①" not in zh and
        not (not re.search(r'[」』\)。！？!\?…]$', cleaned_ja) and ('「' in cleaned_ja or '『' in cleaned_ja))
    )
    
    if is_pristine:
        context_queue.append((cleaned_ja, zh))
    else:
        print(f"  [Y2 隔离] #{eid:02d} 存在残损/断句，不入上下文队列: '{cleaned_ja}'")

    prev_ja = cleaned_ja
    prev_zh = zh
    
    results.append({
        "eval_id": eid,
        "start": item["start"],
        "end": item["end"],
        "category": item["category"],
        "human_ja": human_ja,
        "ocr_ja": ocr_raw,
        "cleaned_ja": cleaned_ja,
        "old_zh": old_zh,
        "new_zh": zh,
        "latency_s": round(dt, 2)
    })
    
    if eid in [15, 33, 34]:
        print(f"  ★ [重点关注 #{eid:02d}] clean='{cleaned_ja}' -> zh='{zh}' ({dt:.2f}s)")
    else:
        print(f"  #{eid:02d} ({dt:.2f}s) -> {zh[:25]}")

total_elapsed = time.time() - t0
print(f"=== 重跑完毕: 60 句耗时 {total_elapsed:.2f}s (均速 {total_elapsed/60:.2f}s/句) ===")

out_data = {
    "total_sentences": len(results),
    "total_time_s": round(total_elapsed, 2),
    "avg_time_per_sentence_s": round(total_elapsed / len(results), 2),
    "records": results
}

with open("bench/audit_60_z_results.json", "w", encoding="utf-8") as f:
    json.dump(out_data, f, ensure_ascii=False, indent=2)

print("Saved results to bench/audit_60_z_results.json")
