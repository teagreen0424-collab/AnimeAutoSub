"""
AnimeAutoSub 阶段: 视频硬字幕检测与 OCR 提取 (core/stages/ocr_extract.py)

硬性契约:
  - requires_gpu = True
  - 产物: ocr_raw.json (兼写入 japanese.json 保持兼容)
  - 严格保持 P2 稳定平原中点提取、HEURISTIC cuDNN 配置、GPU 强校验与帧差变动检测跳过
"""

import sys
import os
import json
import time
import hashlib
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
from difflib import SequenceMatcher
import re
import cv2
import numpy as np

from ..stage import Stage
from ..context import PipelineContext
from ..gpu_lease import acquire_gpu_lease


def is_timecode_or_noise(text: str) -> bool:
    t = text.strip()
    if not t:
        return True
    if re.match(r'^\d{1,2}:\d{2}(:\d{2})?\s*/\s*\d{1,2}:\d{2}(:\d{2})?$', t):
        return True
    if re.match(r'^\d{1,2}:\d{2}(:\d{2})?$', t):
        return True
    if len(t) <= 1 and not ('\u4e00' <= t <= '\u9fff' or '\u3040' <= t <= '\u30ff' or '\uac00' <= t <= '\ud7af'):
        return True
    return False


def extract_ocr_result(out, lang: str = "japan") -> tuple:
    if out is None or out.boxes is None or len(out.boxes) == 0:
        return "", []

    boxes = out.boxes
    txts = out.txts or []
    scores = out.scores or []

    line_items = []
    for box, txt, score in zip(boxes, txts, scores):
        t = txt.strip()
        if is_timecode_or_noise(t):
            continue
        xs = [pt[0] for pt in box]
        ys = [pt[1] for pt in box]
        xmin, ymin, xmax, ymax = min(xs), min(ys), max(xs), max(ys)
        cy = (ymin + ymax) / 2.0
        line_items.append((cy, xmin, t, [xmin, ymin, xmax, ymax]))

    if not line_items:
        return "", []

    line_items.sort(key=lambda item: item[0])

    lines = []
    cur_line = [line_items[0]]
    for item in line_items[1:]:
        if abs(item[0] - cur_line[-1][0]) <= 15:
            cur_line.append(item)
        else:
            lines.append(cur_line)
            cur_line = [item]
    lines.append(cur_line)

    valid_lines = []
    line_boxes = []
    for line in lines:
        line.sort(key=lambda item: item[1])
        t_line = "".join(item[2] for item in line)
        if t_line:
            valid_lines.append(t_line)
            l_xmin = min(item[3][0] for item in line)
            l_ymin = min(item[3][1] for item in line)
            l_xmax = max(item[3][2] for item in line)
            l_ymax = max(item[3][3] for item in line)
            line_boxes.append([l_xmin, l_ymin, l_xmax, l_ymax])

    join_sep = "" if lang in ("japan", "ch", "zh", "ko", "korean") else " "
    return join_sep.join(valid_lines), line_boxes


def text_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def select_stable_midpoint_text(samples: list, min_stable_frames: int = 2, sim_thresh: float = 0.80) -> str:
    if not samples:
        return ""
    if len(samples) == 1:
        return samples[0][1]

    plateaus = []
    current_plateau = [samples[0]]
    for i in range(1, len(samples)):
        sim = text_similarity(samples[i - 1][1], samples[i][1])
        if sim >= sim_thresh:
            current_plateau.append(samples[i])
        else:
            if len(current_plateau) >= min_stable_frames:
                plateaus.append(current_plateau)
            current_plateau = [samples[i]]
    if len(current_plateau) >= min_stable_frames:
        plateaus.append(current_plateau)

    if plateaus:
        longest = max(plateaus, key=len)
        mid_idx = len(longest) // 2
        return longest[mid_idx][1]

    mid_idx = len(samples) // 2
    return samples[mid_idx][1]


def finalize_segment(seg: dict, video_w: int, video_h: int) -> dict:
    samples = seg.get("samples", [])
    selected_text = select_stable_midpoint_text(samples)
    seg["text"] = selected_text
    seg["video_w"] = video_w
    seg["video_h"] = video_h

    valid_boxes = []
    for s in samples:
        if len(s) > 2 and s[2]:
            if text_similarity(s[1], selected_text) >= 0.80:
                valid_boxes.extend(s[2])

    if not valid_boxes:
        for s in samples:
            if len(s) > 2 and s[2]:
                valid_boxes.extend(s[2])

    if valid_boxes:
        xmin = float(min(b[0] for b in valid_boxes))
        ymin = float(min(b[1] for b in valid_boxes))
        xmax = float(max(b[2] for b in valid_boxes))
        ymax = float(max(b[3] for b in valid_boxes))
        seg["box"] = [round(xmin, 1), round(ymin, 1), round(xmax, 1), round(ymax, 1)]
    else:
        seg["box"] = [
            round(video_w * 0.15, 1),
            round(video_h * 0.80, 1),
            round(video_w * 0.85, 1),
            round(video_h * 0.95, 1),
        ]

    seg.pop("samples", None)
    return seg


