import numpy as np
from rapidocr_onnxruntime import RapidOCR

engine = RapidOCR(rec_lang="korean")
# 预热推理
dummy = np.zeros((48, 200, 3), dtype=np.uint8)
res, _ = engine(dummy, use_det=False)

session = getattr(engine.text_rec.session, "session", None)
model_path = getattr(session, "_model_path", "")
print("Model path:", model_path)
chars = getattr(engine.text_rec.postprocess_op, "character", [])
print(f"Vocab size: {len(chars)}")

# 测试韩文字符是否在词表中
sample_hangul = ["안", "녕", "하", "세", "요", "가", "는", "를", "의"]
in_vocab = [c for c in sample_hangul if c in chars]
print(f"Sample hangul in vocab: {len(in_vocab)}/{len(sample_hangul)}")
