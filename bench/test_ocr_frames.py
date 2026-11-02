import sys
sys.path.insert(0, ".")
import animeautosub._env
import cv2
import numpy as np
from core.stages.ocr_extract import build_ocr_engine_instance, extract_ocr_result

video_path = "ocr_input/simulated_ko_1080p.mp4"
cap = cv2.VideoCapture(video_path)
fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
roi_top = int(h * 0.60)

engine = build_ocr_engine_instance(use_cuda=True, rec_lang="korean")

test_times = [2.0, 4.0, 5.5, 6.5, 7.0, 8.0, 9.0, 11.0, 12.0, 14.0]

for t in test_times:
    frame_idx = int(t * fps)
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
    ret, frame = cap.read()
    if not ret:
        print(f"t={t:.1f}s: read failed")
        continue
    roi = frame[roi_top:h, 0:w]
    roi_gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    diff_val = np.std(roi_gray)
    out = engine(roi)
    text, boxes = extract_ocr_result(out, lang="korean")
    print(f"t={t:4.1f}s (std={diff_val:.1f}): text='{text}'")

cap.release()