def build_ocr_engine_instance(use_cuda: bool = True, rec_lang: str = "japan"):
    from rapidocr.utils.log import logger as rapidocr_logger
    rapidocr_logger.setLevel(logging.ERROR)
    for h in rapidocr_logger.handlers:
        h.setLevel(logging.ERROR)
    from rapidocr import RapidOCR

    ocr_params = {}
    if use_cuda:
        ocr_params["EngineConfig.onnxruntime.use_cuda"] = True
        ocr_params["EngineConfig.onnxruntime.cuda_ep_cfg.cudnn_conv_algo_search"] = "HEURISTIC"

    if rec_lang in ("korean", "ko"):
        from rapidocr import OCRVersion, LangRec, ModelType
        ocr_params["Rec.ocr_version"] = OCRVersion.PPOCRV5
        ocr_params["Rec.lang_type"] = LangRec.KOREAN
        ocr_params["Rec.model_type"] = ModelType.MOBILE
        # 视频字幕方向固定为水平，禁用文档级方向分类器 (防止韩文笔画被误判为 180 度翻转颠倒)
        ocr_params["Global.use_cls"] = False

    engine = RapidOCR(params=ocr_params)
    engine._load_det_model()
    engine._load_rec_model()

    if use_cuda:
        det_session = getattr(engine.text_det.session, "session", None)
        rec_session = getattr(engine.text_rec.session, "session", None)
        if det_session is None or rec_session is None:
            raise RuntimeError("OCR Det/Rec 会话未能成功初始化！")
        det_providers = det_session.get_providers()
        rec_providers = rec_session.get_providers()
        if not det_providers or det_providers[0] != "CUDAExecutionProvider":
            raise RuntimeError(f"OCR Det 模型未能加载 CUDAExecutionProvider！实际: {det_providers}")
        if not rec_providers or rec_providers[0] != "CUDAExecutionProvider":
            raise RuntimeError(f"OCR Rec 模型未能加载 CUDAExecutionProvider！实际: {rec_providers}")
    return engine


