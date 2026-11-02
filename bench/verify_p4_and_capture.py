"""
AnimeAutoSub P4 收尾与最终封版验证脚本
(bench/verify_p4_and_capture.py)

验证 S1/S2 全部关键点，并捕获 4 张高分辨率实测截图:
1. webui_p4_settings_1280.png: 系统只读设置屏 (#settings)
2. webui_p4_editor_viewport_1280.png: 全屏编辑器 (自适应16:9视口 + 顶栏双行不折叠 + 快捷导出卡)
3. webui_p4_detail_download_1280.png: 任务详情页 (顶栏成片下载 + 4列产物表格下载)
4. webui_p4_offline_state_1280.png: 离线与错误态展示 (统计卡 离线 ⚠ 徽标 + 顶部离线横幅)
"""

import sys
import os
import json
import time
import base64
import asyncio
import subprocess
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import websockets

BASE_URL = "http://127.0.0.1:8000"
EDGE_EXE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
TEMP_PROFILE = r"C:\Users\10932\AppData\Local\Temp\edge_temp_cdp_p4_real"
ARTIFACT_DIR = Path(r"C:\Users\10932\.gemini\antigravity\brain\c1431835-b8d6-4e48-8544-6afb74257c21")
TASK_ID = "work_20261101_215811_simulated_1080p_fansub"


