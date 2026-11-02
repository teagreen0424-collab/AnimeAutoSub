"""
AnimeAutoSub 阶段: 布局与自适应遮罩字幕生成 (core/stages/layout_ass.py)

硬性契约:
  - 布局参数全部从 ctx.lang.layout 外置档位读取，代码内严禁出现 820、180、68、3.2 等魔法数字
  - 产物: subtitle.ass, subtitle.srt
"""

import json
import hashlib
import numpy as np
from pathlib import Path
from typing import List, Dict, Any, Optional
import logging

from ..stage import Stage
from ..context import PipelineContext


def format_timestamp_ass(sec: float) -> str:
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    cs = int(round((sec - int(sec)) * 100))
    if cs == 100:
        cs = 99
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def format_timestamp_srt(sec: float) -> str:
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    ms = int(round((sec - int(sec)) * 1000))
    if ms == 1000:
        ms = 999
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


class LayoutAssStage(Stage):
    name = "layout_ass"
    requires_gpu = False
    produces = ["subtitle.ass", "subtitle.srt"]

    def fingerprint(self, ctx: PipelineContext) -> str:
        # 参数指纹: 布局档位字典 + 上游 chinese.json 内容哈希
        h = hashlib.sha256()
        layout_str = json.dumps(ctx.lang.layout, sort_keys=True)
        h.update(layout_str.encode("utf-8"))
        upstream = ctx.get_product_path("chinese.json")
        if upstream.exists():
            with open(upstream, "rb") as f:
                h.update(hashlib.sha256(f.read()).hexdigest().encode("utf-8"))
        return h.hexdigest()

    def auto_wrap(self, text: str, max_chars: int, puncts: List[str], enabled: bool) -> str:
        if not enabled or len(text) <= max_chars or "\\N" in text or "\n" in text:
            return text

        mid = len(text) // 2
        best_idx = -1
        best_dist = 999

        for p in puncts:
            idx = -1
            while True:
                idx = text.find(p, idx + 1)
                if idx == -1:
                    break
                cut = idx + len(p)
                dist = abs(cut - mid)
                if dist < best_dist and 3 <= cut <= len(text) - 3:
                    best_dist = dist
                    best_idx = cut

        if best_idx > 0:
            return text[:best_idx] + r"\N" + text[best_idx:]
        return text[:mid] + r"\N" + text[mid:]

    def run(self, ctx: PipelineContext, log: logging.Logger, cancel_token: Optional[Any] = None) -> None:
        log.info("  → [LayoutAssStage] 开始生成自适应排版与 ASS/SRT 字幕...")
        chinese_path = ctx.get_product_path("chinese.json")
        if not chinese_path.exists():
            raise FileNotFoundError(f"上游产物不存在: {chinese_path}")

        with open(chinese_path, "r", encoding="utf-8") as f:
            translated = json.load(f)

        layout = ctx.lang.layout
        overlay_style = layout.get("overlay_style", "replace_mask")
        auto_wrap_enabled = layout.get("auto_wrap", True)
        max_line_chars = layout.get("max_line_chars", 18)
        font_name = layout.get("font_name", "Microsoft YaHei")
        base_fontsize = layout.get("font_size", 68)
        is_bold = layout.get("bold", True)
        base_outline = layout.get("outline", 3.2)
        base_shadow = layout.get("shadow", 0.5)
        base_margin_v = layout.get("margin_v", 16)
        mask_padding = layout.get("mask_padding", 8)
        mask_grid_quant = layout.get("mask_grid_quant", 8)
        char_width_ratio = layout.get("char_width_ratio", 0.95)
        zh_width_padding_ref = layout.get("zh_width_padding_ref", 40.0)
        max_allowed_area_ratio = layout.get("max_allowed_area_ratio", 0.16)

        puncts = ctx.lang.text_rules.wrap_punctuations

        # 获取视频分辨率
        video_width = 1920
        video_height = 1080
        if translated and translated[0].get("video_w") and translated[0].get("video_h"):
            video_width = int(translated[0]["video_w"])
            video_height = int(translated[0]["video_h"])

        scale_y = video_height / 1080.0
        fontsize = max(18, int(round(base_fontsize * scale_y)))
        outline = round(base_outline * scale_y, 1)
        shadow = round(base_shadow * scale_y, 1)
        bold = -1 if is_bold else 0

        if overlay_style in ("replace_mask", "slim_box", "box"):
            styles_section = (
                f"Style: Mask,Arial,10,&H00000000,&H00000000,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1\n"
                f"Style: Default,{font_name},{fontsize},&H00FFFFFF,&H000000FF,&H00000000,&H00000000,{bold},0,0,0,100,100,0,0,1,{outline},{shadow},5,10,10,10,1"
            )
        elif overlay_style == "above":
            styles_section = f"Style: Default,{font_name},{fontsize},&H00FFFFFF,&H000000FF,&H00000000,&H00000000,{bold},0,0,0,100,100,0,0,1,{outline},{shadow},2,30,30,115,1"
        else:
            margin_v = max(10, int(round(base_margin_v * scale_y)))
            styles_section = f"Style: Default,{font_name},{fontsize},&H00FFFFFF,&H000000FF,&H00000000,&H00000000,{bold},0,0,0,100,100,0,0,1,{outline},{shadow},2,20,20,{margin_v},1"

        ass_header = f"""[Script Info]
Title: OCR Anime Subtitles
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709
PlayResX: {video_width}
PlayResY: {video_height}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
{styles_section}

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
        ass_lines = [ass_header]
        srt_lines = []
        srt_idx = 1

        for seg in translated:
            if cancel_token and cancel_token.is_cancelled():
                log.warning("  ⚠ 阶段收到取消信号，安全退出")
                return

            zh = seg.get("zh", "").strip()
            if not zh:
                continue

            zh_wrapped = self.auto_wrap(zh, max_line_chars, puncts, auto_wrap_enabled)
            start_ass = format_timestamp_ass(seg["start"])
            end_ass = format_timestamp_ass(seg["end"])

            if overlay_style in ("replace_mask", "slim_box", "box"):
                box = seg.get("box")
                if box is not None:
                    xmin, ymin, xmax, ymax = box
                else:
                    xmin = video_width * 0.15
                    ymin = video_height * 0.80
                    xmax = video_width * 0.85
                    ymax = video_height * 0.95

                raw_x0 = max(0.0, xmin - mask_padding)
                raw_y0 = max(0.0, ymin - mask_padding)
                raw_x1 = min(float(video_width), xmax + mask_padding)
                raw_y1 = min(float(video_height), ymax + mask_padding)

                # 网格量化
                y0 = max(0, int(np.floor(raw_y0 / mask_grid_quant) * mask_grid_quant))
                y1 = min(video_height, int(np.ceil(raw_y1 / mask_grid_quant) * mask_grid_quant))
                h = int(np.ceil((y1 - y0) / mask_grid_quant) * mask_grid_quant)
                y1 = min(video_height, y0 + h)

                # 中文字幕宽度安全防护 ("中文不压边")
                lines = zh_wrapped.split(r"\N")
                max_line_len = max(len(l) for l in lines) if lines else 0
                char_width = fontsize * char_width_ratio
                zh_width = max_line_len * char_width
                required_w = max(raw_x1 - raw_x0, zh_width + zh_width_padding_ref * (video_width / 1920.0))

                cx = (raw_x0 + raw_x1) / 2.0
                x0 = max(0, int(round(cx - required_w / 2.0)))
                x1 = min(video_width, int(round(cx + required_w / 2.0)))
                w = x1 - x0

                max_allowed_area = max_allowed_area_ratio * video_width * video_height
                if w * h > max_allowed_area and h > 0:
                    w = int(max_allowed_area / h)
                    x0 = max(0, int(round(cx - w / 2.0)))

                cx = int(round(x0 + w / 2.0))
                cy = int(round(y0 + h / 2.0))
                mask_opacity = layout.get("mask_opacity", "00")
                mask_line = (
                    f"Dialogue: 0,{start_ass},{end_ass},Mask,,0,0,0,,"
                    f"{{\\an7\\pos({x0},{y0})\\p1\\c&H0a0a0a&\\1a&H{mask_opacity}&}}"
                    f"m 0 0 l {w} 0 l {w} {h} l 0 {h}{{\\p0}}"
                )
                sub_line = (
                    f"Dialogue: 1,{start_ass},{end_ass},Default,,0,0,0,,"
                    f"{{\\an5\\pos({cx},{cy})}}{zh_wrapped}"
                )
                ass_lines.append(mask_line)
                ass_lines.append(sub_line)
            else:
                line = f"Dialogue: 0,{start_ass},{end_ass},Default,,0,0,0,,{zh_wrapped}"
                ass_lines.append(line)

            # SRT 行
            start_srt = format_timestamp_srt(seg["start"])
            end_srt = format_timestamp_srt(seg["end"])
            srt_text = zh_wrapped.replace(r"\N", "\n")
            srt_lines.append(f"{srt_idx}\n{start_srt} --> {end_srt}\n{srt_text}\n")
            srt_idx += 1

        ass_path = ctx.get_product_path("subtitle.ass")
        srt_path = ctx.get_product_path("subtitle.srt")

        with open(ass_path, "w", encoding="utf-8") as f:
            f.write("\n".join(ass_lines) + "\n")
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write("\n".join(srt_lines) + "\n")

        log.info(f"  ✓ [LayoutAssStage] 字幕生成完毕: {ass_path.name}, {srt_path.name}")

    def verify(self, ctx: PipelineContext) -> bool:
        ass_path = ctx.get_product_path("subtitle.ass")
        srt_path = ctx.get_product_path("subtitle.srt")
        if not ass_path.exists() or ass_path.stat().st_size < 100:
            return False
        if not srt_path.exists() or srt_path.stat().st_size < 10:
            return False
        with open(ass_path, "r", encoding="utf-8") as f:
            content = f.read()
            if "[Script Info]" not in content or "[Events]" not in content:
                return False
        return True
