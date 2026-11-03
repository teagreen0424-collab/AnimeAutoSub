"""
AnimeAutoSub 测试: Y1 Z2 软检查与防重复自愈验证 (tests/test_z2_soft_check.py)

验收要求:
  a) 补 3 条单测:
     1. 连续喘息句不触发 (相似度 >= 0.6 视为正常，不重试)
     2. 明显不同源文本触发重试 (重试自愈为新译文)
     3. 重试后相同不抛异常 (记录 duplicate_translation: true，只告警不 assert)
  b) 在输出记录里给这类句子加 "duplicate_translation": true
"""

import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path
from lang import get_language
from core.context import PipelineContext
from core.stages.translate import TranslateStage


@pytest.fixture
def dummy_context(tmp_path):
    lang_plugin = get_language("ja")
    ctx = PipelineContext(
        video_path=tmp_path / "dummy.mp4",
        work_dir=tmp_path / "work",
        output_dir=tmp_path / "output",
        lang=lang_plugin,
        mode="ocr"
    )
    return ctx


def test_continuous_sigh_does_not_trigger_retry(dummy_context):
    """单测 1: 连续喘息/语气句 (相似度 >= 0.6) 即使输出相同译文，也视为正常，不触发重试"""
    stage = TranslateStage()

    prev_src = "百合「はあ、ふう、はあっ、はあっ……こんな……こんなこと……どうして……私、なんで……どうして、こんなに……」"
    curr_src = "百合「はあ、ふう、はあっ、はあつ……こんな……こんなこと……どうして……私、なんで……どうして、こんなに……」"
    pant_zh = "百合「哈、呼、哈啊、哈啊……这样……这样的事……为什么……我、为什么……为什么、会变成这样……」"

    context_pairs = [(prev_src, pant_zh)]

    # Mock Ollama API: 仅返回一次 pant_zh
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": pant_zh}}]
    }

    with patch("core.stages.translate.get_session") as mock_session_getter:
        mock_session = MagicMock()
        mock_session.post.return_value = mock_resp
        mock_session_getter.return_value = mock_session

        zh_out, is_dup = stage.translate_one(curr_src, dummy_context, context_pairs, return_meta=True)

        # 断言: API 只调用了一次，绝没有触发重试
        assert mock_session.post.call_count == 1
        assert zh_out == pant_zh
        assert is_dup is False, "连续语气句相似度 >= 0.60 属于正常对白，不应标记 duplicate_translation"


def test_distinct_source_triggers_retry_and_recovers(dummy_context):
    """单测 2: 明显不同源文本 (相似度 < 0.6) 输出相同译文时，触发纯净上下文重试并自愈为不同译文"""
    stage = TranslateStage()

    prev_src = "百合「おはようございます、先生」"
    prev_zh = "百合「早上好，老师」"
    curr_src = "百合「どうしてそんな酷いことを言うんですか！」"
    recovered_zh = "百合「为什么要说这么过分的话呢！」"

    context_pairs = [(prev_src, prev_zh)]

    # 模拟第一次调用因注意力坍缩输出重复译文 prev_zh，第二次单句重试返回正确译文 recovered_zh
    resp1 = MagicMock()
    resp1.status_code = 200
    resp1.json.return_value = {"choices": [{"message": {"content": prev_zh}}]}

    resp2 = MagicMock()
    resp2.status_code = 200
    resp2.json.return_value = {"choices": [{"message": {"content": recovered_zh}}]}

    with patch("core.stages.translate.get_session") as mock_session_getter:
        mock_session = MagicMock()
        mock_session.post.side_effect = [resp1, resp2]
        mock_session_getter.return_value = mock_session

        zh_out, is_dup = stage.translate_one(curr_src, dummy_context, context_pairs, return_meta=True)

        # 断言: 触发了重试，API 恰好调用了 2 次
        assert mock_session.post.call_count == 2
        # 断言: 成功自愈为重试后的译文
        assert zh_out == recovered_zh
        assert is_dup is False, "自愈成功后译文不重复，不应标记 duplicate_translation"


def test_distinct_source_retry_same_does_not_raise_and_flags_duplicate(dummy_context):
    """单测 3: 明显不同源文本重试后仍相同，绝不抛出 AssertionError 异常，平滑降级并标记 duplicate_translation"""
    stage = TranslateStage()

    prev_src = "百合「おはようございます、先生」"
    prev_zh = "百合「早上好，老师」"
    curr_src = "百合「どうしてそんな酷いことを言うんですか！」"

    context_pairs = [(prev_src, prev_zh)]

    # 模拟第一次调用和重试调用均固执地返回 prev_zh
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"choices": [{"message": {"content": prev_zh}}]}

    with patch("core.stages.translate.get_session") as mock_session_getter:
        mock_session = MagicMock()
        mock_session.post.return_value = resp
        mock_session_getter.return_value = mock_session

        # 核心断言: 绝不抛出任何异常 (不再 assert)
        try:
            zh_out, is_dup = stage.translate_one(curr_src, dummy_context, context_pairs, return_meta=True)
        except AssertionError:
            pytest.fail("Z2 仍抛出了 AssertionError，软检查降级未生效！")

        # 断言: 尝试了重试 (共 2 次调用)
        assert mock_session.post.call_count == 2
        # 断言: 保留了结果
        assert zh_out == prev_zh
        # 断言: 准确标记 duplicate_translation 供复核
        assert is_dup is True, "重试后仍相同的句子必须标记 duplicate_translation=True"
