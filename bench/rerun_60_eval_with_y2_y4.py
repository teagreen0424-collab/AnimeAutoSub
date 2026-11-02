import json
import time
import re
import requests
from pathlib import Path

# Load audit 60 sentences
with open("bench/audit_60_final_verified.json", "r", encoding="utf-8") as f:
    eval_set = json.load(f)

print(f"Loaded {len(eval_set)} evaluation sentences.")

# Load Y3 glossary
glossary_path = Path("glossary/anime_production.json")
with open(glossary_path, "r", encoding="utf-8") as f:
    glossary_data = json.load(f)
glossary = {k: v for k, v in glossary_data.items() if not k.startswith("_")}
print(f"Loaded {len(glossary)} glossary terms: {list(glossary.keys())}")

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

# Y4 System Prompt
system_prompt = (
    "你是一个轻小说翻译模型，可以流畅通顺地以日本轻小说的风格将日文翻译成简体中文，"
    "并联系上下文正确使用人称代词，不擅自添加原文中没有的代词。"
    "遇到 OCR 明显损毁或无法识别的噪点字符（如带有孤立字母数字如 T、2C、片假名混拉丁等），"
    "请用「□」占位或保留原文，严禁胡乱猜测脑补填充。"
)

session = requests.Session()
api_url = "http://127.0.0.1:11434/v1/chat/completions"

context_queue = []
results = []
placeholder_count = 0
total_chars = 0

t0 = time.time()
print("=== 开始执行 Y2-Y4 增强重跑 (60 句) ===")

for i, item in enumerate(eval_set):
    eid = item["eval_id"]
    ocr_text = item["ocr_ja"]
    human_text = item["human_ja"]
    old_zh = item["zh"]
    
    # 1. 术语注入 (Sakura 官方标准字典 Prompt)
    matched_glossary = {k: v for k, v in glossary.items() if k in ocr_text}
    if matched_glossary:
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
    else:
        user_prompt = f"将下面的日文文本翻译成中文：{ocr_text}"

    messages = [{"role": "system", "content": system_prompt}]
    
    # 2. 上下文注入 (仅从 context_queue 取质检全通过的句子)
    for c_ja, c_zh in context_queue[-5:]:
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

    t_call_0 = time.time()
    new_zh = ""
    for attempt in range(3):
        try:
            resp = session.post(api_url, json=payload, timeout=60)
            if resp.status_code == 200:
                new_zh = resp.json()["choices"][0]["message"]["content"].strip()
                new_zh = re.sub(r'^(翻译结果[：:]\s*|中文[：:]\s*)', '', new_zh)
                break
            else:
                time.sleep(1)
        except Exception:
            time.sleep(1)
            
    dt_call = time.time() - t_call_0
    
    # Y2 上下文隔离准则:
    # 检查当前句是否为质检全通过 (Pristine):
    # 无明显 OCR 碎屑，标点闭合，译文有效
    is_pristine = (
        not re.search(r'[A-Za-z0-9_\<\>¿\?~@#\$%\^&]{2,}', ocr_text) and
        len(new_zh) >= 2 and
        "我柔井" not in new_zh and
        "单①" not in new_zh
    )
    
    if is_pristine:
        context_queue.append((ocr_text, new_zh))
    else:
        print(f"  [Y2 隔离] #{eid:02d} 存在噪点/截断/潜在污染，不加入上下文队列")

    # Y4 统计占位符
    if "□" in new_zh:
        placeholder_count += new_zh.count("□")
    total_chars += len(new_zh)

    record = {
        "eval_id": eid,
        "start": item["start"],
        "end": item["end"],
        "category": item["category"],
        "human_ja": human_text,
        "ocr_ja": ocr_text,
        "old_zh": old_zh,
        "new_zh": new_zh,
        "latency_s": round(dt_call, 2)
    }
    results.append(record)
    
    if eid <= 38:
        # Check target fixes
        fix_note = ""
        if eid == 3:
            fix_note = "✅ #03 输入污染消除" if "我柔井" not in new_zh else "❌ 仍有污染"
        elif eid == 5:
            fix_note = "✅ #05 称谓纠偏为奶奶" if "奶奶" in new_zh else f"⚠️ #05 译文: {new_zh}"
        elif eid == 21:
            fix_note = "✅ #21 幻觉消除" if "晴斗「飞机杯" not in new_zh else "❌ #21 仍有幻觉"
        elif eid == 37 or eid == 38:
            fix_note = "✅ 人名正确保留为瑛斗" if "瑛斗" in new_zh else f"❌ 仍有人名混淆: {new_zh}"
        
        print(f"#{eid:02d} [{item['category']}] ({dt_call:.2f}s) {fix_note}")
        if fix_note:
            print(f"    旧: {old_zh}")
            print(f"    新: {new_zh}")

total_time = time.time() - t0
placeholder_ratio = (placeholder_count / max(1, total_chars)) * 100

print(f"\n全部 60 句重跑完成! 总耗时: {total_time:.2f}s (均值: {total_time/len(results):.2f}s/句)")
print(f"Y4 占位符「□」统计: 出现 {placeholder_count} 次，占总字符比例: {placeholder_ratio:.2f}% (门禁要求 <= 3%)")

out_file = Path("bench/audit_60_y2_y4_results.json")
with open(out_file, "w", encoding="utf-8") as f:
    json.dump({
        "total_sentences": len(results),
        "total_time_s": round(total_time, 2),
        "avg_time_per_sentence_s": round(total_time / len(results), 2),
        "placeholder_count": placeholder_count,
        "placeholder_ratio_pct": round(placeholder_ratio, 2),
        "records": results
    }, f, ensure_ascii=False, indent=2)

print(f"结果已落盘至 {out_file}")
