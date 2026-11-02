"""
H1 & H2 综合实验脚本：
1. 三次重跑量出真实噪声底 (Pass 1, Pass 2, Pass 3)
2. 验证 Rec 模型输入动态宽度假设 (固定 Padding 到 960 对照测试)
"""

import sys
import os
import json
import time
import math
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import animeautosub._env
import cv2
import numpy as np
from rapidocr import RapidOCR
from rapidocr.ch_ppocr_rec.main import TextRecognizer
from animeautosub.core.comparator import compare_texts, calculate_cer

def clean_txt(out) -> str:
    if not out or not out.txts:
        return ""
    return "".join([t.strip() for t in out.txts if t.strip()])

def main():
    video_path = Path("ocr_input/114877-720p.mp4")
    ja_ref_path = Path("bench/fixtures/reference/ocr_720p/japanese.json")
    if not ja_ref_path.exists():
        ja_ref_path = Path("ocr_output/114877-720p/japanese.json")

    with open(ja_ref_path, "r", encoding="utf-8") as f:
        ja_data = json.load(f)

    # 均匀抽取 100 句字幕的中心帧
    total_subs = len(ja_data)
    step = total_subs / 100.0
    selected_indices = [int(i * step) for i in range(100)]
    selected_subs = [ja_data[i] for i in selected_indices]

    cap = cv2.VideoCapture(str(video_path))
    video_fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    roi_top = int(h * (1.0 - 0.28))

    print(f"正在从 {video_path} 截取 100 帧真实硬字幕图像...")
    frames_meta = []
    frames_data = []
    for idx, item in enumerate(selected_subs):
        mid_sec = (item["start"] + item["end"]) / 2.0
        frame_num = int(mid_sec * video_fps)
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
        ret, frame = cap.read()
        if not ret:
            continue
        roi = frame[roi_top:h, 0:w]
        frames_meta.append((idx, mid_sec, item["text"]))
        frames_data.append(roi)
    cap.release()
    print(f"成功截取 {len(frames_data)} 帧。")

    ocr_params = {
        "Rec.lang_type": "japan",
        "EngineConfig.onnxruntime.use_cuda": True
    }

    # =========================================================================
    # 实验一：原生动态宽度下的三次独立重跑 (Pass 1, Pass 2, Pass 3)
    # =========================================================================
    print("\n=======================================================")
    print("【实验一】原生动态宽度下的三次独立重跑 (Pass 1, 2, 3)")
    print("=======================================================")
    ocr_standard = RapidOCR(params=ocr_params)
    
    # 跑 Pass 1
    t0 = time.perf_counter()
    pass1_res = [clean_txt(ocr_standard(f)) for f in frames_data]
    t1 = time.perf_counter()
    p1_time = t1 - t0
    print(f"Pass 1 耗时: {p1_time:.2f}s (单帧平均: {p1_time/len(frames_data)*1000:.1f}ms)")

    # 跑 Pass 2
    t2 = time.perf_counter()
    pass2_res = [clean_txt(ocr_standard(f)) for f in frames_data]
    t3 = time.perf_counter()
    p2_time = t3 - t2
    print(f"Pass 2 耗时: {p2_time:.2f}s (单帧平均: {p2_time/len(frames_data)*1000:.1f}ms)")

    # 跑 Pass 3
    t4 = time.perf_counter()
    pass3_res = [clean_txt(ocr_standard(f)) for f in frames_data]
    t5 = time.perf_counter()
    p3_time = t5 - t4
    print(f"Pass 3 耗时: {p3_time:.2f}s (单帧平均: {p3_time/len(frames_data)*1000:.1f}ms)")

    # 逐帧比对 Pass 1 vs Pass 2
    diffs_p1_p2 = []
    tot_chars = 0
    tot_dist_12 = 0
    for i, ((idx, sec, ref_txt), s1, s2) in enumerate(zip(frames_meta, pass1_res, pass2_res)):
        tot_chars += len(s1)
        d, label = compare_texts(s1, s2)
        if d > 0:
            tot_dist_12 += d
            diffs_p1_p2.append((i+1, sec, s1, s2, d, label))

    # 逐帧比对 Pass 2 vs Pass 3
    diffs_p2_p3 = []
    tot_dist_23 = 0
    for i, ((idx, sec, ref_txt), s2, s3) in enumerate(zip(frames_meta, pass2_res, pass3_res)):
        d, label = compare_texts(s2, s3)
        if d > 0:
            tot_dist_23 += d
            diffs_p2_p3.append((i+1, sec, s2, s3, d, label))

    # 逐帧比对 Pass 1 vs Pass 3
    diffs_p1_p3 = []
    tot_dist_13 = 0
    for i, ((idx, sec, ref_txt), s1, s3) in enumerate(zip(frames_meta, pass1_res, pass3_res)):
        d, label = compare_texts(s1, s3)
        if d > 0:
            tot_dist_13 += d
            diffs_p1_p3.append((i+1, sec, s1, s3, d, label))

    cer_12 = calculate_cer(tot_dist_12, tot_chars)
    cer_23 = calculate_cer(tot_dist_23, tot_chars)
    cer_13 = calculate_cer(tot_dist_13, tot_chars)

    print("\n--- 实验一结果：原生三轮比对 ---")
    print(f"总抽检字符数: {tot_chars} (100 帧)")
    print(f"Pass 1 vs Pass 2: 差异帧数 = {len(diffs_p1_p2)}/100, 累计编辑距离 = {tot_dist_12}, CER = {cer_12*100:.4f}%")
    print(f"Pass 2 vs Pass 3: 差异帧数 = {len(diffs_p2_p3)}/100, 累计编辑距离 = {tot_dist_23}, CER = {cer_23*100:.4f}%")
    print(f"Pass 1 vs Pass 3: 差异帧数 = {len(diffs_p1_p3)}/100, 累计编辑距离 = {tot_dist_13}, CER = {cer_13*100:.4f}%")

    if diffs_p1_p2:
        print("\nPass 1 vs Pass 2 差异帧明细:")
        for fid, sec, s1, s2, d, label in diffs_p1_p2:
            print(f"  Frame {fid:03d} @ {sec:.2f}s: P1='{s1}' vs P2='{s2}' -> {label}")
    else:
        print("Pass 1 与 Pass 2 逐字完全相同！")

    # =========================================================================
    # 实验二：固定宽度 Padding 对照实验 (Fixed Width = 960)
    # =========================================================================
    print("\n=======================================================")
    print("【实验二】固定 Padding 宽度 (960px) 对照实验")
    print("=======================================================")

    FIXED_RECOG_WIDTH = 960

    def fixed_resize_norm_img(self, img: np.ndarray, max_wh_ratio: float) -> np.ndarray:
        img_channel, img_height, _ = self.rec_image_shape
        assert img_channel == img.shape[2]

        # 强制使用固定宽度，消除不同字符长度导致的输入维度抖动
        img_width = FIXED_RECOG_WIDTH

        h, w = img.shape[:2]
        ratio = w / float(h)
        resized_w = min(img_width, int(math.ceil(img_height * ratio)))

        resized_image = cv2.resize(img, (resized_w, img_height))
        resized_image = resized_image.astype("float32")
        resized_image = resized_image.transpose((2, 0, 1)) / 255.0
        resized_image -= 0.5
        resized_image /= 0.5

        padding_im = np.zeros((img_channel, img_height, img_width), dtype=np.float32)
        padding_im[:, :, 0:resized_w] = resized_image
        return padding_im

    # 应用猴子补丁
    orig_resize_norm_img = TextRecognizer.resize_norm_img
    TextRecognizer.resize_norm_img = fixed_resize_norm_img

    try:
        # 新建一个全新的 RapidOCR 实例，测试固定 Padding 下冷启动与稳态耗时
        ocr_fixed = RapidOCR(params=ocr_params)

        t_f0 = time.perf_counter()
        fixed_p1_res = [clean_txt(ocr_fixed(f)) for f in frames_data]
        t_f1 = time.perf_counter()
        fixed_p1_time = t_f1 - t_f0
        print(f"固定 Padding Pass 1 耗时: {fixed_p1_time:.2f}s (单帧平均: {fixed_p1_time/len(frames_data)*1000:.1f}ms)")

        t_f2 = time.perf_counter()
        fixed_p2_res = [clean_txt(ocr_fixed(f)) for f in frames_data]
        t_f3 = time.perf_counter()
        fixed_p2_time = t_f3 - t_f2
        print(f"固定 Padding Pass 2 耗时: {fixed_p2_time:.2f}s (单帧平均: {fixed_p2_time/len(frames_data)*1000:.1f}ms)")

        # 比对固定 Padding 下 Pass 1 vs Pass 2
        diffs_fixed = []
        tot_dist_fixed = 0
        tot_chars_fixed = 0
        for i, ((idx, sec, ref_txt), s1, s2) in enumerate(zip(frames_meta, fixed_p1_res, fixed_p2_res)):
            tot_chars_fixed += len(s1)
            d, label = compare_texts(s1, s2)
            if d > 0:
                tot_dist_fixed += d
                diffs_fixed.append((i+1, sec, s1, s2, d, label))

        cer_fixed = calculate_cer(tot_dist_fixed, tot_chars_fixed)
        print("\n--- 实验二结果：固定 Padding (960px) ---")
        print(f"差异帧数: {len(diffs_fixed)}/100, 累计编辑距离: {tot_dist_fixed}, CER: {cer_fixed*100:.4f}%")
        print(f"Pass 1 耗时对比: 原生动态 = {p1_time:.2f}s vs 固定 Padding = {fixed_p1_time:.2f}s")
        print(f"Pass 2 耗时对比: 原生动态 = {p2_time:.2f}s vs 固定 Padding = {fixed_p2_time:.2f}s")

    finally:
        # 恢复原方法
        TextRecognizer.resize_norm_img = orig_resize_norm_img

    # 导出完整实验报告 JSON
    report = {
        "total_frames": len(frames_data),
        "total_chars": tot_chars,
        "standard": {
            "p1_time": p1_time,
            "p2_time": p2_time,
            "p3_time": p3_time,
            "diffs_p1_p2": len(diffs_p1_p2),
            "cer_p1_p2": cer_12,
            "diffs_p2_p3": len(diffs_p2_p3),
            "cer_p2_p3": cer_23,
            "diffs_p1_p3": len(diffs_p1_p3),
            "cer_p1_p3": cer_13,
            "diff_records_p1_p2": diffs_p1_p2
        },
        "fixed_padding": {
            "p1_time": fixed_p1_time,
            "p2_time": fixed_p2_time,
            "diffs": len(diffs_fixed),
            "cer": cer_fixed,
            "diff_records": diffs_fixed
        }
    }
    with open("bench/h1_h2_experiment_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print("\n已将完整实验报告落盘至 bench/h1_h2_experiment_report.json")

if __name__ == "__main__":
    main()
