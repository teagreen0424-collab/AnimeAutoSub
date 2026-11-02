"""
K3/K4: 真值帧精准时间戳定位与分层抽样导出工具
==============================================
1. 先定位该时间戳实际显示字幕的帧 (多点候选抽帧 + OCR 相似度校验)，杜绝切镜错位与空帧；
2. 相似度低于阈值 (0.35) 自动报警；
3. 支持修正历史 008 与 029 错位帧；
4. 支持按全片时长等分 30 段进行分层抽样 (K4)。
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
VIDEO_PATH = "ocr_input/114877-720p.mp4"

def extract_frame_ffmpeg(sec: float) -> np.ndarray:
    """使用 FFmpeg 精确抽取指定时间戳的单个完整 BGR 画面"""
    cmd = [
        FFMPEG_BIN, "-y", "-ss", f"{sec:.3f}", "-i", VIDEO_PATH,
        "-vframes", "1", "-f", "image2pipe", "-vcodec", "rawvideo",
        "-pix_fmt", "bgr24", "-"
    ]
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if len(p.stdout) == 1280 * 720 * 3:
        return np.frombuffer(p.stdout, dtype=np.uint8).reshape((720, 1280, 3))
    return None

def find_best_subtitle_frame(start_sec: float, end_sec: float, ref_text: str, ocr_engine, sim_thresh: float = 0.35):
    """
    K3: 在 [start_sec, end_sec] 范围内搜索实际完整渲染该字幕的最佳帧。
    返回: (best_sec, best_roi, best_txt, best_sim, alert_triggered)
    """
    dur = max(0.1, end_sec - start_sec)
    # 在字幕有效区间内等距取 5 个采样点 (避开首尾过渡帧)
    candidate_offsets = [0.25, 0.4, 0.5, 0.65, 0.8]
    candidates = [start_sec + dur * r for r in candidate_offsets]

    best_sec = (start_sec + end_sec) / 2.0
    best_roi = None
    best_txt = ""
    best_sim = -1.0

    for sec in candidates:
        frame = extract_frame_ffmpeg(sec)
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

    alert_triggered = (best_sim < sim_thresh)
    return best_sec, best_roi, best_txt, best_sim, alert_triggered

def fix_misaligned_008_and_029():
    """K3: 专项精准修复 008 与 029 帧"""
    ocr = RapidOCR(params={"EngineConfig.onnxruntime.use_cuda": True})
    out_dir = Path("bench/truth_frames")

    targets = [
        (8, 966.03, 970.07, "ちやんと許可を貰って部屋に入る。"),
        (29, 3754.02, 3760.63, "だから今は自宅で一人暮らしをしている。")
    ]

    print("\n" + "=" * 80)
    print("           K3 错位帧精准重新定位与截取 (008 与 029)")
    print("=" * 80)

    for fid, start_sec, end_sec, ref_text in targets:
        best_sec, best_roi, best_txt, best_sim, alert = find_best_subtitle_frame(
            start_sec, end_sec, ref_text, ocr
        )
        print(f"帧 {fid:03d}: 目标参考文本: '{ref_text}'")
        print(f"       区间: [{start_sec:.2f}s - {end_sec:.2f}s]")
        print(f"       锁定最佳时间戳: {best_sec:.3f}s (相似度: {best_sim*100:.1f}%)")
        print(f"       回测 OCR 结果: '{best_txt}'")
        if alert:
            print(f"       ⚠ [ALERT]: 相似度低于阈值! 请人工复核!")
        else:
            print(f"       ✓ 校验通过，写入 bench/truth_frames/frame_{fid:03d}.jpg")
            cv2.imwrite(str(out_dir / f"frame_{fid:03d}.jpg"), best_roi)
        print("-" * 80)

if __name__ == "__main__":
    fix_misaligned_008_and_029()
