"""
AnimeAutoSub 单元测试: 多引擎与云端 API 翻译分支 (tests/test_translation_engines.py)

覆盖验证:
  1. 指纹防穿透: 换引擎 (engine_id / base_url / prompt_version) 指纹必变，防止错误复用缓存
  2. 密钥脱敏: 仓库、日志、异常与前端绝不泄露明文密钥
  3. 拒答三形态识别: 关键词文本、finish_reason content_filter、HTTP 安全错误
  4. 拒答话术绝不写进 chinese.json (产物中查不到拒答提示语)
  5. 累计拒答率 > 20% 立即中止任务并给出切换本地 Sakura 的明确建议
  6. 费用计算、Token 统计与单任务预算硬上限拦截
  7. 日韩双语云端影视 Prompt 构造正确性
"""

import os
import json
import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path

from core.context import PipelineContext
from core.stages.translate import TranslateStage
from core.translation_engine import (
    EngineConfig,
    get_engine_config,
    load_engine_configs,
    redact_secrets,
    register_secret,
    is_refusal_response,
    calculate_cost,
    estimate_tokens
)
from lang import get_language
from lang.ja import CLOUD_JA_SYSTEM_PROMPT, build_cloud_japanese_prompt
from lang.ko import CLOUD_KO_SYSTEM_PROMPT, build_cloud_korean_prompt


@pytest.fixture
def dummy_context(tmp_path):
    lang_plugin = get_language("ja")
    ctx = PipelineContext(
        video_path=tmp_path / "dummy.mp4",
        work_dir=tmp_path / "work",
        output_dir=tmp_path / "output",
        lang=lang_plugin,
        mode="ocr",
        engine_id="sakura-14b"
    )
    return ctx


def test_fingerprint_strictly_changes_on_engine_switch(dummy_context):
    """十条红线之二: 换引擎 → 指纹必变。防止 manifest 三重匹配错误命中旧缓存"""
    stage = TranslateStage()

    # 1. 默认 Sakura 引擎指纹
    dummy_context.engine_id = "sakura-14b"
    fp_sakura = stage.fingerprint(dummy_context)

    # 2. 切换为 DeepSeek 云端引擎
    dummy_context.engine_id = "deepseek-chat"
    fp_deepseek = stage.fingerprint(dummy_context)

    # 3. 切换为 OpenAI 云端引擎
    dummy_context.engine_id = "openai-gpt4o-mini"
    fp_openai = stage.fingerprint(dummy_context)

    assert fp_sakura != fp_deepseek, "切换到 DeepSeek 后指纹未改变，会导致流水线静默跳过并复用旧译文！"
    assert fp_sakura != fp_openai, "切换到 OpenAI 后指纹未改变！"
    assert fp_deepseek != fp_openai, "DeepSeek 与 OpenAI 之间指纹未改变！"


def test_secret_redaction():
    """十条红线之三: 密钥绝不泄露到日志或异常信息中"""
    secret_key = "sk-deepseek-live-secret-test-key-12345678"
    register_secret(secret_key)

    raw_log = f"请求 API 失败: URL=https://api.deepseek.com Bearer {secret_key}, key={secret_key}"
    redacted = redact_secrets(raw_log)

    assert secret_key not in redacted, "明文密钥未被脱敏！"
    assert "***REDACTED***" in redacted or "****" in redacted


def test_refusal_three_forms():
    """拒答三形态识别校验"""
    # 形态 1: 文本关键词匹配
    form1_texts = [
        "抱歉，我无法协助翻译该内容。",
        "对不起，这违反了我们的安全政策，无法提供翻译。",
        "作为AI语言模型，我不能翻译此类文本。",
        "I cannot fulfill this request due to content safety policy."
    ]
    for text in form1_texts:
        is_ref, reason = is_refusal_response(text)
        assert is_ref is True, f"形态 1 未能识别拒答: {text}"

    # 正常文本不应误判
    normal_texts = [
        "你好，今天天气真不错。",
        "お世話になっております。",
        "안녕하세요 반갑습니다."
    ]
    for text in normal_texts:
        is_ref, _ = is_refusal_response(text)
        assert is_ref is False, f"正常文本被误判为拒答: {text}"

    # 形态 2: finish_reason 为 content_filter / safety
    resp_filter = {"choices": [{"finish_reason": "content_filter", "message": {"content": ""}}]}
    is_ref2, r2 = is_refusal_response("", resp_filter)
    assert is_ref2 is True
    assert "content_filter" in r2

    # 形态 3: HTTP 400 / 403 安全政策报错
    resp_err = {"error": {"message": "Content moderation triggered: policy violation", "type": "policy_error"}}
    is_ref3, r3 = is_refusal_response("", resp_err, status_code=400)
    assert is_ref3 is True
    assert "safety_policy" in r3


def test_refusal_text_never_in_chinese_json(dummy_context):
    """十条红线之五: 拒答话术绝不写进 chinese.json"""
    stage = TranslateStage()
    dummy_context.engine_id = "deepseek-chat"

    refusal_msg = "抱歉，作为AI模型，我无法协助翻译包含敏感描述的台词。"
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": refusal_msg}}]
    }

    stats = {}
    with patch("core.stages.translate.get_session") as mock_session_getter:
        mock_session = MagicMock()
        mock_session.post.return_value = mock_resp
        mock_session_getter.return_value = mock_session

        zh_out, is_dup = stage.translate_one("お前を犯してやる", dummy_context, [], return_meta=True, stats=stats)

        # 断言: 译文必须被置空，绝对不能写入拒答话术
        assert zh_out == "", "拒答文本被写入译文输出！"
        assert stats.get("was_refused") is True


