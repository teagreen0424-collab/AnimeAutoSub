"""
AnimeAutoSub 自动化浏览器 CDP 截图与 UI 行为断言验证脚本 (bench/capture_engine_verification_screenshots.py)
针对 Section 7.1 验证要求:
  1. 新建任务弹窗与「翻译引擎」下拉框 (包含本地 Sakura 与云端 DeepSeek)
  2. 选云端引擎时动态展现费用预估行
  3. 选本地 Sakura 时费用行自动隐藏
  4. 系统设置页中多引擎状态表，包含脱敏密钥，且 HTML 源码中绝不包含明文密钥
  5. 任务详情页展现引擎徽章、Token 用量与费用
"""

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

BASE_URL = "http://127.0.0.1:8099"
EDGE_EXE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
TEMP_PROFILE = r"C:\Users\10932\AppData\Local\Temp\edge_temp_cdp_engine_verif"
ARTIFACT_DIR = Path(r"C:\Users\10932\.gemini\antigravity\brain\c1431835-b8d6-4e48-8544-6afb74257c21")


async def run_cdp_verifications():
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
        "--window-size=1400,900",
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
            msg_id = 0

            async def send_and_wait(method, params=None):
                nonlocal msg_id
                msg_id += 1
                req_id = msg_id
                payload = {"id": req_id, "method": method}
                if params:
                    payload["params"] = params
                await ws.send(json.dumps(payload))
                while True:
                    raw = await asyncio.wait_for(ws.recv(), timeout=10.0)
                    m = json.loads(raw)
                    if m.get("id") == req_id:
                        return m

            async def eval_js(expression):
                res = await send_and_wait("Runtime.evaluate", {
                    "expression": expression,
                    "returnByValue": True,
                    "awaitPromise": True
                })
                result = res.get("result", {})
                if "exceptionDetails" in result:
                    raise RuntimeError(f"JS 执行异常: {result['exceptionDetails']}")
                return result.get("result", {}).get("value")

            async def capture_screenshot(output_path: Path):
                res = await send_and_wait("Page.captureScreenshot", {"format": "png"})
                img_data = res["result"]["data"]
                output_path.write_bytes(base64.b64decode(img_data))
                print(f"[CDP] 截图成功写入: {output_path.name} ({len(img_data):,} 字节)")

            await send_and_wait("Page.enable")
            await send_and_wait("Runtime.enable")

            # 1. 导航至 WebUI 首页
            print("[CDP] 导航至 WebUI 首页...")
            await send_and_wait("Page.navigate", {"url": f"{BASE_URL}/#"})
            await asyncio.sleep(2.5)

            # 2. 点击「新建任务」打开弹窗
            print("[CDP] 步骤 1 & 2: 打开新建任务弹窗...")
            await eval_js("document.getElementById('btnNewTask').click()")
            await asyncio.sleep(0.5)

            # 检查 selectEngine 选项内容
            engine_options = await eval_js("""
                (() => {
                    const sel = document.getElementById('selectEngine');
                    return Array.from(sel.options).map(o => ({ value: o.value, text: o.text }));
                })()
            """)
            print(f"[CDP] 下拉选项: {engine_options}")
            assert any("sakura-14b" in o["value"] for o in engine_options), "缺少 sakura-14b"
            assert any("deepseek-chat" in o["value"] for o in engine_options), "缺少 deepseek-chat"

            # 截图 1: 新建任务弹窗
            await capture_screenshot(ARTIFACT_DIR / "webui_engine_modal_dropdown.png")

            # 3. 选云端引擎 DeepSeek
            print("[CDP] 步骤 3: 选云端引擎 deepseek-chat，确认预估费用行显示...")
            cost_visible_deepseek = await eval_js("""
                (() => {
                    const sel = document.getElementById('selectEngine');
                    sel.value = 'deepseek-chat';
                    sel.dispatchEvent(new Event('change'));
                    const row = document.getElementById('engineCostEstimateRow');
                    return row && row.style.display !== 'none';
                })()
            """)
            print(f"[CDP] 选 DeepSeek 费用行可见性: {cost_visible_deepseek}")
            assert cost_visible_deepseek is True, "选择云端引擎后未展现预估费用行！"
            await capture_screenshot(ARTIFACT_DIR / "webui_engine_cost_estimate_visible.png")

            # 4. 选本地引擎 Sakura-14B
            print("[CDP] 步骤 4: 选本地引擎 sakura-14b，确认预估费用行隐藏...")
            cost_hidden_sakura = await eval_js("""
                (() => {
                    const sel = document.getElementById('selectEngine');
                    sel.value = 'sakura-14b';
                    sel.dispatchEvent(new Event('change'));
                    const row = document.getElementById('engineCostEstimateRow');
                    return row && row.style.display === 'none';
                })()
            """)
            print(f"[CDP] 选 Sakura 费用行隐藏: {cost_hidden_sakura}")
            assert cost_hidden_sakura is True, "选择本地引擎后预估费用行未隐藏！"
            await capture_screenshot(ARTIFACT_DIR / "webui_engine_cost_estimate_hidden.png")

            # 关闭弹窗
            await eval_js("document.getElementById('btnCancelModal').click()")
            await asyncio.sleep(0.5)

            # 5. 进入设置页面
            print("[CDP] 步骤 5: 打开系统设置页，核验多引擎列表与脱敏密钥...")
            await eval_js("document.getElementById('btnSettings').click()")
            await asyncio.sleep(1.0)

            settings_table_info = await eval_js("""
                (() => {
                    const tbody = document.getElementById('settingsEnginesTableBody');
                    const rows = Array.from(tbody.querySelectorAll('tr')).map(tr => {
                        return Array.from(tr.querySelectorAll('td')).map(td => td.innerText.trim());
                    });
                    const fullHtml = document.documentElement.outerHTML;
                    return {
                        rows: rows,
                        hasSecretPlaintext: fullHtml.includes('sk-mock-deepseek-key-9876543210')
                    };
                })()
            """)
            print(f"[CDP] 设置页引擎表格: {settings_table_info['rows']}")
            assert settings_table_info["hasSecretPlaintext"] is False, "严重安全漏洞: 设置页源码中发现了明文密钥！"
            await capture_screenshot(ARTIFACT_DIR / "webui_engine_settings_masked_keys.png")

            # 6. 进入云端任务详情页 (展示引擎徽章、Token 用量与费用)
            cloud_task_id = "work_20261104_185858_test_3min"
            print(f"[CDP] 步骤 6: 打开云端任务详情页 (#{cloud_task_id})，核验引擎徽章与用量指标...")
            await send_and_wait("Page.navigate", {"url": f"{BASE_URL}/#task={cloud_task_id}"})
            await asyncio.sleep(2.0)

            detail_info = await eval_js("""
                (() => {
                    const tags = Array.from(document.querySelectorAll('#detailTags .tag-badge')).map(t => t.innerText.trim());
                    const title = document.getElementById('detailTitle').innerText.trim();
                    const status = document.getElementById('detailStatusPill').innerText.trim();
                    return { tags, title, status };
                })()
            """)
            print(f"[CDP] 详情页状态: {detail_info}")
            assert any("deepseek" in t.lower() for t in detail_info["tags"]), f"未在详情页标签中发现 deepseek 徽章: {detail_info['tags']}"
            assert any("token" in t.lower() for t in detail_info["tags"]), f"未在详情页标签中发现 Token 用量: {detail_info['tags']}"
            assert any("￥" in t or "费用" in t for t in detail_info["tags"]), f"未在详情页标签中发现费用信息: {detail_info['tags']}"
            await capture_screenshot(ARTIFACT_DIR / "webui_engine_task_detail_badges.png")

            print("[CDP] 全部 5 张关键验证截图均已成功生成并通过断言！")
    finally:
        proc.terminate()
        proc.wait()


if __name__ == "__main__":
    asyncio.run(run_cdp_verifications())
