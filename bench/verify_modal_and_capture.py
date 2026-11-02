"""
Verify X1-X3 modal controls and capture screenshot
(bench/verify_modal_and_capture.py)
"""
import sys
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
TEMP_PROFILE = r"C:\Users\10932\AppData\Local\Temp\edge_temp_cdp_modal"
ARTIFACT_DIR = Path(r"C:\Users\10932\.gemini\antigravity\brain\c1431835-b8d6-4e48-8544-6afb74257c21")


async def main():
    port = 9228
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
        for _ in range(30):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1) as resp:
                    if resp.status == 200:
                        break
            except Exception:
                await asyncio.sleep(0.2)
        else:
            raise RuntimeError(f"CDP 端口 {port} 响应超时")

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

            # 打开页面并展开新建任务弹窗及高级选项
            print("正在打开首页并展开新建任务弹窗...")
            await send_and_wait(3, "Page.navigate", {"url": f"{BASE_URL}/#"})
            await asyncio.sleep(1.5)

            js_open_modal = """
            (async () => {
                window.app.openNewTaskModal();
                const details = document.querySelector('.form-advanced-details');
                if (details) details.open = true;
                await new Promise(r => setTimeout(r, 400));

                const fps = document.getElementById('inputFps');
                const diff = document.getElementById('inputDiff');
                const labels = Array.from(document.querySelectorAll('.advanced-body .form-label')).map(l => l.textContent.trim());
                const inputs = Array.from(document.querySelectorAll('.advanced-body input')).map(i => ({
                    id: i.id || null,
                    value: i.value,
                    disabled: i.disabled
                }));

                return {
                    fpsDisabled: fps ? fps.disabled : false,
                    fpsVal: fps ? fps.value : null,
                    diffDisabled: diff ? diff.disabled : false,
                    diffVal: diff ? diff.value : null,
                    labels: labels,
                    inputs: inputs
                };
            })()
            """
            eval_res = await send_and_wait(4, "Runtime.evaluate", {"expression": js_open_modal, "awaitPromise": True, "returnByValue": True})
            val = eval_res["result"]["result"]["value"]
            print("弹窗控件验证数据:", json.dumps(val, ensure_ascii=False, indent=2))

            # 校验断言
            assert val["fpsDisabled"] is True, "inputFps 必须为 disabled!"
            assert val["diffDisabled"] is True, "inputDiff 必须为 disabled!"
            assert "2.5%" in val["diffVal"], f"inputDiff 显示值必须为 2.5%, 实际为 {val['diffVal']}"
            assert any("sakura-14b-qwen2.5-v1.0-iq4_xs" in i["value"] for i in val["inputs"]), "翻译模型必须为 sakura-14b-qwen2.5-v1.0-iq4_xs"
            for label in val["labels"]:
                assert "固定值" in label, f"标签未标注'固定值': {label}"

            print("✅ X1 控件属性与显示值断言全部通过!")

            # 截图保存
            shot = await send_and_wait(5, "Page.captureScreenshot", {"format": "png"})
            shot_bytes = base64.b64decode(shot["result"]["data"])
            out_path = ARTIFACT_DIR / "webui_x1_modal_controls_1280.png"
            out_path.write_bytes(shot_bytes)
            print(f"✅ 截图已保存至: {out_path.name} ({len(shot_bytes)} bytes)")

    finally:
        try:
            proc.terminate()
            proc.wait(timeout=2)
        except Exception:
            pass

if __name__ == "__main__":
    asyncio.run(main())
