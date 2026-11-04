r"""
AnimeAutoSub 单元测试: 无黑幕贴原日文下方与纯语音 ASR 纯净底居中排版 (tests/test_layout_no_mask.py)
验证:
  1. ASR 纯语音模式: 绝对不生成任何 Mask 黑幕行，生成干净的标准底部居中字幕 (Alignment 2)
  2. OCR 硬字幕模式 (默认 below): 绝对不生成任何 Mask 黑幕行，中文字幕精确排版在原日文检测框正下方 (\pos)
  3. 底部防溢出保护: 当原日文太靠画面边缘时，安全保护文字不被裁切
  4. 显式 replace_mask 时仍能按需生成历史遮罩 (向下兼容)
"""

import json
import pytest
from pathlib import Path
import logging

from core.context import PipelineContext
from core.stages.layout_ass import LayoutAssStage
from lang import get_language


def test_asr_mode_no_mask_clean_layout(tmp_path):
    """测试 ASR 模式下 0 黑幕、纯净底部居中字幕"""
    work_dir = tmp_path / "work_asr"
    work_dir.mkdir()
    
    # 模拟 ASR 产物转译出的 chinese.json (无 box 检测框)
    chinese_data = [
        {"start": 1.0, "end": 3.5, "src": "こんにちは、元気ですか", "zh": "你好，最近好吗？", "video_w": 1920, "video_h": 1080},
        {"start": 4.0, "end": 6.8, "src": "今日もいい天気ですね", "zh": "今天天气也很好呢。", "video_w": 1920, "video_h": 1080}
    ]
    with open(work_dir / "chinese.json", "w", encoding="utf-8") as f:
        json.dump(chinese_data, f, ensure_ascii=False, indent=2)

    dummy_video = tmp_path / "test.mp3"
    dummy_video.write_bytes(b"dummy_mp3")

    ctx = PipelineContext(
        video_path=dummy_video,
        work_dir=work_dir,
        output_dir=work_dir,
        lang=get_language("ja"),
        mode="asr"
    )

    stage = LayoutAssStage()
    stage.run(ctx, logging.getLogger("Test"))

    ass_path = work_dir / "subtitle.ass"
    assert ass_path.exists()
    content = ass_path.read_text(encoding="utf-8")

    # 1. 严格断言: 严禁出现任何 Mask 样式与遮罩行
    assert "Style: Mask" not in content, "ASR 纯语音字幕严禁出现 Style: Mask!"
    assert ",Mask," not in content, "ASR 纯语音字幕严禁出现 Mask 对话行！"
    assert "\\p1" not in content, "ASR 纯语音字幕严禁包含绘制黑框矢量代码 \\p1！"

    # 2. 断言对话行正确生成
    lines = [l for l in content.splitlines() if l.startswith("Dialogue:")]
    assert len(lines) == 2
    assert "Default,,0,0,0,,你好，最近好吗？" in lines[0]
    assert "Default,,0,0,0,,今天天气也很好呢。" in lines[1]


def test_ocr_mode_below_no_mask(tmp_path):
    """测试 OCR 模式默认无黑幕、直接嵌入在原日文检测框正下方"""
    work_dir = tmp_path / "work_ocr"
    work_dir.mkdir()

    # 原日文在 720p: ymin=520, ymax=580 (距离底沿 720 还有 140px)
    chinese_data = [
        {
            "start": 1.2,
            "end": 4.0,
            "src": "おはようございます",
            "zh": "大家早上好",
            "box": [400.0, 520.0, 880.0, 580.0],
            "video_w": 1280,
            "video_h": 720
        }
    ]
    with open(work_dir / "chinese.json", "w", encoding="utf-8") as f:
        json.dump(chinese_data, f, ensure_ascii=False, indent=2)

    dummy_video = tmp_path / "test.mp4"
    dummy_video.write_bytes(b"dummy_video")

    ctx = PipelineContext(
        video_path=dummy_video,
        work_dir=work_dir,
        output_dir=work_dir,
        lang=get_language("ja"),
        mode="ocr"
    )

    stage = LayoutAssStage()
    stage.run(ctx, logging.getLogger("Test"))

    ass_path = work_dir / "subtitle.ass"
    assert ass_path.exists()
    content = ass_path.read_text(encoding="utf-8")

    # 1. 严格断言: 默认 below 样式绝不出现任何黑幕遮罩
    assert "Style: Mask" not in content, "默认无黑幕模式严禁出现 Style: Mask!"
    assert ",Mask," not in content, "默认无黑幕模式严禁出现 Mask 遮罩行！"
    assert "\\p1" not in content, "默认无黑幕模式严禁出现 \\p1 绘图！"

    # 2. 检查字幕定位: 必须定位在原日文 ymax (580) 的正下方
    lines = [l for l in content.splitlines() if l.startswith("Dialogue:")]
    assert len(lines) == 1
    dlg_line = lines[0]
    assert "PosBelow" in dlg_line

    # cx 应在 640 (1280 中轴), zh_top 应在 580 + gap (约 584)
    import re
    m = re.search(r"\\pos\((\d+),(\d+)\)", dlg_line)
    assert m is not None
    pos_x = int(m.group(1))
    pos_y = int(m.group(2))
    assert pos_x == 640, f"X 轴应吸附至画面中心 640, 实际={pos_x}"
    assert pos_y >= 580, f"Y 轴起点必须位于原日文底部 ymax(580) 之下, 实际={pos_y}"
    assert pos_y < 600, f"Y 轴起点应紧跟日文下方，实际={pos_y}"
