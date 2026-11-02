import pickle, json, time, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import animeautosub._env
import numpy as np
from rapidocr import RapidOCR

pkl_path = r"E:\translate\bench\ocr_test_100_frames.pkl"
out_json = r"E:\translate\bench\i2_proc3_out.json"

with open(pkl_path, "rb") as f:
    frames_data = pickle.load(f)

ocr = RapidOCR(params={"Rec.lang_type": "japan", "EngineConfig.onnxruntime.use_cuda": True})
ocr(np.zeros((100, 100, 3), dtype=np.uint8))

t0 = time.perf_counter()
results = []
for f in frames_data:
    out = ocr(f)
    txt = "".join([t.strip() for t in out.txts if t.strip()]) if out and out.txts else ""
    results.append(txt)
dur = time.perf_counter() - t0

payload = {
    "process_id": 3,
    "pid": os.getpid(),
    "duration_sec": dur,
    "texts": results
}
with open(out_json, "w", encoding="utf-8") as f:
    json.dump(payload, f, ensure_ascii=False, indent=2)

print(f"Worker 3 saved to {out_json}, frames: {len(results)}, dur: {dur:.2f}s")
