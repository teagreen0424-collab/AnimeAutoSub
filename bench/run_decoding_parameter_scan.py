import json
import time
import re
import requests
from pathlib import Path

audit_path = Path("bench/audit_60_sentences.json")
with open(audit_path, "r", encoding="utf-8") as f:
    sentences = json.load(f)

print(f"Loaded {len(sentences)} evaluation sentences.")

# Load glossary
glossary = {}
glossary_dir = Path("glossary")
if glossary_dir.exists():
    for gf in glossary_dir.glob("*.json"):
        try:
            with open(gf, "r", encoding="utf-8") as f:
                d = json.load(f)
                if isinstance(d, dict):
                    for k, v in d.items():
                        if not k.startswith("_"):
                            glossary[k] = v
        except Exception:
            pass

system_prompt = (
    "你是一个轻小说翻译模型，可以流畅通顺地以日本轻小说的风格将日文翻译成简体中文，"
    "并联系上下文正确使用人称代词，不擅自添加原文中没有的代词。"
)

configs = [
    {
        "name": "Config_A_Baseline",
        "desc": "生产默认基线 (低温保守)",
        "temperature": 0.1,
        "top_p": 0.3,
        "repeat_penalty": 1.10
    },
    {
        "name": "Config_B_Fluent",
        "desc": "适度升温档 (增强流畅度与行文表达)",
        "temperature": 0.3,
        "top_p": 0.7,
        "repeat_penalty": 1.15
    },
    {
        "name": "Config_C_Strict",
        "desc": "极低采样档 (极致抗幻觉/高防重复惩罚)",
        "temperature": 0.05,
        "top_p": 0.2,
        "repeat_penalty": 1.25
    }
]

session = requests.Session()
api_url = "http://127.0.0.1:11434/v1/chat/completions"

scan_results = {
    "configs": {},
    "sentence_records": []
}

for cfg in configs:
    cfg_name = cfg["name"]
    print(f"\n=== 开始测试配置: {cfg_name} ({cfg['desc']}) ===")
    print(f"参数: temp={cfg['temperature']}, top_p={cfg['top_p']}, repeat_penalty={cfg['repeat_penalty']}")
    
    t0 = time.time()
    translations = []
    
    context = []
    for i, item in enumerate(sentences):
        ja = item["ja"]
        messages = [{"role": "system", "content": system_prompt}]
        
        matched_g = {k: v for k, v in glossary.items() if k in ja}
        if matched_g:
            hint = "请参考术语表进行翻译：\n" + "\n".join(f"{k} -> {v}" for k, v in matched_g.items())
            messages.append({"role": "system", "content": hint})
            
        for c_ja, c_zh in context[-3:]:
            messages.append({"role": "user", "content": f"将下面的日文文本翻译成中文：{c_ja}"})
            messages.append({"role": "assistant", "content": c_zh})
            
        messages.append({"role": "user", "content": f"将下面的日文文本翻译成中文：{ja}"})
        
        payload = {
            "model": "sakura-14b",
            "messages": messages,
            "temperature": cfg["temperature"],
            "top_p": cfg["top_p"],
            "stream": False,
            "options": {
                "num_predict": 512,
                "repeat_penalty": cfg["repeat_penalty"]
            }
        }
        
        t_call_0 = time.time()
        res_text = ""
        for attempt in range(3):
            try:
                resp = session.post(api_url, json=payload, timeout=60)
                if resp.status_code == 200:
                    res_text = resp.json()["choices"][0]["message"]["content"].strip()
                    res_text = re.sub(r'^(翻译结果[：:]\s*|中文[：:]\s*)', '', res_text)
                    break
                else:
                    time.sleep(1)
            except Exception:
                time.sleep(1)
                
        dt_call = time.time() - t_call_0
        translations.append({
            "eval_id": item["eval_id"],
            "zh": res_text,
            "latency_s": round(dt_call, 3)
        })
        context.append((ja, res_text))
        
        if (i + 1) % 15 == 0 or (i + 1) == len(sentences):
            print(f"  进度: {i+1}/{len(sentences)} 句已翻译 (最近一句耗时: {dt_call:.2f}s)")
            
    total_dt = time.time() - t0
    avg_s = total_dt / len(sentences)
    print(f"--> {cfg_name} 完成! 总耗时: {total_dt:.2f}s, 均值: {avg_s:.3f} s/句")
    
    scan_results["configs"][cfg_name] = {
        "desc": cfg["desc"],
        "temperature": cfg["temperature"],
        "top_p": cfg["top_p"],
        "repeat_penalty": cfg["repeat_penalty"],
        "total_time_s": round(total_dt, 2),
        "avg_time_per_sentence_s": round(avg_s, 3),
        "translations": translations
    }

# Assemble sentence_records for side-by-side comparison
for item in sentences:
    eid = item["eval_id"]
    record = {
        "eval_id": eid,
        "full_idx": item["full_idx"],
        "time": f"{item['start']:.2f}s - {item['end']:.2f}s",
        "category": item["category"],
        "ja_raw": item["ja_raw"],
        "ja": item["ja"],
        "baseline_zh": item["zh_baseline"],
        "config_a_zh": scan_results["configs"]["Config_A_Baseline"]["translations"][eid-1]["zh"],
        "config_b_zh": scan_results["configs"]["Config_B_Fluent"]["translations"][eid-1]["zh"],
        "config_c_zh": scan_results["configs"]["Config_C_Strict"]["translations"][eid-1]["zh"],
    }
    scan_results["sentence_records"].append(record)

out_report = Path("bench/decoding_scan_results.json")
with open(out_report, "w", encoding="utf-8") as f:
    json.dump(scan_results, f, ensure_ascii=False, indent=2)

print(f"\n全部参数扫描完成，结果已保存至 {out_report}")
