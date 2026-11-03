"""
AnimeAutoSub 测试: Z4 拖拽流式上传与 Z5 报错引导复核 (tests/test_z4_upload_and_z5_prompt.py)

验收要求:
  A) 真上传 (POST /api/upload):
     1. UploadFile 流式写入 ocr_input/，使用 shutil.copyfileobj，禁止一次性读入内存;
     2. 同名文件存在时自动递增重命名 (xxx_1.mp4) 而非覆盖;
     3. 限制: 单文件 > 4 GB 拒绝; 磁盘剩余 < 文件大小 * 2 拒绝并提示详细信息;
     4. 上传成功返回规范 rel_path 供前端填入与刷新列表。
  B) 兜底文案与引导:
     1. 弹窗 label 明确提示 "(请填完整路径，或把文件放进 ocr_input 目录)";
     2. Z5: 400 报错补齐路径与操作引导。
"""

import io
import shutil
from pathlib import Path
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient

from web.app import app, PROJECT_ROOT


@pytest.fixture
def client():
    return TestClient(app)


def test_z4_upload_streaming_and_collision_renaming(client):
    """Z4: 测试流式上传、自动落盘至 ocr_input 及同名自动改名机制"""
    ocr_input = PROJECT_ROOT / "ocr_input"
    ocr_input.mkdir(parents=True, exist_ok=True)

    test_filename = "test_upload_sample.mp4"
    target_1 = ocr_input / test_filename
    target_2 = ocr_input / "test_upload_sample_1.mp4"

    # 清理残留
    target_1.unlink(missing_ok=True)
    target_2.unlink(missing_ok=True)

    try:
        content_1 = b"fake mp4 video stream 1"
        file_obj_1 = io.BytesIO(content_1)

        # 1. 首次上传
        resp1 = client.post(
            "/api/upload",
            files={"file": (test_filename, file_obj_1, "video/mp4")}
        )
        assert resp1.status_code == 200, f"首次上传失败: {resp1.text}"
        res1 = resp1.json()
        assert res1["code"] == 0
        assert res1["data"]["filename"] == test_filename
        assert res1["data"]["rel_path"] == f"ocr_input/{test_filename}"
        assert target_1.exists()
        assert target_1.read_bytes() == content_1

        # 2. 第二次上传同名文件 -> 断言改名 (test_upload_sample_1.mp4) 而非覆盖
        content_2 = b"fake mp4 video stream 2 distinct"
        file_obj_2 = io.BytesIO(content_2)
        resp2 = client.post(
            "/api/upload",
            files={"file": (test_filename, file_obj_2, "video/mp4")}
        )
        assert resp2.status_code == 200, f"同名上传失败: {resp2.text}"
        res2 = resp2.json()
        assert res2["code"] == 0
        assert res2["data"]["filename"] == "test_upload_sample_1.mp4"
        assert res2["data"]["rel_path"] == "ocr_input/test_upload_sample_1.mp4"
        assert target_2.exists()
        # 原文件未被覆盖
        assert target_1.read_bytes() == content_1
        # 新文件内容正确
        assert target_2.read_bytes() == content_2

    finally:
        target_1.unlink(missing_ok=True)
        target_2.unlink(missing_ok=True)


def test_z4_upload_exceeds_4gb_rejected(client):
    """Z4: 测试单文件 > 4 GB 限制拦截"""
    fake_header = {"content-length": str(5 * 1024 * 1024 * 1024)}  # 5 GB
    file_obj = io.BytesIO(b"small")

    resp = client.post(
        "/api/upload",
        files={"file": ("large_video.mp4", file_obj, "video/mp4")},
        headers=fake_header
    )
    assert resp.status_code == 400
    assert "4 GB" in resp.json()["detail"] or "4GB" in resp.json()["detail"]


def test_z4_upload_disk_space_insufficient_rejected(client):
    """Z4: 测试磁盘剩余 < 文件大小 * 2 拒绝拦截并提示"""
    # 模拟磁盘剩余仅 500 MB，但文件有 300 MB (需要 600 MB)
    mock_total = 100 * 1024 * 1024 * 1024
    mock_used = 99 * 1024 * 1024 * 1024
    mock_free = 500 * 1024 * 1024  # 500 MB

    with patch("shutil.disk_usage", return_value=(mock_total, mock_used, mock_free)):
        fake_header = {"content-length": str(300 * 1024 * 1024)}
        file_obj = io.BytesIO(b"data")
        resp = client.post(
            "/api/upload",
            files={"file": ("space_test.mp4", file_obj, "video/mp4")},
            headers=fake_header
        )
        assert resp.status_code == 400
        detail = resp.json()["detail"]
        assert "磁盘剩余空间不足" in detail
        assert "文件大小 × 2" in detail


