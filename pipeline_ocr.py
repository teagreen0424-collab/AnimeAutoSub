"""
视频硬字幕全自动 OCR 提取与翻译流水线
======================================
专为画面底部带有日文硬字幕、而音频中无台词（如 ASMR、心理描写、视觉小说）的作品设计。

流程：
  输入视频 → 画面变动检测 → RapidOCR 提取日文字幕与时间轴 → Sakura-14B 翻译 → 遮罩排版 → MKV/MP4 封装
"""

import animeautosub._env  # 必须在最顶层导入，注入 D:\Dev 路径纪律与 Windows CUDA/cuDNN DLL

import sys
import os
import json
import time
import shutil
import logging
import subprocess
from pathlib import Path
from datetime import datetime
import difflib
from difflib import SequenceMatcher
import re

import cv2
import numpy as np
import requests

from config_ocr import (
    PROJECT_DIR, OCR_INPUT_DIR, OCR_OUTPUT_DIR, GLOSSARY_DIR,
    FFMPEG_PATH,
    OCR_ROI_BOTTOM_PERCENT, OCR_SAMPLE_FPS, OCR_FRAME_DIFF_THRESH,
    OCR_MIN_DURATION_SEC, OCR_SIMILARITY_THRESH,
    OCR_USE_CUDA,
    SUBTITLE_OVERLAY_STYLE, AUTO_WRAP_SUBTITLE, SUBTITLE_MAX_LINE_CHARS,
    MASK_PADDING, MASK_GRID_QUANT, MASK_OPACITY,
    SUBTITLE_FONT, SUBTITLE_FONTSIZE, SUBTITLE_BOLD,
    SUBTITLE_OUTLINE, SUBTITLE_SHADOW, SUBTITLE_MARGIN_V,
    OLLAMA_API_URL, SAKURA_MODEL_NAME, CONTEXT_LINES,
    TEMPERATURE, TOP_P, MAX_RETRIES, SAKURA_SYSTEM_PROMPT,
    OUTPUT_MODE, HARDCODED_CRF, HARDCODED_PRESET, VIDEO_EXTENSIONS,
)

# ======================================================================
#                              日志配置
# ======================================================================

def setup_logging():
    log_dir = PROJECT_DIR / "logs_ocr"
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / f"{datetime.now():%Y%m%d_%H%M%S}.log"

    formatter = logging.Formatter(
        "%(asctime)s  %(message)s",
        datefmt="%H:%M:%S"
    )

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.INFO)

    file_handler = logging.FileHandler(str(log_file), encoding="utf-8")
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.handlers.clear()
    root.addHandler(console_handler)
    root.addHandler(file_handler)

    return log_file


# ======================================================================
#                              环境自检
# ======================================================================

def check_environment():
    logging.info("=" * 60)
    logging.info("  环境检查 (视频硬字幕 OCR 模式)")
    logging.info("=" * 60)

    # 1. 检查 GPU
    try:
        import torch
        if torch.cuda.is_available():
            gpu_name = torch.cuda.get_device_name(0)
            logging.info(f"  ✓ GPU: {gpu_name}")
        else:
            logging.warning("  ⚠ 未检测到可用 GPU，将以 CPU 运行")
    except Exception:
        pass

    # 2. 检查 FFmpeg
    try:
        r = subprocess.run([FFMPEG_PATH, "-version"], capture_output=True, text=True)
        if r.returncode == 0:
            first_line = r.stdout.splitlines()[0] if r.stdout else ""
            logging.info(f"  ✓ FFmpeg: {first_line[:50]}")
        else:
            logging.error(f"  ✗ FFmpeg 无法执行: {FFMPEG_PATH}")
            return False
    except Exception as e:
        logging.error(f"  ✗ 找不到 FFmpeg: {e}")
        return False

    # 3. 检查 Ollama 服务与 Sakura-14B 模型 (统一使用 127.0.0.1 避免 IPv6 超时)
    ollama_ok = False
    try:
        r = requests.get("http://127.0.0.1:11434/api/tags", timeout=3)
        if r.status_code == 200:
            models = [m["name"] for m in r.json().get("models", [])]
            if any(SAKURA_MODEL_NAME in m for m in models):
                logging.info(f"  ✓ Ollama 运行中，模型 [{SAKURA_MODEL_NAME}] 已就绪")
                ollama_ok = True
            else:
                logging.error(f"  ✗ Ollama 未找到模型 [{SAKURA_MODEL_NAME}]")
                return False
    except Exception:
        pass

    if not ollama_ok:
        ollama_exe = Path(r"D:\Dev\ollama\ollama.exe")
        if ollama_exe.exists():
            logging.info("  → 正在后台静默启动 Ollama 服务...")
            env = os.environ.copy()
            env["OLLAMA_MODELS"] = r"D:\Dev\ollama\models"
            DETACHED_PROCESS = 0x00000008
            subprocess.Popen(
                [str(ollama_exe), "serve"],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=DETACHED_PROCESS if os.name == 'nt' else 0
            )
            time.sleep(3)
            return True
        else:
            logging.error("  ✗ 无法连接 Ollama 且本地未找到 ollama.exe")
            return False

    return True


# ======================================================================
#             Stage 1: 视频硬字幕检测与 OCR 提取 (RapidOCR)
# ======================================================================

def is_timecode_or_noise(text: str) -> bool:
    """过滤播放器时间码（如 01:17/08:08）或纯无意义符号"""
    t = text.strip()
    if not t:
        return True
    # 纯时间码
    if re.match(r'^\d{1,2}:\d{2}(:\d{2})?\s*/\s*\d{1,2}:\d{2}(:\d{2})?$', t):
        return True
    if re.match(r'^\d{1,2}:\d{2}(:\d{2})?$', t):
        return True
    # 纯标点或单个英文字母
    if len(t) <= 1 and not ('\u4e00' <= t <= '\u9fff' or '\u3040' <= t <= '\u30ff'):
        return True
    return False


