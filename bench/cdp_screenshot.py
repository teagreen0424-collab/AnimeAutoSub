import json
import base64
import asyncio
import subprocess
import urllib.request
import websockets
from pathlib import Path

EDGE_EXE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
TEMP_PROFILE = r"C:\Users\10932\AppData\Local\Temp\edge_temp_cdp"

async def capture_cdp_screenshot(url: str, output_path: str, wait_after_load_s: float = 2.0, width: int = 1400, height: int = 900):
    port = 9222
    cmd = [
        EDGE_EXE,
        "--headless=new",
        "--disable-gpu",
        f"--remote-debugging-port={port}",
        f"--user-data-dir={TEMP_PROFILE}",
        f"--window-size={width},{height}",
        "about:blank"
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        # 等待 CDP 端口就绪
        for _ in range(20):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1) as resp:
                    if resp.status == 200:
                        break
            except Exception:
                await asyncio.sleep(0.2)
        else:
            raise RuntimeError("CDP 端口未能及时响应")

        # 获取可用页面 target
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list") as resp:
            targets = json.loads(resp.read().decode())
        ws_url = targets[0]["webSocketDebuggerUrl"]

        async with websockets.connect(ws_url) as ws:
            # 开启 Page 域
            await ws.send(json.dumps({"id": 1, "method": "Page.enable"}))
            await ws.recv()

            # 导航到目标 URL
            await ws.send(json.dumps({"id": 2, "method": "Page.navigate", "params": {"url": url}}))
            await ws.recv()

            # 等待渲染和 SSE 事件到达
            await asyncio.sleep(wait_after_load_s)

            # 捕获截图
            await ws.send(json.dumps({"id": 3, "method": "Page.captureScreenshot", "params": {"format": "png"}}))
            resp = json.loads(await ws.recv())
            # 可能有事件推过来，循环读取到 id == 3
            while resp.get("id") != 3:
                resp = json.loads(await ws.recv())

            img_bytes = base64.b64decode(resp["result"]["data"])
            Path(output_path).write_bytes(img_bytes)
            print(f"[CDP] 截图成功写入: {output_path} ({len(img_bytes):,} 字节)")
    finally:
        proc.terminate()
        proc.wait()

if __name__ == "__main__":
    asyncio.run(capture_cdp_screenshot("http://127.0.0.1:8000/#task=work_20261101_215333_simulated_1080p_fansub", "bench/test_cdp.png", wait_after_load_s=1.5))
