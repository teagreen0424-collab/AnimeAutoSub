"""
AnimeAutoSub 阶段: 智能文本清洗与机器翻译 (core/stages/translate.py)

硬性契约:
  - 产物: chinese.json, n5_rejection_report.json
  - 落实 Y2 上下文隔离准则
  - 落实 Z2 强断言与防重复降级自愈机制
  - 落实 Z3 助词浊点纠偏 (由 lang 插件驱动)
"""

import re
import json
import time
import hashlib
import requests
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional

from ..stage import Stage
from ..context import PipelineContext
from ..gpu_lease import release_ollama_vram

_SESSION = None

def get_session():
    global _SESSION
    if _SESSION is None:
        _SESSION = requests.Session()
    return _SESSION


class TranslateStage(Stage):
    name = "translate"
    requires_gpu = False
    produces = ["chinese.json", "n5_rejection_report.json"]

    def fingerprint(self, ctx: PipelineContext) -> str:
        h = hashlib.sha256()
        t_cfg = ctx.lang.translator
        params = {
            "model": t_cfg.model_name,
            "system_prompt": t_cfg.system_prompt,
            "temp": t_cfg.temperature,
            "top_p": t_cfg.top_p,
            "context_lines": t_cfg.context_lines,
            "glossary_hash": hashlib.sha256(json.dumps(ctx.lang.glossary, sort_keys=True).encode("utf-8")).hexdigest()
        }
        h.update(json.dumps(params, sort_keys=True).encode("utf-8"))
        # 上游产物哈希 (ocr_raw.json 或 asr_raw.json)
        upstream_name = "ocr_raw.json" if ctx.mode == "ocr" else "asr_raw.json"
        upstream = ctx.get_product_path(upstream_name)
        if upstream.exists():
            with open(upstream, "rb") as f:
                h.update(hashlib.sha256(f.read()).hexdigest().encode("utf-8"))
        return h.hexdigest()

    def translate_one(self, text: str, ctx: PipelineContext, context_pairs: list) -> str:
        t_cfg = ctx.lang.translator
        glossary = ctx.lang.glossary
        prompt_builder = t_cfg.prompt_builder

        if prompt_builder:
            user_prompt = prompt_builder(text, glossary, context_pairs)
        else:
            user_prompt = f"将下面的日文文本翻译成中文：{text}"

        messages = [{"role": "system", "content": t_cfg.system_prompt}]
        for src_text, zh in context_pairs[-t_cfg.context_lines:]:
            if prompt_builder:
                ctx_prompt = prompt_builder(src_text, glossary, [])
            else:
                ctx_prompt = f"将下面的日文文本翻译成中文：{src_text}"
            messages.append({"role": "user", "content": ctx_prompt})
            messages.append({"role": "assistant", "content": zh})
        messages.append({"role": "user", "content": user_prompt})

        payload = {
            "model": t_cfg.model_name,
            "messages": messages,
            "temperature": t_cfg.temperature,
            "top_p": t_cfg.top_p,
            "stream": False,
            "options": {"num_predict": 512, "repeat_penalty": 1.10}
        }

        session = get_session()
        result = None
        for attempt in range(t_cfg.max_retries):
            try:
                resp = session.post(t_cfg.api_url, json=payload, timeout=60)
                if resp.status_code == 200:
                    out = resp.json()["choices"][0]["message"]["content"].strip()
                    result = re.sub(r'^(翻译结果[：:]\s*|中文[：:]\s*)', '', out)
                    break
                time.sleep(1)
            except Exception:
                time.sleep(1)

        if result is None:
            result = text

        # Z2 强断言与防重复降级自愈：
        if context_pairs and result == context_pairs[-1][1] and text != context_pairs[-1][0]:
            logging.warning(f"    ⚠ [Z2 拦截] 检测到与上句译文完全相同，触发纯净重试自愈...")
            result_retry = self.translate_one(text, ctx, context_pairs=[])
            assert result_retry != context_pairs[-1][1], f"翻译复用错误: 源文本 [{text}] 输出了与上句相同的译文"
            result = result_retry

        return result

    def run(self, ctx: PipelineContext, log: logging.Logger, cancel_token: Optional[Any] = None) -> None:
        log.info(f"  → [TranslateStage] 开始执行智能清洗与翻译 (模型: [{ctx.lang.translator.model_name}])...")
        upstream_name = "ocr_raw.json" if ctx.mode == "ocr" else "asr_raw.json"
        raw_path = ctx.get_product_path(upstream_name)
        if not raw_path.exists():
            raise FileNotFoundError(f"上游产物不存在: {raw_path}")

        with open(raw_path, "r", encoding="utf-8") as f:
            segments = json.load(f)

        total = len(segments)
        results = []
        context = []
        rejection_records = []
        salvaged_records = []
        rejected_count = 0
        start_time = time.time()

        sanitizer = ctx.lang.text_rules.sanitizer

        for idx, seg in enumerate(segments):
            if cancel_token and cancel_token.is_cancelled():
                log.warning("  ⚠ 阶段收到取消信号，中止翻译")
                return

            raw_text = seg["text"]
            cleaned_text, is_rej, action_info = sanitizer(raw_text)

            if is_rej:
                rejected_count += 1
                zh_text = ""
                rejection_records.append({
                    "index": idx,
                    "start": seg["start"],
                    "end": seg["end"],
                    "raw_text": raw_text,
                    "cleaned_text": cleaned_text,
                    "action": "rejected",
                    "reason": action_info
                })
            else:
                is_incomplete = not bool(re.search(r'[」』\)。！？!\?…]$', cleaned_text)) and ('「' in cleaned_text or '『' in cleaned_text)
                zh_text = self.translate_one(cleaned_text, ctx, context)

                # Y2 上下文隔离准则
                is_pristine = (action_info == "clean_pass") and (not is_incomplete) and (not re.search(r'[A-Za-z0-9_\<\>¿\?~@#\$%\^&]{2,}', cleaned_text))
                if is_pristine and zh_text and len(zh_text) >= 2:
                    context.append((cleaned_text, zh_text))

                if action_info != "clean_pass":
                    salvaged_records.append({
                        "index": idx,
                        "start": seg["start"],
                        "end": seg["end"],
                        "raw_text": raw_text,
                        "cleaned_text": cleaned_text,
                        "zh_text": zh_text,
                        "action": "salvaged",
                        "cut_snippets": action_info,
                        "incomplete_translation": is_incomplete
                    })

            item = {
                "start": seg["start"],
                "end": seg["end"],
                "src": cleaned_text if not is_rej else raw_text,
                "src_raw": raw_text,
                "zh": zh_text,
                "rejected": is_rej,
                "incomplete_translation": is_incomplete if not is_rej else False,
                "box": seg.get("box"),
                "video_w": seg.get("video_w"),
                "video_h": seg.get("video_h")
            }
            results.append(item)

            if (idx + 1) % 20 == 0 or (idx + 1) == total:
                elapsed = time.time() - start_time
                pct = (idx + 1) / total * 100
                speed = elapsed / (idx + 1)
                remain = speed * (total - idx - 1)
                log.info(f"    [翻译进度] {idx+1}/{total} ({pct:.0f}%) [约剩 {remain/60:.1f} 分钟]")

        chinese_path = ctx.get_product_path("chinese.json")
        with open(chinese_path, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)

        rej_report = {
            "total_segments": total,
            "rejected_count": rejected_count,
            "rejected_percent": round(rejected_count / max(1, total) * 100, 2),
            "salvaged_total_count": len(salvaged_records),
            "salvaged_records": salvaged_records,
            "rejected_records": rejection_records
        }
        rej_path = ctx.get_product_path("n5_rejection_report.json")
        with open(rej_path, "w", encoding="utf-8") as f:
            json.dump(rej_report, f, ensure_ascii=False, indent=2)

        log.info(f"  ✓ [TranslateStage] 翻译完成: 有效翻译 {total - rejected_count} 句, 拒识 {rejected_count} 句 ({rej_report['rejected_percent']}%)")

        # 任务阶段完成后主动释放大模型显存，断言显存回落
        try:
            release_ollama_vram(log)
        except Exception as e:
            log.warning(f"  ⚠ 释放 Ollama 显存失败: {e}")

    def verify(self, ctx: PipelineContext) -> bool:
        c_path = ctx.get_product_path("chinese.json")
        r_path = ctx.get_product_path("n5_rejection_report.json")
        if not c_path.exists() or c_path.stat().st_size < 10:
            return False
        if not r_path.exists():
            return False
        try:
            with open(c_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return isinstance(data, list)
        except Exception:
            return False