def clean_ocr_text(lines: list, lang: str = "japan") -> str:
    """清理并拼接一帧内识别出的多行字幕文本。
    
    - 日语/中文无词间空格，默认使用空字符串直接连接，避免在句中强插空格污染 japanese.json 及下游翻译；
    - 西欧等使用空格分词的语言，保留单个空格拼接；
    - 确保若已包含换行语义（\\N 或 \\n），原样完整保留，不被吞掉。
    """
    valid_lines = []
    for l in lines:
        cleaned = l.strip()
        if not is_timecode_or_noise(cleaned):
            valid_lines.append(cleaned)
    if not valid_lines:
        return ""
    
    join_sep = "" if lang in ("japan", "ch", "zh") else " "
    return join_sep.join(valid_lines)


def text_similarity(a: str, b: str) -> float:
    """计算两句话的文字相似度"""
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def select_stable_midpoint_text(samples: list, min_stable_frames: int = 2, sim_thresh: float = 0.80) -> str:
    """
    P2 生产规则：从同一句字幕的所有采样帧中，提取稳定平原区（plateau）的中点帧文本。
    杜绝取首帧（淡入过渡态残片）或尾帧（淡出过渡态残片）。
    
    samples: list of (timestamp_sec, text)
    """
    if not samples:
        return ""
    if len(samples) == 1:
        return samples[0][1]

    # 寻找连续相似度 >= sim_thresh 的稳定片段 (plateaus)
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
        # 选取最长稳定平原区的几何中点帧
        best_plateau = max(plateaus, key=len)
        mid_idx = len(best_plateau) // 2
        return best_plateau[mid_idx][1]
    else:
        # 回退：取整体采样区间的时间中点帧
        mid_idx = len(samples) // 2
        return samples[mid_idx][1]


def finalize_segment(seg: dict, video_w: int, video_h: int) -> dict:
    """
    闭合字幕分段 (P2 + R1 综合治理)：
    1. 使用 P2 稳定中点帧选取最具代表性的日语文本；
    2. 计算该句所有稳定帧 OCR 检测框的并集 [xmin, ymin, xmax, ymax] 供 R1 自适应遮罩使用；
    3. 写入 video_w, video_h 保证下游排版 100% 对齐。
    """
    samples = seg.get("samples", [])
    if not samples:
        return seg

    selected_text = select_stable_midpoint_text(samples)
    seg["text"] = selected_text
    seg["video_w"] = video_w
    seg["video_h"] = video_h

    # 提取与选定文本高度一致 (sim >= 0.80) 的稳定采样帧中的检测框并集
    valid_boxes = []
    for s in samples:
        if len(s) > 2 and s[2]:
            if text_similarity(s[1], selected_text) >= 0.80:
                valid_boxes.extend(s[2])

    # 兜底：若未聚类到稳定框，取该句全部检出框
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
        # 极少见无检出框情况，兜底使用默认底部安全区域
        seg["box"] = [
            round(video_w * 0.15, 1),
            round(video_h * 0.80, 1),
            round(video_w * 0.85, 1),
            round(video_h * 0.95, 1),
        ]

    seg.pop("samples", None)
    return seg


def build_ocr_engine(use_cuda: bool = True):
    """
    构建 RapidOCR 引擎实例（生产标准路径）。

    【模型决策】
    刻意使用默认 PP-OCRv6 多语种模型。
    实测：PP-OCRv6 multi CER 16.72%；japan_PP-OCRv4_rec_mobile CER 27.44%（更差）。
    不要"修正"成 japan 专用模型，会掉 10 个百分点。详见 docs/OCR_MODEL_DECISION.md。

    【GPU 强校验 (R3)】
    当 use_cuda=True 时，强制断言 Det 与 Rec 推理会话的 primary provider 为 CUDAExecutionProvider。
    严禁任何 silent fallback 或 try/except: pass 降级。
    """
    from rapidocr.utils.log import logger as rapidocr_logger
    rapidocr_logger.setLevel(logging.ERROR)
    for h in rapidocr_logger.handlers:
        h.setLevel(logging.ERROR)
    from rapidocr import RapidOCR

    ocr_params = {}
    if use_cuda:
        ocr_params["EngineConfig.onnxruntime.use_cuda"] = True
        # U1: 设 cudnn_conv_algo_search = "HEURISTIC"，消除 EXHAUSTIVE autotune 动态尺寸评测造成的停顿
        ocr_params["EngineConfig.onnxruntime.cuda_ep_cfg.cudnn_conv_algo_search"] = "HEURISTIC"

    engine = RapidOCR(params=ocr_params)

    # 预加载模型并进行 GPU Provider 强校验
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
            raise RuntimeError(
                f"OCR Det 模型未能加载 CUDAExecutionProvider！实际 providers: {det_providers}。"
                "请检查 CUDA 12/cuDNN 9 动态库注入（animeautosub._env）。"
            )
        if not rec_providers or rec_providers[0] != "CUDAExecutionProvider":
            raise RuntimeError(
                f"OCR Rec 模型未能加载 CUDAExecutionProvider！实际 providers: {rec_providers}。"
                "请检查 CUDA 12/cuDNN 9 动态库注入（animeautosub._env）。"
            )

        det_opts = det_session.get_provider_options().get("CUDAExecutionProvider", {})
        algo = det_opts.get("cudnn_conv_algo_search", "")
        if algo != "HEURISTIC":
            logging.warning(f"    ⚠ cudnn_conv_algo_search 当前为 {algo}，期望为 HEURISTIC")
        else:
            logging.info("    ✓ OCR 引擎已启用 cudnn_conv_algo_search = HEURISTIC (已消除 autotune 停顿)")

        logging.info("    ✓ OCR 引擎 (Det/Rec) 已通过 GPU 强校验 (CUDAExecutionProvider 首选运行)")
    else:
        logging.info("    ⚠ OCR 引擎显式以 CPU 模式运行 (use_cuda=False)")

    return engine


