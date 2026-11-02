"""
M2 对照组: 5 帧随机取一帧 对照基线评测
======================================
1. 对 12 帧人工真值时间戳，取 5 帧: [t-0.5s, t-0.25s, t, t+0.25s, t+0.5s]；
2. 使用默认 PP-OCRv6 (直接调用，零空格注入) 识别全部 60 个候选画面；
3. 计算逐帧、各时间偏移、以及 5 帧随机选一帧 (Monte Carlo 1000次模拟期望值与固定种子 seed=42) 的 CER；
4. 输出至 bench/m2_control_baseline_report.json。
"""

import sys
import json
import random
import subprocess
from pathlib import Path
import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import animeautosub._env
from rapidocr import RapidOCR
from animeautosub.core.comparator import compare_texts, calculate_cer

FFMPEG_BIN = r"D:\Dev\ffmpeg\bin\ffmpeg.exe"
VIDEO_PATH = "ocr_input/114877-720p.mp4"

def extract_frame_ffmpeg(sec: float) -> np.ndarray:
    """使用 FFmpeg 精确抽取指定秒数的画面"""
    cmd = [
        FFMPEG_BIN, "-y", "-ss", f"{sec:.3f}", "-i", VIDEO_PATH,
        "-vframes", "1", "-f", "image2pipe", "-vcodec", "rawvideo",
        "-pix_fmt", "bgr24", "-"
    ]
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if len(p.stdout) == 1280 * 720 * 3:
        return np.frombuffer(p.stdout, dtype=np.uint8).reshape((720, 1280, 3))
    return None

def clean_ocr(out) -> str:
    if not out or not out.txts:
        return ""
    return "".join([t.strip() for t in out.txts if t.strip()])

