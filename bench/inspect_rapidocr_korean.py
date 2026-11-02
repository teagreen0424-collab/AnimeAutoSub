import sys
from rapidocr_onnxruntime import RapidOCR

print("RapidOCR onnxruntime import ok")

# 尝试默认实例
try:
    engine_def = RapidOCR()
    print("Default RapidOCR init ok")
except Exception as e:
    print("Default RapidOCR init error:", e)

# 尝试指定 korean
try:
    engine_ko = RapidOCR(rec_lang="korean")
    print("RapidOCR rec_lang='korean' init ok!")
except Exception as e:
    print("RapidOCR rec_lang='korean' error:", e)

# 查看 rapidocr_onnxruntime 包内模型文件
import rapidocr_onnxruntime
from pathlib import Path
pkg_dir = Path(rapidocr_onnxruntime.__file__).parent
print("Package dir:", pkg_dir)
models = list(pkg_dir.glob("**/*.onnx"))
print("Bundled ONNX models:")
for m in models:
    print(" -", m.name)

# 也查看 rapidocr (如果两个包都有)
try:
    import rapidocr
    p_dir = Path(rapidocr.__file__).parent
    print("rapidocr dir:", p_dir)
    for m in p_dir.glob("**/*.onnx"):
        print(" [rapidocr] -", m.name)
except Exception as e:
    print("rapidocr inspection error:", e)