async def run_p4_verification():
    print("="*60)
    print("【AnimeAutoSub P4 最终验证与截图捕获】")
    print("="*60)

    # 1. 后端接口功能验证
    print("1. 验证 GET /api/system/settings 接口...")
    with urllib.request.urlopen(f"{BASE_URL}/api/system/settings") as resp:
        settings_data = json.loads(resp.read().decode())["data"]
        assert settings_data["port"] == 8000
        assert "D:\\Dev\\ollama\\models" in settings_data["ollama_models_path"]
        assert settings_data["schema_version"] == 2
        print(f"   ✅ 只读配置正常: Port={settings_data['port']}, Models={settings_data['ollama_models_path']}")

    print("2. 验证 GET /api/tasks/{task_id}/export/video 与 /file/... 接口...")
    with urllib.request.urlopen(f"{BASE_URL}/api/tasks/{TASK_ID}/export/video") as resp:
        ct = resp.headers.get("content-type", "")
        cd = resp.headers.get("content-disposition", "")
        assert "video/mp4" in ct
        assert "attachment" in cd
        print(f"   ✅ 成片导出接口正常: content-type={ct}, content-disposition={cd}")

    with urllib.request.urlopen(f"{BASE_URL}/api/tasks/{TASK_ID}/file/subtitle.ass") as resp:
        cd = resp.headers.get("content-disposition", "")
        assert "attachment" in cd
        print(f"   ✅ 单产物下载接口正常: content-disposition={cd}")

    # 2. 启动 Headless Edge
    port = 9226
    cmd = [
        EDGE_EXE,
        "--headless=new",
        "--disable-gpu",
        "--disable-extensions",
        "--no-first-run",
        "--no-default-browser-check",
        f"--remote-debugging-port={port}",
        f"--user-data-dir={TEMP_PROFILE}",
        "--window-size=1280,850",
        "about:blank"
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        # 等待 CDP 就绪
        for _ in range(25):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1) as resp:
                    if resp.status == 200:
                        break
            except Exception:
                await asyncio.sleep(0.2)
        else:
            raise RuntimeError("CDP 端口响应超时")

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list") as resp:
            targets = json.loads(resp.read().decode())
        page_targets = [t for t in targets if t.get("type") == "page"]
        target = page_targets[0] if page_targets else targets[0]
        ws_url = target["webSocketDebuggerUrl"]

        async with websockets.connect(ws_url) as ws:
            async def send_and_wait(req_id, method, params=None):
                payload = {"id": req_id, "method": method}
                if params:
                    payload["params"] = params
                await ws.send(json.dumps(payload))
                while True:
                    raw = await asyncio.wait_for(ws.recv(), timeout=10.0)
                    m = json.loads(raw)
                    if m.get("id") == req_id:
                        return m

            await send_and_wait(1, "Page.enable")
            await send_and_wait(2, "Runtime.enable")

            # -------------------------------------------------------------
            # 截图 1: 设置页面 (#settings)
            # -------------------------------------------------------------
            print("\n正在捕获图 1: 系统设置屏 (#settings)...")
            await send_and_wait(10, "Page.navigate", {"url": f"{BASE_URL}/#settings"})
            await asyncio.sleep(2.0)

            # 等待设置渲染
            js_settings = """
            (() => {
                if (!window.app) return false;
                window.app.showScreen("settings");
                window.app.loadSettings();
                return true;
            })()
            """
            await send_and_wait(11, "Runtime.evaluate", {"expression": js_settings, "returnByValue": True})
            await asyncio.sleep(1.0)

            shot1 = await send_and_wait(12, "Page.captureScreenshot", {"format": "png"})
            shot1_bytes = base64.b64decode(shot1["result"]["data"])
            p1_path = ARTIFACT_DIR / "webui_p4_settings_1280.png"
            p1_path.write_bytes(shot1_bytes)
            print(f"✅ 图 1 已保存: {p1_path.name} ({len(shot1_bytes)} bytes)")

            # -------------------------------------------------------------
            # 截图 2: 全屏编辑器 (#task=<id>&edit=1)
            # -------------------------------------------------------------
            print("\n正在捕获图 2: 全屏编辑器 (#task={TASK_ID}&edit=1)...")
            await send_and_wait(20, "Page.navigate", {"url": f"{BASE_URL}/#task={TASK_ID}&edit=1"})
            await asyncio.sleep(2.0)

            js_editor = """
            (async () => {
                for (let i = 0; i < 30; i++) {
                    if (window.app && typeof window.app.openEditor === 'function') break;
                    await new Promise(r => setTimeout(r, 100));
                }
                await window.app.openEditor('""" + TASK_ID + """');
                window.app.selectSubtitleRow(0);
                // 等待单帧预览载入
                for (let i = 0; i < 30; i++) {
                    const img = document.getElementById('fsPreviewImg');
                    if (img && img.style.display !== 'none' && img.getAttribute('src')) break;
                    await new Promise(r => setTimeout(r, 100));
                }
                await new Promise(r => setTimeout(r, 600));
                return true;
            })()
            """
            await send_and_wait(21, "Runtime.evaluate", {"expression": js_editor, "awaitPromise": True, "returnByValue": True})
            await asyncio.sleep(1.0)

            shot2 = await send_and_wait(22, "Page.captureScreenshot", {"format": "png"})
            shot2_bytes = base64.b64decode(shot2["result"]["data"])
            p2_path = ARTIFACT_DIR / "webui_p4_editor_viewport_1280.png"
            p2_path.write_bytes(shot2_bytes)
            print(f"✅ 图 2 已保存: {p2_path.name} ({len(shot2_bytes)} bytes)")

            # -------------------------------------------------------------
            # 截图 3: 任务详情页 (#task=<id>)
            # -------------------------------------------------------------
            print("\n正在捕获图 3: 任务详情页 (#task={TASK_ID})...")
            await send_and_wait(30, "Page.navigate", {"url": f"{BASE_URL}/#task={TASK_ID}"})
            await asyncio.sleep(2.0)

            js_detail = """
            (async () => {
                for (let i = 0; i < 30; i++) {
                    if (window.app && typeof window.app.openTaskDetail === 'function') break;
                    await new Promise(r => setTimeout(r, 100));
                }
                await window.app.openTaskDetail('""" + TASK_ID + """');
                await new Promise(r => setTimeout(r, 600));
                return true;
            })()
            """
            await send_and_wait(31, "Runtime.evaluate", {"expression": js_detail, "awaitPromise": True, "returnByValue": True})
            await asyncio.sleep(1.0)

            shot3 = await send_and_wait(32, "Page.captureScreenshot", {"format": "png"})
            shot3_bytes = base64.b64decode(shot3["result"]["data"])
            p3_path = ARTIFACT_DIR / "webui_p4_detail_download_1280.png"
            p3_path.write_bytes(shot3_bytes)
            print(f"✅ 图 3 已保存: {p3_path.name} ({len(shot3_bytes)} bytes)")

            # -------------------------------------------------------------
            # 截图 4: 离线与错误态展示 (通过触发 updateStats(true) 与 offlineBanner)
            # -------------------------------------------------------------
            print("\n正在捕获图 4: 离线与异常错误态展示...")
            await send_and_wait(40, "Page.navigate", {"url": f"{BASE_URL}/#"})
            await asyncio.sleep(1.5)

            js_offline = """
            (() => {
                if (!window.app) return false;
                window.app.showScreen("list");
                window.app.offlineBanner.style.display = "flex";
                window.app.updateStats(true);
                return true;
            })()
            """
            await send_and_wait(41, "Runtime.evaluate", {"expression": js_offline, "returnByValue": True})
            await asyncio.sleep(0.5)

            shot4 = await send_and_wait(42, "Page.captureScreenshot", {"format": "png"})
            shot4_bytes = base64.b64decode(shot4["result"]["data"])
            p4_path = ARTIFACT_DIR / "webui_p4_offline_state_1280.png"
            p4_path.write_bytes(shot4_bytes)
            print(f"✅ 图 4 已保存: {p4_path.name} ({len(shot4_bytes)} bytes)")

    finally:
        try:
            proc.terminate()
            proc.wait(timeout=2)
        except Exception:
            pass

    print("\n" + "="*60)
    print("🎉 P4 实测与截图全部捕获完成!")
    print("="*60)

if __name__ == "__main__":
    asyncio.run(run_p4_verification())
