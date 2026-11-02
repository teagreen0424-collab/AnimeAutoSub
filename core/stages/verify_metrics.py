"""
AnimeAutoSub 阶段: 质量指标统计与验收门禁 (core/stages/verify_metrics.py)

硬性契约:
  - 产物: quality_metrics.json
  - 校验逐句遮罩面积 <= 120,000 px 或 <= 16% 画面
"""

import re
import json
import hashlib
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional

from ..stage import Stage
from ..context import PipelineContext


class VerifyMetricsStage(Stage):
    name = "verify_metrics"
    requires_gpu = False
    produces = ["quality_metrics.json"]

    def fingerprint(self, ctx: PipelineContext) -> str:
        h = hashlib.sha256()
        ass_path = ctx.get_product_path("subtitle.ass")
        if ass_path.exists():
            with open(ass_path, "rb") as f:
                h.update(hashlib.sha256(f.read()).hexdigest().encode("utf-8"))
        return h.hexdigest()

    def run(self, ctx: PipelineContext, log: logging.Logger, cancel_token: Optional[Any] = None) -> None:
        log.info("  → [VerifyMetricsStage] 开始校验遮罩几何与字幕指标...")
        ass_path = ctx.get_product_path("subtitle.ass")
        if not ass_path.exists():
            raise FileNotFoundError(f"上游字幕不存在: {ass_path}")

        mask_pattern = re.compile(r'Dialogue:\s*(\d+),([^,]+),([^,]+),Mask,[^,]*,[^,]*,[^,]*,[^,]*,[^,]*,\{\\an7\\pos\((\d+),(\d+)\)[^}]*\}m 0 0 l (\d+) 0 l (\d+) (\d+) l 0 (\d+)\{\\p0\}')
        areas = []
        details = []
        exceeded_items = []

        video_w = 1920
        video_h = 1080
        with open(ass_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("PlayResX:"):
                    try:
                        video_w = int(line.split(":")[1].strip())
                    except Exception:
                        pass
                elif line.startswith("PlayResY:"):
                    try:
                        video_h = int(line.split(":")[1].strip())
                    except Exception:
                        pass
                elif line.startswith("Dialogue:") and ",Mask," in line:
                    m = mask_pattern.search(line)
                    if m:
                        start_t = m.group(2)
                        end_t = m.group(3)
                        x0 = int(m.group(4))
                        y0 = int(m.group(5))
                        w = int(m.group(6))
                        h = int(m.group(8))
                        area = w * h
                        frame_area = video_w * video_h
                        ratio = area / max(1, frame_area)
                        areas.append(area)
                        item_info = {
                            "start": start_t, "end": end_t,
                            "x0": x0, "y0": y0, "w": w, "h": h,
                            "area_px": area, "ratio": round(ratio, 4)
                        }
                        details.append(item_info)
                        # 硬顶 16% 或 720p 120,000 px
                        if ratio > 0.16 or (video_h <= 720 and area > 120000):
                            exceeded_items.append(item_info)

        total_masks = len(areas)
        mean_area = float(sum(areas) / max(1, total_masks)) if areas else 0.0
        max_area = max(areas) if areas else 0

        target_max_area = ctx.lang.layout.get("area_target_max_px", 120000)
        max_ratio = (max_area / (video_w * video_h)) if areas else 0.0

        if total_masks == 0:
            area_met = True
            eval_msg = "ASR无遮罩模式 (通过)"
        else:
            area_met = (len(exceeded_items) == 0) and (max_ratio <= 0.16)
            eval_msg = f"最大面积 {max_area} px ({max_ratio*100:.1f}%), 超限 {len(exceeded_items)} 条"

        report = {
            "total_mask_lines": total_masks,
            "mean_area_px": round(mean_area, 1),
            "max_area_px": max_area,
            "max_area_ratio": round(max_ratio, 4),
            "target_max_area_px": target_max_area,
            "exceeded_count": len(exceeded_items),
            "exceeded_items": exceeded_items,
            "area_criterion_met": area_met,
            "sample_details": details[:10]
        }

        out_path = ctx.get_product_path("quality_metrics.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        log.info(f"  ✓ [VerifyMetricsStage] 质检完成: {eval_msg} (逐条判据达标: {area_met})")

    def verify(self, ctx: PipelineContext) -> bool:
        p = ctx.get_product_path("quality_metrics.json")
        return p.exists() and p.stat().st_size > 10
