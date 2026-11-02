"""
S 阶段结构解耦与布局外置回归单测 (tests/test_s_stage_parity.py)

门禁判据:
  1. 60 句评测集: 文本逐条一致 (0 差异), 坐标/遮罩偏差 <= 2px
  2. 前 10 分钟真实素材: 文本逐条一致, 坐标偏差 <= 2px, 抽帧像素差 < 0.5%
"""

import pytest
from pathlib import Path
from bench.run_s_parity_regression import run_regression_60, run_regression_10min


def test_s_stage_60_sentences_parity():
    """60 句评测集确定性回归"""
    run_regression_60()


def test_s_stage_10min_material_parity():
    """全片前 10 分钟真实视频素材回归"""
    video_file = Path("ocr_input/114877-720p.mp4")
    src_chinese = Path("ocr_output/114877-720p/chinese.json")
    if not video_file.exists() or not src_chinese.exists():
        pytest.skip("本地缺少 114877-720p 母片或基准产物，跳过真实视频抽帧比对")
    run_regression_10min()
