import sys
import json
import logging
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.manifest import ManifestManager
from core.context import get_subtitle_src, get_subtitle_src_raw
from core.gpu_lease import get_current_gpu_memory_used, release_ollama_vram, is_ollama_empty
from web.app import app


def test_manifest_schema_version(tmp_path):
    """断言 manifest 默认包含 schema_version = 2"""
    mm = ManifestManager(tmp_path)
    mm.save()
    with open(tmp_path / "manifest.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    assert "schema_version" in data
    assert data["schema_version"] == 2


def test_field_rename_backwards_compatibility(caplog):
    """
    断言读取端兼容:
    1. 优先读取 src / src_raw，不触发 deprecation 日志
    2. 无 src 时回落 ja / ja_raw，并打印 deprecation 日志
    """
    logger = logging.getLogger("test_compat")
    caplog.set_level(logging.WARNING)

    # 1. 新规范 src
    new_item = {"src": "こんにちは", "src_raw": "こんにちは_raw", "zh": "你好"}
    assert get_subtitle_src(new_item, logger) == "こんにちは"
    assert get_subtitle_src_raw(new_item, logger) == "こんにちは_raw"
    assert "deprecated" not in caplog.text

    # 2. 旧规范 ja 回落
    caplog.clear()
    old_item = {"ja": "さようなら", "ja_raw": "さようなら_raw", "zh": "再见"}
    assert get_subtitle_src(old_item, logger) == "さようなら"
    assert "deprecated" in caplog.text or "已废弃" in caplog.text
    
    caplog.clear()
    assert get_subtitle_src_raw(old_item, logger) == "さようなら_raw"
    assert "deprecated" in caplog.text or "已废弃" in caplog.text


def test_ollama_vram_release_threshold():
    """断言调用 release_ollama_vram 后，实测 GPU 显存回落至 1024MB 以下 (或 Ollama 进程已彻底释放且无模型驻留)"""
    log_messages = []
    res = release_ollama_vram(log_messages.append)
    freed_mb = res["freed_mb"]
    curr_mb = res["curr_mb"]
    assert is_ollama_empty(), "Ollama 必须无任何模型驻留"
    assert curr_mb <= 1024 or is_ollama_empty(), f"GPU 显存必须回落至 1024MB 以下，实测: {curr_mb}MB"
    assert any("已释放显存" in msg for msg in log_messages)


def test_p3_web_api_endpoints(tmp_path):
    """
    集成测试 P3 API 接口:
    - GET /api/tasks/{task_id}/subtitles
    - PUT /api/tasks/{task_id}/subtitles (生成 .bak)
    - GET /api/tasks/{task_id}/export/{format}
    """
    client = TestClient(app)

    # 准备测试工作目录
    task_id = "test_p3_dummy_task"
    work_dir = PROJECT_ROOT / "work_tasks" / task_id
    work_dir.mkdir(parents=True, exist_ok=True)

    chinese_data = [
        {"start": 1.0, "end": 2.5, "src": "テスト台詞1", "zh": "测试台词1"},
        {"start": 3.0, "end": 4.5, "ja": "旧台詞2", "zh": "旧台词2"}  # 兼容旧 ja
    ]
    with open(work_dir / "chinese.json", "w", encoding="utf-8") as f:
        json.dump(chinese_data, f, ensure_ascii=False, indent=2)

    with open(work_dir / "subtitle.ass", "w", encoding="utf-8") as f:
        f.write("[Script Info]\nTitle: Test\n")

    with open(work_dir / "subtitle.srt", "w", encoding="utf-8") as f:
        f.write("1\n00:00:01,000 --> 00:00:02,500\n测试\n")

    try:
        # 1. 测试读取字幕
        resp = client.get(f"/api/tasks/{task_id}/subtitles")
        assert resp.status_code == 200
        res = resp.json()
        assert res["code"] == 0
        items = res["data"]
        assert len(items) == 2
        assert items[0]["src"] == "テスト台詞1"
        assert items[1]["src"] == "旧台詞2"  # 旧字段回落成功

        # 2. 测试行内改字保存与 .bak 自动备份
        update_payload = {
            "subtitles": [
                {"start": 1.0, "end": 2.5, "src": "テスト台詞1", "zh": "用户修改后的中文1"},
                {"start": 3.0, "end": 4.5, "src": "旧台詞2", "zh": "用户修改后的中文2"}
            ]
        }
        resp_put = client.put(f"/api/tasks/{task_id}/subtitles", json=update_payload)
        assert resp_put.status_code == 200
        assert (work_dir / "chinese.json.bak").exists(), "必须自动生成 chinese.json.bak 备份"
        
        with open(work_dir / "chinese.json", "r", encoding="utf-8") as f:
            updated_json = json.load(f)
            assert updated_json[0]["zh"] == "用户修改后的中文1"
            assert updated_json[0]["src"] == "テスト台詞1"

        # 3. 测试导出 ASS 与 SRT
        resp_ass = client.get(f"/api/tasks/{task_id}/export/ass")
        assert resp_ass.status_code == 200
        assert "[Script Info]" in resp_ass.text

        resp_srt = client.get(f"/api/tasks/{task_id}/export/srt")
        assert resp_srt.status_code == 200
        assert "00:00:01,000" in resp_srt.text

    finally:
        # 清理测试目录
        import shutil
        if work_dir.exists():
            shutil.rmtree(work_dir, ignore_errors=True)
