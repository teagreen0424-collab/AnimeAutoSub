"""
AnimeAutoSub 测试: Z9 重启停服在途任务保护与 interrupted 状态机复核 (tests/test_z9_z10_interrupted_and_shutdown.py)

验收要求:
  a) 重启/停服前查询 queue_manager 是否有 running 任务;
  b) 若有，控制台明确警告并等待 (或要求显式 --force);
  c) 被强制中断的任务，manifest 标记为 interrupted 而非 canceled，
     并在界面上显示「▶ 恢复」，允许一键续跑;
  d) 重启脚本 (启动WebUI.bat) 在检测到 running 任务时提示用户。
"""

import sys
import json
import subprocess
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from core.manifest import ManifestManager
from core.stage import Stage
from core.context import PipelineContext
from web.app import app, PROJECT_ROOT, check_remote_running_tasks
from web.task_manager import TaskManager
from web.queue_manager import queue_manager, QueueManager


@pytest.fixture
def client():
    return TestClient(app)


class MockStage(Stage):
    name = "mock_stage"
    requires_gpu = False
    produces = ["mock.txt"]

    def fingerprint(self, ctx):
        return "mock_fingerprint_123"

    def run(self, ctx, log, cancel_token):
        return True

    def verify(self, ctx):
        return True


def test_z9_manifest_record_interrupted_and_resume_clear(tmp_path):
    """Z9: 测试 manifest.record_interrupted 正确记录状态，且在续跑启动时被安全重置"""
    mgr = ManifestManager(tmp_path)
    stage = MockStage()

    # 1. 模拟阶段开始
    mgr.record_stage_start(stage)
    assert mgr._data["status"] == "running"
    assert mgr._data["stages"]["mock_stage"]["status"] == "running"

    # 2. 模拟外部中断触发
    mgr.record_interrupted(stage_name="mock_stage", reason="服务重启中断")
    assert mgr._data["status"] == "interrupted"
    assert mgr._data["is_interrupted"] is True
    assert mgr._data["interrupted_reason"] == "服务重启中断"
    assert mgr._data["stages"]["mock_stage"]["status"] == "interrupted"

    # 3. TaskManager 扫描推导该任务
    tm = TaskManager(PROJECT_ROOT)
    task_info = tm._parse_task_directory(tmp_path)
    assert task_info is not None
    assert task_info["status"] == "interrupted"
    assert task_info["can_resume"] is True
    assert "中断" in task_info["status_reason"]

    # 4. 模拟一键续跑启动阶段 -> 断言 interrupted 标记被清除，重回 running
    mgr.record_stage_start(stage)
    assert mgr._data["status"] == "running"
    assert "is_interrupted" not in mgr._data
    assert "interrupted_reason" not in mgr._data
    assert mgr._data["stages"]["mock_stage"]["status"] == "running"


def test_z9_derive_status_from_abrupt_process_kill(tmp_path):
    """Z9: 模拟进程被 kill -9 强杀场景（无优雅停机），TaskManager 依据 running 遗留阶段判定 interrupted"""
    # 构造残留在 running 状态的 manifest
    mf_path = tmp_path / "manifest.json"
    mf_data = {
        "version": 1,
        "schema_version": 2,
        "status": "running",
        "stages": {
            "ocr_extract": {"status": "running", "started_at": "2026-11-03T12:51:30"}
        }
    }
    mf_path.write_text(json.dumps(mf_data), encoding="utf-8")

    tm = TaskManager(PROJECT_ROOT)
    task_info = tm._parse_task_directory(tmp_path)
    assert task_info is not None
    assert task_info["status"] == "interrupted"
    assert task_info["can_resume"] is True
    assert "异常中断" in task_info["status_reason"] or "中断" in task_info["status_reason"]


def test_z9_system_running_check_api(client):
    """Z9: 测试 /api/system/running_check 接口能够精准报告在途/排队任务"""
    resp = client.get("/api/system/running_check")
    assert resp.status_code == 200
    res = resp.json()
    assert res["code"] == 0
    assert "has_running" in res["data"]
    assert "active_task" in res["data"]
    assert "pid" in res["data"]


def test_z9_interrupt_and_stop_protection(client):
    """Z9: 测试中断停机接口，有任务时必须要求 force=True"""
    with queue_manager._lock:
        # 伪造一个活跃任务
        orig_active = queue_manager.active_task_id
        queue_manager.active_task_id = "test_active_task_999"
        queue_manager.task_states["test_active_task_999"] = {
            "task_id": "test_active_task_999",
            "status": "running",
            "current_stage": "ocr_extract",
            "stage_pct": 1.5,
            "total_pct": 0.4
        }

    try:
        # 1. 未携带 force=true -> 必须 400 拦截
        resp_block = client.post("/api/system/interrupt_and_stop?force=false")
        assert resp_block.status_code == 400
        assert "正在执行" in resp_block.json()["detail"]

        # 2. 携带 force=true -> 成功中断并标记
        resp_force = client.post("/api/system/interrupt_and_stop?force=true")
        assert resp_force.status_code == 200
        assert resp_force.json()["code"] == 0
    finally:
        with queue_manager._lock:
            queue_manager.active_task_id = orig_active
            queue_manager.task_states.pop("test_active_task_999", None)


def test_z9_cli_check_running_argument():
    """Z9: 验证 python -m web.app --check-running 在离线或空闲端口时退出码为 0"""
    # 指定一个未监听的随机独立端口测试
    cmd = [sys.executable, "-m", "web.app", "--check-running", "--port", "59876"]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=5)
    assert proc.returncode == 0
    assert "[OK]" in proc.stdout


def test_z9_cli_check_running_detects_active_task_and_returns_code_2():
    """Z9: 验证 python -m web.app --check-running 在检测到在途任务时返回退出码 2 并输出任务详情"""
    from http.server import HTTPServer, BaseHTTPRequestHandler
    import threading

    class MockRunningHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/api/system/running_check":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                data = {
                    "code": 0,
                    "data": {
                        "has_running": True,
                        "active_task": {
                            "task_id": "work_20261103_125130_37215-1080p",
                            "current_stage": "ocr_extract",
                            "stage_pct": 1.5,
                            "total_pct": 0.4
                        },
                        "queue_length": 1,
                        "pid": 99999
                    }
                }
                self.wfile.write(json.dumps(data).encode("utf-8"))
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, format, *args):
            pass

    server = HTTPServer(("127.0.0.1", 59877), MockRunningHandler)
    t = threading.Thread(target=server.handle_request)
    t.start()

    try:
        cmd = [sys.executable, "-m", "web.app", "--check-running", "--port", "59877"]
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=5)
        assert proc.returncode == 2
        assert "[WARN]" in proc.stdout
        assert "work_20261103_125130_37215-1080p" in proc.stdout
        assert "ocr_extract" in proc.stdout
    finally:
        server.server_close()
        t.join(timeout=2)