def test_cumulative_refusal_aborts_pipeline(tmp_path):
    """十条红线之五: 累计拒答率超过 20% 时立即中止任务并给出明确建议"""
    lang_plugin = get_language("ja")
    ctx = PipelineContext(
        video_path=tmp_path / "dummy.mp4",
        work_dir=tmp_path / "work",
        output_dir=tmp_path / "output",
        lang=lang_plugin,
        mode="ocr",
        engine_id="deepseek-chat"
    )

    # 构造包含 6 句的上游 ocr_raw.json
    raw_segments = [
        {"start": 1.0, "end": 2.0, "text": f"台詞テスト番号 {i}"}
        for i in range(6)
    ]
    raw_path = ctx.get_product_path("ocr_raw.json")
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump(raw_segments, f, ensure_ascii=False)

    stage = TranslateStage()
    mock_logger = MagicMock()

    # 模拟 API: 前两句正常，后面连续拒答 (拒答率 4/6 = 66% > 20%)
    normal_resp = MagicMock()
    normal_resp.status_code = 200
    normal_resp.json.return_value = {"choices": [{"message": {"content": "这是正常译文"}}]}

    refusal_resp = MagicMock()
    refusal_resp.status_code = 200
    refusal_resp.json.return_value = {"choices": [{"message": {"content": "抱歉，我无法协助提供翻译。"}}]}

    responses = [normal_resp, normal_resp, refusal_resp, refusal_resp, refusal_resp, refusal_resp]

    with patch("core.stages.translate.get_session") as mock_session_getter:
        mock_session = MagicMock()
        mock_session.post.side_effect = responses
        mock_session_getter.return_value = mock_session

        with pytest.raises(RuntimeError) as exc_info:
            stage.run(ctx, mock_logger)

        assert "拒答率超过 20%" in str(exc_info.value)
        assert "建议切换为本地 Sakura-14B 引擎" in str(exc_info.value)


def test_hard_cost_cap_aborts(tmp_path):
    """预算安全: 累计费用超过 hard_cost_cap 自动中止"""
    lang_plugin = get_language("ja")
    ctx = PipelineContext(
        video_path=tmp_path / "dummy.mp4",
        work_dir=tmp_path / "work",
        output_dir=tmp_path / "output",
        lang=lang_plugin,
        mode="ocr",
        engine_id="deepseek-chat"
    )

    raw_segments = [{"start": 1.0, "end": 2.0, "text": f"こんにちは、お元気ですか、テスト番号 {i}。"} for i in range(5)]
    raw_path = ctx.get_product_path("ocr_raw.json")
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump(raw_segments, f, ensure_ascii=False)

    stage = TranslateStage()
    mock_logger = MagicMock()

    # 将硬上限临时调低至 0.0001
    mock_engine_cfg = get_engine_config("deepseek-chat")
    mock_engine_cfg.hard_cost_cap = 0.000001

    with patch("core.stages.translate.get_engine_config", return_value=mock_engine_cfg):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "正常译文"}}],
            "usage": {"prompt_tokens": 100000, "completion_tokens": 50000}
        }
        with patch("core.stages.translate.get_session") as mock_session_getter:
            mock_session = MagicMock()
            mock_session.post.return_value = mock_resp
            mock_session_getter.return_value = mock_session

            with pytest.raises(RuntimeError) as exc_info:
                stage.run(ctx, mock_logger)

            assert "超过单任务硬上限" in str(exc_info.value)


def test_ja_and_ko_cloud_prompts():
    """日韩双语云端影视台词专用 Prompt 测试"""
    # 1. 日语 Prompt 测试
    glossary_ja = {"田中": "田中"}
    prompt_ja = build_cloud_japanese_prompt("田中さん、こんにちは", glossary_ja, [])
    assert "影视字幕风格" in prompt_ja
    assert "田中->田中" in prompt_ja
    assert "影视字幕翻译专家" in CLOUD_JA_SYSTEM_PROMPT

    # 2. 韩语 Prompt 测试
    glossary_ko = {"지훈": "志勋"}
    prompt_ko = build_cloud_korean_prompt("지훈아, 밥 먹었어?", glossary_ko, [])
    assert "影视字幕风格" in prompt_ko
    assert "지훈->志勋" in prompt_ko
    assert "影视字幕翻译专家" in CLOUD_KO_SYSTEM_PROMPT


def test_engine_gpu_and_masked_key_properties():
    """核验 GPU 独占隔离与密钥脱敏显示"""
    engines = load_engine_configs()
    sakura = engines.get("sakura-14b")
    deepseek = engines.get("deepseek-chat")

    assert sakura is not None
    assert sakura.requires_gpu is True, "本地 Sakura-14B 必须标记 requires_gpu=True"

    assert deepseek is not None
    assert deepseek.requires_gpu is False, "云端 API 引擎必须标记 requires_gpu=False"
    assert deepseek.type == "api"

    # 验证 get_masked_key 不泄露明文
    deepseek.api_key = "sk-1234567890abcdef123456"
    masked = deepseek.get_masked_key()
    assert "sk-1234567890abcdef123456" not in masked
    assert "****" in masked
