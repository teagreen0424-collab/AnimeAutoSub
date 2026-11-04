import json
import shutil
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from web.app import app
from web.task_manager import TaskManager
from web.queue_manager import queue_manager

client = TestClient(app)


@pytest.fixture
def mock_task_dir(tmp_path):
    """构建一个仿真任务目录，包含成片、音频、切片缓存和字幕文件"""
    task_id = "test_task_for_delete_999"
    task_dir = tmp_path / "work_tasks" / task_id
    task_dir.mkdir(parents=True)

    # 1. 模拟成片 (100KB)
    (task_dir / "output.mp4").write_bytes(b"MOCK_VIDEO_DATA" * 5000)

    # 2. 模拟抠出语音 (50KB)
    (task_dir / "extracted_speech_16k.mp3").write_bytes(b"MOCK_AUDIO_DATA" * 2500)
    (task_dir / "extracted_audio.wav").write_bytes(b"MOCK_WAV_DATA" * 2500)

    # 3. 模拟切片帧缓存目录
    cache_dir = task_dir / ".frame_cache"
    cache_dir.mkdir()
    (cache_dir / "frame_001.jpg").write_bytes(b"MOCK_IMAGE_DATA" * 500)

    # 4. 模拟字幕与元数据
    (task_dir / "subtitle.ass").write_text("[Events]\nDialogue: 0,0:00:01.00,0:00:03.00,Default,,0,0,0,,测试字幕\n", encoding="utf-8")
    (task_dir / "task_meta.json").write_text(json.dumps({
        "task_id": task_id,
        "title": "测试待删除任务",
        "video_path": str(tmp_path / "ocr_input" / "raw_video.mp4"),
        "lang": "ja",
        "mode": "asr"
    }), encoding="utf-8")
    (task_dir / "manifest.json").write_text(json.dumps({
        "task_id": task_id,
        "status": "done",
        "stages": {"burn_subtitles": {"status": "completed"}}
    }), encoding="utf-8")

    # 5. 模拟外部原始片源 (绝不可删除)
    ocr_input = tmp_path / "ocr_input"
    ocr_input.mkdir(parents=True, exist_ok=True)
    raw_video = ocr_input / "raw_video.mp4"
    raw_video.write_bytes(b"RAW_USER_VIDEO_DO_NOT_DELETE" * 1000)

    return tm_fixture(tmp_path, task_id, raw_video)


class tm_fixture:
    def __init__(self, root, task_id, raw_video):
        self.root = root
        self.task_id = task_id
        self.raw_video = raw_video
        self.tm = TaskManager(project_root=root)


def test_storage_stats_breakdown(mock_task_dir):
    """断言存储统计能够精确分解成片、中间资源缓存、字幕大小"""
    f = mock_task_dir
    stats = f.tm.get_task_storage_stats(f.task_id)
    assert stats["task_id"] == f.task_id
    assert stats["video_bytes"] > 0
    assert stats["cache_bytes"] > 0
    assert stats["subtitle_bytes"] > 0
    assert stats["total_bytes"] == stats["video_bytes"] + stats["cache_bytes"] + stats["subtitle_bytes"] + stats["other_bytes"]
    assert stats["is_legacy"] is False


def test_clean_cache_mode_preserves_output_video_and_subtitles(mock_task_dir):
    """断言瘦身模式 (clean_cache) 仅删除抠出的音频与缓存，完好保留成片与字幕"""
    f = mock_task_dir
    task_dir = f.root / "work_tasks" / f.task_id

    # 执行瘦身
    res = f.tm.delete_task(f.task_id, mode="clean_cache")
    assert res["mode"] == "clean_cache"
    assert res["freed_bytes"] > 0

    # 验证中间缓存已被清理
    assert not (task_dir / "extracted_speech_16k.mp3").exists()
    assert not (task_dir / "extracted_audio.wav").exists()
    assert not (task_dir / ".frame_cache").exists()

    # 验证成片和最终字幕完好无损
    assert (task_dir / "output.mp4").exists()
    assert (task_dir / "subtitle.ass").exists()
    assert (task_dir / "task_meta.json").exists()

    # 验证外部原始片源绝对安全
    assert f.raw_video.exists()


def test_full_delete_removes_directory_safely(mock_task_dir):
    """断言全量删除模式 (full) 彻底清除任务目录，但不触碰外部原始片源"""
    f = mock_task_dir
    task_dir = f.root / "work_tasks" / f.task_id

    res = f.tm.delete_task(f.task_id, mode="full")
    assert res["mode"] == "full"
    assert res["freed_bytes"] > 0

    # 验证任务目录彻底从磁盘消失
    assert not task_dir.exists()
    # 验证外部原始片源完好无损
    assert f.raw_video.exists()


def test_legacy_task_is_protected():
    """断言历史基准任务受到系统保护，不可删除"""
    tm = TaskManager()
    # 寻找一个 legacy 任务
    legacy_id = None
    for tid, info in tm.tasks.items():
        if info.get("is_legacy"):
            legacy_id = tid
            break

    if legacy_id:
        with pytest.raises(PermissionError, match="历史基准产物受系统保护"):
            tm.delete_task(legacy_id, mode="full")


def test_api_endpoints_for_delete_and_storage(mock_task_dir, monkeypatch):
    """测试 Web API: GET /api/tasks/{id}/storage 和 DELETE /api/tasks/{id}"""
    from web import app as app_module
    f = mock_task_dir
    monkeypatch.setattr(app_module, "task_manager", f.tm)

    # 1. GET /api/tasks/{task_id}/storage
    resp = client.get(f"/api/tasks/{f.task_id}/storage")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["task_id"] == f.task_id
    assert "total_human" in data

    # 2. DELETE /api/tasks/{task_id}?mode=full
    del_resp = client.delete(f"/api/tasks/{f.task_id}?mode=full")
    assert del_resp.status_code == 200
    del_data = del_resp.json()
    assert del_data["code"] == 0
    assert "已彻底删除" in del_data["message"]

    # 3. 再次查询返回 404
    get_again = client.get(f"/api/tasks/{f.task_id}/storage")
    assert get_again.status_code == 404
