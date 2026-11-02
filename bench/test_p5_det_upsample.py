"""
P5 定向实验：det-only 2x 上采样与按 y 轴聚类双行合并
===================================================
1. 基准：1x det + 1x rec (当前生产配置)
2. 实验 A: 2x det-only 上采样 -> 坐标映射回原图 -> 原图裁切 1x rec
3. 实验 B: 在 A 的基础上进行 y 轴聚类与双行合并
"""

import sys
import json
import re
import cv2
import numpy as np
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import animeautosub._env
from rapidocr import RapidOCR
from animeautosub.core.comparator import levenshtein_distance, calculate_cer

def normalize_text(text: str) -> str:
    return re.sub(r'\s+', '', text)

def run_standard_ocr(engine, img: np.ndarray):
    """标准 1x det + 1x rec"""
    out = engine(img)
    if out and out.txts:
        # 拼接
        txt = normalize_text("".join([t.strip() for t in out.txts if t.strip()]))
        return txt, out.boxes
    return "", []

def run_det2x_ocr(engine, img: np.ndarray):
    """
    P5(a): det-only 2x 上采样：
    1. ROI 放大 2 倍只喂检测器 det_model；
    2. 拿到 boxes 后除以 2 映射回原分辨率；
    3. 从原分辨率 img 裁切送识别器 rec_model（识别器不放大）。
    """
    det_model = engine._load_det_model()
    rec_model = engine._load_rec_model()

    h, w, _ = img.shape
    img_2x = cv2.resize(img, (w * 2, h * 2), interpolation=cv2.INTER_LINEAR)
    
    det_res = det_model(img_2x)
    if det_res.boxes is None or len(det_res.boxes) == 0:
        return "", []

    # 坐标缩放回 1x
    boxes_1x = det_res.boxes / 2.0

    # 按照 top-to-bottom, left-to-right 排序
    boxes_sorted = sorted(boxes_1x, key=lambda b: (np.mean(b[:, 1]), np.mean(b[:, 0])))

    # 从原图裁剪送入识别
    crops = engine.crop_text_regions(img, np.array(boxes_sorted, dtype=np.float32))
    if not crops:
        return "", []

    try:
        rec_res = engine.recognize_txt(crops)
    except Exception:
        return "", boxes_sorted

    if rec_res.txts is None:
        return "", boxes_sorted

    txt = normalize_text("".join([t.strip() for t in rec_res.txts if t.strip()]))
    return txt, boxes_sorted

def run_det2x_merged_ocr(engine, img: np.ndarray):
    """
    P5(b): 在 det-only 2x 的基础上增加 y 轴聚类与行合并：
    同一水平带内、垂直间距 < 1.2 倍字高的多个框按 x 坐标合并。
    """
    det_model = engine._load_det_model()
    rec_model = engine._load_rec_model()

    h, w, _ = img.shape
    img_2x = cv2.resize(img, (w * 2, h * 2), interpolation=cv2.INTER_LINEAR)
    det_res = det_model(img_2x)
    if det_res.boxes is None or len(det_res.boxes) == 0:
        return "", []

    boxes_1x = det_res.boxes / 2.0

    # 计算各框中心与高度
    box_infos = []
    for b in boxes_1x:
        center_y = np.mean(b[:, 1])
        center_x = np.mean(b[:, 0])
        height = np.max(b[:, 1]) - np.min(b[:, 1])
        box_infos.append({"box": b, "cy": center_y, "cx": center_x, "h": height})

    # 按 y 轴进行聚类成行
    # 平均字高
    avg_h = np.mean([bi["h"] for bi in box_infos]) if box_infos else 20.0
    y_threshold = avg_h * 0.8

    # 聚类算法：将 cy 相差小于 y_threshold 的框归入同一行
    lines = []
    # 先按 cy 排序
    box_infos.sort(key=lambda x: x["cy"])
    for bi in box_infos:
        placed = False
        for line in lines:
            line_cy = np.mean([b["cy"] for b in line])
            if abs(bi["cy"] - line_cy) < y_threshold:
                line.append(bi)
                placed = True
                break
        if not placed:
            lines.append([bi])

    # 每一行按 cx 从左到右排序
    ordered_boxes = []
    for line in lines:
        line.sort(key=lambda x: x["cx"])
        for bi in line:
            ordered_boxes.append(bi["box"])

    # 从原图裁剪送识别
    crops = engine.crop_text_regions(img, np.array(ordered_boxes, dtype=np.float32))
    if not crops:
        return "", ordered_boxes

    try:
        rec_res = engine.recognize_txt(crops)
    except Exception:
        return "", ordered_boxes

    if rec_res.txts is None:
        return "", ordered_boxes

    txt = normalize_text("".join([t.strip() for t in rec_res.txts if t.strip()]))
    return txt, ordered_boxes

