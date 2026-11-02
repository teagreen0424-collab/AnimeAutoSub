"""
I6 探查与调优：18.0~22.5s 双行字幕检测漏检根因定位与三档修复对比
================================================================
针对 simulated_1080p_fansub.mp4 在 18.0~22.5s 漏检下半行台词的问题：
a) 逐帧输出 det 检测框数量、坐标与置信度；
b) 测试三档 det 参数修复；
c) 评测修复前后的双行 CER。
"""

import sys
import os
import json
import cv2
import numpy as np
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import animeautosub._env
from rapidocr import RapidOCR
from animeautosub.core.comparator import compare_texts, calculate_cer

def clean_txt(out) -> str:
    if not out or not out.txts:
        return ""
    txts = [t.strip() for t in out.txts if t.strip() and t.strip() != "HOTEL"]
    return "".join(txts)

def main():
    video_path = Path("ocr_input/simulated_1080p_fansub.mp4")
    cap = cv2.VideoCapture(str(video_path))
    video_fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    roi_top = int(h * (1.0 - 0.28))

    # 问题时间段帧 (18.0, 19.0, 21.0, 22.0, 22.5s)
    problem_secs = [18.0, 19.0, 20.0, 21.0, 22.0, 22.5]
    problem_frames = []
    for s in problem_secs:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(s * video_fps))
        ret, frame = cap.read()
        if ret:
            roi = frame[roi_top:h, 0:w]
            problem_frames.append((s, roi))
    
    # 全部双行 20 帧 (用于最终 CER 复测)
    double_samples = [
        (17.0, "たとえ世界中が君の敵になったとしても、私はずっと君の味方でいると誓うよ。"),
        (18.0, "たとえ世界中が君の敵になったとしても、私はずっと君の味方でいると誓うよ。"),
        (19.0, "たとえ世界中が君の敵になったとしても、私はずっと君の味方でいると誓うよ。"),
        (20.0, "たとえ世界中が君の敵になったとしても、私はずっと君の味方でいると誓うよ。"),
        (21.0, "たとえ世界中が君の敵になったとしても、私はずっと君の味方でいると誓うよ。"),
        (22.0, "たとえ世界中が君の敵になったとしても、私はずっと君の味方でいると誓うよ。"),
        (22.5, "たとえ世界中が君の敵になったとしても、私はずっと君の味方でいると誓うよ。"),
        (26.0, "あの日の約束を覚えていますか？桜が散る頃に、もう一度ここで会おうと言ったことを。"),
        (27.0, "あの日の約束を覚えていますか？桜が散る頃に、もう一度ここで会おうと言ったことを。"),
        (28.0, "あの日の約束を覚えていますか？桜が散る頃に、もう一度ここで会おうと言ったことを。"),
        (29.0, "あの日の約束を覚えていますか？桜が散る頃に、もう一度ここで会おうと言ったことを。"),
        (30.0, "あの日の約束を覚えていますか？桜が散る頃に、もう一度ここで会おうと言ったことを。"),
        (31.0, "あの日の約束を覚えていますか？桜が散る頃に、もう一度ここで会おうと言ったことを。"),
        (31.5, "あの日の約束を覚えていますか？桜が散る頃に、もう一度ここで会おうと言ったことを。"),
        (43.0, "「これで終わりじゃない、ここからが始まりだ」そう強く自分に言い聞かせていた。"),
        (44.0, "「これで終わりじゃない、这里からが始まりだ」そう強く自分に言い聞かせていた。".replace("这里", "ここ")),
        (45.0, "「これで終わりじゃない、ここからが始まりだ」そう強く自分に言い闻かせていた。".replace("闻", "言")),
        (46.0, "「これで終わりじゃない、ここからが始まりだ」そう強く自分に言い聞かせていた。"),
        (47.0, "「これで終わりじゃない、ここからが始まりだ」そう強く自分に言い聞かせていた。"),
        (48.0, "「これで終わりじゃない、ここからが始まりだ」そう強く自分に言い聞かせていた。"),
    ]
    all_double_frames = []
    for s, ref in double_samples:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(s * video_fps))
        ret, frame = cap.read()
        if ret:
            roi = frame[roi_top:h, 0:w]
            all_double_frames.append((s, ref, roi))
    cap.release()

    # 1. 深度剖析默认配置下 det 的输出
    print("=" * 80)
    print("a) 默认配置下 18.0~22.5s 检测框与识别结果分析")
    print("=" * 80)
    default_ocr = RapidOCR(params={
        "Rec.lang_type": "japan",
        "EngineConfig.onnxruntime.use_cuda": True
    })
    # 预热
    default_ocr(np.zeros((100, 100, 3), dtype=np.uint8))

    for s, roi in problem_frames:
        out = default_ocr(roi)
        dt_boxes = out.boxes if out and out.boxes is not None else []
        txts = out.txts if out and out.txts is not None else []
        scores = out.scores if out and out.scores is not None else []
        print(f"时间 {s:4.1f}s | 检测框数量: {len(dt_boxes)}")
        for idx, (b, t, sc) in enumerate(zip(dt_boxes, txts, scores)):
            # 计算 box 的 y 坐标跨度 (min_y, max_y)
            b = np.array(b)
            min_y, max_y = int(np.min(b[:, 1])), int(np.max(b[:, 1]))
            min_x, max_x = int(np.min(b[:, 0])), int(np.max(b[:, 0]))
            print(f"   Box {idx+1}: y=[{min_y}:{max_y}] x=[{min_x}:{max_x}] | score={sc:.3f} | text='{t}'")

    # 2. 三档调优实验
    candidates = [
        ("基准 (Default)", {
            "Rec.lang_type": "japan",
            "EngineConfig.onnxruntime.use_cuda": True
        }),
        ("档位 1: 调低 box_thresh (0.5 -> 0.3)", {
            "Rec.lang_type": "japan",
            "EngineConfig.onnxruntime.use_cuda": True,
            "Det.box_thresh": 0.3
        }),
        ("档位 2: 调低 box_thresh (0.3) + unclip_ratio (1.6 -> 2.0)", {
            "Rec.lang_type": "japan",
            "EngineConfig.onnxruntime.use_cuda": True,
            "Det.box_thresh": 0.3,
            "Det.unclip_ratio": 2.0
        }),
        ("档位 3: 调低 box_thresh (0.3) + 增大 limit_side_len (960 -> 1280)", {
            "Rec.lang_type": "japan",
            "EngineConfig.onnxruntime.use_cuda": True,
            "Det.box_thresh": 0.3,
            "Det.limit_side_len": 1280
        })
    ]

    print("\n" + "=" * 80)
    print("b) & c) 三档参数修复后的双行 (20 帧) CER 评测对比")
    print("=" * 80)
    results_summary = []

    for name, params in candidates:
        ocr_inst = RapidOCR(params=params)
        ocr_inst(np.zeros((100, 100, 3), dtype=np.uint8))

        tot_dist = 0
        tot_chars = 0
        diff_count = 0

        for s, ref, roi in all_double_frames:
            out = ocr_inst(roi)
            pred = clean_txt(out)
            d, label = compare_texts(pred, ref)
            tot_chars += len(ref)
            if d > 0:
                tot_dist += d
                diff_count += 1

        cer = calculate_cer(tot_dist, tot_chars)
        print(f"{name:<50} | 差异帧: {diff_count:>2}/20 | 编辑距离: {tot_dist:>3} | 双行 CER: {cer*100:.2f}%")
        results_summary.append({
            "name": name,
            "params": params,
            "diff_count": diff_count,
            "tot_dist": tot_dist,
            "tot_chars": tot_chars,
            "cer": cer
        })

    with open("bench/i6_double_line_fix_report.json", "w", encoding="utf-8") as f:
        json.dump(results_summary, f, ensure_ascii=False, indent=2)
    print("\n已保存评测报告至 bench/i6_double_line_fix_report.json")

if __name__ == "__main__":
    main()
