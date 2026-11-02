"""
S2 专项测试：FFmpeg 解码层抽帧 vs OpenCV 性能对照与三段拆分
=============================================================
目标：
1. Stage 1 耗时 <= 20 秒
2. 给出 解码耗时 / 推理耗时 / 其他 三段精确拆分
3. 验证提取出的日文字幕段落完整度与准确性
"""

import sys
import time
import json
import subprocess
import cv2
import numpy as np
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import animeautosub._env
import pipeline_ocr
from config_ocr import (
    FFMPEG_PATH, OCR_SAMPLE_FPS, OCR_ROI_BOTTOM_PERCENT,
    OCR_FRAME_DIFF_THRESH, OCR_SIMILARITY_THRESH, OCR_MIN_DURATION_SEC
)

def run_stage1_ffmpeg(video_path: Path, work_dir: Path):
    print("=" * 60)
    print(f"  正在执行 FFmpeg 解码层抽帧 Stage 1: {video_path.name}")
    print("=" * 60)

    t0_total = time.time()
    t_decode_accum = 0.0
    t_ocr_accum = 0.0
    t_other_accum = 0.0

    # 1. 获取视频基本信息
    t_probe_start = time.time()
    cap = cv2.VideoCapture(str(video_path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 29.97
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration_sec = total_frames / fps
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    t_other_accum += (time.time() - t_probe_start)

    roi_top = int(height * (1.0 - OCR_ROI_BOTTOM_PERCENT))
    roi_h = height - roi_top
    roi_w = width
    frame_bytes = roi_w * roi_h * 3
    sample_interval_sec = 1.0 / OCR_SAMPLE_FPS

    print(f"  分辨率: {width}x{height}, 时长: {duration_sec:.1f}s, ROI: y=[{roi_top}:{height}] (h={roi_h})")

    # 2. 初始化 OCR 引擎
    t_eng_start = time.time()
    ocr_engine = pipeline_ocr.build_ocr_engine()
    t_other_accum += (time.time() - t_eng_start)

    # 3. 启动 FFmpeg 解码与 ROI 抽帧管道
    # -hwaccel cuda 加速，-vf 抽帧与裁剪一步到位
    cmd = [
        FFMPEG_PATH,
        "-hwaccel", "cuda",
        "-i", str(video_path),
        "-vf", f"fps={OCR_SAMPLE_FPS},crop={roi_w}:{roi_h}:0:{roi_top}",
        "-f", "rawvideo",
        "-pix_fmt", "bgr24",
        "-an", "-sn",
        "-"
    ]

    t_pipe_start = time.time()
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        bufsize=10**8
    )

    segments = []
    current_seg = None
    last_roi_gray = None
    last_ocr_text = ""
    last_ocr_boxes = []

    frame_idx = 0
    ocr_call_count = 0
    skip_count = 0

    while True:
        # 解码阶段：从管道读取一帧已裁剪完成的 ROI 原始字节
        t_d0 = time.time()
        raw = proc.stdout.read(frame_bytes)
        t_decode_accum += (time.time() - t_d0)

        if len(raw) < frame_bytes:
            break

        curr_sec = frame_idx * sample_interval_sec

        # 其他处理阶段：转 numpy 与灰度、帧差检测
        t_o0 = time.time()
        roi = np.frombuffer(raw, dtype=np.uint8).reshape((roi_h, roi_w, 3))
        roi_gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)

        diff = 1.0
        if last_roi_gray is not None:
            diff = np.mean(cv2.absdiff(roi_gray, last_roi_gray)) / 255.0
        last_roi_gray = roi_gray

        detected_text = ""
        detected_boxes = []
        t_other_accum += (time.time() - t_o0)

        # 判定是否需要 OCR
        if diff < OCR_FRAME_DIFF_THRESH:
            detected_text = last_ocr_text
            detected_boxes = last_ocr_boxes
            skip_count += 1
        else:
            t_o1 = time.time()
            roi_std = np.std(roi_gray)
            t_other_accum += (time.time() - t_o1)

            if roi_std < 12:
                detected_text = ""
                detected_boxes = []
                skip_count += 1
            else:
                # 推理阶段：GPU OCR
                t_r0 = time.time()
                out = ocr_engine(roi)
                t_ocr_accum += (time.time() - t_r0)
                ocr_call_count += 1

                t_o2 = time.time()
                if out and out.txts:
                    detected_text = pipeline_ocr.clean_ocr_text(out.txts)
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

        # 时间轴与段落合并阶段
        t_o3 = time.time()
        if detected_text:
            if current_seg is None:
                current_seg = {
                    "start": round(curr_sec, 2),
                    "end": round(curr_sec + sample_interval_sec, 2),
                    "text": detected_text,
                    "samples": [(curr_sec, detected_text, detected_boxes)]
                }
            else:
                sim = pipeline_ocr.text_similarity(current_seg["text"], detected_text)
                if sim >= OCR_SIMILARITY_THRESH:
                    current_seg["end"] = round(curr_sec + sample_interval_sec, 2)
                    current_seg.setdefault("samples", []).append((curr_sec, detected_text, detected_boxes))
                else:
                    if (current_seg["end"] - current_seg["start"]) >= OCR_MIN_DURATION_SEC:
                        segments.append(pipeline_ocr.finalize_segment(current_seg, width, height))
                    current_seg = {
                        "start": round(curr_sec, 2),
                        "end": round(curr_sec + sample_interval_sec, 2),
                        "text": detected_text,
                        "samples": [(curr_sec, detected_text, detected_boxes)]
                    }
        else:
            if current_seg is not None:
                if (current_seg["end"] - current_seg["start"]) >= OCR_MIN_DURATION_SEC:
                    segments.append(pipeline_ocr.finalize_segment(current_seg, width, height))
                current_seg = None
        t_other_accum += (time.time() - t_o3)

        frame_idx += 1

    proc.stdout.close()
    proc.wait()

    t_o4 = time.time()
    if current_seg is not None and (current_seg["end"] - current_seg["start"]) >= OCR_MIN_DURATION_SEC:
        segments.append(pipeline_ocr.finalize_segment(current_seg, width, height))

    cleaned_segments = []
    for seg in segments:
        if not cleaned_segments:
            cleaned_segments.append(seg)
        else:
            prev = cleaned_segments[-1]
            if seg["start"] - prev["end"] <= 0.4 and pipeline_ocr.text_similarity(prev["text"], seg["text"]) >= 0.85:
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

    total_time = time.time() - t0_total

    result_report = {
        "video": str(video_path),
        "total_frames_sampled": frame_idx,
        "ocr_call_count": ocr_call_count,
        "skip_count": skip_count,
        "extracted_segments_count": len(cleaned_segments),
        "timings_sec": {
            "decode_time_s": round(t_decode_accum, 3),
            "inference_time_s": round(t_ocr_accum, 3),
            "other_overhead_s": round(t_other_accum, 3),
            "total_stage1_s": round(total_time, 3)
        },
        "timings_percent": {
            "decode_pct": round(t_decode_accum / total_time * 100, 1),
            "inference_pct": round(t_ocr_accum / total_time * 100, 1),
            "other_pct": round(t_other_accum / total_time * 100, 1)
        },
        "sec_per_ocr_call": round(t_ocr_accum / max(1, ocr_call_count), 4)
    }

    with open(work_dir / "s2_ffmpeg_stage1_report.json", "w", encoding="utf-8") as f:
        json.dump(result_report, f, ensure_ascii=False, indent=2)

    with open(work_dir / "japanese_ffmpeg.json", "w", encoding="utf-8") as f:
        json.dump(cleaned_segments, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 60)
    print("  ✓ S2 FFmpeg 抽帧 Stage 1 实测完成！")
    print(f"  总耗时: {total_time:.2f}s (目标 <= 20.0s: {total_time <= 20.0})")
    print(f"    - 解码耗时: {t_decode_accum:.2f}s ({result_report['timings_percent']['decode_pct']}%)")
    print(f"    - 推理耗时: {t_ocr_accum:.2f}s ({result_report['timings_percent']['inference_pct']}%), 调用 {ocr_call_count} 次, {result_report['sec_per_ocr_call']*1000:.1f}ms/次")
    print(f"    - 其他耗时: {t_other_accum:.2f}s ({result_report['timings_percent']['other_pct']}%)")
    print(f"  提取字幕数: {len(cleaned_segments)} 句")
    print("=" * 60)
    return result_report

if __name__ == "__main__":
    v_path = PROJECT_ROOT / "ocr_input" / "test_3min.mp4"
    w_dir = PROJECT_ROOT / "bench"
    run_stage1_ffmpeg(v_path, w_dir)
