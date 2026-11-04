import sys
import json
import base64
import asyncio
import subprocess
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import websockets

PORT = 8097
BASE_URL = f"http://127.0.0.1:{PORT}"
EDGE_EXE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
TEMP_PROFILE = r"C:\Users\10932\AppData\Local\Temp\edge_temp_cdp_cyber_verif"
ARTIFACT_DIR = Path(r"C:\Users\10932\.gemini\antigravity\brain\c1431835-b8d6-4e48-8544-6afb74257c21")


async def run_cyber_captures():
    uvicorn_cmd = [
        str(PROJECT_ROOT / "venv" / "Scripts" / "python.exe"),
        "-m", "uvicorn", "web.app:app",
        "--host", "127.0.0.1",
        "--port", str(PORT),
        "--log-level", "warning"
    ]
    srv_proc = subprocess.Popen(uvicorn_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(40):
            try:
                with urllib.request.urlopen(f"{BASE_URL}/api/tasks", timeout=1) as resp:
                    if resp.status == 200:
                        break
            except Exception:
                await asyncio.sleep(0.2)
        else:
            raise RuntimeError(f"WebUI 服务未能在 {PORT} 端口启动")

        print("WebUI server is ready on port", PORT)

        cdp_port = 9230
        edge_cmd = [
            EDGE_EXE,
            "--headless=new",
            "--disable-gpu",
            "--disable-extensions",
            "--no-first-run",
            "--no-default-browser-check",
            f"--remote-debugging-port={cdp_port}",
            f"--user-data-dir={TEMP_PROFILE}",
            "--window-size=1440,920",
            "about:blank"
        ]
        edge_proc = subprocess.Popen(edge_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for _ in range(30):
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{cdp_port}/json/version", timeout=1) as resp:
                        if resp.status == 200:
                            break
                except Exception:
                    await asyncio.sleep(0.2)
            else:
                raise RuntimeError(f"CDP 端口 {cdp_port} 响应超时")

            with urllib.request.urlopen(f"http://127.0.0.1:{cdp_port}/json/list") as resp:
                targets = json.loads(resp.read().decode())
            page_targets = [t for t in targets if t.get("type") == "page"]
            target = page_targets[0] if page_targets else targets[0]
            ws_url = target["webSocketDebuggerUrl"]

            async with websockets.connect(ws_url, max_size=20 * 1024 * 1024) as ws:
                msg_id = 0

                async def send_cmd(method, params=None):
                    nonlocal msg_id
                    msg_id += 1
                    payload = {"id": msg_id, "method": method}
                    if params:
                        payload["params"] = params
                    await ws.send(json.dumps(payload))
                    while True:
                        res = json.loads(await ws.recv())
                        if res.get("id") == msg_id:
                            return res.get("result", {})

                await send_cmd("Page.enable")
                await send_cmd("Runtime.enable")

                print("Navigating to", f"{BASE_URL}/?no_sse=1")
                await send_cmd("Page.navigate", {"url": f"{BASE_URL}/?no_sse=1"})

                # 等待任务卡片渲染完毕
                for _ in range(30):
                    eval_res = await send_cmd("Runtime.evaluate", {
                        "expression": "document.querySelectorAll('.task-card').length"
                    })
                    count = eval_res.get("result", {}).get("value", 0)
                    if count > 0:
                        print(f"Found {count} task cards rendered on screen")
                        break
                    await asyncio.sleep(0.3)

                # 模拟鼠标移动以激活卡片全息探照高光与神经网络粒子
                await send_cmd("Runtime.evaluate", {
                    "expression": """
                    const card = document.querySelector('.task-card');
                    if (card) {
                      const evt = new MouseEvent('mousemove', {
                        clientX: 250,
                        clientY: 280,
                        bubbles: true
                      });
                      card.dispatchEvent(evt);
                    }
                    """
                })

                await asyncio.sleep(1.2)

                async def capture_screenshot(path: Path):
                    shot = await send_cmd("Page.captureScreenshot", {"format": "png"})
                    data = base64.b64decode(shot["data"])
                    path.write_bytes(data)
                    print(f"Captured: {path.name} ({len(data)} bytes)")

                # 截图 1: 赛博朋克极光工作台主页
                await capture_screenshot(ARTIFACT_DIR / "webui_cyberpunk_task_list.png")

                # 截图 2: 新建任务弹窗 (全息拟态毛玻璃与荧光表单)
                await send_cmd("Runtime.evaluate", {
                    "expression": "document.getElementById('btnNewTask').click()"
                })
                await asyncio.sleep(1.0)
                await capture_screenshot(ARTIFACT_DIR / "webui_cyberpunk_new_task_modal.png")

                # 关闭弹窗
                await send_cmd("Runtime.evaluate", {
                    "expression": "document.getElementById('modalCloseBtn').click()"
                })
                await asyncio.sleep(0.5)

                # 截图 3: 任务详情页 (环绕光晕播放器、能量管道状态追踪与 CRT 终端日志)
                await send_cmd("Runtime.evaluate", {
                    "expression": "document.querySelector('.task-card').click()"
                })
                await asyncio.sleep(1.5)
                await capture_screenshot(ARTIFACT_DIR / "webui_cyberpunk_task_detail.png")

                print("All Cyberpunk UI screenshots captured successfully!")

        finally:
            edge_proc.terminate()
            try:
                edge_proc.wait(timeout=3)
            except Exception:
                edge_proc.kill()
    finally:
        srv_proc.terminate()
        try:
            srv_proc.wait(timeout=3)
        except Exception:
            srv_proc.kill()


if __name__ == "__main__":
    asyncio.run(run_cyber_captures())
