import sys
import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from web.app import app

client = TestClient(app)


def test_system_settings_endpoint():
    """断言 /api/system/settings 返回只读端口、模型路径、OCR引擎与 Schema 版本"""
    resp = client.get("/api/system/settings")
    assert resp.status_code == 200
    res = resp.json()
    assert res["code"] == 0
    data = res["data"]
    assert "port" in data and data["port"] == 8000
    assert "ollama_models_path" in data
    assert "D:\\Dev\\ollama\\models" in data["ollama_models_path"]
    assert "RapidOCR" in data["ocr_engine"]
    assert data["schema_version"] == 2


def test_video_export_download_endpoint(tmp_path):
    """断言 /api/tasks/{task_id}/export/video 可直接作为成片下载附件返回"""
    task_id = "test_p4_export_task"
    work_dir = PROJECT_ROOT / "work_tasks" / task_id
    work_dir.mkdir(parents=True, exist_ok=True)
    video_file = work_dir / "output.mp4"
    video_file.write_bytes(b"dummy_mp4_content_for_download_test")

    try:
        resp = client.get(f"/api/tasks/{task_id}/export/video")
        assert resp.status_code == 200
        assert resp.headers.get("content-type") == "video/mp4"
        assert "attachment" in resp.headers.get("content-disposition", "")
        assert resp.content == b"dummy_mp4_content_for_download_test"

        # 测试指定产物文件下载端点
        resp_file = client.get(f"/api/tasks/{task_id}/file/output.mp4")
        assert resp_file.status_code == 200
        assert resp_file.headers.get("content-type") == "video/mp4"
        assert resp_file.content == b"dummy_mp4_content_for_download_test"
    finally:
        import shutil
        if work_dir.exists():
            shutil.rmtree(work_dir)


def test_work_tasks_root_directory_exclusion():
    """E3 契约: 确保扫描时排除 work_tasks 根目录本身，严禁被当作独立任务"""
    resp = client.get("/api/tasks")
    assert resp.status_code == 200
    res = resp.json()
    assert res["code"] == 0
    tasks = res["data"]["tasks"]
    task_ids = [t["task_id"] for t in tasks]
    assert "work_tasks" not in task_ids


def test_x1_fake_controls_elimination():
    """X1 契约: 新建弹窗高级参数假控件彻底清除，改为只读固定值"""
    html_path = PROJECT_ROOT / "web" / "static" / "index.html"
    html = html_path.read_text(encoding="utf-8")

    import re
    # 1. inputFps 必须为 disabled 只读
    fps_match = re.search(r'<input[^>]*id=["\']inputFps["\'][^>]*>', html)
    assert fps_match is not None, "缺少 inputFps"
    assert "disabled" in fps_match.group(0), "inputFps 必须包含 disabled 属性"

    # 2. inputDiff 必须为 disabled 只读，且值更正为 2.5%
    diff_match = re.search(r'<input[^>]*id=["\']inputDiff["\'][^>]*>', html)
    assert diff_match is not None, "缺少 inputDiff"
    assert "disabled" in diff_match.group(0), "inputDiff 必须包含 disabled 属性"
    assert "2.5%" in diff_match.group(0), "inputDiff 显示值必须为 2.5%"

    # 3. 翻译模型必须统一为 sakura-14b-qwen2.5-v1.0-iq4_xs
    assert "sakura-14b-qwen2.5-v1.0-iq4_xs" in html

    # 4. 4 项标签全部标注 (固定值)
    advanced_section = html[html.find("form-advanced-details"):html.find("modal-footer")]
    labels = re.findall(r'<label class="form-label">([^<]+)</label>', advanced_section)
    assert len(labels) == 4, f"应有 4 个参数标签，实际为 {len(labels)}"
    for l in labels:
        assert "固定值" in l, f"标签未标注'固定值': {l}"
