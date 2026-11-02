import rapidocr
from pathlib import Path

# 查找 rapidocr 中定义 Enum 的地方
import inspect
from rapidocr import RapidOCR

# 检查 rapidocr.params 里的类或枚举
import rapidocr
for k, v in inspect.getmembers(rapidocr):
    if inspect.isclass(v):
        print("Class in rapidocr:", k)

# 打印 config.yaml
cfg_path = Path(rapidocr.__file__).parent / "config.yaml"
with open(cfg_path, encoding="utf-8") as f:
    for line in f:
        if "ocr_version" in line or "lang_type" in line or "Rec:" in line:
            print("config.yaml:", line.strip())