class OcrExtractStage(Stage):
    name = "ocr_extract"
    requires_gpu = True
    produces = ["ocr_raw.json", "japanese.json"]

    def fingerprint(self, ctx: PipelineContext) -> str:
        h = hashlib.sha256()
        ocr_cfg = ctx.lang.ocr
        params = {
            "engine": ocr_cfg.engine_name,
            "sample_fps": ocr_cfg.sample_fps,
            "min_duration_sec": ocr_cfg.min_duration_sec,
            "roi_bottom_percent": ocr_cfg.roi_bottom_percent,
            "similarity_thresh": ocr_cfg.similarity_thresh,
            "rec_lang": ocr_cfg.rec_lang
        }
        h.update(json.dumps(params, sort_keys=True).encode("utf-8"))
        if ctx.video_path.exists():
            h.update(f"{ctx.video_path.stat().st_size}_{ctx.video_path.stat().st_mtime}".encode("utf-8"))
        return h.hexdigest()

    def run(self, ctx: PipelineContext, log: logging.Logger, cancel_token: Optional[Any] = None) -> None:
        log.info(f"  → [OcrExtractStage] 启动视频硬字幕高精度提取: {ctx.video_path.name}")
        ocr_raw_path = ctx.get_product_path("ocr_raw.json")
        japanese_path = ctx.get_product_path("japanese.json")

        sample_fps = ctx.lang.ocr.sample_fps
        roi_bottom_pct = ctx.lang.ocr.roi_bottom_percent
        min_duration_sec = ctx.lang.ocr.min_duration_sec
        similarity_thresh = ctx.lang.ocr.similarity_thresh
        rec_lang = ctx.lang.ocr.rec_lang

        with acquire_gpu_lease(required_vram_mb=1200):
            ocr_engine = build_ocr_engine_instance(use_cuda=ctx.lang.ocr.use_cuda, rec_lang=rec_lang)

            cap = cv2.VideoCapture(str(ctx.video_path))
            if not cap.isOpened():
                raise RuntimeError(f"无法打开视频: {ctx.video_path}")

            fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            duration_sec = total_frames / fps
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

            roi_top = int(height * (1.0 - roi_bottom_pct))
            sample_step = max(1, int(fps / sample_fps))
            sample_interval_sec = sample_step / fps

            segments = []
            current_seg = None
            last_roi_gray = None
            last_ocr_text = ""
            last_ocr_boxes = []

            frame_idx = 0
            last_log_sec = 0

            try:
                while True:
                    if cancel_token and cancel_token.is_cancelled():
                        log.warning("  ⚠ 阶段收到取消信号，中止提取")
                        return

                    if frame_idx % sample_step == 0:
                        ret, frame = cap.read()
                        if not ret:
                            break
                        curr_sec = frame_idx / fps

                        if curr_sec - last_log_sec >= 30:
                            pct = (curr_sec / duration_sec) * 100 if duration_sec > 0 else 0
                            log.info(f"    ⏳ OCR 进度: {curr_sec/60:.1f}/{duration_sec/60:.1f}m ({pct:.1f}%), 已提取 {len(segments)} 句")
                            last_log_sec = curr_sec

                        roi = frame[roi_top:height, 0:width]
                        roi_gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)

                        diff = 1.0
                        if last_roi_gray is not None:
                            diff = np.mean(cv2.absdiff(roi_gray, last_roi_gray)) / 255.0
                        last_roi_gray = roi_gray

                        diff_thresh_ratio = (ctx.lang.ocr.frame_diff_thresh / 255.0) if ctx.lang.ocr.frame_diff_thresh > 1.0 else ctx.lang.ocr.frame_diff_thresh
                        if diff < diff_thresh_ratio:
                            detected_text = last_ocr_text
                            detected_boxes = last_ocr_boxes
                        else:
                            if np.std(roi_gray) < 12:
                                detected_text = ""
                                detected_boxes = []
                            else:
                                out = ocr_engine(roi)
                                detected_text, raw_boxes = extract_ocr_result(out, lang=rec_lang)
                                detected_boxes = []
                                for b in raw_boxes:
                                    detected_boxes.append([b[0], b[1] + roi_top, b[2], b[3] + roi_top])

                        last_ocr_text = detected_text
                        last_ocr_boxes = detected_boxes

                        if detected_text:
                            if current_seg is None:
                                current_seg = {
                                    "start": round(curr_sec, 2),
                                    "end": round(curr_sec + sample_interval_sec, 2),
                                    "samples": [(round(curr_sec, 2), detected_text, detected_boxes)]
                                }
                            else:
                                last_text = current_seg["samples"][-1][1]
                                sim = text_similarity(detected_text, last_text)
                                is_adjacent = (curr_sec - current_seg["end"]) <= (sample_interval_sec * 2.0)

                                if sim >= similarity_thresh and is_adjacent:
                                    current_seg["end"] = round(curr_sec + sample_interval_sec, 2)
                                    current_seg["samples"].append((round(curr_sec, 2), detected_text, detected_boxes))
                                else:
                                    if (current_seg["end"] - current_seg["start"]) >= min_duration_sec:
                                        segments.append(finalize_segment(current_seg, width, height))
                                    current_seg = {
                                        "start": round(curr_sec, 2),
                                        "end": round(curr_sec + sample_interval_sec, 2),
                                        "samples": [(round(curr_sec, 2), detected_text, detected_boxes)]
                                    }
                        else:
                            if current_seg is not None:
                                if (current_seg["end"] - current_seg["start"]) >= min_duration_sec:
                                    segments.append(finalize_segment(current_seg, width, height))
                                current_seg = None
                    else:
                        ret = cap.grab()
                        if not ret:
                            break

                    frame_idx += 1

                if current_seg is not None and (current_seg["end"] - current_seg["start"]) >= min_duration_sec:
                    segments.append(finalize_segment(current_seg, width, height))

            finally:
                cap.release()

        with open(ocr_raw_path, "w", encoding="utf-8") as f:
            json.dump(segments, f, ensure_ascii=False, indent=2)
        with open(japanese_path, "w", encoding="utf-8") as f:
            json.dump(segments, f, ensure_ascii=False, indent=2)

        log.info(f"  ✓ [OcrExtractStage] OCR 提取完成，共聚类有效字幕 {len(segments)} 句 -> {ocr_raw_path.name}")

    def verify(self, ctx: PipelineContext) -> bool:
        p1 = ctx.get_product_path("ocr_raw.json")
        p2 = ctx.get_product_path("japanese.json")
        if not p1.exists() or p1.stat().st_size < 10:
            return False
        if not p2.exists():
            return False
        try:
            with open(p1, "r", encoding="utf-8") as f:
                data = json.load(f)
                return isinstance(data, list)
        except Exception:
            return False
