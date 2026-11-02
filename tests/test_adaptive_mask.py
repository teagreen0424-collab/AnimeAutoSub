import re
import pytest
from pathlib import Path
import animeautosub._env
from pipeline_ocr import generate_subtitles


def test_adaptive_mask_geometry_and_area(tmp_path):
    """
    R1 专项契约测试：
    1. 废弃 MASK_TOP/MASK_HEIGHT 等固定全宽黑条 (1920x180)；
    2. 遮罩几何由该句 OCR 检测框并集 + 8px padding 逐句自适应；
    3. 原画遮盖面积必须 <= 120,000 px；
    4. 日文笔画必须 100% 落在遮罩内（日文残留率 ≈ 0）；
    5. 同一场景内遮罩高度方差 <= 8px。
    """
    translated = [
        {
            "start": 0.0,
            "end": 3.74,
            "ja": "枝彌「はいはい。二人とも、気を付けて行ってらっしゃいね」",
            "zh": "枝弥「好好好。你们两个，路上小心哦。」",
            "box": [203.0, 529.0, 998.0, 656.0],  # 720p 真实双行检测框并集
            "video_w": 1280,
            "video_h": 720,
        },
        {
            "start": 3.74,
            "end": 7.94,
            "ja": "それぞれ仕事と学校に行く二人を、玄関で見送",
            "zh": "在玄关目送各自去工作和上学的两人。",
            "box": [203.0, 557.0, 998.0, 621.0],  # 720p 真实单行检测框并集
            "video_w": 1280,
            "video_h": 720,
        },
        {
            "start": 7.94,
            "end": 9.81,
            "ja": "残ったのは私と、三男の拓斗。",
            "zh": "留下来的只有我和三男拓斗。",
            "box": [197.0, 589.0, 726.0, 661.0],  # 720p 真实单行短句检测框并集
            "video_w": 1280,
            "video_h": 720,
        },
    ]

    ass_path, srt_path = generate_subtitles(translated, tmp_path, video_width=1280, video_height=720)
    assert ass_path.exists()
    assert srt_path.exists()

    content = ass_path.read_text(encoding="utf-8")

    # 1. 断言严禁出现原固定全宽 1920x180 或 1280x180 全宽黑条
    assert "m 0 0 l 1920 0 l 1920 180" not in content, "检测到废弃的 1920x180 全宽实心矩形！"
    assert "m 0 0 l 1280 0 l 1280 180" not in content, "检测到全宽黑条！"

    # 2. 解析生成的遮罩几何
    # Dialogue: 0,0:00:00.00,0:00:03.74,Mask,,0,0,0,,{\an7\pos(X,Y)\p1...}m 0 0 l W 0 l W H l 0 H{\p0}
    mask_pattern = re.compile(
        r"Dialogue:\s*0,[^,]+,[^,]+,Mask,,0,0,0,,\{\\an7\\pos\((\d+),(\d+)\)[^}]*\}m 0 0 l (\d+) 0 l \3 (\d+) l 0 \4\{\\p0\}"
    )
    matches = mask_pattern.findall(content)
    assert len(matches) == len(translated), f"遮罩行数量异常: 预期 {len(translated)}，实际 {len(matches)}"

    heights_1line = []
    for idx, (x_str, y_str, w_str, h_str) in enumerate(matches):
        x0, y0, w, h = int(x_str), int(y_str), int(w_str), int(h_str)
        area = w * h
        box = translated[idx]["box"]

        # 指标 1: 遮罩面积必须 <= 120,000 px
        assert area <= 120_000, f"句子 {idx} 遮罩面积超标: {area} px > 120,000 px (w={w}, h={h})"

        # 指标 2: 日文检测框完全被遮罩包含且外扩 padding >= 8px
        assert x0 <= box[0] - 8, f"句子 {idx} 左侧未能完全覆盖日文: x0={x0} > {box[0]-8}"
        assert y0 <= box[1] - 8, f"句子 {idx} 顶部未能完全覆盖日文 (露笔画): y0={y0} > {box[1]-8}"
        assert x0 + w >= box[2] + 8, f"句子 {idx} 右侧未能完全覆盖日文"
        assert y0 + h >= box[3] + 8, f"句子 {idx} 底部未能完全覆盖日文"

        # 收集单行高度
        if idx in (1, 2):
            heights_1line.append(h)

    # 指标 3: 同一场景同类型（单行）遮罩高度方差 <= 8px (网格量化后高度差应 <= 8px)
    assert abs(heights_1line[0] - heights_1line[1]) <= 8, (
        f"单行遮罩高度跳动过大: {heights_1line}"
    )
