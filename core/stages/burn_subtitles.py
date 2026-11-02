"""
AnimeAutoSub 阶段: 视频字幕烧录压制 (core/stages/burn_subtitles.py)

硬性契约:
  - 产物: output.mp4
  - 使用 FFmpeg libx264 crf=20 preset=fast 进行高质量原画无损压制
"""

import os
import hashlib
import logging
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional

from ..stage import Stage
from ..context import PipelineContext

FFMPEG_PATH = r"D:\Dev\ffmpeg\bin\ffmpeg.exe"


class BurnSubtitlesStage(Stage):
    name = "burn_subtitles"
    requires_gpu = False
    produces = ["output.mp4"]

    def fingerprint(self, ctx: PipelineContext) -> str:
        h = hashlib.sha256()
        h.update(b"libx264_crf20_preset_fast")
        ass_path = ctx.get_product_path("subtitle.ass")
        if ass_path.exists():
            with open(ass_path, "rb") as f:
                h.update(hashlib.sha256(f.read()).hexdigest().encode("utf-8"))
        return h.hexdigest()

    def run(self, ctx: PipelineContext, log: logging.Logger, cancel_token: Optional[Any] = None) -> None:
        log.info("  → [BurnSubtitlesStage] 开始执行 FFmpeg 压制成片...")
        ass_path = ctx.get_product_path("subtitle.ass")
        if not ass_path.exists():
            raise FileNotFoundError(f"上游字幕不存在: {ass_path}")

        output_path = ctx.get_product_path("output.mp4")
        if output_path.exists():
            try:
                output_path.unlink()
            except Exception:
                pass

        # Windows 路径转义 (处理冒号与反斜杠)
        ass_filter_path = str(ass_path.resolve()).replace("\\", "/").replace(":", "\\:")
        is_audio = ctx.video_path.suffix.lower() in [".mp3", ".wav", ".m4a", ".aac", ".flac"]

        if is_audio:
            cmd = [
                FFMPEG_PATH,
                "-y",
                "-f", "lavfi", "-i", "color=c=0x111111:s=1280x720:r=24",
                "-i", str(ctx.video_path),
                "-vf", f"subtitles='{ass_filter_path}'",
                "-c:v", "libx264",
                "-crf", "20",
                "-preset", "fast",
                "-c:a", "aac",
                "-shortest",
                "-v", "warning",
                str(output_path)
            ]
        else:
            cmd = [
                FFMPEG_PATH,
                "-y",
                "-i", str(ctx.video_path),
                "-vf", f"subtitles='{ass_filter_path}'",
                "-c:v", "libx264",
                "-crf", "20",
                "-preset", "fast",
                "-c:a", "copy",
                "-v", "warning",
                str(output_path)
            ]

        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        while proc.poll() is None:
            if cancel_token and cancel_token.is_cancelled():
                log.warning("  ⚠ 阶段收到取消信号，中止压制")
                proc.kill()
                if output_path.exists():
                    output_path.unlink()
                return
            try:
                proc.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                pass

        if proc.returncode != 0:
            err = proc.stderr.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"FFmpeg 压制失败 (退出码 {proc.returncode}): {err[:500]}")

        log.info(f"  ✓ [BurnSubtitlesStage] 压制完成 -> {output_path.name} (大小: {output_path.stat().st_size / (1024*1024):.1f} MB)")

    def verify(self, ctx: PipelineContext) -> bool:
        p = ctx.get_product_path("output.mp4")
        return p.exists() and p.stat().st_size > 10 * 1024
