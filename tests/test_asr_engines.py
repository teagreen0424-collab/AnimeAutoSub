"""
AnimeAutoSub 单元测试: 多引擎与云端 ASR 语音识别 (tests/test_asr_engines.py)
验证:
  1. ASR 引擎配置正确加载 (siliconflow-sensevoice, local-whisper)
  2. 零 GPU 依赖契约 (API ASR requires_gpu=False)
  3. 密钥严格脱敏保护 (get_masked_key)
  4. AsrStage 指纹感知引擎切换
  5. API 语音转写解析 (含 segments 与纯文本兜底)
  6. Web API 接口 /api/system/asr_engines 与新建任务集成
"""

import os
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from core.asr_engine import (
    load_asr_engine_configs,
    get_asr_engine_config,
    AsrEngineConfig,
    transcribe_via_api,
    extract_audio_for_api
)
from core.stages.asr import AsrStage
from core.context import PipelineContext
from lang import get_language


def test_load_asr_engine_configs():
    """测试从 config/engines.json 正确加载 ASR 引擎配置"""
    configs = load_asr_engine_configs()
    assert "siliconflow-sensevoice" in configs
    assert "local-whisper" in configs

    sf = configs["siliconflow-sensevoice"]
    assert sf.type == "api"
    assert sf.requires_gpu is False
    assert sf.model_name == "FunAudioLLM/SenseVoiceSmall"
    assert "siliconflow.cn" in sf.api_url

    wh = configs["local-whisper"]
    assert wh.type == "local"
    assert wh.requires_gpu is True


def test_asr_gpu_discipline():
    """硬性测试: 云端 ASR 引擎严格零 GPU 依赖"""
    sf = get_asr_engine_config("siliconflow-sensevoice")
    assert sf.requires_gpu is False, "云端 ASR 必须为 requires_gpu=False"

    wh = get_asr_engine_config("local-whisper")
    assert wh.requires_gpu is True, "本地 Whisper 必须为 requires_gpu=True"


def test_asr_key_masking(monkeypatch):
    """测试密钥安全脱敏，绝不泄露原始 key"""
    cfg = AsrEngineConfig(
        id="test-cloud-asr",
        name="测试 ASR",
        type="api",
        api_key="sk-abc123456789xyz"
    )
    masked = cfg.get_masked_key()
    assert "123456789" not in masked
    assert masked.startswith("sk-")
    assert masked.endswith("xyz")

    # 未配置状态
    cfg_empty = AsrEngineConfig(
        id="test-empty",
        name="空密钥测试",
        type="api"
    )
    assert cfg_empty.get_masked_key() == "未配置密钥"
    assert cfg_empty.is_configured() is False


def test_asr_stage_fingerprint_changes(tmp_path):
    """测试切换 ASR 引擎能敏感改变阶段参数指纹，避免错误缓存"""
    stage = AsrStage()
    dummy_video = tmp_path / "test.mp4"
    dummy_video.write_bytes(b"dummy_video_bytes")

    ctx_sf = PipelineContext(
        video_path=dummy_video,
        work_dir=tmp_path / "work1",
        output_dir=tmp_path / "out1",
        lang=get_language("ja"),
        mode="asr",
        asr_engine_id="siliconflow-sensevoice"
    )

    ctx_local = PipelineContext(
        video_path=dummy_video,
        work_dir=tmp_path / "work2",
        output_dir=tmp_path / "out2",
        lang=get_language("ja"),
        mode="asr",
        asr_engine_id="local-whisper"
    )

    fp_sf = stage.fingerprint(ctx_sf)
    fp_local = stage.fingerprint(ctx_local)

    assert fp_sf != fp_local, "切换 ASR 引擎后指纹必须改变"


def test_transcribe_via_api_with_segments(tmp_path):
    """测试模拟 SiliconFlow API 返回 verbose_json segments 的解析"""
    cfg = AsrEngineConfig(
        id="siliconflow-sensevoice",
        name="硅基流动 SenseVoice",
        type="api",
        api_url="https://api.siliconflow.cn/v1/audio/transcriptions",
        api_key="sk-test-asr-mock-key-123456"
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "task": "transcribe",
        "language": "japanese",
        "duration": 5.4,
        "text": "こんにちは世界",
        "segments": [
            {"id": 0, "start": 0.0, "end": 2.5, "text": "こんにちは"},
            {"id": 1, "start": 2.5, "end": 5.4, "text": "世界"}
        ]
    }

    dummy_audio = tmp_path / "test.mp3"
    dummy_audio.write_bytes(b"dummy_mp3_content")

    logger = MagicMock()
    with patch("requests.Session.post", return_value=mock_resp):
        results = transcribe_via_api(
            audio_path=dummy_audio,
            engine_cfg=cfg,
            language_code="ja",
            log=logger
        )

    assert len(results) == 2
    assert results[0]["text"] == "こんにちは"
    assert results[0]["start"] == 0.0
    assert results[0]["end"] == 2.5
    assert results[1]["text"] == "世界"


def test_transcribe_via_api_plain_text_fallback(tmp_path):
    """测试 SiliconFlow API 仅返回纯文本时的标点分句兜底解析"""
    cfg = AsrEngineConfig(
        id="siliconflow-sensevoice",
        name="硅基流动 SenseVoice",
        type="api",
        api_url="https://api.siliconflow.cn/v1/audio/transcriptions",
        api_key="sk-test-asr-mock-key-123456"
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "text": "こんにちは！いい天気ですね。"
    }

    dummy_audio = tmp_path / "test.mp3"
    dummy_audio.write_bytes(b"dummy_mp3_content")

    logger = MagicMock()
    with patch("requests.Session.post", return_value=mock_resp):
        results = transcribe_via_api(
            audio_path=dummy_audio,
            engine_cfg=cfg,
            language_code="ja",
            log=logger
        )

    assert len(results) == 2
    assert "こんにちは" in results[0]["text"]
    assert "いい天気ですね" in results[1]["text"]


def test_web_system_asr_engines():
    """测试 FastAPI /api/system/asr_engines 接口正确脱敏返回"""
    from fastapi.testclient import TestClient
    from web.app import app

    client = TestClient(app)
    resp = client.get("/api/system/asr_engines")
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    engines = body["data"]
    ids = [e["id"] for e in engines]
    assert "siliconflow-sensevoice" in ids
    assert "local-whisper" in ids

    # 验证脱敏
    for e in engines:
        assert "api_key" not in e or not e["api_key"]
        assert "masked_key" in e