def extract_hardsub_from_video(video_path: Path, work_dir: Path) -> list:
    """
    全自动抽取视频画面中的硬字幕：
    1. 动态自适应抽帧（2.5 fps）
    2. 区域帧差变动检测（极速跳过静止画面）
    3. RapidOCR-Japanese 高精度日语识别
    4. 时间轴连续区间平滑聚类
    """
    ja_path = work_dir / "japanese.json"
    if ja_path.exists():
        logging.info("    ✓ 日语字幕文件已存在，跳过 OCR 阶段")
        with open(ja_path, "r", encoding="utf-8") as f:
            return json.load(f)

    logging.info(f"    → 正在加载日语 OCR 引擎 (RapidOCR)...")
    ocr_engine = build_ocr_engine(use_cuda=OCR_USE_CUDA)

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"无法打开视频文件: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration_sec = total_frames / fps
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    # 字幕区域 (ROI): 默认底部 28%
    roi_top = int(height * (1.0 - OCR_ROI_BOTTOM_PERCENT))

    sample_step = max(1, int(fps / OCR_SAMPLE_FPS))
    sample_interval_sec = sample_step / fps

    logging.info(f"    → 视频分辨率: {width}x{height}, 总时长: {int(duration_sec//60):02d}:{int(duration_sec%60):02d}")
    logging.info(f"    → 扫描区域: 底部 {int(OCR_ROI_BOTTOM_PERCENT*100)}% (y: {roi_top} ~ {height}), 采样率: {OCR_SAMPLE_FPS} fps")

    segments = []
    current_seg = None
    last_roi_gray = None
    last_ocr_text = ""
    last_ocr_boxes = []

    t_ocr_start = time.time()
    t_decode_accum = 0.0
    t_inference_accum = 0.0
    t_other_accum = 0.0
    call_records = []

    frame_idx = 0
    last_log_sec = 0
    ocr_call_count = 0
    skip_count = 0

    while True:
        if frame_idx % sample_step == 0:
            t_d0 = time.time()
            ret, frame = cap.read()
            t_decode_accum += (time.time() - t_d0)
            if not ret:
                break
            curr_sec = frame_idx / fps

            t_o0 = time.time()
            # 打印进度日志 (每 30 秒更新一次进度)
            if curr_sec - last_log_sec >= 30:
                pct = (curr_sec / duration_sec) * 100 if duration_sec > 0 else 0
                logging.info(f"    ⏳ OCR 进度: {curr_sec/60:.1f}/{duration_sec/60:.1f} 分钟 ({pct:.1f}%), 已提取 {len(segments)} 句, OCR调用 {ocr_call_count} 次, 跳过 {skip_count} 帧")
                last_log_sec = curr_sec

            # 裁切字幕 ROI 区域
            roi = frame[roi_top:height, 0:width]
            roi_gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)

            # 帧差变动检测：如果与上一采样帧变化极小，直接继承上一帧识别结果，极速省时
            diff = 1.0
            if last_roi_gray is not None:
                diff = np.mean(cv2.absdiff(roi_gray, last_roi_gray)) / 255.0

            last_roi_gray = roi_gray

            detected_text = ""
            detected_boxes = []
            t_other_accum += (time.time() - t_o0)

            # 若画面变动低于阈值，无需调用 OCR 引擎——极速跳过
            if diff < OCR_FRAME_DIFF_THRESH:
                detected_text = last_ocr_text
                detected_boxes = last_ocr_boxes
                skip_count += 1
            else:
                t_o1 = time.time()
                # 进一步快速判断：字幕区域是否基本全黑/无字（标准差极低 → 没有文字）
                roi_std = np.std(roi_gray)
                t_other_accum += (time.time() - t_o1)

                if roi_std < 12:
                    # 纯黑或纯色无字画面，跳过 OCR
                    detected_text = ""
                    detected_boxes = []
                    skip_count += 1
                else:
                    # 画面有变动且有内容，调用 OCR 识别 (精确打点)
                    t_r0 = time.time()
                    out = ocr_engine(roi)
                    dt_call = time.time() - t_r0
                    t_inference_accum += dt_call
                    ocr_call_count += 1

                    n_boxes = len(out.boxes) if (out is not None and out.boxes is not None) else 0
                    call_records.append({
                        "call": ocr_call_count,
                        "sec": round(curr_sec, 2),
                        "duration_ms": round(dt_call * 1000, 1),
                        "boxes_count": n_boxes
                    })

                    t_o2 = time.time()
                    if out and out.txts:
                        detected_text = clean_ocr_text(out.txts)
                        if out.boxes is not None and len(out.boxes) > 0:
                            for b in out.boxes:
                                b_arr = np.array(b)
                                x0 = float(np.min(b_arr[:, 0]))
                                y0 = float(np.min(b_arr[:, 1])) + roi_top
                                x1 = float(np.max(b_arr[:, 0]))
                                y1 = float(np.max(b_arr[:, 1])) + roi_top
                                detected_boxes.append([x0, y0, x1, y1])
                    t_other_accum += (time.time() - t_o2)

            last_ocr_text = detected_text
            last_ocr_boxes = detected_boxes

            t_o3 = time.time()
            # 处理字幕时间轴合并
            if detected_text:
                if current_seg is None:
                    # 新字幕产生
                    current_seg = {
                        "start": round(curr_sec, 2),
                        "end": round(curr_sec + sample_interval_sec, 2),
                        "text": detected_text,
                        "samples": [(curr_sec, detected_text, detected_boxes)]
                    }
                else:
                    # 检查是否为同句延续
                    sim = text_similarity(current_seg["text"], detected_text)
                    if sim >= OCR_SIMILARITY_THRESH:
                        # 延续当前句，更新结束时间并累积采样帧
                        current_seg["end"] = round(curr_sec + sample_interval_sec, 2)
                        current_seg.setdefault("samples", []).append((curr_sec, detected_text, detected_boxes))
                    else:
                        # 旧句结束，提交旧句（需满足最短时长）
                        if (current_seg["end"] - current_seg["start"]) >= OCR_MIN_DURATION_SEC:
                            segments.append(finalize_segment(current_seg, width, height))
                        # 开启新句
                        current_seg = {
                            "start": round(curr_sec, 2),
                            "end": round(curr_sec + sample_interval_sec, 2),
                            "text": detected_text,
                            "samples": [(curr_sec, detected_text, detected_boxes)]
                        }
            else:
                # 当前帧无字幕，如果之前有字幕，则闭合
                if current_seg is not None:
                    if (current_seg["end"] - current_seg["start"]) >= OCR_MIN_DURATION_SEC:
                        segments.append(finalize_segment(current_seg, width, height))
                    current_seg = None
            t_other_accum += (time.time() - t_o3)
        else:
            # 非采样帧使用 grab() 快速跳过解码
            t_d0 = time.time()
            ret = cap.grab()
            t_decode_accum += (time.time() - t_d0)
            if not ret:
                break

        frame_idx += 1

    cap.release()

    t_o4 = time.time()
    # 闭合最后一句
    if current_seg is not None and (current_seg["end"] - current_seg["start"]) >= OCR_MIN_DURATION_SEC:
        segments.append(finalize_segment(current_seg, width, height))

    # 简单相邻碎片合并（若两句间隔 < 0.4s 且文本一致）
    cleaned_segments = []
    for seg in segments:
        if not cleaned_segments:
            cleaned_segments.append(seg)
        else:
            prev = cleaned_segments[-1]
            if seg["start"] - prev["end"] <= 0.4 and text_similarity(prev["text"], seg["text"]) >= 0.85:
                prev["end"] = seg["end"]
                if prev.get("box") and seg.get("box"):
                    prev["box"] = [
                        min(prev["box"][0], seg["box"][0]),
                        min(prev["box"][1], seg["box"][1]),
                        max(prev["box"][2], seg["box"][2]),
                        max(prev["box"][3], seg["box"][3]),
                    ]
            else:
                cleaned_segments.append(seg)
    t_other_accum += (time.time() - t_o4)

    # 保存中间结果
    with open(ja_path, "w", encoding="utf-8") as f:
        json.dump(cleaned_segments, f, ensure_ascii=False, indent=2)

    ocr_duration = time.time() - t_ocr_start
    sec_per_call = t_inference_accum / max(1, ocr_call_count)

    fast_calls = [c for c in call_records if c["duration_ms"] <= 250]
    slow_calls = [c for c in call_records if c["duration_ms"] > 250]
    fast_time_s = sum(c["duration_ms"] for c in fast_calls) / 1000.0
    slow_time_s = sum(c["duration_ms"] for c in slow_calls) / 1000.0
    
    stage1_report = {
        "video": str(video_path),
        "total_frames_sampled": frame_idx,
        "ocr_call_count": ocr_call_count,
        "skip_count": skip_count,
        "extracted_segments_count": len(cleaned_segments),
        "timings_sec": {
            "decode_time_s": round(t_decode_accum, 3),
            "inference_time_s": round(t_inference_accum, 3),
            "other_overhead_s": round(t_other_accum, 3),
            "total_stage1_s": round(ocr_duration, 3)
        },
        "timings_percent": {
            "decode_pct": round(t_decode_accum / max(0.001, ocr_duration) * 100, 1),
            "inference_pct": round(t_inference_accum / max(0.001, ocr_duration) * 100, 1),
            "other_pct": round(t_other_accum / max(0.001, ocr_duration) * 100, 1)
        },
        "timing_analysis": {
            "fast_calls_count": len(fast_calls),
            "fast_calls_time_s": round(fast_time_s, 3),
            "slow_calls_count": len(slow_calls),
            "slow_calls_time_s": round(slow_time_s, 3),
            "shape_pause_pct_of_inference": round(slow_time_s / max(0.001, t_inference_accum) * 100, 1)
        },
        "sec_per_ocr_call": round(sec_per_call, 4),
        "call_records": call_records
    }
    with open(work_dir / "stage1_production_timing_report.json", "w", encoding="utf-8") as f:
        json.dump(stage1_report, f, ensure_ascii=False, indent=2)

    logging.info(
        f"    ✓ 视觉 OCR 扫描完成：共提取 {len(cleaned_segments)} 句日文字幕，"
        f"总耗时: {ocr_duration:.2f}s (解码: {t_decode_accum:.2f}s, 推理: {t_inference_accum:.2f}s, 其他: {t_other_accum:.2f}s)，"
        f"OCR调用 {ocr_call_count} 次 (快调用: {len(fast_calls)}次, 慢调用: {len(slow_calls)}次)，跳过 {skip_count} 帧，"
        f"单次纯推理: {sec_per_call*1000:.1f} ms/次"
    )
    return cleaned_segments


