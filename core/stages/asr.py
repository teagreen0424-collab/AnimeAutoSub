"""
AnimeAutoSub 阶段: 语音 ASR 转写 (core/stages/asr.py)

复用于 ja-asr 与 ko-asr，统一调用 faster-whisper large-v3。
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


class AsrStage(Stage):
    name = "asr"
    requires_gpu = True
    produces = ["asr_raw.json"]

    def fingerprint(self, ctx: PipelineContext) -> str:
        h = hashlib.sha256()
        asr_cfg = ctx.lang.asr
        params = {
            "model": asr_cfg.model_name,
            "lang": asr_cfg.language_code,
            "beam_size": asr_cfg.beam_size,
            "vad": asr_cfg.vad_filter
        }
        h.update(json.dumps(params, sort_keys=True).encode("utf-8"))
        if ctx.video_path.exists():
            h.update(f"{ctx.video_path.stat().st_size}_{ctx.video_path.stat().st_mtime}".encode("utf-8"))
        return h.hexdigest()

    def run(self, ctx: PipelineContext, log: logging.Logger, cancel_token: Optional[Any] = None) -> None:
        log.info(f"  → [AsrStage] 启动 Whisper ASR 语音识别 (语言: [{ctx.lang.asr.language_code}], 模型: [{ctx.lang.asr.model_name}])...")
        output_path = ctx.get_product_path("asr_raw.json")

        # 检查输入音频源 (若传入视频则先提取音频，或直接使用音频文件)
        input_audio = ctx.video_path
        if input_audio.suffix.lower() in [".mp4", ".mkv", ".avi", ".webm"]:
            # 临时抽取 wav 音频
            extracted_wav = ctx.work_dir / "extracted_audio.wav"
            if not extracted_wav.exists():
                log.info("    从视频中抽取音频流...")
                import subprocess
                subprocess.run([
                    r"D:\Dev\ffmpeg\bin\ffmpeg.exe", "-y",
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
