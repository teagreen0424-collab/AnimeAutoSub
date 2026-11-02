"""
N3: 真实时间戳多点扫描与校验回填工具 (verify_timestamps_n3.py)
============================================================
1. 对 12 帧长集与 15 帧短集中的每一帧，在原时间戳 t ± 2.0s 范围内以 0.1s 步长密集扫描 (41个时间戳)；
2. 提取画面底部 28% 区域运行 RapidOCR；
3. 将扫描结果与已导出的裁图 OCR 及真值文本比对；
4. 定位稳定显示区间（plateau），选取区间中点作为 verified_ts，彻底杜绝淡入/淡出边界抽样；
5. 将 verified_ts 回填至 truth_metadata.json，并生成详细校验报告 bench/n3_verified_timestamps.json。
"""

import sys
import json
import re
import subprocess
from pathlib import Path
from difflib import SequenceMatcher
import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import animeautosub._env
from rapidocr import RapidOCR
from animeautosub.core.comparator import levenshtein_distance

FFMPEG_BIN = r"D:\Dev\ffmpeg\bin\ffmpeg.exe"

def extract_crop_ffmpeg(video_path: str, sec: float, height_ratio: float = 0.28) -> np.ndarray:
    """使用 FFmpeg 精确抽取指定时间戳画面并裁剪底部 height_ratio 区域"""
    cmd = [
        FFMPEG_BIN, "-y", "-ss", f"{sec:.3f}", "-i", video_path,
        "-vframes", "1", "-f", "image2pipe", "-vcodec", "rawvideo",
        "-pix_fmt", "bgr24", "-"
    ]
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if len(p.stdout) == 1280 * 720 * 3:
        frame = np.frombuffer(p.stdout, dtype=np.uint8).reshape((720, 1280, 3))
        h, w, _ = frame.shape
        crop_y = int(h * (1.0 - height_ratio))
        return frame[crop_y:h, 0:w]
    return None

def normalize_text(text: str) -> str:
    """规范化文本，去除空白字符"""
    return re.sub(r'\s+', '', text)

def run_ocr(ocr_engine, img: np.ndarray) -> str:
    """运行 OCR 并返回去除空白的整句文本"""
    if img is None:
        return ""
    out = ocr_engine(img)
    if out and out.txts:
        # 使用修正后的 clean_ocr_text 语义：直接拼接
        raw = "".join([t.strip() for t in out.txts if t.strip()])
        return normalize_text(raw)
    return ""

def scan_frame_timestamp(
    video_path: str,
    orig_ts: float,
    crop_path: str,
    truth_text: str,
    ocr_engine,
    scan_range: float = 2.0,
    step: float = 0.1
) -> dict:
    """在 orig_ts ± scan_range 范围内以 step 扫描，寻找稳定显示中心 verified_ts"""
    # 1. 获取原裁图的 OCR 文本
    crop_img = cv2.imread(crop_path)
    crop_ocr = run_ocr(ocr_engine, crop_img)
    norm_truth = normalize_text(truth_text) if truth_text else crop_ocr

    # 2. 扫描候选时间戳
    steps_count = int(round(scan_range * 2 / step)) + 1
    candidates = []
    
    for i in range(steps_count):
        curr_ts = round(orig_ts - scan_range + i * step, 3)
        if curr_ts < 0:
            continue
        c_crop = extract_crop_ffmpeg(video_path, curr_ts)
        c_ocr = run_ocr(ocr_engine, c_crop)
        
        sim_to_crop = SequenceMatcher(None, c_ocr, crop_ocr).ratio() if crop_ocr else 0.0
        dist_to_truth = levenshtein_distance(c_ocr, norm_truth)
        
        candidates.append({
            "ts": curr_ts,
            "ocr": c_ocr,
            "sim_to_crop": round(sim_to_crop, 3),
            "dist_to_truth": dist_to_truth
        })

    # 3. 寻找稳定匹配 plateau（sim_to_crop >= 0.85 或与 truth 编辑距离在最优档内）
    # 先找出最小编辑距离
    min_dist = min(c["dist_to_truth"] for c in candidates)
    # 最优候选集合
    best_cands = [c for c in candidates if c["dist_to_truth"] <= min_dist + 1 and c["sim_to_crop"] >= 0.70]
    
    if not best_cands:
        # 回退到相似度最高者
        max_sim = max(c["sim_to_crop"] for c in candidates)
        best_cands = [c for c in candidates if c["sim_to_crop"] >= max_sim - 0.05]
    
    # 选取连续稳定区间的中点
    # 取 best_cands 的中位数时间戳
    best_cands.sort(key=lambda x: x["ts"])
    mid_idx = len(best_cands) // 2
    selected = best_cands[mid_idx]
    verified_ts = selected["ts"]

    # 原时间戳下的表现 vs verified_ts 下的表现
    orig_cand = min(candidates, key=lambda x: abs(x["ts"] - orig_ts))

    return {
        "orig_ts": orig_ts,
        "verified_ts": verified_ts,
        "delta_sec": round(verified_ts - orig_ts, 3),
        "crop_ocr": crop_ocr,
        "truth": norm_truth,
        "orig_perf": {
            "ts": orig_cand["ts"],
            "ocr": orig_cand["ocr"],
            "dist": orig_cand["dist_to_truth"],
            "sim_to_crop": orig_cand["sim_to_crop"]
        },
        "verified_perf": {
            "ts": selected["ts"],
            "ocr": selected["ocr"],
            "dist": selected["dist_to_truth"],
            "sim_to_crop": selected["sim_to_crop"]
        },
        "stable_window": [best_cands[0]["ts"], best_cands[-1]["ts"]]
    }