def test_z5_nonexistent_file_guidance_prompt(client):
    """Z5: 测试片源不存在时的详细引导文案"""
    fake_path = r"D:\non_existent_folder_xyz\37215-1080p.mp4"
    resp = client.post(
        "/api/tasks",
        json={"video_path": fake_path}
    )
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "片源文件不存在" in detail
    assert "请填写完整路径（如 D:\\视频\\a.mp4）" in detail
    assert "或先把文件复制到 ocr_input 目录后从下拉框选择" in detail


def test_z4_frontend_label_and_progress_dom():
    """Z4 B: 检查 index.html 文案已更新为 '(请填完整路径，或把文件放进 ocr_input 目录)' 且存在进度条容器"""
    html_path = PROJECT_ROOT / "web" / "static" / "index.html"
    content = html_path.read_text(encoding="utf-8")

    assert "(请填完整路径，或把文件放进 ocr_input 目录)" in content
    assert 'id="uploadProgressContainer"' in content
    assert 'id="uploadProgressBar"' in content
    assert 'id="uploadStatusText"' in content


def test_z7_duplicate_upload_bypass_and_no_redundant_write(client):
    """Z7: 测试上传同名且大小相同的文件时，直接复用已有片源，杜绝冗余落盘生成 _1 副本"""
    ocr_input = PROJECT_ROOT / "ocr_input"
    ocr_input.mkdir(parents=True, exist_ok=True)

    test_filename = "z7_dedup_test.mp4"
    target_original = ocr_input / test_filename
    target_duplicate = ocr_input / "z7_dedup_test_1.mp4"

    # 清理残留
    target_original.unlink(missing_ok=True)
    target_duplicate.unlink(missing_ok=True)

    try:
        content = b"fixed content for z7 deduplication test 12345678"
        
        # 1. 首次上传写入文件
        resp1 = client.post(
            "/api/upload",
            files={"file": (test_filename, io.BytesIO(content), "video/mp4")}
        )
        assert resp1.status_code == 200
        res1 = resp1.json()
        assert res1["code"] == 0
        assert res1.get("existed") is not True
        assert target_original.exists()
        assert not target_duplicate.exists()

        # 2. 第二次上传同名同大小文件 -> 命中 Z7 判重机制，免传复用
        resp2 = client.post(
            "/api/upload",
            files={"file": (test_filename, io.BytesIO(content), "video/mp4")}
        )
        assert resp2.status_code == 200
        res2 = resp2.json()
        assert res2["code"] == 0
        assert res2.get("existed") is True
        assert "该片源已存在，已为你选中" in res2["message"]
        assert res2["data"]["rel_path"] == f"ocr_input/{test_filename}"
        # 强断言: 严禁产生 _1.mp4 冗余文件
        assert not target_duplicate.exists(), "命中判重时不应产生 _1.mp4 副本"

        # 3. 校验 /api/server/input_files 返回包含 size_bytes 字段，供前端毫秒级预检
        list_resp = client.get("/api/server/input_files")
        assert list_resp.status_code == 200
        items = list_resp.json()["data"]
        matched_item = next((item for item in items if item["name"] == test_filename), None)
        assert matched_item is not None
        assert matched_item["size_bytes"] == len(content)
        assert matched_item["folder"] == "ocr_input"

        # 4. 上传同名但大小不同的文件 -> 不命中 Z7，正常生成 _1.mp4 防覆盖
        diff_content = b"different content length"
        resp3 = client.post(
            "/api/upload",
            files={"file": (test_filename, io.BytesIO(diff_content), "video/mp4")}
        )
        assert resp3.status_code == 200
        res3 = resp3.json()
        assert res3["code"] == 0
        assert res3.get("existed") is not True
        assert res3["data"]["filename"] == "z7_dedup_test_1.mp4"
        assert target_duplicate.exists()
        assert target_duplicate.read_bytes() == diff_content

    finally:
        target_original.unlink(missing_ok=True)
        target_duplicate.unlink(missing_ok=True)
