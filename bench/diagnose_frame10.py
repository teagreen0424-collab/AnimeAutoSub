import sys
sys.path.insert(0, ".")
import cv2
import numpy as np
from rapidocr import RapidOCR
from bench.eval_p5_clustering import cluster_and_order_boxes

img = cv2.imread('bench/truth_short/frame_010.jpg')
h, w, _ = img.shape
engine = RapidOCR()
det_model = engine._load_det_model()

print('=== 1. 1x Det Raw Output ===')
det_res_1x = det_model(img)
for i, b in enumerate(det_res_1x.boxes):
    pts = np.array(b)
    xmin, ymin = pts[:, 0].min(), pts[:, 1].min()
    xmax, ymax = pts[:, 0].max(), pts[:, 1].max()
    crops = engine.crop_text_regions(img, np.array([b], dtype=np.float32))
    rec = engine.recognize_txt(crops)
    t = rec.txts[0] if rec and rec.txts else ''
    s = rec.scores[0] if rec and rec.scores else 0
    print(f'  Box {i}: x=[{xmin:.1f}, {xmax:.1f}], y=[{ymin:.1f}, {ymax:.1f}], txt="{t}", s={s:.3f}')

print('\n=== 2. 2x Det Raw Output ===')
img_2x = cv2.resize(img, (w * 2, h * 2), interpolation=cv2.INTER_LINEAR)
det_res_2x = det_model(img_2x)
boxes_2x_scaled = det_res_2x.boxes / 2.0
for i, b in enumerate(boxes_2x_scaled):
    pts = np.array(b)
    xmin, ymin = pts[:, 0].min(), pts[:, 1].min()
    xmax, ymax = pts[:, 0].max(), pts[:, 1].max()
    crops = engine.crop_text_regions(img, np.array([b], dtype=np.float32))
    rec = engine.recognize_txt(crops)
    t = rec.txts[0] if rec and rec.txts else ''
    s = rec.scores[0] if rec and rec.scores else 0
    print(f'  Box {i}: x=[{xmin:.1f}, {xmax:.1f}], y=[{ymin:.1f}, {ymax:.1f}], txt="{t}", s={s:.3f}')

ordered_boxes, lines = cluster_and_order_boxes(boxes_2x_scaled)
print(f'\n=== 3. 2x Det Clustered Lines ({len(lines)} lines) ===')
for li, l in enumerate(lines):
    line_txts = []
    cy_list = [x['cy'] for x in l]
    for info in l:
        b = info['box']
        crops = engine.crop_text_regions(img, np.array([b], dtype=np.float32))
        rec = engine.recognize_txt(crops)
        t = rec.txts[0] if rec and rec.txts else ''
        line_txts.append(t)
    print(f'  Line {li}: y_mean={np.mean(cy_list):.1f}, boxes={len(l)}, txts={line_txts}')
