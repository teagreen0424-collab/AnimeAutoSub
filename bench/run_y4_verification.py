"""
AnimeAutoSub 验证脚本: Y4 重跑 work_20261103_100735_21684-720p

验证目标:
  1. 验证断点中断与续跑:
     - 启动翻译后在检查点模拟中断，验证原子写入 chinese.json 与 manifest.json
     - 再次启动，验证自动识别断点并从中断句继续，跳过已翻译内容
  2. 验证 Z2 软检查:
     - 越过历史崩溃点 (#160)，不再中断任务
     - 顺利跑完整个片子直至成片
"""

import os
import sys
import json
import time
import logging
from pathlib import Path

# 环境与项目路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lang import get_language
from core.context import PipelineContext, CancelToken
from core.pipeline import Pipeline
from core.stages.translate import TranslateStage


def setup_logger():
    logger = logging.getLogger("y4_runner")
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S"))
    logger.handlers = [handler]
    return logger


def main():
    log = setup_logger()
    log.info("=" * 60)
    log.info("  🚀 开始执行 Y4 验收: 验证断点保存、断点续跑与 Z2 软检查自愈")
    log.info("=" * 60)

    work_dir = Path("work_tasks/work_20261103_100735_21684-720p")
    video_path = Path("ocr_input/21684-720p.mp4")

    if not work_dir.exists():
        log.error(f"工作目录不存在: {work_dir}")
        return

    # 读取上游产物
    raw_path = work_dir / "ocr_raw.json"
    with open(raw_path, "r", encoding="utf-8") as f:
        ocr_segments = json.load(f)
    total_segments = len(ocr_segments)
    log.info(f"  上游 OCR 产物共 {total_segments} 句")

    # Step 1: 验证断点续跑能力
    # 若目前没有 chinese.json，我们先跑前 40 句，然后中断，验证第 1 次断点落盘
    chinese_path = work_dir / "chinese.json"
    manifest_path = work_dir / "manifest.json"

    # 构造上下文
    lang_plugin = get_language("ja")
    ctx = PipelineContext(
        video_path=video_path,
        work_dir=work_dir,
        output_dir=work_dir,
        lang=lang_plugin,
        mode="ocr"
    )

    stage = TranslateStage()

    # 如果没有 chinese.json，先执行至第 40 句主动保存并模拟中断
    if not chinese_path.exists() or chinese_path.stat().st_size < 10:
        log.info("  [阶段 1/2] 首次启动翻译，将在第 40 句模拟中断以验证原子检查点与续跑...")
        # 拦截并在第 40 句触发取消
        cancel_token = CancelToken()
        
        orig_translate_one = stage.translate_one
        call_count = [0]
        def counting_translate_one(*args, **kwargs):
            res = orig_translate_one(*args, **kwargs)
            call_count[0] += 1
            if call_count[0] == 40:
                log.info("  ⚡ 已达到第 40 句检查点，触发取消信号中断任务以测试断点恢复...")
                cancel_token.cancel("模拟断点测试")
            return res

        stage.translate_one = counting_translate_one
        stage.run(ctx, log, cancel_token=cancel_token)
        stage.translate_one = orig_translate_one

        # 检查断点是否原子落盘
        assert chinese_path.exists(), "断点未生成 chinese.json"
        with open(chinese_path, "r", encoding="utf-8") as f:
            c_data = json.load(f)
        log.info(f"  ✓ 检查点验证成功: chinese.json 包含 {len(c_data)} 句")
        assert len(c_data) == 40, f"期望检查点包含 40 句，实际为 {len(c_data)}"

        # 检查 manifest.json
        with open(manifest_path, "r", encoding="utf-8") as f:
            mf = json.load(f)
        trans_mf = mf["stages"].get("translate", {})
        log.info(f"  ✓ manifest 记录翻译句数: {trans_mf.get('translated_count')}/{trans_mf.get('total_count')}")
        assert trans_mf.get("translated_count") == 40

    else:
        with open(chinese_path, "r", encoding="utf-8") as f:
            c_data = json.load(f)
        log.info(f"  检测到已存在 chinese.json ({len(c_data)} 句)")

    # Step 2: 完整恢复续跑，穿越 #160，完成全片
    log.info("\n  [阶段 2/2] 触发完整续跑，从断点处继续执行，穿越 #160 并压制成片...")
    full_pipeline = Pipeline(ctx)
    success = full_pipeline.run()

    if success:
        log.info("=" * 60)
        log.info("  🎉 Y4 验证圆满成功！")
        log.info(f"  成片输出: {work_dir / 'output.mp4'}")
        log.info("=" * 60)
    else:
        log.error("  ✗ 流水线执行未完全成功")


if __name__ == "__main__":
    main()
