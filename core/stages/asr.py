"""
AnimeAutoSub 阶段: 语音 ASR 转写 (core/stages/asr.py)

支持本地 Whisper (large-v3) 与云端 API (硅基流动 SenseVoiceSmall 等)。
产物: asr_raw.json
"""

import json
import hashlib
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional

from ..stage import Stage
from ..context import PipelineContext
from ..gpu_lease import acquire_gpu_lease
from ..asr_engine import get_asr_engine_config, extract_audio_for_api, transcribe_via_api
from ..translation_engine import redact_secrets


class AsrStage(Stage):
    name = "asr"
    produces = ["asr_raw.json"]

    @property
    def requires_gpu(self) -> bool:
        """根据当前配置的 ASR 引擎动态决定是否需要 GPU 租约 (云端 API 零 GPU 依赖)"""
        ctx = getattr(self, "ctx", None)
        if ctx:
            engine_id = getattr(ctx, "asr_engine_id", None) or (
                ctx.custom_params.get("asr_engine_id") if hasattr(ctx, "custom_params") and ctx.custom_params else None
            )
            cfg = get_asr_engine_config(engine_id)
            return cfg.requires_gpu
        return False

    def fingerprint(self, ctx: PipelineContext) -> str:
        h = hashlib.sha256()
        asr_engine_id = getattr(ctx, "asr_engine_id", None) or (
            ctx.custom_params.get("asr_engine_id") if hasattr(ctx, "custom_params") and ctx.custom_params else None
        )
        asr_cfg = get_asr_engine_config(asr_engine_id)
        params = {
            "engine_id": asr_cfg.id,
            "engine_type": asr_cfg.type,
            "engine_model": asr_cfg.model_name,
            "engine_api_url": asr_cfg.api_url,
            "lang": ctx.lang.asr.language_code,
            "beam_size": ctx.lang.asr.beam_size,
            "vad": ctx.lang.asr.vad_filter
        }
        h.update(json.dumps(params, sort_keys=True).encode("utf-8"))
        if ctx.video_path.exists():
            h.update(f"{ctx.video_path.stat().st_size}_{ctx.video_path.stat().st_mtime}".encode("utf-8"))
        return h.hexdigest()

    def run(self, ctx: PipelineContext, log: logging.Logger, cancel_token: Optional[Any] = None) -> None:
        asr_engine_id = getattr(ctx, "asr_engine_id", None) or (
            ctx.custom_params.get("asr_engine_id") if hasattr(ctx, "custom_params") and ctx.custom_params else None
        )
        engine_cfg = get_asr_engine_config(asr_engine_id)

        log.info(f"  → [AsrStage] 启动 ASR 语音识别 (引擎: [{engine_cfg.name}], 模型: [{engine_cfg.model_name}], GPU需求: {engine_cfg.requires_gpu})...")
        output_path = ctx.get_product_path("asr_raw.json")

        if engine_cfg.type == "api":
            # === 云端 API 语音识别 (硅基流动 SenseVoiceSmall 等) ===
            audio_file = extract_audio_for_api(ctx.video_path, ctx.work_dir, log)
            if cancel_token and cancel_token.is_cancelled():
                log.warning("  ⚠ 阶段收到取消信号，中止 ASR")
                return

            results = transcribe_via_api(
                audio_path=audio_file,
                engine_cfg=engine_cfg,
                language_code=ctx.lang.asr.language_code,
                log=log
            )

        else:
            # === 本地 Whisper 离线推理 (需 4GB+ 显存) ===
            input_audio = ctx.video_path
            if input_audio.suffix.lower() in [".mp4", ".mkv", ".avi", ".webm"]:
                extracted_wav = ctx.work_dir / "extracted_audio.wav"
                if not extracted_wav.exists():
                    log.info("    从视频中抽取音频流...")
                    import subprocess
                    ffmpeg_bin = r"D:\Dev\ffmpeg\bin\ffmpeg.exe"
                    if not Path(ffmpeg_bin).exists():
                        ffmpeg_bin = "ffmpeg"
                    subprocess.run([
                        str(ffmpeg_bin), "-y",
                        "-i", str(input_audio),
                        "-vn", "-ac", "1", "-ar", "16000",
                        str(extracted_wav)
                    ], check=True, capture_output=True)
                audio_source = extracted_wav
            else:
                audio_source = input_audio

            with acquire_gpu_lease(required_vram_mb=3000):
                from faster_whisper import WhisperModel
                log.info("    正在加载 faster-whisper 模型...")
                local_whisper = Path(r"D:\Dev\huggingface\models--faster-whisper-large-v3")
                if (ctx.lang.asr.model_name in ("large-v3", "large")) and local_whisper.exists():
                    model_path = str(local_whisper)
                else:
                    model_path = ctx.lang.asr.model_name

                model = WhisperModel(
                    model_path,
                    device="cuda",
                    compute_type="float16"
                )

                segments, info = model.transcribe(
                    str(audio_source),
                    language=ctx.lang.asr.language_code,
                    beam_size=ctx.lang.asr.beam_size,
                    vad_filter=ctx.lang.asr.vad_filter,
                    word_timestamps=True
                )

                results = []
                for s in segments:
                    if cancel_token and cancel_token.is_cancelled():
                        log.warning("  ⚠ 阶段收到取消信号，中止 ASR")
                        return
                    words = list(s.words or [])
                    if words:
                        cur_words = []
                        for w in words:
                            cur_words.append(w)
                            if w.word.strip().endswith((".", "?", "!", "。", "？", "！")):
                                text_sub = "".join(x.word for x in cur_words).strip()
                                if text_sub:
                                    results.append({
                                        "start": round(cur_words[0].start, 2),
                                        "end": round(cur_words[-1].end, 2),
                                        "text": text_sub,
                                        "words": [{"word": x.word, "start": round(x.start, 2), "end": round(x.end, 2)} for x in cur_words]
                                    })
                                cur_words = []
                        if cur_words:
                            text_sub = "".join(x.word for x in cur_words).strip()
                            if text_sub:
                                results.append({
                                    "start": round(cur_words[0].start, 2),
                                    "end": round(cur_words[-1].end, 2),
                                    "text": text_sub,
                                    "words": [{"word": x.word, "start": round(x.start, 2), "end": round(x.end, 2)} for x in cur_words]
                                })
                    else:
                        t = s.text.strip()
                        if t:
                            results.append({
                                "start": round(s.start, 2),
                                "end": round(s.end, 2),
                                "text": t,
                                "words": []
                            })

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)

        # 在 manifest.json 中登记 ASR 引擎与片段数
        manifest_file = ctx.work_dir / "manifest.json"
        if manifest_file.exists():
            try:
                with open(manifest_file, "r", encoding="utf-8") as mf_f:
                    mf_data = json.load(mf_f)
                if "stages" not in mf_data:
                    mf_data["stages"] = {}
                if "asr" not in mf_data["stages"]:
                    mf_data["stages"]["asr"] = {}
                mf_data["stages"]["asr"]["asr_engine_id"] = engine_cfg.id
                mf_data["stages"]["asr"]["asr_model_name"] = engine_cfg.model_name
                mf_data["stages"]["asr"]["segments_count"] = len(results)
                mf_data["asr_engine_id"] = engine_cfg.id
                with open(manifest_file, "w", encoding="utf-8") as mf_f:
                    json.dump(mf_data, mf_f, ensure_ascii=False, indent=2)
            except Exception:
                pass

        log.info(f"  ✓ [AsrStage] 语音识别完成，共识别 {len(results)} 句 -> {output_path.name}")

    def verify(self, ctx: PipelineContext) -> bool:
        p = ctx.get_product_path("asr_raw.json")
        if not p.exists() or p.stat().st_size < 10:
            return False
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            return isinstance(data, list)
        except Exception:
            return False
