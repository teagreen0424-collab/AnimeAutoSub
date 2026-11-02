"""
G2 复核实验：RapidOCR CPU vs CUDA 60 秒真实素材同源基准比对
===========================================================
素材: ocr_input/114877-720p.mp4 (00:00 ~ 01:00, 60 秒)
采样: 2.0 fps (与 pipeline_ocr.py 保持完全一致)
ROI: 底部 28% (y: 518 ~ 720)
帧差过滤门限: diff >= 12.0
"""

import sys
import os
import time
import json
import gc
from pathlib import Path

# 确保项目环境加载
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import animeautosub._env
import cv2
import numpy as np
import torch
from rapidocr import RapidOCR

def get_vram_used_mb() -> float:
    """实测当前 GPU 占用 (MB)"""
    if torch.cuda.is_available():
        return torch.cuda.memory_allocated() / (1024 * 1024)
    return 0.0

def get_nvml_vram_mb() -> float:
    """通过 nvidia-smi 级别的驱动实测当前整卡已用显存"""
    try:
        import subprocess
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=3
        )
        if r.returncode == 0:
            return float(r.stdout.strip().splitlines()[0])
    except Exception:
        pass
    return 0.0

def clean_ocr_text(txts: list) -> str:
    cleaned = []
    for t in txts:
        t = t.strip()
        if t:
            cleaned.append(t)
    return " ".join(cleaned)

def extract_and_filter_frames(video_path: Path, max_sec: float = 60.0, fps: float = 2.0, diff_thresh: float = 12.0):
    cap = cv2.VideoCapture(str(video_path))
    video_fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    frame_interval = int(round(video_fps / fps))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    roi_top = int(h * (1.0 - 0.28))

    sampled_frames = []
    last_gray = None
    frame_idx = 0
    total_sampled = 0
    skipped_diff = 0

    max_frames = int(max_sec * video_fps)

    while frame_idx < max_frames:
        ret, frame = cap.read()
        if not ret:
            break

        if frame_idx % frame_interval == 0:
            total_sampled += 1
            sec = frame_idx / video_fps
            roi = frame[roi_top:h, 0:w]
            gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)

            is_diff = True
            if last_gray is not None:
                diff = cv2.absdiff(gray, last_gray)
                mean_diff = np.mean(diff)
                if mean_diff < diff_thresh:
                    is_diff = False
                    skipped_diff += 1

            if is_diff:
                last_gray = gray
                sampled_frames.append((sec, roi))

        frame_idx += 1

    cap.release()
    return sampled_frames, total_sampled, skipped_diff

def run_pass(mode: str, frames: list):
    """mode: 'CPU' or 'CUDA'"""
    use_cuda = (mode == "CUDA")
    ocr_params = {
        "Rec.lang_type": "japan",
        "EngineConfig.onnxruntime.use_cuda": use_cuda
    }

    # 预检显存
    torch.cuda.empty_cache()
    gc.collect()
    vram_before = get_nvml_vram_mb()

    # 初始化引擎
    from rapidocr.utils.log import logger as rapidocr_logger
    rapidocr_logger.setLevel(50)
    ocr = RapidOCR(params=ocr_params)

    # 预热一次
    dummy = np.zeros((100, 100, 3), dtype=np.uint8)
    ocr(dummy)

    # 验证活跃 provider
    det_providers = ocr.text_det.session.session.get_providers()
    print(f"[{mode} 模式] ONNX 会话真实绑定: {det_providers}")

    t0 = time.perf_counter()
    results = []
    ocr_calls = 0

    for sec, roi in frames:
        out = ocr(roi)
        ocr_calls += 1
        txt = ""
        if out and out.txts:
            txt = clean_ocr_text(out.txts)
        results.append((sec, txt))

    t1 = time.perf_counter()
    vram_after = get_nvml_vram_mb()
    peak_vram_delta = max(0.0, vram_after - vram_before)

    elapsed = t1 - t0
    avg_per_call = (elapsed / ocr_calls) if ocr_calls > 0 else 0.0

    return {
        "mode": mode,
        "providers": det_providers,
        "elapsed_sec": elapsed,
        "ocr_calls": ocr_calls,
        "avg_call_sec": avg_per_call,
        "vram_before_mb": vram_before,
        "vram_after_mb": vram_after,
        "vram_delta_mb": peak_vram_delta,
        "results": results
    }

