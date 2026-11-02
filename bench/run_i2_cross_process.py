"""
I2 实验：跨独立 Python 进程的 RapidOCR (CUDA) 确定性实测与真实噪声底标定
========================================================================
启动 3 个完全独立的 Python 子进程，各自创建独立的 CUDA 上下文与 ORT Session，
推理完全相同的 100 帧硬字幕画面，两两比对，量化跨进程真实噪声底。
"""

import sys
import os
import json
import time
import pickle
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import animeautosub._env
from animeautosub.core.comparator import compare_texts, calculate_cer

def clean_txt(out) -> str:
    if not out or not out.txts:
        return ""
    return "".join([t.strip() for t in out.txts if t.strip()])

def run_worker(proc_id: int, pkl_path: str, out_json: str):
    import cv2
    import numpy as np
    from rapidocr import RapidOCR

    with open(pkl_path, "rb") as f:
        frames_data = pickle.load(f)

    ocr_params = {
        "Rec.lang_type": "japan",
        "EngineConfig.onnxruntime.use_cuda": True
    }
    ocr = RapidOCR(params=ocr_params)
    # 预热
    ocr(np.zeros((100, 100, 3), dtype=np.uint8))

    t0 = time.perf_counter()
    results = []
    for f in frames_data:
        res = ocr(f)
        results.append(clean_txt(res))
    dur = time.perf_counter() - t0

    payload = {
        "process_id": proc_id,
        "pid": os.getpid(),
        "duration_sec": dur,
        "texts": results
    }
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"[Process {proc_id} (PID {os.getpid()})] 完成 100 帧识别，耗时: {dur:.2f}s")

def main():
    if len(sys.argv) > 1 and sys.argv[1] == "worker":
        proc_id = int(sys.argv[2])
        pkl_path = sys.argv[3]
        out_json = sys.argv[4]
        run_worker(proc_id, pkl_path, out_json)
        return

    # 主控逻辑
    video_path = Path("ocr_input/114877-720p.mp4")
    ja_ref_path = Path("bench/fixtures/reference/ocr_720p/japanese.json")
    if not ja_ref_path.exists():
        ja_ref_path = Path("ocr_output/114877-720p/japanese.json")

    with open(ja_ref_path, "r", encoding="utf-8") as f:
        ja_data = json.load(f)

    # 均匀抽取 100 句
    total_subs = len(ja_data)
    step = total_subs / 100.0
    selected_indices = [int(i * step) for i in range(100)]
    selected_subs = [ja_data[i] for i in selected_indices]

    import cv2
    cap = cv2.VideoCapture(str(video_path))
    video_fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    roi_top = int(h * (1.0 - 0.28))

    print(f"正在抽取 100 帧基准图像...")
    frames_data = []
    frames_meta = []
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

    pkl_path = "bench/ocr_test_100_frames.pkl"
    with open(pkl_path, "wb") as f:
        pickle.dump(frames_data, f)
    print(f"已暂存 100 帧基准图像至 {pkl_path}")

    # 分别启动 3 个完全独立的子进程
    out_files = [
        "bench/i2_proc1_out.json",
        "bench/i2_proc2_out.json",
        "bench/i2_proc3_out.json"
    ]

    for i in range(3):
        proc_id = i + 1
        out_f = out_files[i]
        cmd = [sys.executable, str(Path(__file__).resolve()), "worker", str(proc_id), pkl_path, out_f]
        print(f"\n正在启动独立子进程 {proc_id}...")
        r = subprocess.run(cmd, capture_output=True, text=True)
        print(r.stdout.strip())
        if r.returncode != 0:
            print(f"子进程 {proc_id} 报错:\n{r.stderr}")
            return

    # 读取 3 个进程的输出并两两比对
    proc_data = []
    for f in out_files:
        with open(f, "r", encoding="utf-8") as fp:
            proc_data.append(json.load(fp))

    texts1 = proc_data[0]["texts"]
    texts2 = proc_data[1]["texts"]
    texts3 = proc_data[2]["texts"]

    def evaluate_pair(t_a, t_b, name_a, name_b):
        diffs = []
        tot_dist = 0
        tot_chars = 0
        for i, (s_a, s_b) in enumerate(zip(t_a, t_b)):
            tot_chars += len(s_a)
            d, label = compare_texts(s_a, s_b)
            if d > 0:
                tot_dist += d
                diffs.append((i+1, frames_meta[i][1], s_a, s_b, d, label))
        cer = calculate_cer(tot_dist, tot_chars)
        return {
            "pair": f"{name_a} vs {name_b}",
            "tot_chars": tot_chars,
            "diff_count": len(diffs),
            "tot_dist": tot_dist,
            "cer": cer,
            "diff_records": diffs
        }

    res_12 = evaluate_pair(texts1, texts2, "Process 1", "Process 2")
    res_23 = evaluate_pair(texts2, texts3, "Process 2", "Process 3")
    res_13 = evaluate_pair(texts1, texts3, "Process 1", "Process 3")

    print("\n" + "=" * 90)
    print("                 I2 跨独立进程确定性两两比对结果")
    print("=" * 90)
    for r in [res_12, res_23, res_13]:
        print(f"{r['pair']:<24} | 差异帧数: {r['diff_count']:>2}/100 | 编辑距离: {r['tot_dist']:>2} | 字符数: {r['tot_chars']} | CER: {r['cer']*100:.4f}%")

    all_diffs = res_12["diff_records"] + res_23["diff_records"] + res_13["diff_records"]
    if all_diffs:
        print("\n[差异项明细清单]:")
        for fid, sec, s1, s2, d, label in all_diffs:
            print(f"  Frame {fid:03d} @ {sec:.2f}s: '{s1}' vs '{s2}' -> {label}")
    else:
        print("\n跨 3 个独立进程两两比对完全无差异 (差异帧数 = 0, CER = 0.0000%)！")

    final_report = {
        "proc1": {"pid": proc_data[0]["pid"], "dur": proc_data[0]["duration_sec"]},
        "proc2": {"pid": proc_data[1]["pid"], "dur": proc_data[1]["duration_sec"]},
        "proc3": {"pid": proc_data[2]["pid"], "dur": proc_data[2]["duration_sec"]},
        "pairs": [res_12, res_23, res_13]
    }
    with open("bench/i2_cross_process_report.json", "w", encoding="utf-8") as f:
        json.dump(final_report, f, ensure_ascii=False, indent=2)
    print("\n已保存评测报告至 bench/i2_cross_process_report.json")

if __name__ == "__main__":
    main()