# ======================================================================
#             Stage 2: 中文翻译 (Sakura-14B via Ollama) & 智能清洗拒识
# ======================================================================

# 日语常见数量词与假名匹配 (U2: 避免误伤合法数字台词)
JP_UNITS_PATTERN = r'[人つ円回日月年分秒時点個番歳才倍割度本枚匹頭台万億千百％%kmgM]'
KANA_PATTERN = r'[\u3040-\u309F\u30A0-\u30FF]'

def is_garbled_number(match, full_text: str) -> bool:
    """
    判断匹配到的数字是否为乱码 (U2)：
    数字仅在孤立出现且前后无假名（或前后非合法日语数量搭配）时判为乱码；
    长数字（>=5位）直接判定为乱码水印/时间码。
    """
    num_str = match.group()
    start, end = match.span()
    if len(num_str) >= 5:
        return True
    prev_char = full_text[start - 1] if start > 0 else ""
    next_char = full_text[end] if end < len(full_text) else ""
    if re.match(KANA_PATTERN, next_char) or re.match(JP_UNITS_PATTERN, next_char):
        return False
    if re.match(KANA_PATTERN, prev_char) and not re.match(r'[っッ]', prev_char):
        return False
    return True


def sanitize_japanese_text(raw_text: str) -> tuple:
    """
    日语专用文本清洗规则:
    1. 乱码片段过滤 (N5/U2/Z1)
    2. 切除尾部乱码 (Z1: 匹配连续拉丁/希腊字母/数字/点号，切除后剩余 < 50% 拒识)
    3. 字母数字混杂碎片过滤 (如 iz2 等 OCR 劣化残渣)
    4. 助词浊点误识正规化 (Z3: 誰がに -> 誰かに)
    5. 整理标点与未闭合截断
    返回: (cleaned_text: str, is_rejected: bool, action_info: str)
    """
    if not raw_text:
        return "", True, "empty"

    orig_len = len(raw_text)

    # 1. 查找混合乱码片段 (含大写字母序列、符号乱码、括号带英文字符、5位以上纯数字等)
    garble_patterns = [
        r'[A-Za-z0-9_]*[A-Z]{2,}[A-Za-z0-9_「」]*',
        r'\[[A-Za-z0-9_]+',
        r'[&#@$%^~+=*|/\\<>]{1,}[A-Za-z0-9_?]*',
        r'\d{5,}'
    ]
    combined_pattern = re.compile('|'.join(garble_patterns))

    removed_snippets = []
    for m in combined_pattern.finditer(raw_text):
        s = m.group()
        if s:
            removed_snippets.append(s)

    cleaned = combined_pattern.sub('', raw_text)

    # 2. 查找并切除孤立 3-4 位数字（前后无假名）
    def replace_isolated_digits(m):
        if is_garbled_number(m, cleaned):
            removed_snippets.append(m.group())
            return ""
        return m.group()

    cleaned = re.sub(r'\d{3,4}', replace_isolated_digits, cleaned)

    # 3. 尾部乱码切除 (Z1 标准规则)
    has_cjk = bool(re.search(r'[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]', cleaned))
    if has_cjk:
        # a) 匹配尾部退化希腊字母混杂段与标点组合尾部
        greek_tail_pattern = re.compile(r'(?:……|…|\.{2,})?[0-9α-ωΑ-Ωぁ-んァ-ヶ]*[α-ωΑ-Ω]+[0-9A-Za-zα-ωΑ-Ωぁ-んァ-ヶ\.…\s]*$')
        tail_pattern = re.compile(r'[0-9A-Za-zα-ωΑ-Ω\.·\s…\?!~¿]{3,}$')

        m_greek = greek_tail_pattern.search(cleaned)
        if m_greek and m_greek.group():
            removed_snippets.append(m_greek.group())
            cleaned = greek_tail_pattern.sub('', cleaned).rstrip()

        m_tail = tail_pattern.search(cleaned)
        if m_tail and m_tail.group():
            removed_snippets.append(m_tail.group())
            cleaned = tail_pattern.sub('', cleaned).rstrip()

        # 标准 Z1 正则切除
        cleaned = re.sub(r'[0-9A-Za-zα-ωΑ-Ω\.·\s]{3,}$', '', cleaned).rstrip()
        # 清除台词中绝无可能的希腊字母与混杂字母数字碎片
        cleaned = re.sub(r'[α-ωΑ-Ω]+', '', cleaned)
        cleaned = re.sub(r'[a-zA-Z]+[0-9]+|[0-9]+[a-zA-Z]+', '', cleaned)

    # 4. 整理标点与常见助词浊点误识规整 (Z3: 修复 誰がに -> 誰かに 等 OCR 浊点误识)
    cleaned = re.sub(r'誰がに', '誰かに', cleaned)
    cleaned = re.sub(r'[\s「」\[\]&]+$', '', cleaned).strip()

    rem_len = len(cleaned)
    rem_ratio = rem_len / max(1, orig_len)

    # 5. 仅当剩余有效文本 < 50% 或剩余有效文本不足 3 字符时整句拒识 (Z1: 门禁 < 0.50)
    if rem_ratio < 0.50:
        return cleaned, True, f"remaining_ratio_{rem_ratio:.2f}_lt_0.50"
    if rem_len < 3:
        return cleaned, True, f"rem_len_{rem_len}_lt_3"

    action = f"cut_{','.join(removed_snippets)}" if removed_snippets else "clean_pass"
    return cleaned, False, action


