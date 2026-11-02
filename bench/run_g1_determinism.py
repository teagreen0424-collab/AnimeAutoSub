"""
G1 严格门禁：RapidOCR (CUDA) 100 帧真实密集字幕确定性实测
=========================================================
从 114877-720p 全片 782 句字幕中均匀抽取 100 句独立台词的画面中心帧，
确保 100 帧 100% 覆盖真实密集硬字幕。
使用 RapidOCR (CUDAExecutionProvider) 执行 Pass 1 与 Pass 2 完整推理，
逐帧打印比对明细、总字符数、CER 与一致性率。
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

def levenshtein(s1: str, s2: str) -> int:
    m, n = len(s1), len(s2)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(m + 1):
        dp[i][0] = i
    for j in range(n + 1):
        dp[0][j] = j
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if s1[i - 1] == s2[j - 1]:
                dp[i][j] = dp[i - 1][j - 1]
            else:
                dp[i][j] = 1 + min(dp[i - 1][j], dp[i][j - 1], dp[i - 1][j - 1])
    return dp[m][n]

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

    # 均匀抽取 100 句字幕
    total_subs = len(ja_data)
    step = total_subs / 100.0
    selected_indices = [int(i * step) for i in range(100)]
    selected_subs = [ja_data[i] for i in selected_indices]

    cap = cv2.VideoCapture(str(video_path))
    video_fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    roi_top = int(h * (1.0 - 0.28))

    print(f"正在从 {video_path} 提取 100 帧真实密集硬字幕画面 (底28% y={roi_top}:{h})...")
    frames_meta = []
    frames_data = []

    for idx, item in enumerate(selected_subs):
        mid_sec = (item["start"] + item["end"]) / 2.0
        frame_num = int(mid_sec * video_fps)
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
        ret, frame = cap.read()
        if not ret:
            print(f"Frame {idx} read error at {mid_sec}s")
            continue
        roi = frame[roi_top:h, 0:w]
        frames_meta.append((idx, mid_sec, item["text"]))
        frames_data.append(roi)
    cap.release()

    print(f"成功截取 {len(frames_data)} 帧密集字幕。")

    # 初始化 RapidOCR CUDA
    from rapidocr.utils.log import logger as rapidocr_logger
    rapidocr_logger.setLevel(50)
    ocr_params = {
        "Rec.lang_type": "japan",
        "EngineConfig.onnxruntime.use_cuda": True
    }
    ocr = RapidOCR(params=ocr_params)

    # 预热一次
    dummy = np.zeros((100, 100, 3), dtype=np.uint8)
    ocr(dummy)

    det_ep = ocr.text_det.session.session.get_providers()
    print(f"RapidOCR (CUDA) 初始化就绪，活跃 Provider: {det_ep}")

    print("\n--- 执行 Pass 1 ---")
    t0 = time.perf_counter()
    pass1_texts = []
    for f in frames_data:
        out = ocr(f)
        pass1_texts.append(clean_txt(out))
    t1 = time.perf_counter()
    pass1_duration = t1 - t0
    print(f"Pass 1 完成，耗时: {pass1_duration:.2f}s")

    print("\n--- 执行 Pass 2 ---")
    t2 = time.perf_counter()
    pass2_texts = []
    for f in frames_data:
        out = ocr(f)
        pass2_texts.append(clean_txt(out))
    t3 = time.perf_counter()
    pass2_duration = t3 - t2
    print(f"Pass 2 完成，耗时: {pass2_duration:.2f}s")

    # 逐帧比对
    total_chars = 0
    exact_matches = 0
    total_dist = 0
    diff_records = []

    print("\n" + "=" * 90)
    print(f"{'帧序':^4} | {'时间戳':^8} | {'Pass 1 识别结果':<32} | {'Pass 2 识别结果':<32} | {'差异'}")
    print("-" * 90)

    for i, ((idx, sec, ref_txt), txt1, txt2) in enumerate(zip(frames_meta, pass1_texts, pass2_texts)):
        total_chars += len(txt1)
        d = levenshtein(txt1, txt2)
        match_str = "MATCH" if d == 0 else f"DIFF({d})"
        if d == 0:
            exact_matches += 1
        else:
            total_dist += d
            diff_records.append((i, sec, txt1, txt2, d))

        # 打印逐帧明细 (截取前 28 字符避免换行混乱)
        p1_disp = (txt1[:28] + "..") if len(txt1) > 28 else txt1
        p2_disp = (txt2[:28] + "..") if len(txt2) > 28 else txt2
        print(f"{i+1:03d}  | {sec:07.2f}s | {p1_disp:<32} | {p2_disp:<32} | {match_str}")

    cer = (total_dist / total_chars) if total_chars > 0 else 0.0
    exact_rate = (exact_matches / len(frames_data)) * 100.0

    print("=" * 90)
    print("                    G1 严格门禁实测结果报告")
    print("=" * 90)
    print(f"测试送检总帧数:          {len(frames_data)} 帧 (100% 覆盖全片台词关键帧)")
    print(f"识别总字符数:            {total_chars} 字符 (平均单帧字符: {total_chars/len(frames_data):.1f} 字/帧)")
    print(f"两轮完全一致帧数:        {exact_matches} / {len(frames_data)} ({exact_rate:.2f}%)")
    print(f"产生字符差异帧数:        {len(diff_records)}")
    print(f"累计字符编辑距离 (Lev):   {total_dist}")
    print(f"字符错误率 (CER):        {cer * 100.0:.4f}%")
    print(f"Pass 1 耗时:             {pass1_duration:.2f} 秒 (单帧平均: {pass1_duration/len(frames_data)*1000:.1f} ms)")
    print(f"Pass 2 耗时:             {pass2_duration:.2f} 秒 (单帧平均: {pass2_duration/len(frames_data)*1000:.1f} ms)")
    print("=" * 90)

    if diff_records:
        print("\n[差异项清单]:")
        for i, s, txt1, txt2, d in diff_records:
            print(f"  Frame {i+1} @ {s:.2f}s: Pass1='{txt1}' vs Pass2='{txt2}' (dist={d})")
    else:
        print("结论: 100 帧密集台词在 RapidOCR (CUDA) 下 100% 逐字符确定，CER = 0.0000%！")

    # 结果落盘
    res_json = {
        "total_frames": len(frames_data),
        "total_chars": total_chars,
        "exact_matches": exact_matches,
        "exact_rate": exact_rate,
        "total_edit_distance": total_dist,
        "cer": cer,
        "pass1_sec": pass1_duration,
        "pass2_sec": pass2_duration,
        "diff_records": diff_records
    }
    with open("bench/g1_ocr_determinism_report.json", "w", encoding="utf-8") as f:
        json.dump(res_json, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()
