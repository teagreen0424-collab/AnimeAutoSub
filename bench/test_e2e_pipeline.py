import sys
sys.path.insert(0, ".")
from pathlib import Path
from lang import get_language
from core.context import PipelineContext
from core.pipeline import Pipeline

work_dir = Path("ocr_output/test_e2e_pipeline")
work_dir.mkdir(parents=True, exist_ok=True)

ctx = PipelineContext(
    video_path=Path("ocr_input/test_3min.mp4"),
    work_dir=work_dir,
    output_dir=work_dir,
    lang=get_language("ja"),
    mode="ocr"
)

print("=== 第一次端到端执行 ===")
p1 = Pipeline(ctx)
p1.run()

print("\n=== 第二次执行 (断言三元组命中跳过) ===")
p2 = Pipeline(ctx)
p2.run()
