"""
I3 实验：Rec 输入宽度统计与三档对比 (原生动态 vs 960固定 vs 32对齐分桶)
========================================================================
1. 遍历 100 帧硬字幕，统计检测框原始最长 Rec 宽度，验证 960 是否存在截断；
2. 实现 32 像素倍数分桶 (Bucket-32) 预处理；
3. 对比三档在 Pass 1 (冷启) 与 Pass 2 (稳态) 的实测耗时与 CER。
"""

import sys
import os
import json
import time
import math
import pickle
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
    pkl_path = "bench/ocr_test_100_frames.pkl"
    with open(pkl_path, "rb") as f:
        frames_data = pickle.load(f)

    # 1. 统计 100 帧中所有文本框的 Rec 裁剪尺寸
    det_ocr = RapidOCR(params={"EngineConfig.onnxruntime.use_cuda": True})
    det_ocr(np.zeros((100, 100, 3), dtype=np.uint8))

    rec_height = 48
    max_raw_w = 0
    raw_widths = []

    for f in frames_data:
        out = det_ocr(f)
        if not out or out.boxes is None:
            continue
        for box in out.boxes:
            b = np.array(box)
            w_box = np.linalg.norm(b[0] - b[1])
            h_box = np.linalg.norm(b[0] - b[3])
            if h_box > 0:
                ratio = w_box / float(h_box)
                w_rec = int(math.ceil(rec_height * ratio))
                raw_widths.append(w_rec)
                if w_rec > max_raw_w:
                    max_raw_w = w_rec

    print("=" * 80)
    print("1. 数据集中 Rec 裁剪输入宽度统计")
    print("=" * 80)
    print(f"有效检测框总数: {len(raw_widths)}")
    print(f"最大原始裁剪宽度: {max_raw_w} px (最长文本框)")
    print(f"最小原始裁剪宽度: {min(raw_widths)} px")
    print(f"平均原始裁剪宽度: {sum(raw_widths)/len(raw_widths):.1f} px")
    print(f"960 门槛检查: 960 >= {max_raw_w} -> {'[安全无截断]' if 960 >= max_raw_w else '[警告: 存在截断!]'}")

    # 2. 三档预处理对比
    orig_resize_norm = TextRecognizer.resize_norm_img

    # 档位 B: 960 固定
    def fixed_960_resize(self, img: np.ndarray, max_wh_ratio: float) -> np.ndarray:
        img_channel, img_height, _ = self.rec_image_shape
        img_width = 960
        h, w = img.shape[:2]
        ratio = w / float(h)
        resized_w = min(img_width, int(math.ceil(img_height * ratio)))
        resized_image = cv2.resize(img, (resized_w, img_height)).astype("float32")
        resized_image = resized_image.transpose((2, 0, 1)) / 255.0
        resized_image = (resized_image - 0.5) / 0.5
        padding_im = np.zeros((img_channel, img_height, img_width), dtype=np.float32)
        padding_im[:, :, 0:resized_w] = resized_image
        return padding_im

    # 档位 C: 32 对齐分桶 (Bucket-32)
    def bucket32_resize(self, img: np.ndarray, max_wh_ratio: float) -> np.ndarray:
        img_channel, img_height, _ = self.rec_image_shape
        h, w = img.shape[:2]
        ratio = w / float(h)
        raw_w = int(math.ceil(img_height * ratio))
        # 向上对齐到 32 的整数倍
        bucket_w = int(math.ceil(raw_w / 32.0) * 32)
        resized_w = raw_w
        resized_image = cv2.resize(img, (resized_w, img_height)).astype("float32")
        resized_image = resized_image.transpose((2, 0, 1)) / 255.0
        resized_image = (resized_image - 0.5) / 0.5
        padding_im = np.zeros((img_channel, img_height, bucket_w), dtype=np.float32)
        padding_im[:, :, 0:resized_w] = resized_image
        return padding_im

    modes = [
        ("原生动态 (Dynamic)", orig_resize_norm),
        ("960 固定 (Fixed-960)", fixed_960_resize),
        ("32 对齐分桶 (Bucket-32)", bucket32_resize)
    ]

    print("\n" + "=" * 80)
    print("2. 三档输入宽度实测对比 (Pass 1 冷启 vs Pass 2 稳态)")
    print("=" * 80)
    report_data = []

    for name, fn in modes:
        TextRecognizer.resize_norm_img = fn
        ocr_inst = RapidOCR(params={"EngineConfig.onnxruntime.use_cuda": True})
        ocr_inst(np.zeros((100, 100, 3), dtype=np.uint8))

        # Pass 1
        t0 = time.perf_counter()
        p1_res = [clean_txt(ocr_inst(f)) for f in frames_data]
        p1_dur = time.perf_counter() - t0

        # Pass 2
        t1 = time.perf_counter()
        p2_res = [clean_txt(ocr_inst(f)) for f in frames_data]
        p2_dur = time.perf_counter() - t1

        # 比对一致性
        tot_dist = 0
        tot_chars = 0
        for s1, s2 in zip(p1_res, p2_res):
            tot_chars += len(s1)
            d, _ = compare_texts(s1, s2)
            tot_dist += d
        cer = calculate_cer(tot_dist, tot_chars)

        print(f"{name:<26} | Pass 1: {p1_dur:>6.2f}s (单帧 {p1_dur/100*1000:>6.1f}ms) | Pass 2: {p2_dur:>5.2f}s (单帧 {p2_dur/100*1000:>5.1f}ms) | CER: {cer*100:.4f}%")
        report_data.append({
            "name": name,
            "pass1_sec": p1_dur,
            "pass2_sec": p2_dur,
            "cer": cer
        })

    # 恢复原方法
    TextRecognizer.resize_norm_img = orig_resize_norm

    with open("bench/i3_bucket_rec_report.json", "w", encoding="utf-8") as f:
        json.dump({
            "max_raw_w": max_raw_w,
            "comparison": report_data
        }, f, ensure_ascii=False, indent=2)
    print("\n已保存实测对比至 bench/i3_bucket_rec_report.json")

if __name__ == "__main__":
    main()
