"""
AnimeAutoSub E1-E4 专项截图复核与自动化几何断言脚本
(bench/capture_e1_e4_screenshots.py)

验收要求:
1. 1280 与 1920 两个宽度下各截一张任务列表
2. 没有任何按钮溢出卡片 (通过 getBoundingClientRect() 数学断言)
3. 每张卡片的按钮组一致 (四颗按钮: 下载成片 / 编辑字幕 / 恢复 / 重渲染，不可用置灰 disabled)
4. 列表中不出现名为 work_tasks 的任务
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
TEMP_PROFILE = r"C:\Users\10932\AppData\Local\Temp\edge_temp_cdp_e1_e4"
ARTIFACT_DIR = Path(r"C:\Users\10932\.gemini\antigravity\brain\c1431835-b8d6-4e48-8544-6afb74257c21")


async def capture_at_resolution(width, height, output_filename):
    port = 9227
    cmd = [
        EDGE_EXE,
        "--headless=new",
        "--disable-gpu",
        "--disable-extensions",
        "--no-first-run",
        "--no-default-browser-check",
        f"--remote-debugging-port={port}",
        f"--user-data-dir={TEMP_PROFILE}_{width}",
        f"--window-size={width},{height}",
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

            # 导航至首页任务列表
            print(f"正在以分辨率 {width}x{height} 打开首页...")
            await send_and_wait(3, "Page.navigate", {"url": f"{BASE_URL}/#"})
            await asyncio.sleep(2.0)

            # 等待任务列表渲染
            js_verify = """
            (async () => {
                for (let i = 0; i < 30; i++) {
                    const cards = document.querySelectorAll('.task-card');
                    if (cards.length > 0) break;
                    await new Promise(r => setTimeout(r, 100));
                }
                const cards = document.querySelectorAll('.task-card');
                if (cards.length === 0) return { error: "未找到任何任务卡片" };

                const results = {
                    totalCards: cards.length,
                    hasWorkTasks: false,
                    overflowIssues: [],
                    buttonSets: []
                };

                cards.forEach((card, idx) => {
                    const cardRect = card.getBoundingClientRect();
                    const titleEl = card.querySelector('.task-card-title');
                    const idEl = card.querySelector('.task-card-id');
                    const titleText = titleEl ? titleEl.textContent.trim() : '';
                    const idText = idEl ? idEl.textContent.trim() : '';

                    if (titleText === 'work_tasks' || idText === 'work_tasks') {
                        results.hasWorkTasks = true;
                    }

                    // 检查操作行按钮
                    const actionBtns = Array.from(card.querySelectorAll('.task-card-actions button'));
                    const btnTexts = actionBtns.map(b => b.textContent.trim());
                    results.buttonSets.push(btnTexts);

                    // 几何溢出检测: 每一个按钮必须严格完全落在 cardRect 边框之内
                    actionBtns.forEach(btn => {
                        const btnRect = btn.getBoundingClientRect();
                        // 允许 1px 浮点舍入容差
                        if (btnRect.left < cardRect.left - 1 || btnRect.right > cardRect.right + 1) {
                            results.overflowIssues.push({
                                cardIdx: idx,
                                title: titleText,
                                btn: btn.textContent.trim(),
                                btnRight: btnRect.right,
                                cardRight: cardRect.right
                            });
                        }
                    });
                });

                return results;
            })()
            """
            eval_res = await send_and_wait(4, "Runtime.evaluate", {"expression": js_verify, "awaitPromise": True, "returnByValue": True})
            val = eval_res.get("result", {}).get("result", {}).get("value", {})
            print(f"[{width}px] 检查结果:")
            print(f"   卡片总数: {val.get('totalCards')}")
            print(f"   是否存在 work_tasks: {val.get('hasWorkTasks')}")
            print(f"   溢出卡片数量: {len(val.get('overflowIssues', []))}")
            if val.get("overflowIssues"):
                print(f"   ⚠️ 溢出详情: {val['overflowIssues']}")

            # 严格断言
            assert val.get("totalCards", 0) > 0, "卡片总数应大于 0"
            assert not val.get("hasWorkTasks"), "列表中仍存在 work_tasks 根目录任务!"
            assert len(val.get("overflowIssues", [])) == 0, f"存在 {len(val['overflowIssues'])} 处按钮溢出卡片!"
            # 验证每张卡片的按钮文字都必须为 ["下载成片", "编辑字幕", "恢复", "重渲染"]
            for b_set in val.get("buttonSets", []):
                assert b_set == ["下载成片", "编辑字幕", "恢复", "重渲染"], f"按钮组不符合标准: {b_set}"
            print(f"   ✅ 全部几何与结构契约通过!")

            # 截图保存
            shot = await send_and_wait(5, "Page.captureScreenshot", {"format": "png"})
            shot_bytes = base64.b64decode(shot["result"]["data"])
            out_path = ARTIFACT_DIR / output_filename
            out_path.write_bytes(shot_bytes)
            print(f"   ✅ 截图已保存至: {out_path.name} ({len(shot_bytes)} bytes)")
            return out_path
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=2)
        except Exception:
            pass


async def main():
    print("="*60)
    print("【AnimeAutoSub E1-E4 专项截图与几何断言】")
    print("="*60)

    # 1. 1280 宽度截图
    await capture_at_resolution(1280, 850, "webui_p4_tasklist_1280.png")

    # 2. 1920 宽度截图
    await capture_at_resolution(1920, 1080, "webui_p4_tasklist_1920.png")

    print("\n" + "="*60)
    print("🎉 E1-E4 双分辨率截图与几何断言全部顺利完成!")
    print("="*60)

if __name__ == "__main__":
    asyncio.run(main())
