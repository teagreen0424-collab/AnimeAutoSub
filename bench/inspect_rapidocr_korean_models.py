from rapidocr import RapidOCR
import numpy as np

# 检查 rapidocr 的默认参数与可配置项
print("Testing rapidocr.RapidOCR...")
try:
    engine1 = RapidOCR(params={"Rec.lang_type": "korean"})
    print("Rec.lang_type='korean' initialized.")
except Exception as e:
    print("Error:", e)

# 查看 rapidocr 源码或 models 目录
import rapidocr
from pathlib import Path
p = Path(rapidocr.__file__).parent
print("rapidocr files in package:")
for f in p.rglob("*"):
    if f.suffix in [".onnx", ".txt", ".yaml", ".json"]:
        print(" -", f.relative_to(p))
