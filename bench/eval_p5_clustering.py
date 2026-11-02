"""
[STATUS: REJECTED / 已废止 - 判定为负结果]
P5 聚类算法全量验证 (15 帧短集与 12 帧长集)
==============================================
评测结论 (2026-11-01):
  短集 15 帧: baseline 68 (15.49%) -> p5 65 (14.81%), +0.68pt (+3 字符, 抽样误差内)
  长集 12 帧: baseline 42 (13.25%) -> p5 52 (16.40%), -3.15pt (-10 字符, 背景噪点退化)
综合判定: det 2x 上采样 + y 轴聚类在本素材上无效/有害，已废止，严禁合入生产流水线。
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
from bench.run_m2_m3_full_pipeline import extract_crop_ffmpeg

def normalize_text(text: str) -> str:
    return re.sub(r'\s+', '', text)

def cluster_and_order_boxes(boxes_1x: np.ndarray) -> list:
    """
    P5(b) 工程行聚类：
    1. 计算每个检测框的几何中心 cy, cx 与高度 h；
    2. 计算基准字高 H = median(h)；
    3. 若两个框垂直中心距 |cy1 - cy2| < 0.45 * H 且水平无重大重叠，归为同一行；
    4. 行与行按 cy 从上到下排列；
    5. 行内各个框按 xmin 从左到右严格排列。
    """
    if boxes_1x is None or len(boxes_1x) == 0:
        return [], []

    boxes = list(boxes_1x)
    if len(boxes) == 1:
        return boxes, [boxes]

    infos = []
    for b in boxes:
        ymin, ymax = float(b[:, 1].min()), float(b[:, 1].max())
        xmin, xmax = float(b[:, 0].min()), float(b[:, 0].max())
        cy = (ymin + ymax) / 2.0
        cx = (xmin + xmax) / 2.0
        h = max(1.0, ymax - ymin)
        w = max(1.0, xmax - xmin)
        infos.append({
            "box": b, "cy": cy, "cx": cx,
            "ymin": ymin, "ymax": ymax,
            "xmin": xmin, "xmax": xmax,
            "h": h, "w": w
        })

    # 基准字高
    H = float(np.median([info["h"] for info in infos]))
    cy_threshold = H * 0.45

    # 聚类成行
    # 按 cy 从小到大排序
    infos.sort(key=lambda x: x["cy"])

    lines = [] # 每个元素为一行中的 infos 列表
    for info in infos:
        matched_line = None
        for line in lines:
            line_cy = np.mean([b["cy"] for b in line])
            # 判断垂直距离
            if abs(info["cy"] - line_cy) < cy_threshold:
                # 检查水平重叠度 (同一行内的文本块不应严重水平重叠)
                has_large_overlap = False
                for b_in_line in line:
                    x_overlap = max(0.0, min(info["xmax"], b_in_line["xmax"]) - max(info["xmin"], b_in_line["xmin"]))
                    min_w = min(info["w"], b_in_line["w"])
                    if x_overlap / min_w > 0.35: # 水平重合度超过 35% 说明是上下双行
                        has_large_overlap = True
                        break
                if not has_large_overlap:
                    matched_line = line
                    break
        if matched_line is not None:
            matched_line.append(info)
        else:
            lines.append([info])

    # 1. 行与行从上到下排序
    lines.sort(key=lambda l: np.mean([b["cy"] for b in l]))

    # 2. 行内从左到右排序
    ordered_boxes = []
    for l in lines:
        l.sort(key=lambda b: b["xmin"])
        for b in l:
            ordered_boxes.append(b["box"])

    return ordered_boxes, lines

def run_p5_pipeline(engine, img: np.ndarray, use_det2x: bool = True):
    det_model = engine._load_det_model()

    if use_det2x:
        h, w, _ = img.shape
        img_det = cv2.resize(img, (w * 2, h * 2), interpolation=cv2.INTER_LINEAR)
        scale = 2.0
    else:
        img_det = img
        scale = 1.0

    det_res = det_model(img_det)
    if det_res.boxes is None or len(det_res.boxes) == 0:
        return "", [], 0

    boxes_1x = det_res.boxes / scale
    ordered_boxes, lines = cluster_and_order_boxes(boxes_1x)

    crops = engine.crop_text_regions(img, np.array(ordered_boxes, dtype=np.float32))
    if not crops:
        return "", ordered_boxes, len(lines)

    try:
        rec_res = engine.recognize_txt(crops)
        if rec_res.txts:
            txt = normalize_text("".join([t.strip() for t in rec_res.txts if t.strip()]))
            return txt, ordered_boxes, len(lines)
    except Exception:
        pass

    return "", ordered_boxes, len(lines)

def evaluate_dataset(name: str, meta_path: str, truth_path: str, video_path: str, engine):
    with open(meta_path, "r", encoding="utf-8") as f:
        metas = json.load(f)
    with open(truth_path, "r", encoding="utf-8") as f:
        truth_items = json.load(f)["items"]

    truth_map = {item["id"]: normalize_text(item["truth"]) for item in truth_items if item.get("kind") != "watermark"}
    valid_metas = [m for m in metas if m["id"] in truth_map]

    print(f"\n=======================================================")
    print(f"评测数据集: {name} ({len(valid_metas)} 帧)")
    print(f"=======================================================")

    results = []
    for m in valid_metas:
        fid = m["id"]
        v_ts = m.get("verified_ts", m.get("clip_timestamp_sec", m.get("timestamp_sec")))
        truth_str = truth_map[fid]

        crop = extract_crop_ffmpeg(video_path, v_ts)
        if crop is None:
            continue

        # 1. 当前基线 (1x det + 默认)
        txt_base, _, _ = run_p5_pipeline(engine, crop, use_det2x=False)
        # 2. P5 组合 (2x det + 水平带聚类)
        txt_p5, _, num_lines = run_p5_pipeline(engine, crop, use_det2x=True)

        d_base = levenshtein_distance(txt_base, truth_str)
        d_p5 = levenshtein_distance(txt_p5, truth_str)

        results.append({
            "id": fid,
            "truth": truth_str,
            "dist_base": d_base,
            "dist_p5": d_p5,
            "txt_base": txt_base,
            "txt_p5": txt_p5,
            "num_lines": num_lines
        })

        flag = "✓ 改善" if d_p5 < d_base else ("✗ 退化" if d_p5 > d_base else "= 持平")
        print(f"  帧 {fid:02d} (len={len(truth_str):2d}): Base={d_base:2d} -> P5={d_p5:2d} ({flag}, lines={num_lines})")
        if d_p5 != d_base:
            print(f"         REF : {truth_str}")
            print(f"         BASE: {txt_base}")
            print(f"         P5  : {txt_p5}")

    total_chars = sum(len(r["truth"]) for r in results)
    tot_base = sum(r["dist_base"] for r in results)
    tot_p5 = sum(r["dist_p5"] for r in results)

    cer_base = tot_base / total_chars * 100
    cer_p5 = tot_p5 / total_chars * 100

    print(f"\n--- {name} 汇总 ---")
    print(f"总真值字符: {total_chars}")
    print(f"基线 (1x det): 编辑距离 {tot_base} | CER: {cer_base:.2f}%")
    print(f"P5 (2x det + 聚类): 编辑距离 {tot_p5} | CER: {cer_p5:.2f}% (净收益: {cer_base - cer_p5:+.2f}%)")

    return {
        "dataset": name,
        "total_chars": total_chars,
        "baseline": {"dist": tot_base, "cer_percent": round(cer_base, 2)},
        "p5_result": {"dist": tot_p5, "cer_percent": round(cer_p5, 2)},
        "improvement_cer_percent": round(cer_base - cer_p5, 2),
        "frames": results
    }

def main():
    engine = RapidOCR(params={"EngineConfig.onnxruntime.use_cuda": True})

    # 1. 评测 15 帧短集
    short_res = evaluate_dataset(
        name="15_frames_short_set",
        meta_path="bench/truth_short/truth_metadata.json",
        truth_path="bench/truth_short/truth_manual.json",
        video_path="ocr_input/test_3min.mp4",
        engine=engine
    )

    # 2. 评测 12 帧长集
    long_res = evaluate_dataset(
        name="12_frames_long_set",
        meta_path="bench/truth_frames/truth_metadata.json",
        truth_path="bench/truth_frames/truth_manual.json",
        video_path="ocr_input/114877-720p.mp4",
        engine=engine
    )

    out = {
        "short_15_frames": short_res,
        "long_12_frames": long_res
    }
    with open("bench/p5_final_eval_report.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("\n✓ 结构化评测结果已写入 bench/p5_final_eval_report.json")

if __name__ == "__main__":
    main()
