"""
AnimeAutoSub 阶段: 智能文本清洗与机器翻译 (core/stages/translate.py)

硬性契约:
  - 产物: chinese.json, n5_rejection_report.json
  - 落实 Y2 上下文隔离准则
  - 落实 Z2 强断言与防重复降级自愈机制
  - 落实 Z3 助词浊点纠偏 (由 lang 插件驱动)
"""

import os
import re
import json
import time
import difflib
import hashlib
import requests
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional

from ..stage import Stage
from ..context import PipelineContext
from ..gpu_lease import release_ollama_vram
from ..translation_engine import (
    get_engine_config,
    is_refusal_response,
    estimate_tokens,
    calculate_cost,
    redact_secrets
)
from lang.ja import CLOUD_JA_SYSTEM_PROMPT, build_cloud_japanese_prompt
from lang.ko import CLOUD_KO_SYSTEM_PROMPT, build_cloud_korean_prompt

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
        engine_id = getattr(ctx, "engine_id", None) or (ctx.custom_params.get("engine_id") if hasattr(ctx, "custom_params") and ctx.custom_params else None) or "sakura-14b"
        engine_cfg = get_engine_config(engine_id)

        t_cfg = ctx.lang.translator
        if engine_cfg.type == "api":
            if ctx.lang.code == "ko":
                system_prompt = CLOUD_KO_SYSTEM_PROMPT
            else:
                system_prompt = CLOUD_JA_SYSTEM_PROMPT
            prompt_version = engine_cfg.prompt_version or "film_v1.0"
            base_url = engine_cfg.api_url
            model_name = engine_cfg.model_name
            temp = engine_cfg.temperature
            top_p = engine_cfg.top_p
            context_lines = engine_cfg.context_lines
        else:
            system_prompt = t_cfg.system_prompt
            prompt_version = getattr(t_cfg, "prompt_version", "sakura_v1.0") or "sakura_v1.0"
            base_url = t_cfg.api_url
            model_name = t_cfg.model_name
            temp = t_cfg.temperature
            top_p = t_cfg.top_p
            context_lines = t_cfg.context_lines

        params = {
            "engine_id": engine_cfg.id,
            "base_url": base_url,
            "prompt_version": prompt_version,
            "model": model_name,
            "system_prompt": system_prompt,
            "temp": temp,
            "top_p": top_p,
            "context_lines": context_lines,
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

    def translate_one(self, text: str, ctx: PipelineContext, context_pairs: list, return_meta: bool = False, stats: Optional[Dict[str, Any]] = None, **kwargs) -> Any:
        effective_stats = stats if stats is not None else getattr(self, "_current_stats", None)
        engine_id = getattr(ctx, "engine_id", None) or (ctx.custom_params.get("engine_id") if hasattr(ctx, "custom_params") and ctx.custom_params else None) or "sakura-14b"
        engine_cfg = get_engine_config(engine_id)

        t_cfg = ctx.lang.translator
        glossary = ctx.lang.glossary

        if engine_cfg.type == "api":
            if ctx.lang.code == "ko":
                sys_prompt = CLOUD_KO_SYSTEM_PROMPT
                builder = build_cloud_korean_prompt
            else:
                sys_prompt = CLOUD_JA_SYSTEM_PROMPT
                builder = build_cloud_japanese_prompt
            ctx_lines = engine_cfg.context_lines
            model_name = engine_cfg.model_name
            api_url = engine_cfg.api_url
            temp = engine_cfg.temperature
            top_p = engine_cfg.top_p
            max_retries = engine_cfg.max_retries
            headers = {"Content-Type": "application/json"}
            if engine_cfg.api_key:
                headers["Authorization"] = f"Bearer {engine_cfg.api_key}"
            is_cloud = True
        else:
            sys_prompt = t_cfg.system_prompt
            builder = t_cfg.prompt_builder
            ctx_lines = t_cfg.context_lines
            model_name = t_cfg.model_name
            api_url = t_cfg.api_url
            temp = t_cfg.temperature
            top_p = t_cfg.top_p
            max_retries = t_cfg.max_retries
            headers = {"Content-Type": "application/json"}
            is_cloud = False

        lang_name = "韩文" if ctx.lang.code == "ko" else "日文"
        if builder:
            user_prompt = builder(text, glossary, context_pairs)
        else:
            user_prompt = f"将下面的{lang_name}文本翻译成中文：{text}"

        messages = [{"role": "system", "content": sys_prompt}]
        for src_text, zh in context_pairs[-ctx_lines:]:
            if builder:
                ctx_prompt = builder(src_text, glossary, [])
            else:
                ctx_prompt = f"将下面的{lang_name}文本翻译成中文：{src_text}"
            messages.append({"role": "user", "content": ctx_prompt})
            messages.append({"role": "assistant", "content": zh})
        messages.append({"role": "user", "content": user_prompt})

        payload = {
            "model": model_name,
            "messages": messages,
            "temperature": temp,
            "top_p": top_p,
            "stream": False
        }
        if not is_cloud:
            payload["options"] = {"num_predict": 512, "repeat_penalty": 1.10}

        session = get_session()
        result = None
        was_refused = False
        refusal_reason = ""
        prompt_tokens = estimate_tokens(json.dumps(messages, ensure_ascii=False))
        completion_tokens = 0

        for attempt in range(max_retries):
            try:
                resp = session.post(api_url, json=payload, headers=headers, timeout=60)
                resp_json = None
                try:
                    resp_json = resp.json()
                except Exception:
                    pass

                # 拒答校验 (形态 3: 状态码; 形态 2: finish_reason; 形态 1: 文本)
                is_ref, reason = is_refusal_response("", resp_json, resp.status_code)
                if is_ref:
                    was_refused = True
                    refusal_reason = reason
                    result = ""
                    logging.warning(redact_secrets(f"    ⚠ [拒答] 云端 API 拒答 (形态 2/3: {reason})"))
                    break

                if resp.status_code == 200 and resp_json:
                    choices = resp_json.get("choices", [])
                    if choices:
                        out = choices[0].get("message", {}).get("content", "").strip()
                        # 检查形态 1 (文本关键词)
                        is_ref_text, text_reason = is_refusal_response(out, resp_json, 200)
                        if is_ref_text:
                            was_refused = True
                            refusal_reason = text_reason
                            result = ""
                            logging.warning(redact_secrets(f"    ⚠ [拒答] 译文命中拒答关键词 ({text_reason})，拒绝写入"))
                            break

                        # 正常提取译文
                        result = re.sub(r'^(翻译结果[：:]\s*|中文[：:]\s*)', '', out)

                        # Token 用量统计
                        usage = resp_json.get("usage", {})
                        if usage and isinstance(usage, dict):
                            prompt_tokens = usage.get("prompt_tokens", prompt_tokens)
                            completion_tokens = usage.get("completion_tokens", estimate_tokens(result))
                        else:
                            completion_tokens = estimate_tokens(result)
                        break

                time.sleep(1)
            except Exception as e:
                logging.debug(redact_secrets(f"    API 请求异常: {e}"))
                time.sleep(1)

        if effective_stats is not None:
            effective_stats["total_prompt_tokens"] = effective_stats.get("total_prompt_tokens", 0) + prompt_tokens
            effective_stats["total_completion_tokens"] = effective_stats.get("total_completion_tokens", 0) + completion_tokens
            call_cost = calculate_cost(prompt_tokens, completion_tokens, engine_cfg.pricing)
            effective_stats["total_cost"] = round(effective_stats.get("total_cost", 0.0) + call_cost, 6)
            effective_stats["was_refused"] = was_refused
            if was_refused:
                effective_stats["refused_count"] = effective_stats.get("refused_count", 0) + 1
                effective_stats["refusal_reason"] = refusal_reason

        if result is None:
            result = "" if was_refused else text

        is_dup_translation = False
        # Z2 防重复检查：只告警，绝不中断任务。
        # 连续语气句（喘息、拟声、重复台词）相邻两句译文相同属于正常现象，不是缺陷。
        if not was_refused and result and context_pairs and result == context_pairs[-1][1]:
            prev_src = context_pairs[-1][0]
            similar_src = (
                text == prev_src
                or difflib.SequenceMatcher(None, text, prev_src).ratio() >= 0.60
            )
            if similar_src:
                logging.debug("    [Z2] 相邻源文本相近，译文相同属正常，跳过")
            else:
                logging.warning(
                    "    ⚠ [Z2] 源文本差异明显却输出相同译文，用干净上下文重试一次（不中断任务）"
                )
                retry = self.translate_one(text, ctx, context_pairs=[], return_meta=False)
                if retry and retry != context_pairs[-1][1]:
                    result = retry
                else:
                    logging.warning(
                        "    ⚠ [Z2] 重试后仍相同，保留该结果并继续，标记待人工复核"
                    )
                    is_dup_translation = True

        if return_meta:
            return result, is_dup_translation
        return result

    def run(self, ctx: PipelineContext, log: logging.Logger, cancel_token: Optional[Any] = None) -> None:
        engine_id = getattr(ctx, "engine_id", None) or (ctx.custom_params.get("engine_id") if hasattr(ctx, "custom_params") and ctx.custom_params else None) or "sakura-14b"
        engine_cfg = get_engine_config(engine_id)

        log.info(f"  → [TranslateStage] 开始执行智能清洗与翻译 (引擎: [{engine_cfg.name}], 模型: [{engine_cfg.model_name}], GPU需求: {engine_cfg.requires_gpu})...")
        upstream_name = "ocr_raw.json" if ctx.mode == "ocr" else "asr_raw.json"
        raw_path = ctx.get_product_path(upstream_name)
        if not raw_path.exists():
            raise FileNotFoundError(f"上游产物不存在: {raw_path}")

        with open(raw_path, "r", encoding="utf-8") as f:
            segments = json.load(f)

        total = len(segments)
        chinese_path = ctx.get_product_path("chinese.json")
        rej_path = ctx.get_product_path("n5_rejection_report.json")
        manifest_file = ctx.work_dir / "manifest.json"

        results = []
        context = []
        rejection_records = []
        salvaged_records = []
        rejected_count = 0
        start_time = time.time()

        sanitizer = ctx.lang.text_rules.sanitizer
        t_cfg = ctx.lang.translator

        stats = {
            "total_prompt_tokens": 0,
            "total_completion_tokens": 0,
            "total_cost": 0.0,
            "refused_count": 0,
            "was_refused": False
        }
        processed_translation_count = 0

        # Y2 断点恢复检查: 若存在 chinese.json 且条目数小于上游产物，从断点续跑
        if chinese_path.exists():
            try:
                with open(chinese_path, "r", encoding="utf-8") as f:
                    existing_results = json.load(f)
                if isinstance(existing_results, list) and 0 < len(existing_results) < total:
                    results = list(existing_results)
                    log.info(f"  ⚡ [TranslateStage] 发现历史断点: 已翻译 {len(results)}/{total} 句，从第 {len(results) + 1} 句继续...")

                    # 尝试恢复拒识统计
                    if rej_path.exists():
                        try:
                            with open(rej_path, "r", encoding="utf-8") as rf:
                                r_data = json.load(rf)
                            rejection_records = r_data.get("rejected_records", [])
                            salvaged_records = r_data.get("salvaged_records", [])
                            rejected_count = r_data.get("rejected_count", 0)
                        except Exception:
                            pass
                    if not rejection_records:
                        for idx_r, r in enumerate(results):
                            if r.get("rejected"):
                                rejected_count += 1
                                rejection_records.append({
                                    "index": idx_r,
                                    "start": r["start"],
                                    "end": r["end"],
                                    "raw_text": r.get("src_raw", ""),
                                    "cleaned_text": r.get("src", ""),
                                    "action": "rejected",
                                    "reason": "resumed_from_checkpoint"
                                })

                    # 重建最近的有效上下文
                    for r in results:
                        if not r.get("rejected") and not r.get("refused"):
                            zh = r.get("zh", "")
                            src = r.get("src", "")
                            is_inc = r.get("incomplete_translation", False)
                            if zh and len(zh) >= 2 and not is_inc and not re.search(r'[A-Za-z0-9_\<\>¿\?~@#\$%\^&]{2,}', src):
                                context.append((src, zh))
                    ctx_lines = engine_cfg.context_lines if engine_cfg.type == "api" else t_cfg.context_lines
                    context = context[-ctx_lines:]
            except Exception as e:
                log.warning(f"  ⚠ 读取历史翻译断点失败: {e}，将从头开始翻译")
                results = []

        start_idx = len(results)

        def _save_checkpoint(curr_results: list, is_final: bool = False):
            """原子写入 chinese.json 与 n5_rejection_report.json，并在 manifest 中记录已翻译句数与用量账本"""
            # 1. 原子写入 chinese.json
            tmp_c = chinese_path.with_suffix(f".tmp_{int(time.time()*1000)}")
            with open(tmp_c, "w", encoding="utf-8") as f_c:
                json.dump(curr_results, f_c, ensure_ascii=False, indent=2)
            os.replace(tmp_c, chinese_path)

            # 2. 原子写入 n5_rejection_report.json
            rej_report = {
                "total_segments": total,
                "translated_count": len(curr_results),
                "rejected_count": rejected_count,
                "rejected_percent": round(rejected_count / max(1, len(curr_results)) * 100, 2),
                "salvaged_total_count": len(salvaged_records),
                "salvaged_records": salvaged_records,
                "rejected_records": rejection_records
            }
            tmp_r = rej_path.with_suffix(f".tmp_{int(time.time()*1000)}")
            with open(tmp_r, "w", encoding="utf-8") as f_r:
                json.dump(rej_report, f_r, ensure_ascii=False, indent=2)
            os.replace(tmp_r, rej_path)

            # 3. 在 manifest.json 中原子更新已翻译句数与费用用量
            if manifest_file.exists():
                try:
                    with open(manifest_file, "r", encoding="utf-8") as mf_f:
                        mf_data = json.load(mf_f)
                    if "stages" not in mf_data:
                        mf_data["stages"] = {}
                    if "translate" not in mf_data["stages"]:
                        mf_data["stages"]["translate"] = {}
                    mf_data["stages"]["translate"]["translated_count"] = len(curr_results)
                    mf_data["stages"]["translate"]["total_count"] = total
                    mf_data["stages"]["translate"]["engine_id"] = engine_cfg.id
                    mf_data["stages"]["translate"]["model_name"] = engine_cfg.model_name
                    mf_data["stages"]["translate"]["token_usage"] = {
                        "prompt_tokens": stats["total_prompt_tokens"],
                        "completion_tokens": stats["total_completion_tokens"],
                        "total_tokens": stats["total_prompt_tokens"] + stats["total_completion_tokens"]
                    }
                    mf_data["stages"]["translate"]["cost_estimate"] = {
                        "cost": stats["total_cost"],
                        "currency": engine_cfg.pricing.get("currency", "CNY")
                    }
                    mf_data["stages"]["translate"]["refusal_stats"] = {
                        "refused_count": stats["refused_count"],
                        "processed_count": processed_translation_count
                    }
                    mf_data["engine_id"] = engine_cfg.id
                    mf_data["updated_at"] = datetime.now().isoformat()
                    tmp_m = manifest_file.with_suffix(f".tmp_{int(time.time()*1000)}")
                    with open(tmp_m, "w", encoding="utf-8") as mf_f:
                        json.dump(mf_data, mf_f, ensure_ascii=False, indent=2)
                    os.replace(tmp_m, manifest_file)
                except Exception as ex:
                    log.warning(f"  ⚠ 写入 manifest 进度失败: {ex}")

        for idx in range(start_idx, total):
            if cancel_token and cancel_token.is_cancelled():
                log.warning("  ⚠ 阶段收到取消信号，中止翻译并保存当前断点")
                _save_checkpoint(results)
                return

            seg = segments[idx]
            raw_text = seg["text"]
            cleaned_text, is_rej, action_info = sanitizer(raw_text)

            is_dup = False
            was_ref = False
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
                self._current_stats = stats
                stats["was_refused"] = False
                zh_text, is_dup = self.translate_one(cleaned_text, ctx, context, return_meta=True)
                was_ref = stats.get("was_refused", False)
                processed_translation_count += 1

                # 拒答率检查 (> 20% 立即中止)
                if was_ref:
                    refusal_rate = stats["refused_count"] / max(1, processed_translation_count)
                    if processed_translation_count >= 5 and refusal_rate > 0.20:
                        err_msg = (
                            f"检测到云端 API [{engine_cfg.name}] 拒答率超过 20% "
                            f"({stats['refused_count']}/{processed_translation_count})，"
                            f"片源内容可能触发云端模型安全审查。建议切换为本地 Sakura-14B 引擎重试。"
                        )
                        log.error(f"  ✗ {err_msg}")
                        _save_checkpoint(results)
                        raise RuntimeError(err_msg)

                # 费用硬上限检查
                if stats["total_cost"] > engine_cfg.hard_cost_cap:
                    err_msg = (
                        f"累计翻译费用已达 ￥{stats['total_cost']:.4f}，"
                        f"超过单任务硬上限 ￥{engine_cfg.hard_cost_cap:.2f}。自动中止以保护用户预算。"
                    )
                    log.error(f"  ✗ {err_msg}")
                    _save_checkpoint(results)
                    raise RuntimeError(err_msg)

                # Y2 上下文隔离准则: 仅当非拒答、非残缺且无杂质时才追加至上下文
                is_pristine = (action_info == "clean_pass") and (not is_incomplete) and (not was_ref) and (not re.search(r'[A-Za-z0-9_\<\>¿\?~@#\$%\^&]{2,}', cleaned_text))
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
                "refused": was_ref,
                "incomplete_translation": is_incomplete if not is_rej else False,
                "duplicate_translation": is_dup if not is_rej else False,
                "box": seg.get("box"),
                "video_w": seg.get("video_w"),
                "video_h": seg.get("video_h")
            }
            results.append(item)

            # 每 20 句把结果原子写入 chinese.json，并在 manifest 里记录已翻译句数与用量
            if (idx + 1) % 20 == 0 or (idx + 1) == total:
                _save_checkpoint(results, is_final=((idx + 1) == total))
                elapsed = time.time() - start_time
                done_in_run = idx + 1 - start_idx
                pct = (idx + 1) / total * 100
                if done_in_run > 0:
                    speed = elapsed / done_in_run
                    remain = speed * (total - idx - 1)
                    if engine_cfg.type == "api":
                        log.info(
                            f"    [翻译进度] {idx+1}/{total} ({pct:.0f}%) "
                            f"[Token用量: 输入 {stats['total_prompt_tokens']:,}, 输出 {stats['total_completion_tokens']:,} "
                            f"| 预估累计费用: ￥{stats['total_cost']:.4f} {engine_cfg.pricing.get('currency', 'CNY')}] "
                            f"[约剩 {remain/60:.1f} 分钟]"
                        )
                    else:
                        log.info(f"    [翻译进度] {idx+1}/{total} ({pct:.0f}%) [约剩 {remain/60:.1f} 分钟]")

        # 确保完成时写入全量终态
        _save_checkpoint(results, is_final=True)

        log.info(f"  ✓ [TranslateStage] 翻译完成: 有效翻译 {total - rejected_count} 句, 拒识 {rejected_count} 句 ({round(rejected_count/max(1, total)*100, 2)}%)")

        # 仅针对本地 Ollama 引擎主动释放显存
        if engine_cfg.type == "ollama" or engine_cfg.requires_gpu:
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
            if not isinstance(data, list) or len(data) == 0:
                return False

            # 断言条目数不少于上游产物
            upstream_name = "ocr_raw.json" if ctx.mode == "ocr" else "asr_raw.json"
            raw_path = ctx.get_product_path(upstream_name)
            if raw_path.exists():
                with open(raw_path, "r", encoding="utf-8") as rf:
                    raw_data = json.load(rf)
                if len(data) < len(raw_data):
                    return False

            return True
        except Exception:
            return False
