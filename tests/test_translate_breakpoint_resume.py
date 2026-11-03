"""
AnimeAutoSub 测试: Y2 翻译断点原子写入与续跑验证 (tests/test_translate_breakpoint_resume.py)

验收要求:
  1. 每 20 句把结果原子写入 chinese.json (临时文件 + os.replace)
  2. 启动时若存在 chinese.json 且句子数小于 ocr_raw.json，从中断处续跑
  3. manifest 里记录已翻译句数
"""

import json
import logging
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from lang import get_language
from core.context import PipelineContext
from core.stages.translate import TranslateStage
from core.manifest import ManifestManager


@pytest.fixture
def test_env(tmp_path):
    lang_plugin = get_language("ja")
    work_dir = tmp_path / "work"
    work_dir.mkdir(parents=True, exist_ok=True)
    out_dir = tmp_path / "output"
    out_dir.mkdir(parents=True, exist_ok=True)

    ctx = PipelineContext(
        video_path=tmp_path / "dummy.mp4",
        work_dir=work_dir,
        output_dir=out_dir,
        lang=lang_plugin,
        mode="ocr"
    )

    manifest_mgr = ManifestManager(work_dir)
    manifest_mgr.save()

    return ctx, logging.getLogger("test_logger")


def test_translate_atomic_checkpoint_and_manifest_record(test_env):
    """测试: 翻译流水线每 20 句原子保存检查点，并在 manifest 中记录 translated_count"""
    ctx, log = test_env
    stage = TranslateStage()

    # 准备 25 句测试数据
    total_count = 25
    segments = [
        {"start": i * 2.0, "end": (i + 1) * 2.0, "text": f"テスト対話_{i:02d}。"}
        for i in range(total_count)
    ]
    raw_path = ctx.get_product_path("ocr_raw.json")
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump(segments, f, ensure_ascii=False, indent=2)

    # Mock translate_one: 返回固定译文
    with patch.object(stage, "translate_one") as mock_trans:
        mock_trans.side_effect = lambda text, c, ctx_p, return_meta=False: (
            (f"中文译文_{text}", False) if return_meta else f"中文译文_{text}"
        )

        stage.run(ctx, log)

    # 验证最终 chinese.json 存在且包含全部 25 句
    chinese_path = ctx.get_product_path("chinese.json")
    assert chinese_path.exists()
    with open(chinese_path, "r", encoding="utf-8") as f:
        results = json.load(f)
    assert len(results) == total_count
    assert all("duplicate_translation" in r for r in results)

    # 验证 manifest.json 中准确记录已翻译句数
    manifest_path = ctx.work_dir / "manifest.json"
    with open(manifest_path, "r", encoding="utf-8") as f:
        mf_data = json.load(f)
    translate_mf = mf_data["stages"]["translate"]
    assert translate_mf["translated_count"] == total_count
    assert translate_mf["total_count"] == total_count


def test_translate_resumes_from_breakpoint(test_env):
    """测试: 若已存在部分 chinese.json (如 20 句)，启动时从第 21 句续跑，跳过前 20 句"""
    ctx, log = test_env
    stage = TranslateStage()

    # 准备 30 句上游数据
    total_count = 30
    segments = [
        {"start": i * 2.0, "end": (i + 1) * 2.0, "text": f"テスト対話_{i:02d}。"}
        for i in range(total_count)
    ]
    raw_path = ctx.get_product_path("ocr_raw.json")
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump(segments, f, ensure_ascii=False, indent=2)

    # 模拟历史断点: 前 20 句已提前写入 chinese.json
    pre_translated = [
        {
            "start": i * 2.0,
            "end": (i + 1) * 2.0,
            "src": f"テスト対話_{i:02d}。",
            "src_raw": f"テスト対話_{i:02d}。",
            "zh": f"已存中文_{i:02d}",
            "rejected": False,
            "incomplete_translation": False,
            "duplicate_translation": False
        }
        for i in range(20)
    ]
    chinese_path = ctx.get_product_path("chinese.json")
    with open(chinese_path, "w", encoding="utf-8") as f:
        json.dump(pre_translated, f, ensure_ascii=False, indent=2)

    # 执行 stage.run()，断言 translate_one 仅针对后 10 句被调用
    with patch.object(stage, "translate_one") as mock_trans:
        mock_trans.side_effect = lambda text, c, ctx_p, return_meta=False: (
            (f"续跑中文_{text}", False) if return_meta else f"续跑中文_{text}"
        )

        stage.run(ctx, log)

        # 断言: 前 20 句全部跳过，只翻译了后 10 句
        assert mock_trans.call_count == 10

    # 验证最终产物完整拼接为 30 句
    with open(chinese_path, "r", encoding="utf-8") as f:
        final_results = json.load(f)
    assert len(final_results) == 30
    # 前 20 句保持历史结果
    assert final_results[0]["zh"] == "已存中文_00"
    assert final_results[19]["zh"] == "已存中文_19"
    # 后 10 句为续跑生成的新结果
    assert "续跑中文" in final_results[20]["zh"]
    assert "续跑中文" in final_results[29]["zh"]

    # 验证 manifest 中记录句数为 30
    manifest_path = ctx.work_dir / "manifest.json"
    with open(manifest_path, "r", encoding="utf-8") as f:
        mf_data = json.load(f)
    assert mf_data["stages"]["translate"]["translated_count"] == 30