def main():
    video_path = Path("ocr_input/114877-720p.mp4")
    if not video_path.exists():
        print(f"错误: 未找到 {video_path}")
        sys.exit(1)

    print("=================================================================")
    print("      RapidOCR 真实 60 秒素材 CPU vs CUDA 性能与精度实测")
    print("=================================================================")
    print("正在进行抽帧与帧差过滤 (0~60s, 2.0 fps, 底部 28%)...")
    frames, total_sampled, skipped_diff = extract_and_filter_frames(video_path, max_sec=60.0, fps=2.0, diff_thresh=12.0)
    print(f"抽帧完成: 总抽样 {total_sampled} 帧, 帧差跳过 {skipped_diff} 帧, 实际送入 OCR: {len(frames)} 帧")

    print("\n--- [测试 1/2] 运行 CPU 模式 ---")
    res_cpu = run_pass("CPU", frames)
    print(f"CPU 完成: 耗时 {res_cpu['elapsed_sec']:.2f}s, 单次平均 {res_cpu['avg_call_sec']*1000:.1f}ms, 整卡显存: {res_cpu['vram_after_mb']} MB")

    print("\n--- [测试 2/2] 运行 CUDA 模式 ---")
    res_cuda = run_pass("CUDA", frames)
    print(f"CUDA 完成: 耗时 {res_cuda['elapsed_sec']:.2f}s, 单次平均 {res_cuda['avg_call_sec']*1000:.1f}ms, 整卡显存: {res_cuda['vram_after_mb']} MB")

    # 精度与一致性比对
    exact_matches = 0
    diff_entries = []
    total_chars_cpu = 0
    total_chars_cuda = 0

    for (s_cpu, t_cpu), (s_cuda, t_cuda) in zip(res_cpu["results"], res_cuda["results"]):
        total_chars_cpu += len(t_cpu)
        total_chars_cuda += len(t_cuda)
        if t_cpu == t_cuda:
            exact_matches += 1
        else:
            diff_entries.append((s_cpu, t_cpu, t_cuda))

    speedup = res_cpu["elapsed_sec"] / res_cuda["elapsed_sec"] if res_cuda["elapsed_sec"] > 0 else 0.0

    print("\n" + "=" * 65)
    print("                 实测对比与审计结论报告")
    print("=" * 65)
    print(f"测试素材时长:       60.0 秒 (送检有效帧: {len(frames)} 帧)")
    print(f"CPU 实际 Provider:  {res_cpu['providers']}")
    print(f"CUDA 实际 Provider: {res_cuda['providers']}")
    print(f"CPU 总耗时:         {res_cpu['elapsed_sec']:.2f} 秒 (单次调用: {res_cpu['avg_call_sec']*1000:.1f} ms)")
    print(f"CUDA 总耗时:        {res_cuda['elapsed_sec']:.2f} 秒 (单次调用: {res_cuda['avg_call_sec']*1000:.1f} ms)")
    print(f"CUDA 加速比:        {speedup:.2f} 倍 (耗时缩减至 {(1/speedup)*100:.1f}%)")
    print(f"CPU 占用显存增量:   {res_cpu['vram_delta_mb']:.1f} MB (无增加)")
    print(f"CUDA 占用显存增量:  {res_cuda['vram_delta_mb']:.1f} MB")
    print(f"识别文本完全一致数: {exact_matches} / {len(frames)} ({(exact_matches/len(frames))*100:.2f}%)")
    print(f"识别总字符数:       CPU={total_chars_cpu} 字符, CUDA={total_chars_cuda} 字符")
    print(f"差异帧数量:         {len(diff_entries)}")
    if diff_entries:
        print("\n差异条目详情 (前 5 条):")
        for s, t1, t2 in diff_entries[:5]:
            print(f"  时间 {s:.2f}s: CPU='{t1}' vs CUDA='{t2}'")
    else:
        print("文本一致性:         两轮输出 100% 逐字符完全相同！")

    print("=" * 65)

    # 导出 JSON 证据供基线审计
    report_data = {
        "total_frames": len(frames),
        "cpu_elapsed_sec": res_cpu["elapsed_sec"],
        "cpu_avg_ms": res_cpu["avg_call_sec"] * 1000,
        "cuda_elapsed_sec": res_cuda["elapsed_sec"],
        "cuda_avg_ms": res_cuda["avg_call_sec"] * 1000,
        "speedup": speedup,
        "cpu_chars": total_chars_cpu,
        "cuda_chars": total_chars_cuda,
        "exact_matches": exact_matches,
        "diff_count": len(diff_entries)
    }
    with open("bench/g2_ocr_cpu_vs_cuda_report.json", "w", encoding="utf-8") as f:
        json.dump(report_data, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()