def main():
    engine = RapidOCR(params={"EngineConfig.onnxruntime.use_cuda": True})
    
    with open("bench/truth_short/truth_manual.json", "r", encoding="utf-8") as f:
        truth_items = json.load(f)["items"]
    with open("bench/truth_short/truth_metadata.json", "r", encoding="utf-8") as f:
        meta_items = json.load(f)

    truth_map = {item["id"]: normalize_text(item["truth"]) for item in truth_items}

    # 从视频提取 verified_ts 的中心裁图
    from bench.run_m2_m3_full_pipeline import extract_crop_ffmpeg
    video_path = "ocr_input/test_3min.mp4"

    results_baseline = []
    results_det2x = []
    results_merged = []

    print("=== 开始 P5 实验 (15 帧短集) ===")
    for m in meta_items:
        fid = m["id"]
        if fid not in truth_map:
            continue
        v_ts = m["verified_ts"]
        truth_str = truth_map[fid]

        crop = extract_crop_ffmpeg(video_path, v_ts)
        if crop is None:
            continue

        txt_base, boxes_base = run_standard_ocr(engine, crop)
        txt_2x, boxes_2x = run_det2x_ocr(engine, crop)
        txt_m, boxes_m = run_det2x_merged_ocr(engine, crop)

        d_base = levenshtein_distance(txt_base, truth_str)
        d_2x = levenshtein_distance(txt_2x, truth_str)
        d_m = levenshtein_distance(txt_m, truth_str)

        results_baseline.append({"id": fid, "dist": d_base, "txt": txt_base, "truth": truth_str})
        results_det2x.append({"id": fid, "dist": d_2x, "txt": txt_2x, "truth": truth_str})
        results_merged.append({"id": fid, "dist": d_m, "txt": txt_m, "truth": truth_str})

        print(f"帧 {fid:02d} (len={len(truth_str):2d}): Base={d_base:2d} -> Det2x={d_2x:2d} -> Merged={d_m:2d}")
        if d_2x != d_base or d_m != d_base:
            print(f"       REF : {truth_str}")
            print(f"       BASE: {txt_base}")
            print(f"       DET2: {txt_2x}")

    total_chars = sum(len(r["truth"]) for r in results_baseline)
    tot_base = sum(r["dist"] for r in results_baseline)
    tot_2x = sum(r["dist"] for r in results_det2x)
    tot_m = sum(r["dist"] for r in results_merged)

    print("\n" + "=" * 60)
    print(f"P5 实验汇总结果 (总真值: {total_chars} 字符):")
    print(f"1. 基线 (1x det + 1x rec):      编辑距离 {tot_base:3d} | CER: {tot_base/total_chars*100:.2f}%")
    print(f"2. P5(a) det-only 2x 上采样:    编辑距离 {tot_2x:3d} | CER: {tot_2x/total_chars*100:.2f}% (改善: {(tot_base-tot_2x)/total_chars*100:+.2f}%)")
    print(f"3. P5(b) det2x + y轴行聚类合并: 编辑距离 {tot_m:3d} | CER: {tot_m/total_chars*100:.2f}% (改善: {(tot_base-tot_m)/total_chars*100:+.2f}%)")
    print("=" * 60)

    # 导出 JSON 报告
    out_data = {
        "benchmark": "P5 Directed Experiment: Det-Only 2x Upsampling & Y-axis Line Merging",
        "total_truth_chars": total_chars,
        "baseline_1x": {"total_dist": tot_base, "cer_percent": round(tot_base/total_chars*100, 2)},
        "p5_a_det2x": {"total_dist": tot_2x, "cer_percent": round(tot_2x/total_chars*100, 2)},
        "p5_b_merged": {"total_dist": tot_m, "cer_percent": round(tot_m/total_chars*100, 2)},
        "frames_comparison": []
    }
    for i in range(len(results_baseline)):
        out_data["frames_comparison"].append({
            "id": results_baseline[i]["id"],
            "truth": results_baseline[i]["truth"],
            "baseline_dist": results_baseline[i]["dist"],
            "det2x_dist": results_det2x[i]["dist"],
            "merged_dist": results_merged[i]["dist"],
            "baseline_text": results_baseline[i]["txt"],
            "det2x_text": results_det2x[i]["txt"],
            "merged_text": results_merged[i]["txt"]
        })

    with open("bench/p5_experiment_report.json", "w", encoding="utf-8") as f:
        json.dump(out_data, f, ensure_ascii=False, indent=2)
    print("✓ 实验结果已保存至 bench/p5_experiment_report.json")

if __name__ == "__main__":
    main()
