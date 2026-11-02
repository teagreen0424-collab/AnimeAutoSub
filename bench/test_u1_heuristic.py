import time
import json
import cv2
import numpy as np
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import animeautosub._env
from rapidocr import RapidOCR
from pipeline_ocr import clean_ocr_text, text_similarity, finalize_segment

def test_heuristic():
    video_path = Path("ocr_input/test_3min.mp4")
    cap = cv2.VideoCapture(str(video_path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration_sec = total_frames / fps
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    roi_top = int(height * (1.0 - 0.28))
    sample_step = max(1, int(fps / 2.0))
    sample_interval_sec = sample_step / fps

    params = {
        'EngineConfig.onnxruntime.use_cuda': True,
        'EngineConfig.onnxruntime.cuda_ep_cfg.cudnn_conv_algo_search': 'HEURISTIC'
    }
    t_init0 = time.time()
    engine = RapidOCR(params=params)
    engine._load_det_model()
    engine._load_rec_model()
    t_init = time.time() - t_init0
    print(f"Engine init time: {t_init:.2f}s")

    frame_idx = 0
    last_roi_gray = None
    last_ocr_text = ""
    last_ocr_boxes = []
    ocr_call_count = 0
    skip_count = 0
    call_records = []

    t_decode_accum = 0.0
    t_inference_accum = 0.0
    t_other_accum = 0.0
    t_start = time.time()

    while True:
        if frame_idx % sample_step == 0:
            t_d0 = time.time()
            ret, frame = cap.read()
            t_decode_accum += (time.time() - t_d0)
            if not ret:
                break
            curr_sec = frame_idx / fps

            t_o0 = time.time()
            roi = frame[roi_top:height, 0:width]
            roi_gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
            diff = 1.0
            if last_roi_gray is not None:
                diff = np.mean(cv2.absdiff(roi_gray, last_roi_gray)) / 255.0
            last_roi_gray = roi_gray

            t_other_accum += (time.time() - t_o0)

            if diff < 0.015:
                skip_count += 1
            else:
                t_o1 = time.time()
                roi_std = np.std(roi_gray)
                t_other_accum += (time.time() - t_o1)

                if roi_std < 12:
                    skip_count += 1
                else:
                    t_r0 = time.time()
                    out = engine(roi)
                    dt_call = time.time() - t_r0
                    t_inference_accum += dt_call
                    ocr_call_count += 1
                    n_boxes = len(out.boxes) if (out is not None and out.boxes is not None) else 0
                    call_records.append({
                        "call": ocr_call_count,
                        "sec": round(curr_sec, 2),
                        "duration_ms": round(dt_call * 1000, 1),
                        "boxes_count": n_boxes
                    })
        else:
            t_d0 = time.time()
            ret = cap.grab()
            t_decode_accum += (time.time() - t_d0)
            if not ret:
                break
        frame_idx += 1

    cap.release()
    total_time = time.time() - t_start
    print(f"Total time: {total_time:.2f}s")
    print(f"Decode: {t_decode_accum:.2f}s, Inference: {t_inference_accum:.2f}s, Other: {t_other_accum:.2f}s")
    print(f"Calls: {ocr_call_count}, Avg inference: {t_inference_accum / max(1, ocr_call_count) * 1000:.1f} ms/call")

    slow_calls = [c for c in call_records if c["duration_ms"] > 250]
    fast_calls = [c for c in call_records if c["duration_ms"] <= 250]
    print(f"Fast calls (<=250ms): {len(fast_calls)}, sum: {sum(c['duration_ms'] for c in fast_calls)/1000:.2f}s")
    print(f"Slow calls (>250ms): {len(slow_calls)}, sum: {sum(c['duration_ms'] for c in slow_calls)/1000:.2f}s")
    for sc in slow_calls:
        print(f"  Slow call #{sc['call']} (sec {sc['sec']}): {sc['duration_ms']}ms, {sc['boxes_count']} boxes")

    with open("bench/u1_heuristic_timing.json", "w", encoding="utf-8") as f:
        json.dump({
            "total_time_s": round(total_time, 3),
            "decode_s": round(t_decode_accum, 3),
            "inference_s": round(t_inference_accum, 3),
            "other_s": round(t_other_accum, 3),
            "call_records": call_records
        }, f, indent=2)

if __name__ == "__main__":
    test_heuristic()
