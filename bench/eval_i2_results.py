import sys
import os
import json
import time
import pickle
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import animeautosub._env
import numpy as np
from rapidocr import RapidOCR
from animeautosub.core.comparator import compare_texts, calculate_cer

def clean_txt(out) -> str:
    if not out or not out.txts:
        return ""
    return "".join([t.strip() for t in out.txts if t.strip()])

def main():
    root = Path(__file__).resolve().parent.parent
    bench_dir = root / "bench"
    pkl_path = bench_dir / "ocr_test_100_frames.pkl"
    p3_path = bench_dir / "i2_proc3_out.json"

    # 如果 proc3 不完整，现场跑一次 worker 3 并写入
    needs_run = True
    if p3_path.exists():
        try:
            with open(p3_path, "r", encoding="utf-8") as f:
                d = json.load(f)
                if len(d.get("texts", [])) == 100:
                    needs_run = False
        except Exception:
            needs_run = True

    if needs_run:
        print("正在独立执行 Worker 3 (PID: %d)..." % os.getpid())
        with open(pkl_path, "rb") as f:
            frames_data = pickle.load(f)
        ocr = RapidOCR(params={"Rec.lang_type": "japan", "EngineConfig.onnxruntime.use_cuda": True})
        ocr(np.zeros((100, 100, 3), dtype=np.uint8))
        t0 = time.perf_counter()
        texts3 = [clean_txt(ocr(frame)) for frame in frames_data]
        dur3 = time.perf_counter() - t0
        payload3 = {
            "process_id": 3,
            "pid": os.getpid(),
            "duration_sec": dur3,
            "texts": texts3
        }
        with open(p3_path, "w", encoding="utf-8") as f:
            json.dump(payload3, f, ensure_ascii=False, indent=2)
        print("Worker 3 执行完成并保存，耗时: %.2fs" % dur3)

    out_files = [
        bench_dir / "i2_proc1_out.json",
        bench_dir / "i2_proc2_out.json",
        bench_dir / "i2_proc3_out.json"
    ]
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
                diffs.append((i+1, s_a, s_b, d, label))
        cer = calculate_cer(tot_dist, tot_chars)
        return {
            "pair": f"{name_a} vs {name_b}",
            "tot_chars": tot_chars,
            "diff_count": len(diffs),
            "tot_dist": tot_dist,
            "cer": cer,
            "diff_records": diffs
        }

    res_12 = evaluate_pair(texts1, texts2, "Process 1 (PID %d)" % proc_data[0]["pid"], "Process 2 (PID %d)" % proc_data[1]["pid"])
    res_23 = evaluate_pair(texts2, texts3, "Process 2 (PID %d)" % proc_data[1]["pid"], "Process 3 (PID %d)" % proc_data[2]["pid"])
    res_13 = evaluate_pair(texts1, texts3, "Process 1 (PID %d)" % proc_data[0]["pid"], "Process 3 (PID %d)" % proc_data[2]["pid"])

    print("\n" + "=" * 95)
    print("                 I2 跨独立进程确定性两两比对实测结果")
    print("=" * 95)
    for r in [res_12, res_23, res_13]:
        print(f"{r['pair']:<38} | 差异帧: {r['diff_count']:>2}/100 | 编辑距离: {r['tot_dist']:>2} | 字符数: {r['tot_chars']} | CER: {r['cer']*100:.4f}%")

    all_diffs = res_12["diff_records"] + res_23["diff_records"] + res_13["diff_records"]
    if all_diffs:
        print("\n[差异项明细清单]:")
        for fid, s1, s2, d, label in all_diffs:
            print(f"  Frame {fid:03d}: '{s1}' vs '{s2}' -> {label}")
    else:
        print("\n结论: 3 个完全独立 Python 进程 (独立 PID / 独立 CUDA 上下文) 两两比对 100% 逐字完全相同！")
        print("跨进程实测真实噪声底: 差异帧数 = 0 帧，累计编辑距离 = 0，真实 CER 噪声底 = 0.0000%！")

    final_report = {
        "proc1": {"pid": proc_data[0]["pid"], "dur": proc_data[0]["duration_sec"]},
        "proc2": {"pid": proc_data[1]["pid"], "dur": proc_data[1]["duration_sec"]},
        "proc3": {"pid": proc_data[2]["pid"], "dur": proc_data[2]["duration_sec"]},
        "pairs": [res_12, res_23, res_13]
    }
    with open(bench_dir / "i2_cross_process_report.json", "w", encoding="utf-8") as f:
        json.dump(final_report, f, ensure_ascii=False, indent=2)
    print("\n已保存实测报告至 bench/i2_cross_process_report.json")

if __name__ == "__main__":
    main()