def main():
    with open("bench/truth_frames/truth_manual.json", "r", encoding="utf-8") as f:
        manual_data = json.load(f)
    with open("bench/truth_frames/truth_metadata.json", "r", encoding="utf-8") as f:
        meta_data = json.load(f)

    meta_dict = {m["id"]: m for m in meta_data}
    sub_items = [item for item in manual_data["items"] if item["kind"] == "subtitle"]

    ocr = RapidOCR(params={"EngineConfig.onnxruntime.use_cuda": True})

    offsets = [-0.5, -0.25, 0.0, 0.25, 0.5]
    total_truth_chars = sum(len(x["truth"]) for x in sub_items)

    print("=" * 80)
    print(f"      开始评测 M2 对照组 (12 个真值时间戳 x 5 个偏移点 = 60 帧识别)")
    print("=" * 80)

    dataset_eval = []
    # 统计各个固定偏移维度的总编辑距离
    offset_dist_totals = {off: 0 for off in offsets}

    for item in sub_items:
        fid = item["id"]
        truth = item["truth"]
        center_t = meta_dict[fid]["timestamp_sec"]

        item_records = []
        center_text = ""

        # 先识别 t=0 的中心帧
        frame_t0 = extract_frame_ffmpeg(center_t)
        roi_t0 = frame_t0[int(720 * 0.72):, :] if frame_t0 is not None else np.zeros((200, 1280, 3), dtype=np.uint8)
        out_t0 = ocr(roi_t0)
        center_text = clean_ocr(out_t0)

        for off in offsets:
            ts = center_t + off
            frame = extract_frame_ffmpeg(ts)
            roi = frame[int(720 * 0.72):, :] if frame is not None else np.zeros((200, 1280, 3), dtype=np.uint8)
            out = ocr(roi)
            txt = clean_ocr(out)

            dist_truth, _ = compare_texts(truth, txt)
            dist_center, _ = compare_texts(center_text, txt)
            sim_to_center = 1.0 - (dist_center / max(len(center_text), len(txt), 1)) if center_text else 0.0

            offset_dist_totals[off] += dist_truth

            item_records.append({
                "offset_sec": off,
                "timestamp_sec": round(ts, 3),
                "ocr_text": txt,
                "edit_dist_to_truth": dist_truth,
                "similarity_to_center": round(sim_to_center, 3),
                "valid_neighbor": (sim_to_center >= 0.6)
            })

        print(f"帧 {fid:03d} (t={center_t:7.2f}s | 真值 {len(truth):2d}字):")
        for rec in item_records:
            flag = "✓" if rec["valid_neighbor"] else "✗"
            print(f"  off={rec['offset_sec']:+5.2f}s | dist={rec['edit_dist_to_truth']:2d} | sim0={rec['similarity_to_center']:4.2f} [{flag}] | ocr: {rec['ocr_text'][:25]}")
        print("-" * 80)

        dataset_eval.append({
            "id": fid,
            "truth": truth,
            "truth_len": len(truth),
            "center_timestamp": center_t,
            "candidates": item_records
        })

    # 1. 各单一固定偏移的 CER
    offset_cers = {}
    for off in offsets:
        c = calculate_cer(offset_dist_totals[off], total_truth_chars)
        offset_cers[f"offset_{off:+.2f}s"] = {
            "total_edit_distance": offset_dist_totals[off],
            "cer_percent": round(c * 100, 2)
        }

    # 2. 对照组: 5 帧随机取 1 帧 (未过滤)
    # (a) 固定种子 seed=42
    rng42 = random.Random(42)
    dist_rand42 = 0
    picked_rand42 = []
    for item in dataset_eval:
        pick = rng42.choice(item["candidates"])
        dist_rand42 += pick["edit_dist_to_truth"]
        picked_rand42.append({"id": item["id"], "offset": pick["offset_sec"], "dist": pick["edit_dist_to_truth"]})
    cer_rand42 = calculate_cer(dist_rand42, total_truth_chars)

    # (b) Monte Carlo 10,000 次无偏采样，计算严格期望 CER 与标准差
    monte_carlo_runs = 10000
    mc_dists = []
    for _ in range(monte_carlo_runs):
        d = sum(random.choice(item["candidates"])["edit_dist_to_truth"] for item in dataset_eval)
        mc_dists.append(d)
    expected_dist = float(np.mean(mc_dists))
    expected_cer = (expected_dist / float(total_truth_chars)) * 100.0

    # 3. 对照组: 过滤后随机取 1 帧 (邻帧有效性过滤 similarity >= 0.6)
    mc_filtered_dists = []
    for _ in range(monte_carlo_runs):
        d = 0
        for item in dataset_eval:
            valid_cands = [c for c in item["candidates"] if c["valid_neighbor"]]
            if not valid_cands:
                valid_cands = item["candidates"]
            d += random.choice(valid_cands)["edit_dist_to_truth"]
        mc_filtered_dists.append(d)
    expected_filtered_dist = float(np.mean(mc_filtered_dists))
    expected_filtered_cer = (expected_filtered_dist / float(total_truth_chars)) * 100.0

    center_dist = offset_dist_totals[0.0]
    center_cer = calculate_cer(center_dist, total_truth_chars) * 100.0

    print("=" * 80)
    print("                     M2 对照基线汇总结果")
    print("=" * 80)
    print(f"总真值字符:                {total_truth_chars}")
    print(f"原中心帧 t=0.0s 基线:       编辑距离 {center_dist:2d} | CER = {center_cer:5.2f}%")
    print(f"5 帧随机取 1 帧 (seed=42):  编辑距离 {dist_rand42:2d} | CER = {cer_rand42*100:5.2f}%")
    print(f"5 帧随机取 1 帧 (1万次期望): 编辑距离 {expected_dist:.1f} | CER = {expected_cer:5.2f}%")
    print(f"有效性过滤后随机取 1 帧期望: 编辑距离 {expected_filtered_dist:.1f} | CER = {expected_filtered_cer:5.2f}%")
    print("-" * 80)
    for off, val in offset_cers.items():
        print(f"单一时间偏移 {off:<10}: 编辑距离 {val['total_edit_distance']:2d} | CER = {val['cer_percent']:5.2f}%")
    print("=" * 80)

    report = {
        "benchmark": "M2 5-frame Random Control Baseline",
        "total_truth_chars": total_truth_chars,
        "center_frame_baseline": {
            "offset_sec": 0.0,
            "edit_distance": center_dist,
            "cer_percent": round(center_cer, 2)
        },
        "random_pick_seed42": {
            "seed": 42,
            "edit_distance": dist_rand42,
            "cer_percent": round(cer_rand42 * 100, 2),
            "picks": picked_rand42
        },
        "random_pick_monte_carlo_expected": {
            "runs": monte_carlo_runs,
            "expected_edit_distance": round(expected_dist, 2),
            "expected_cer_percent": round(expected_cer, 2)
        },
        "filtered_random_pick_expected": {
            "filter": "similarity_to_center >= 0.6",
            "runs": monte_carlo_runs,
            "expected_edit_distance": round(expected_filtered_dist, 2),
            "expected_cer_percent": round(expected_filtered_cer, 2)
        },
        "individual_offsets": offset_cers,
        "per_frame_details": dataset_eval
    }

    report_path = Path("bench/m2_control_baseline_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"✓ 完整测试报告已保存至 {report_path}")

if __name__ == "__main__":
    main()
