import sys
sys.path.insert(0, ".")
import logging
from pathlib import Path

# 配置详细控制台日志
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s [%(levelname)s] %(message)s")

from lang import get_language
from core.context import PipelineContext
from core.stages.ocr_extract import OcrExtractStage

ctx = PipelineContext(
    video_path=Path("ocr_input/test_3min.mp4"),
    work_dir=Path("ocr_output/test_debug"),
    output_dir=Path("ocr_output/test_debug"),
    lang=get_language("ja"),
    mode="ocr"
)

stage = OcrExtractStage()
print("Starting stage.run...")
stage.run(ctx, logging.getLogger("Debug"))
print("Stage.run finished!")
