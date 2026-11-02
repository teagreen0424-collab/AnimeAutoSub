"""
I4: 114877-720p (69分15秒) 全片真实 OCR 阶段物理耗时实测
=========================================================
严禁估算，全量跑完 69 分钟全片：
- 2fps 底部 28% 抽帧 (全片约 8311 抽样帧)
- 帧差过滤 (MSE > 5.0)
- RapidOCR (CUDAExecutionProvider)
记录真实 OCR 阶段墙钟耗时、实际 OCR 调用次数与峰值显存。
"""

import sys
import os
import json
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import animeautosub._env
import cv2
import numpy as np
import torch
from rapidocr import RapidOCR

def main():
    video_path = Path("ocr_input/114877-720p.mp4")
    if not video_path.exists():
        print(f"Error: {video_path} 不存在")
        return

    cap = cv2.VideoCapture(str(video_path))
    video_fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    total_video_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    video_duration = total_video_frames / video_fps
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    roi_top = int(h * (1.0 - 0.28))

    print(f"=== 开始执行 114877 全片真实 OCR 阶段评测 ===")
    print(f"视频: {video_path}")
    print(f"时长: {video_duration:.2f} 秒 ({video_duration/60:.2f} 分钟)")
    print(f"分辨率: {w}x{h} (底部 28% ROI y={roi_top}:{h})")

    # 初始化 RapidOCR CUDA
    ocr_params = {
        "Rec.lang_type": "japan",
        "EngineConfig.onnxruntime.use_cuda": True,
        "Det.limit_side_len": 960  # 保持 720p 生产基准
    }
    ocr = RapidOCR(params=ocr_params)
    ocr(np.zeros((100, 100, 3), dtype=np.uint8))

    # 抽帧设置 (2 fps -> 步长为 video_fps / 2)
    step = int(round(video_fps / 2.0))
    if step < 1:
        step = 1

    sample_count = 0
    ocr_call_count = 0
    prev_roi_gray = None
    results = []

    torch.cuda.reset_peak_memory_stats()
    vram_start = torch.cuda.memory_allocated() / (1024**2)

    t_start = time.perf_counter()
    curr_frame_idx = 0

    while curr_frame_idx < total_video_frames:
        cap.set(cv2.CAP_PROP_POS_FRAMES, curr_frame_idx)
        ret, frame = cap.read()
        if not ret:
            break

        roi = frame[roi_top:h, 0:w]
        sample_count += 1
        sec = curr_frame_idx / video_fps

        # 帧差过滤
        roi_gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        is_keyframe = False
        if prev_roi_gray is None:
            is_keyframe = True
        else:
            diff = cv2.absdiff(roi_gray, prev_roi_gray)
            mse = np.mean(diff ** 2)
            if mse > 5.0:  # 帧差门槛
                is_keyframe = True

        if is_keyframe:
            prev_roi_gray = roi_gray
            out = ocr(roi)
            ocr_call_count += 1
            if out and out.txts:
                txt = "".join([t.strip() for t in out.txts if t.strip()])
                if txt:
                    results.append({"time": sec, "text": txt})

        curr_frame_idx += step

        # 每 500 抽样帧打印进度
        if sample_count % 500 == 0:
            elapsed = time.perf_counter() - t_start
            pct = (curr_frame_idx / total_video_frames) * 100
            print(f"进度: {pct:5.1f}% | 抽样帧: {sample_count} | 触发 OCR: {ocr_call_count} | 耗时: {elapsed:5.1f}s")

    cap.release()
    t_end = time.perf_counter()
    total_ocr_sec = t_end - t_start
    peak_vram_mb = torch.cuda.max_memory_allocated() / (1024**2)

    print("\n" + "=" * 80)
    print("           114877 全片真实 OCR 阶段物理耗时实测结果")
    print("=" * 80)
    print(f"全片视频总时长:          {video_duration:.2f} 秒 ({video_duration/60:.2f} 分钟)")
    print(f"2fps 实际抽样帧数:       {sample_count} 帧")
    print(f"帧差过滤后实际 OCR 次数:  {ocr_call_count} 次 (过滤比: {(1 - ocr_call_count/sample_count)*100:.1f}%)")
    print(f"识别出的非空字幕行数:    {len(results)} 行")
    print(f"真实 OCR 阶段全量耗时:    {total_ocr_sec:.2f} 秒 ({total_ocr_sec/60:.2f} 分钟)")
    print(f"单次 OCR 调用平均耗时:    {total_ocr_sec/ocr_call_count*1000:.1f} ms")
    print(f"峰值显存占用:            {peak_vram_mb:.1f} MB (增量)")
    print("=" * 80)

    report = {
        "video_duration_sec": video_duration,
        "sample_count": sample_count,
        "ocr_call_count": ocr_call_count,
        "recognized_lines": len(results),
        "total_ocr_sec": total_ocr_sec,
        "avg_call_ms": total_ocr_sec / ocr_call_count * 1000 if ocr_call_count > 0 else 0,
        "peak_vram_mb": peak_vram_mb
    }
    with open("bench/i4_full_video_ocr_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print("实测报告已落盘至 bench/i4_full_video_ocr_report.json")

if __name__ == "__main__":
    main()
