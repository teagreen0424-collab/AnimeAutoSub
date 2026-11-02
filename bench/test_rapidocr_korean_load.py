import time
from rapidocr import RapidOCR
import numpy as np

print("Testing RapidOCR with PP-OCRv5 korean...")
t0 = time.time()
try:
    engine = RapidOCR(params={
        "Rec.ocr_version": "PP-OCRv5",
        "Rec.lang_type": "korean"
    })
    print("Initialized in", round(time.time() - t0, 2), "s")
    
    # 预热推理
    dummy = np.zeros((48, 200, 3), dtype=np.uint8)
    res = engine(dummy, use_det=False)
    print("Warmup inference res:", res)
    
    session = getattr(engine.text_rec.session, "session", None)
    if session:
        print("Model path:", getattr(session, "_model_path", ""))
        chars = getattr(engine.text_rec.postprocess_op, "character", [])
        print("Vocab size:", len(chars))
        sample_hangul = ["안", "녕", "하", "세", "요", "가", "는", "를", "의"]
        in_vocab = [c for c in sample_hangul if c in chars]
        print(f"Sample hangul in vocab: {len(in_vocab)}/{len(sample_hangul)}")
except Exception as e:
    print("Error:", e)