def is_n5_rejected(text: str) -> tuple:
    """兼容旧接口：返回 (is_rejected: bool, action_info: str)"""
    cleaned, is_rej, action = sanitize_japanese_text(text)
    return is_rej, action


_TRANSLATE_SESSION = None

def get_translate_session() -> requests.Session:
    """复用 TCP 连接池，避免每次请求重复进行 TCP 握手 (T3)"""
    global _TRANSLATE_SESSION
    if _TRANSLATE_SESSION is None:
        _TRANSLATE_SESSION = requests.Session()
    return _TRANSLATE_SESSION


def load_glossary() -> dict:
    glossary = {}
    if not GLOSSARY_DIR.exists():
        return glossary
    for gf in GLOSSARY_DIR.glob("*.json"):
        try:
            with open(gf, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                for k, v in data.items():
                    if not k.startswith("_"):
                        glossary[k] = v
        except Exception:
            pass
    return glossary


def translate_one(text: str, glossary: dict, context_pairs: list) -> str:
    messages = [{"role": "system", "content": SAKURA_SYSTEM_PROMPT}]

    # 术语注入 (匹配 SakuraLLM 官方标准微调 Prompt 模板)
    matched_glossary = {k: v for k, v in glossary.items() if k in text}
    
    if matched_glossary:
        dict_lines = [f"{k}->{v}" for k, v in matched_glossary.items()]
        user_prompt = (
            "根据以下字典翻译：\n"
            + "\n".join(dict_lines)
            + "\n将下面的日文文本翻译成中文："
            + text
        )
    else:
        user_prompt = f"将下面的日文文本翻译成中文：{text}"

    # 上下文注入 (仅注入质检全通过的高纯净历史对白)
    for ja, zh in context_pairs[-CONTEXT_LINES:]:
        messages.append({"role": "user", "content": f"将下面的日文文本翻译成中文：{ja}"})
        messages.append({"role": "assistant", "content": zh})

    messages.append({"role": "user", "content": user_prompt})

    payload = {
        "model": SAKURA_MODEL_NAME,
        "messages": messages,
        "temperature": TEMPERATURE,
        "top_p": TOP_P,
        "stream": False,
        "options": {
            "num_predict": 512,
        }
    }

    session = get_translate_session()

    result = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = session.post(OLLAMA_API_URL, json=payload, timeout=60)
            if resp.status_code == 200:
                out = resp.json()["choices"][0]["message"]["content"].strip()
                result = re.sub(r'^(翻译结果[：:]\s*|中文[：:]\s*)', '', out)
                break
            else:
                time.sleep(2)
        except Exception as e:
            time.sleep(2)

    if result is None:
        result = text  # 重试失败返回原文兜底

    # Z2 防重复检查：只告警，绝不中断任务。
    # 连续语气句（喘息、拟声、重复台词）相邻两句译文相同属于正常现象，不是缺陷。
    if context_pairs and result == context_pairs[-1][1]:
        prev_src = context_pairs[-1][0]
        similar_src = (
            text == prev_src
            or difflib.SequenceMatcher(None, text, prev_src).ratio() >= 0.60
        )
        if similar_src:
            logging.debug("    [Z2] 相邻源文本相近，译文相同属正常，跳过")
        else:
            logging.warning("    ⚠ [Z2] 源文本差异明显却输出相同译文，用干净上下文重试一次（不中断任务）")
            result_retry = translate_one(text, glossary, context_pairs=[])
            if result_retry and result_retry != context_pairs[-1][1]:
                result = result_retry
            else:
                logging.warning("    ⚠ [Z2] 重试后仍相同，保留该结果并继续，标记待人工复核")

    return result


def translate_segments(segments: list, work_dir: Path) -> list:
    zh_path = work_dir / "chinese.json"
    if zh_path.exists():
        logging.info("    ✓ 中文翻译已存在，跳过")
        with open(zh_path, "r", encoding="utf-8") as f:
            return json.load(f)

    glossary = load_glossary()
    total = len(segments)
    logging.info(f"    → 开始翻译 (共 {total} 句，使用模型 [{SAKURA_MODEL_NAME}])...")

    results = []
    context = []
    rejection_records = []
    salvaged_records = []
    rejected_count = 0
    start_time = time.time()

    for idx, seg in enumerate(segments):
        raw_text = seg["text"]
        cleaned_text, is_rej, action_info = sanitize_japanese_text(raw_text)

        if is_rej:
            # U2: 仅当剩余有效文本 < 40% 时整句拒识留空
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
            logging.info(f"    🚫 [U2 拒识 #{rejected_count}] Idx {idx+1}: '{raw_text[:20]}...' 触发拒识: {action_info}，留空丢弃")
        else:
            is_incomplete = not bool(re.search(r'[」』\)。！？!\?…]$', cleaned_text)) and ('「' in cleaned_text or '『' in cleaned_text)
            zh_text = translate_one(cleaned_text, glossary, context)

            # Y2 上下文隔离准则：
            # 被拒识、切除过尾部/噪声、断句未闭合、或含有未识别残留字母数字的句子，严禁加入翻译上下文队列！
            # 仅当质检全通过（clean_pass 且 not is_incomplete）时，才准许进入上下文，杜绝下游连环污染
            is_pristine = (action_info == "clean_pass") and (not is_incomplete) and (not re.search(r'[A-Za-z0-9]{2,}', cleaned_text))
            if is_pristine and zh_text and len(zh_text) >= 2:
                context.append((cleaned_text, zh_text))
            else:
                logging.debug(f"    🛡️ [Y2 上下文隔离] Idx {idx+1}: 存在切除/截断/噪声，隔离不入上下文")

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
                    "incomplete_translation": is_incomplete,
                    "incomplete_note": "日文原文在画面边缘被截断（缺失闭合引号），中文译文忠实保留截断状态，未脑补补全" if is_incomplete else ""
                })
                tag = " [断句未闭合]" if is_incomplete else ""
                logging.info(f"    ✂️ [U2 切除修复{tag}] Idx {idx+1}: 原文 '{raw_text}' -> 修复后 '{cleaned_text}' (切除: {action_info})")

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
            "video_h": seg.get("video_h"),
        }
        results.append(item)

        if (idx + 1) % 10 == 0 or (idx + 1) == total:
            pct = (idx + 1) / total * 100
            elapsed = time.time() - start_time
            speed = elapsed / (idx + 1)
            remain = speed * (total - idx - 1)
            display_zh = zh_text[:20] if zh_text else "[拒识留空]"
            logging.info(f"    📝 {idx+1}/{total} ({pct:.0f}%) [约剩 {remain/60:.1f} 分钟] -> {display_zh}...")

    with open(zh_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    salvaged_complete = [s for s in salvaged_records if not s.get("incomplete_translation")]
    salvaged_incomplete = [s for s in salvaged_records if s.get("incomplete_translation")]

    rej_report = {
        "total_segments": total,
        "rejected_count": rejected_count,
        "rejected_percent": round(rejected_count / max(1, total) * 100, 2),
        "salvaged_total_count": len(salvaged_records),
        "salvaged_perfect_count": len(salvaged_complete),
        "salvaged_incomplete_count": len(salvaged_incomplete),
        "target_max_reject_percent": 3.0,
        "salvaged_records": salvaged_records,
        "rejected_records": rejection_records
    }
    with open(work_dir / "n5_rejection_report.json", "w", encoding="utf-8") as f:
        json.dump(rej_report, f, ensure_ascii=False, indent=2)

    logging.info(
        f"    ✓ 翻译完成 (有效翻译: {total - rejected_count} 句, 切除完美修复: {len(salvaged_complete)} 句, "
        f"断句截断修复: {len(salvaged_incomplete)} 句, 整句拒识: {rejected_count} 句, 拒识率: {rej_report['rejected_percent']}%)"
    )
    return results


# ======================================================================
#             Stage 3: 智能排版与生成遮罩字幕 (ASS / SRT)
# ======================================================================

def auto_wrap_subtitle(text: str, max_chars: int = SUBTITLE_MAX_LINE_CHARS) -> str:
    """日漫字幕双行居中折行"""
    if not AUTO_WRAP_SUBTITLE or len(text) <= max_chars or "\\N" in text or "\n" in text:
        return text

    puncts = ['。', '！', '？', '!', '?', '，', ',', '…', '、', ' ']
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
    else:
        return text[:mid] + r"\N" + text[mid:]


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


def generate_subtitles(translated: list, work_dir: Path, video_width: int = None, video_height: int = None) -> tuple:
    """
    生成 ASS（贴下方/自适应贴合遮罩/上浮）和标准 SRT 字幕。
    【R1 规范】
    废除 MASK_TOP/MASK_HEIGHT 全局黑条，由每句 OCR 检测框并集 + 8px padding 计算自适应矩形；
    施加 8px 高度网格量化（确保同一场景高度方差 <= 8px）；
    动态校核中文字幕宽度（确保中文不压边）；
    PlayResX/PlayResY 自动适配视频真实宽高，保证 1080p 与 720p 像素级等比例渲染。
    """
    ass_path = work_dir / "subtitle.ass"
    srt_path = work_dir / "subtitle.srt"

    # 获取视频真实分辨率
    if video_width is None or video_height is None:
        if translated and translated[0].get("video_w") and translated[0].get("video_h"):
            video_width = int(translated[0]["video_w"])
            video_height = int(translated[0]["video_h"])
        else:
            video_width = 1920
            video_height = 1080

    scale_y = video_height / 1080.0
    fontsize = max(18, int(round(SUBTITLE_FONTSIZE * scale_y)))
    outline = round(SUBTITLE_OUTLINE * scale_y, 1)
    shadow = round(SUBTITLE_SHADOW * scale_y, 1)
    bold = -1 if SUBTITLE_BOLD else 0

    if SUBTITLE_OVERLAY_STYLE in ("replace_mask", "slim_box", "box"):
        styles_section = f"""Style: Mask,Arial,10,&H00000000,&H00000000,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1
Style: Default,{SUBTITLE_FONT},{fontsize},&H00FFFFFF,&H000000FF,&H00000000,&H00000000,{bold},0,0,0,100,100,0,0,1,{outline},{shadow},5,10,10,10,1"""
    elif SUBTITLE_OVERLAY_STYLE == "above":
        styles_section = f"""Style: Default,{SUBTITLE_FONT},{fontsize},&H00FFFFFF,&H000000FF,&H00000000,&H00000000,{bold},0,0,0,100,100,0,0,1,{outline},{shadow},2,30,30,115,1"""
    else:
        margin_v = max(10, int(round(SUBTITLE_MARGIN_V * scale_y)))
        styles_section = f"""Style: Default,{SUBTITLE_FONT},{fontsize},&H00FFFFFF,&H000000FF,&H00000000,&H00000000,{bold},0,0,0,100,100,0,0,1,{outline},{shadow},2,20,20,{margin_v},1"""

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

    for i, seg in enumerate(translated, 1):
        zh = seg.get("zh", "").strip()
        if not zh:
            # T1: N5 拒识留空项不生成遮罩与中文字幕，彻底阻断空黑块或乱码上屏
            continue

        zh_wrapped = auto_wrap_subtitle(zh)

        # ASS 行
        start_ass = format_timestamp_ass(seg["start"])
        end_ass = format_timestamp_ass(seg["end"])

        if SUBTITLE_OVERLAY_STYLE in ("replace_mask", "slim_box", "box"):
            box = seg.get("box")
            if box is not None:
                xmin, ymin, xmax, ymax = box
            else:
                xmin = video_width * 0.15
                ymin = video_height * 0.80
                xmax = video_width * 0.85
                ymax = video_height * 0.95

            # 1. 8px padding
            raw_x0 = max(0.0, xmin - MASK_PADDING)
            raw_y0 = max(0.0, ymin - MASK_PADDING)
            raw_x1 = min(float(video_width), xmax + MASK_PADDING)
            raw_y1 = min(float(video_height), ymax + MASK_PADDING)

            # 2. 8px 网格量化 (Y 轴与高度方差 <= 8px 约束)
            y0 = max(0, int(np.floor(raw_y0 / MASK_GRID_QUANT) * MASK_GRID_QUANT))
            y1 = min(video_height, int(np.ceil(raw_y1 / MASK_GRID_QUANT) * MASK_GRID_QUANT))
            h = int(np.ceil((y1 - y0) / MASK_GRID_QUANT) * MASK_GRID_QUANT)
            y1 = min(video_height, y0 + h)

            # 3. 中文字幕宽度安全防护 ("中文不压边")
            lines = zh_wrapped.split(r"\N")
            max_line_len = max(len(l) for l in lines) if lines else 0
            char_width = fontsize * 0.95
            zh_width = max_line_len * char_width
            required_w = max(raw_x1 - raw_x0, zh_width + 40.0 * (video_width / 1920.0))

            cx = (raw_x0 + raw_x1) / 2.0
            x0 = max(0, int(round(cx - required_w / 2.0)))
            x1 = min(video_width, int(round(cx + required_w / 2.0)))
            w = x1 - x0

            # 4. 比例判据硬顶约束 (T1): 任意单句遮罩面积 <= 16.0% 画面
            max_allowed_area = 0.16 * video_width * video_height
            if w * h > max_allowed_area and h > 0:
                w = int(max_allowed_area / h)
                x0 = max(0, int(round(cx - w / 2.0)))
                x1 = min(video_width, x0 + w)

            cx = int(round(x0 + w / 2.0))
            cy = int(round(y0 + h / 2.0))

            mask_line = (
                f"Dialogue: 0,{start_ass},{end_ass},Mask,,0,0,0,,"
                f"{{\\an7\\pos({x0},{y0})\\p1\\c&H0a0a0a&\\1a&H{MASK_OPACITY}&}}"
                f"m 0 0 l {w} 0 l {w} {h} l 0 {h}{{\\p0}}\n"
            )
            text_line = (
                f"Dialogue: 1,{start_ass},{end_ass},Default,,0,0,0,,"
                f"{{\\an5\\pos({cx},{cy})}}{zh_wrapped}\n"
            )
            ass_lines.append(mask_line)
            ass_lines.append(text_line)
        else:
            ass_lines.append(f"Dialogue: 0,{start_ass},{end_ass},Default,,0,0,0,,{zh_wrapped}\n")

        # SRT 行
        start_srt = format_timestamp_srt(seg["start"])
        end_srt = format_timestamp_srt(seg["end"])
        srt_text = zh_wrapped.replace(r"\N", "\n")
        srt_lines.append(f"{i}\n{start_srt} --> {end_srt}\n{srt_text}\n\n")

    with open(ass_path, "w", encoding="utf-8") as f:
        f.writelines(ass_lines)

    with open(srt_path, "w", encoding="utf-8") as f:
        f.writelines(srt_lines)

    logging.info(f"    ✓ 字幕文件已生成 ({SUBTITLE_OVERLAY_STYLE} 自适应排版)")
    return ass_path, srt_path


# ======================================================================
#             Stage 4: FFmpeg 软封与压制
# ======================================================================

def mux_mkv(video_path: Path, ass_path: Path, out_path: Path):
    cmd = [
        FFMPEG_PATH,
        "-i", str(video_path),
        "-i", str(ass_path),
        "-map", "0",
        "-map", "1",
        "-c", "copy",
        "-c:s", "ass",
        "-metadata:s:s:0", "title=中文(OCR遮罩翻译)",
        "-metadata:s:s:0", "language=chi",
        "-disposition:s:0", "default",
        "-y",
        str(out_path),
    ]
    env = os.environ.copy()
    r = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if r.returncode != 0:
        raise RuntimeError(f"MKV 封装失败:\n{r.stderr[-800:]}")


def hardcode_mp4(video_path: Path, ass_path: Path, out_path: Path):
    ass_escaped = str(ass_path).replace("\\", "/").replace(":", r"\:")
    cmd = [
        FFMPEG_PATH,
        "-i", str(video_path),
        "-vf", f"subtitles='{ass_escaped}'",
        "-c:v", "libx264",
        "-crf", str(HARDCODED_CRF),
        "-preset", HARDCODED_PRESET,
        "-c:a", "copy",
        "-y",
        str(out_path),
    ]
    env = os.environ.copy()
    r = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if r.returncode != 0:
        raise RuntimeError(f"MP4 硬压失败:\n{r.stderr[-800:]}")


# ======================================================================
#                              主循环
# ======================================================================

def process_one_video(video_path: Path):
    stem = video_path.stem
    work_dir = OCR_OUTPUT_DIR / stem
    work_dir.mkdir(parents=True, exist_ok=True)

    logging.info("\n" + "=" * 60)
    logging.info(f"  正在处理: {video_path.name} (兼容层桥接 -> Core Stage 流水线)")
    logging.info("=" * 60)

    # 委托给解耦后的新架构 Stage 流水线
    from lang import get_language
    from core.context import PipelineContext
    from core.pipeline import Pipeline

    ctx = PipelineContext(
        video_path=video_path,
        work_dir=work_dir,
        output_dir=work_dir,
        lang=get_language("ja"),
        mode="ocr"
    )
    pipeline = Pipeline(ctx)
    success = pipeline.run()
    if not success:
        raise RuntimeError(f"流水线执行失败: {video_path}")

    # 生成 MKV/MP4 兼容产物名 (若配置需要)
    ass_path = work_dir / "subtitle.ass"
    if OUTPUT_MODE in ("mkv", "both"):
        mkv_out = work_dir / f"{stem}_中文字幕.mkv"
        if not mkv_out.exists() and ass_path.exists():
            mux_mkv(video_path, ass_path, mkv_out)

    if OUTPUT_MODE in ("mp4", "both"):
        mp4_out = work_dir / f"{stem}_中文字幕.mp4"
        out_prod = work_dir / "output.mp4"
        if out_prod.exists() and not mp4_out.exists():
            import shutil
            shutil.copyfile(out_prod, mp4_out)

    logging.info(f"  🎉 处理完成！成品保存在: {work_dir}")


def main():
    setup_logging()
    print(r"""
==============================================================
   视频硬字幕 OCR 识别与翻译流水线 v1.0
   视频画面(硬字幕) → RapidOCR → Sakura-14B → 黑底遮罩排版
==============================================================
""")
    if not check_environment():
        sys.exit(1)

    OCR_INPUT_DIR.mkdir(exist_ok=True)
    OCR_OUTPUT_DIR.mkdir(exist_ok=True)

    if len(sys.argv) > 1 and Path(sys.argv[1]).exists():
        videos = [Path(sys.argv[1])]
    else:
        videos = [
            p for p in OCR_INPUT_DIR.iterdir()
            if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS
        ]

    if not videos:
        logging.info(f"\n[提示] 请把需要识别硬字幕的视频放入: {OCR_INPUT_DIR}")
        logging.info("放入后重新运行此脚本即可！")
        return

    logging.info(f"\n找到 {len(videos)} 个视频文件待处理:")
    for v in videos:
        mb = v.stat().st_size / (1024 * 1024)
        logging.info(f"  • {v.name} ({mb:.1f} MB)")

    for idx, v in enumerate(videos, 1):
        logging.info(f"\n▶ 总体进度: {idx}/{len(videos)}")
        try:
            process_one_video(v)
        except Exception as e:
            logging.error(f"  ❌ 处理失败: {e}", exc_info=True)


if __name__ == "__main__":
    main()
