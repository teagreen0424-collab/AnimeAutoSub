"""
AnimeAutoSub 单元测试: WebUI 多引擎 API 路由与安全隔离 (tests/test_webui_engines.py)
"""

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from web.app import app
from core.translation_engine import register_secret


@pytest.fixture
def client():
    return TestClient(app)


def test_api_system_engines_list_and_secret_safety(client):
    """验证 GET /api/system/engines 返回结构且明文密钥绝不出库"""
    # 注入一个带临时 key 的引擎配置以验证打码
    test_key = "sk-deepseek-webui-secret-key-99998888"
    register_secret(test_key)

    resp = client.get("/api/system/engines")
    assert resp.status_code == 200
    data = resp.json()
    assert data["code"] == 0
    engines = data["data"]
    assert len(engines) >= 3

    engine_ids = [e["id"] for e in engines]
    assert "sakura-14b" in engine_ids
    assert "deepseek-chat" in engine_ids
    assert "openai-gpt4o-mini" in engine_ids

    # 严格断言: 任何引擎对象的响应中都不包含 api_key 字段，且全局搜不到 test_key 明文
    raw_text = resp.text
    assert test_key not in raw_text
    for e in engines:
        assert "api_key" not in e, "敏感字段 api_key 不应暴露在 API 响应结构中！"
        assert "masked_key" in e
        assert "configured" in e
        assert "pricing" in e


def test_create_task_with_valid_and_invalid_engine(client, tmp_path):
    """验证 POST /api/tasks 携带 engine_id 创建任务及非法引擎报错拦截"""
    # 1. 尝试非法引擎
    bad_payload = {
        "video_path": "ocr_input/test_3min.mp4",
        "engine_id": "non_existent_engine_xxx",
        "auto_start": False
    }
    resp_bad = client.post("/api/tasks", json=bad_payload)
    assert resp_bad.status_code == 400
    assert "不支持的翻译引擎" in resp_bad.json()["detail"]

    # 2. 正常指定 deepseek-chat 引擎
    good_payload = {
        "video_path": "ocr_input/test_3min.mp4",
        "engine_id": "deepseek-chat",
        "auto_start": False
    }
    with patch("web.queue_manager.queue_manager.submit_task", return_value={"status": "queued", "position": 1}):
        resp_good = client.post("/api/tasks", json=good_payload)
        assert resp_good.status_code == 200
        res_data = resp_good.json()["data"]
        task_id = res_data["task_id"]
        assert res_data["engine_id"] == "deepseek-chat"

        # 检查持久化的 task_meta.json
        meta_file = Path("work_tasks") / task_id / "task_meta.json"
        if meta_file.exists():
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
            assert meta.get("engine_id") == "deepseek-chat"


def test_system_settings_contains_engines_info(client):
    """验证 GET /api/system/settings 包含脱敏的多引擎状态汇总"""
    resp = client.get("/api/system/settings")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "engines" in data
    assert isinstance(data["engines"], list)
    assert len(data["engines"]) >= 3
