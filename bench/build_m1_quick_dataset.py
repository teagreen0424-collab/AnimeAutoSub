"""
M1: 建立 3 分钟快速迭代集与 15 帧真值模板
=========================================
1. 3 分钟视频 test_3min.mp4 对应原片 300s - 480s；
2. 180 秒均分为 15 段 (每段 12 秒)，均匀分层选取 15 句台词；
3. 多点候选寻优确定最佳清晰帧，截取底部 28% ROI；
4. 导出至 bench/truth_short/frame_001.jpg ~ frame_015.jpg；
5. 生成 truth_template.md 留空供 PO 人工填写真值。
"""

import sys
import json
import subprocess
from pathlib import Path
import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import animeautosub._env
from rapidocr import RapidOCR
from animeautosub.core.comparator import compare_texts

FFMPEG_BIN = r"D:\Dev\ffmpeg\bin\ffmpeg.exe"
SRC_VIDEO = "ocr_input/114877-720p.mp4"
CLIP_VIDEO = "ocr_input/test_3min.mp4"

def extract_frame_exact(sec: float) -> np.ndarray:
    """使用 FFmpeg 精确抽取指定时间戳 (原片绝对秒数) 的完整画面"""
    cmd = [
        FFMPEG_BIN, "-y", "-ss", f"{sec:.3f}", "-i", SRC_VIDEO,
        "-vframes", "1", "-f", "image2pipe", "-vcodec", "rawvideo",
        "-pix_fmt", "bgr24", "-"
    ]
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if len(p.stdout) == 1280 * 720 * 3:
        return np.frombuffer(p.stdout, dtype=np.uint8).reshape((720, 1280, 3))
    return None

def find_best_frame(start_sec: float, end_sec: float, ref_text: str, ocr_engine):
    """在 [start_sec, end_sec] 范围内寻找最佳字幕渲染帧"""
    dur = max(0.1, end_sec - start_sec)
    offsets = [0.25, 0.4, 0.5, 0.65, 0.8]
    candidates = [start_sec + dur * r for r in offsets]

    best_sec = (start_sec + end_sec) / 2.0
    best_roi = None
    best_txt = ""
    best_sim = -1.0

    for sec in candidates:
        frame = extract_frame_exact(sec)
        if frame is None:
            continue
        roi = frame[int(720 * 0.72):, :]
        out = ocr_engine(roi)
        txt = "".join([t.strip() for t in out.txts if t.strip()]) if (out and out.txts) else ""
        d, _ = compare_texts(ref_text, txt)
        max_l = max(len(ref_text), len(txt), 1)
        sim = 1.0 - (d / max_l)

        if sim > best_sim:
            best_sim = sim
            best_sec = sec
            best_roi = roi
            best_txt = txt

    return best_sec, best_roi, best_txt, best_sim

def main():
    with open("ocr_output/114877-720p/japanese.json", "r", encoding="utf-8") as f:
        subs = json.load(f)

    # 3分钟区间 [300.0, 480.0]
    base_start = 300.0
    base_end = 480.0
    num_segments = 15
    seg_dur = (base_end - base_start) / float(num_segments) # 12.0s

    in_clip_subs = [s for s in subs if s["start"] >= base_start and s["end"] <= base_end]

    selected_items = []
    for i in range(num_segments):
        t0 = base_start + i * seg_dur
        t1 = base_start + (i + 1) * seg_dur
        seg_subs = [s for s in in_clip_subs if (s["start"] >= t0 and s["start"] < t1)]
        if not seg_subs:
            # 找中心点最近的
            mid = (t0 + t1) / 2.0
            seg_subs = sorted(in_clip_subs, key=lambda s: abs((s["start"] + s["end"]) / 2.0 - mid))[:1]
        
        # 选第 1 个代表句
        selected_items.append(seg_subs[0])

    out_dir = Path("bench/truth_short")
    out_dir.mkdir(parents=True, exist_ok=True)

    # 默认 multi PP-OCRv6 (基线最优)
    ocr = RapidOCR(params={"EngineConfig.onnxruntime.use_cuda": True})

    template_lines = [
        "# AnimeAutoSub · 3 分钟快速迭代集 15 帧人工真值模板",
        "",
        "> 视频源: `ocr_input/test_3min.mp4` (原片 05:00 ~ 08:00，全片均匀 15 段分层抽样)。",
        "> 图像文件保存在 `bench/truth_short/frame_001.jpg` ~ `frame_015.jpg`。",
        "> 请 PO 在 `【PO 人工转写真值】` 栏填写准确文字（包含标点符号，留空则不计）。",
        "",
        "| 序号 | 图像文件 | 3min片时间戳 | 原片时间戳 | 当前默认 OCR 输出 | 【PO 人工转写真值】 |",
        "| :---: | :---: | :---: | :---: | :--- | :--- |"
    ]

    meta_list = []
    for idx, item in enumerate(selected_items):
        fid = idx + 1
        fname = f"frame_{fid:03d}.jpg"
        fpath = out_dir / fname

        best_sec, best_roi, best_txt, best_sim = find_best_frame(
            item["start"], item["end"], item["text"], ocr
        )

        if best_roi is not None:
            cv2.imwrite(str(fpath), best_roi)

        clip_sec = best_sec - base_start
        clip_m, clip_s = int(clip_sec // 60), clip_sec % 60
        orig_m, orig_s = int(best_sec // 60), best_sec % 60

        clip_time_str = f"{clip_m:02d}:{clip_s:05.2f}"
        orig_time_str = f"{orig_m:02d}:{orig_s:05.2f}"

        clean_ocr = best_txt.replace("\n", " ").replace("|", " ")
        template_lines.append(
            f"| {fid:03d} | [{fname}]({fname}) | `{clip_time_str}` | `{orig_time_str}` | {clean_ocr} |  |"
        )

        meta_list.append({
            "id": fid,
            "filename": fname,
            "clip_timestamp_sec": round(clip_sec, 3),
            "orig_timestamp_sec": round(best_sec, 3),
            "clip_time_str": clip_time_str,
            "orig_time_str": orig_time_str,
            "reference_text": item["text"],
            "current_ocr_text": best_txt,
            "ocr_similarity": round(best_sim, 3)
        })

        print(f"[{fid:02d}/15] `{clip_time_str}` (原片 `{orig_time_str}`) | sim={best_sim*100:5.1f}% | OCR: {clean_ocr[:25]}")

    md_path = out_dir / "truth_template.md"
    md_path.write_text("\n".join(template_lines), encoding="utf-8")

    json_path = out_dir / "truth_metadata.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(meta_list, f, ensure_ascii=False, indent=2)

    print("=" * 80)
    print(f"✓ 15 帧裁图已导出至 {out_dir}/")
    print(f"✓ 真值模板已生成: {md_path}")
    print("=" * 80)

if __name__ == "__main__":
    main()