def main():
    ocr_engine = RapidOCR(params={"EngineConfig.onnxruntime.use_cuda": True})
    print("[N3] 开始执行真实时间戳多点扫描与校验...")

    # -------------------------------------------------------------
    # A. 处理 12 帧长集 (truth_frames)
    # -------------------------------------------------------------
    long_meta_path = Path("bench/truth_frames/truth_metadata.json")
    long_truth_path = Path("bench/truth_frames/truth_manual.json")
    long_video = "ocr_input/114877-720p.mp4"

    with open(long_meta_path, "r", encoding="utf-8") as f:
        long_meta = json.load(f)
    with open(long_truth_path, "r", encoding="utf-8") as f:
        long_truth = json.load(f)

    long_truth_map = {item["id"]: item["truth"] for item in long_truth["items"] if item.get("kind") != "watermark"}

    report_path = Path("bench/n3_verified_timestamps.json")
    if report_path.exists():
        with open(report_path, "r", encoding="utf-8") as f:
            prev_report = json.load(f)
            long_results = prev_report.get("long_12_frames", {})
    else:
        long_results = {}

    print("\n>>> 检查 12 帧长集 (720p 全片)...")
    for meta_item in long_meta:
        fid = meta_item["id"]
        if fid not in long_truth_map:
            continue
        if "verified_ts" in meta_item:
            print(f"  帧 {fid:02d}: 已有 verified_ts={meta_item['verified_ts']}")
            long_results[str(fid)] = {
                "orig_ts": meta_item["timestamp_sec"],
                "verified_ts": meta_item["verified_ts"],
                "delta_sec": round(meta_item["verified_ts"] - meta_item["timestamp_sec"], 3)
            }
            continue
        crop_file = f"bench/truth_frames/frame_{fid:03d}.jpg"
        truth_str = long_truth_map[fid]
        res = scan_frame_timestamp(
            video_path=long_video,
            orig_ts=meta_item["timestamp_sec"],
            crop_path=crop_file,
            truth_text=truth_str,
            ocr_engine=ocr_engine,
            scan_range=2.0,
            step=0.1
        )
        long_results[str(fid)] = res
        meta_item["verified_ts"] = res["verified_ts"]
        print(f"  帧 {fid:02d}: 原 ts={res['orig_ts']:.3f}s (dist={res['orig_perf']['dist']}) "
              f"-> verified_ts={res['verified_ts']:.3f}s (dist={res['verified_perf']['dist']}, "
              f"Δ={res['delta_sec']:+.2f}s, 稳定区间=[{res['stable_window'][0]:.1f}~{res['stable_window'][1]:.1f}])")

    # 写回 long_meta
    with open(long_meta_path, "w", encoding="utf-8") as f:
        json.dump(long_meta, f, ensure_ascii=False, indent=2)
    print(f"✓ 12 帧长集 verified_ts 已写回 {long_meta_path}")

    # -------------------------------------------------------------
    # B. 处理 15 帧短集 (truth_short)
    # -------------------------------------------------------------
    short_meta_path = Path("bench/truth_short/truth_metadata.json")
    short_truth_path = Path("bench/truth_short/truth_manual.json")
    short_video = "ocr_input/test_3min.mp4"

    with open(short_meta_path, "r", encoding="utf-8") as f:
        short_meta = json.load(f)
    with open(short_truth_path, "r", encoding="utf-8") as f:
        short_truth = json.load(f)

    short_truth_map = {item["id"]: item["truth"] for item in short_truth["items"]}

    short_results = {}
    print("\n>>> 正在扫描 15 帧短集 (3min 切片)...")
    for meta_item in short_meta:
        fid = meta_item["id"]
        crop_file = f"bench/truth_short/frame_{fid:03d}.jpg"
        truth_str = short_truth_map.get(fid, "")
        orig_sec = meta_item.get("clip_timestamp_sec", meta_item.get("timestamp_sec", 0.0))
        res = scan_frame_timestamp(
            video_path=short_video,
            orig_ts=orig_sec,
            crop_path=crop_file,
            truth_text=truth_str,
            ocr_engine=ocr_engine,
            scan_range=2.0,
            step=0.1
        )
        short_results[fid] = res
        meta_item["verified_ts"] = res["verified_ts"]
        print(f"  短集帧 {fid:02d}: 原 ts={res['orig_ts']:.3f}s (dist={res['orig_perf']['dist']}) "
              f"-> verified_ts={res['verified_ts']:.3f}s (dist={res['verified_perf']['dist']}, "
              f"Δ={res['delta_sec']:+.2f}s, 稳定区间=[{res['stable_window'][0]:.1f}~{res['stable_window'][1]:.1f}])")

    # 写回 short_meta
    with open(short_meta_path, "w", encoding="utf-8") as f:
        json.dump(short_meta, f, ensure_ascii=False, indent=2)
    print(f"✓ 15 帧短集 verified_ts 已写回 {short_meta_path}")

    # 保存完整校验报告
    report = {
        "long_12_frames": long_results,
        "short_15_frames": short_results
    }
    with open("bench/n3_verified_timestamps.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"✓ 完整时间戳扫描报告已保存至 bench/n3_verified_timestamps.json")

if __name__ == "__main__":
    main()
