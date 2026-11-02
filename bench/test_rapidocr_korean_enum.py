from rapidocr import RapidOCR, OCRVersion, LangRec, ModelType
import numpy as np

print("Testing RapidOCR with PP-OCRv5 Korean via Enums...")
engine = RapidOCR(params={
    "Rec.ocr_version": OCRVersion.PPOCRV5,
    "Rec.lang_type": LangRec.KOREAN,
    "Rec.model_type": ModelType.MOBILE
})

# 预热推理触发按需加载模型
dummy = np.zeros((48, 200, 3), dtype=np.uint8)
res = engine(dummy, use_det=False)

session = getattr(engine.text_rec.session, "session", None)
model_path = getattr(session, "_model_path", "")
print("Loaded model path:", model_path)
chars = getattr(engine.text_rec.postprocess_op, "character", [])
print(f"Loaded Vocab size: {len(chars)}")

sample_hangul = ["안", "녕", "하", "세", "요", "가", "는", "를", "의"]
in_vocab = [c for c in sample_hangul if c in chars]
print(f"Sample hangul in vocab: {len(in_vocab)}/{len(sample_hangul)}")
assert len(in_vocab) == len(sample_hangul), "韩语常见字符未能全部匹配！"
print("✓ Korean PP-OCRv5 验证 100% 成功！")
