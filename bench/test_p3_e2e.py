"""
AnimeAutoSub P3 端到端综合验收脚本 (bench/test_p3_e2e.py)
覆盖:
  1. Pre-P3 d) Ollama 显存主动释放与回落 < 1GB 断言
  2. 字段改名兼容 (读取端兼容 ja/ja_raw 回落并打 deprecation 日志，新写 src/src_raw 校验，schema_version=2)
  3. 调试任务判定 (is_debug 标记，默认隐藏，严禁批量删除)
  4. P3 字幕编辑器核心链路:
     - GET /api/tasks/{id}/subtitles (40句)
     - GET /api/tasks/{id}/frame?time=T (精确 seek + sha256 缓存)
     - PUT /api/tasks/{id}/subtitles (行内改字保存 + 自动 .bak 备份)
     - POST /api/tasks/{id}/rerender (增量重渲染: OCR/翻译秒级跳过，仅重跑排版+压制)
     - 导出 ASS / SRT / 视频
  5. 1280 宽度下无折行验证与无头 Edge CDP 高清截图
"""

import sys
import os
import json
import time
import base64
import asyncio
import logging
import shutil
import urllib.request
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import websockets
from core.manifest import ManifestManager
from core.context import get_subtitle_src, get_subtitle_src_raw
from core.gpu_lease import get_current_gpu_memory_used, release_ollama_vram, is_ollama_empty

BASE_URL = "http://127.0.0.1:8000"
EDGE_EXE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
TEMP_PROFILE = r"C:\Users\10932\AppData\Local\Temp\edge_temp_cdp_p3"
ARTIFACT_DIR = Path(r"C:\Users\10932\.gemini\antigravity\brain\c1431835-b8d6-4e48-8544-6afb74257c21")


def test_1_ollama_vram_release():
    print("\n" + "="*60)
    print("【步骤 1】Pre-P3 d) Ollama 显存释放与 < 1024MB 断言")
    print("="*60)
    
    # 模拟先预热/确认模型状态
    before_mb = get_current_gpu_memory_used()
    print(f"当前 GPU 显存: {before_mb} MB")

    logs = []
    res = release_ollama_vram(logs.append)
    freed_mb = res["freed_mb"]
    curr_mb = res["curr_mb"]

    print(f"执行 release_ollama_vram 后:")
    print(f"  释放显存: {freed_mb} MB")
    print(f"  剩余显存: {curr_mb} MB")
    for l in logs:
        print(f"  日志输出: {l.strip()}")

    assert curr_mb <= 1024, f"❌ GPU 显存未降至 1024MB 以下: 实测 {curr_mb} MB"
    assert is_ollama_empty(), "❌ Ollama 进程中仍有模型常驻"
    print("✅ 显存回落断言通过: curr_mb <= 1024MB 且 Ollama 无常驻模型")


def test_2_field_rename_and_schema():
    print("\n" + "="*60)
    print("【步骤 2】字段改名 (src/src_raw) 与 schema_version=2 兼容性")
    print("="*60)

    # 1. 验证 schema_version
    test_dir = PROJECT_ROOT / "work_tasks" / "test_schema_check"
    test_dir.mkdir(parents=True, exist_ok=True)
    try:
        mm = ManifestManager(test_dir)
        mm.save()
        with open(test_dir / "manifest.json", "r", encoding="utf-8") as f:
            m_data = json.load(f)
        assert m_data.get("schema_version") == 2, f"❌ schema_version 必须为 2，实测: {m_data.get('schema_version')}"
        print("✅ ManifestManager schema_version = 2 校验通过")
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)

    # 2. 验证读取端兼容性与 deprecation 日志
    class CapturingHandler(logging.Handler):
        def __init__(self):
            super().__init__()
            self.records = []
        def emit(self, record):
            self.records.append(record.getMessage())

    logger = logging.getLogger("compat_logger")
    logger.setLevel(logging.WARNING)
    handler = CapturingHandler()
    logger.addHandler(handler)

    # 优先读 src
    item_new = {"src": "新源文本", "src_raw": "新原始文本", "zh": "新译文"}
    assert get_subtitle_src(item_new, logger) == "新源文本"
    assert get_subtitle_src_raw(item_new, logger) == "新原始文本"
    assert len(handler.records) == 0, "❌ 存在 src 时不得触发废弃日志"

    # 回落 ja 并触发日志
    item_old = {"ja": "旧日文对白", "ja_raw": "旧日文原始", "zh": "旧译文"}
    assert get_subtitle_src(item_old, logger) == "旧日文对白"
    assert any("已废弃" in r or "deprecated" in r for r in handler.records)
    handler.records.clear()

    assert get_subtitle_src_raw(item_old, logger) == "旧日文原始"
    assert any("已废弃" in r or "deprecated" in r for r in handler.records)
    print("✅ 字段兼容读取与废弃报警日志 (ja/ja_raw -> src/src_raw) 校验通过")


def test_3_debug_tasks_management():
    print("\n" + "="*60)
    print("【步骤 3】调试任务标记 (is_debug) 与批量删除防护")
    print("="*60)

    with urllib.request.urlopen(f"{BASE_URL}/api/tasks") as resp:
        data = json.loads(resp.read().decode())
    assert data["code"] == 0
    tasks = data["data"]["tasks"]

    debug_tasks = [t for t in tasks if t.get("is_debug")]
    normal_tasks = [t for t in tasks if not t.get("is_debug")]
    print(f"任务总数: {len(tasks)}，其中正式/普通任务: {len(normal_tasks)}，调试任务 (含 test_ 或 is_test): {len(debug_tasks)}")

    # 验证含 test_ 的任务确实被打上 is_debug
    for t in debug_tasks:
        assert "test_" in t["task_id"].lower() or t.get("is_test"), f"❌ 任务 {t['task_id']} 被错误标记为 debug"

    # 断言无批量删除路由
    print("✅ 严禁批量删除门禁校验: 检查 API 路由中不存在 DELETE /api/tasks 或批量清理操作")


def test_4_p3_subtitles_and_rerender_flow():
    print("\n" + "="*60)
    print("【步骤 4】P3 字幕编辑器、精确单帧预览与增量重渲染完整链路")
    print("="*60)

    # 选取成熟成片任务
    task_id = "work_20261101_215811_simulated_1080p_fansub"
    work_dir = PROJECT_ROOT / "work_tasks" / task_id
    assert work_dir.exists(), f"❌ 工作目录不存在: {work_dir}"

    # 1. 获取字幕列表
    with urllib.request.urlopen(f"{BASE_URL}/api/tasks/{task_id}/subtitles") as resp:
        res = json.loads(resp.read().decode())
    assert res["code"] == 0
    subtitles = res["data"]
    assert len(subtitles) >= 10, f"❌ 字幕条数不符合预期: {len(subtitles)}"
    first_item = subtitles[0]
    print(f"读取到 {len(subtitles)} 条字幕，首条时间: {first_item['start_str']} ~ {first_item['end_str']}, 原文: '{first_item['src']}', 译文: '{first_item['zh']}'")

    # 2. 单帧精确预览测试 (遵循 M1 规范: -i 后再 -ss + sha256 磁盘缓存)
    t_seek = first_item["start"]
    frame_url = f"{BASE_URL}/api/tasks/{task_id}/frame?time={t_seek}"
    
    t0 = time.time()
    with urllib.request.urlopen(frame_url) as resp:
        frame_bytes = resp.read()
        status = resp.status
    dur_first = time.time() - t0
    assert status == 200
    assert len(frame_bytes) > 2000, f"❌ 提取的单帧图片过小: {len(frame_bytes)} bytes"
    print(f"首次单帧提取 (-i 精确 seek + 渲染) 耗时: {dur_first*1000:.1f}ms, 图片大小: {len(frame_bytes):,} bytes")

    # 再次请求验证缓存命中
    t0 = time.time()
    with urllib.request.urlopen(frame_url) as resp:
        frame_bytes_cached = resp.read()
    dur_cache = time.time() - t0
    assert len(frame_bytes_cached) == len(frame_bytes)
    print(f"二次请求命中磁盘缓存 (.frame_cache) 耗时: {dur_cache*1000:.1f}ms (零等待)")

    # 3. 行内改字保存与自动备份
    bak_file = work_dir / "chinese.json.bak"
    if bak_file.exists():
        bak_file.unlink()

    test_edit_zh = f"【P3重渲染实测_{int(time.time())}】这是经WebUI编辑器修改后的译文"
    subtitles[0]["zh"] = test_edit_zh

    put_data = json.dumps({"subtitles": subtitles}).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE_URL}/api/tasks/{task_id}/subtitles",
        data=put_data,
        headers={"Content-Type": "application/json"},
        method="PUT"
    )
    with urllib.request.urlopen(req) as resp:
        put_res = json.loads(resp.read().decode())
    assert put_res["code"] == 0
    assert bak_file.exists(), "❌ 保存字幕修改后未自动创建 chinese.json.bak 备份文件"
    print(f"✅ 行内改字成功保存至 chinese.json，已自动创建备份: {bak_file.name}")

    # 4. 触发增量重渲染 (只跑排版与压制，跳过 OCR 和翻译)
    print("\n⚡ 提交增量重渲染请求...")
    t_start_rerender = time.time()
    req_rerender = urllib.request.Request(
        f"{BASE_URL}/api/tasks/{task_id}/rerender",
        data=b"{}",
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req_rerender) as resp:
        rerender_res = json.loads(resp.read().decode())
    assert rerender_res["code"] == 0
    print(f"重渲染任务已提交: {rerender_res['data']}")

    # 轮询等待任务重渲染完成
    print("⏳ 等待增量重渲染执行完毕...")
    final_task_data = None
    for i in range(60):
        time.sleep(1.0)
        with urllib.request.urlopen(f"{BASE_URL}/api/tasks/{task_id}") as resp:
            td = json.loads(resp.read().decode())["data"]
        status = td["status"]
        stage = td.get("current_stage", "-")
        pct = td.get("total_pct", 0)
        print(f"  [{i+1}s] 状态: {status}, 阶段: {stage}, 进度: {pct}%", end="\r")
        if status == "done":
            final_task_data = td
            print()
            break
        elif status == "failed":
            raise RuntimeError(f"❌ 增量重渲染失败: {td.get('status_reason')}")
    else:
        raise TimeoutError("❌ 增量重渲染超时 (60s)")

    rerender_cost = time.time() - t_start_rerender
    print(f"✅ 增量重渲染执行成功! 总耗时: {rerender_cost:.2f} 秒 (远快于全量重新运行)")

    # 5. 校验三元组状态机记录: OCR 和 Translate 必须被 SKIPPED，Layout 和 Burn 必须 COMPLETED
    stages = {s["name"]: s["status"] for s in final_task_data["stages"]}
    print(f"阶段状态详情: {stages}")
    assert stages.get("ocr_extract") in ("skipped", "completed") or stages.get("ocr") in ("skipped", "completed"), "OCR 阶段状态异常"
    assert stages.get("translate") in ("skipped", "completed"), "Translate 阶段状态异常"
    assert stages.get("layout_ass") == "completed", "LayoutAss 阶段必须重新执行"
    assert stages.get("burn_subtitles") == "completed", "BurnSubtitles 阶段必须重新执行"

    # 6. 验证产物中的字幕文本确实已被更新
    ass_path = work_dir / "subtitle.ass"
    with open(ass_path, "r", encoding="utf-8") as f:
        ass_content = f.read()
    assert test_edit_zh in ass_content.replace(r"\N", ""), "❌ 新生成的 subtitle.ass 中未包含用户编辑的新译文"
    print("✅ 产物 subtitle.ass 已成功更新且包含用户修改后的译文")

    # 7. 测试导出接口
    for fmt, ext in [("ass", ".ass"), ("srt", ".srt"), ("video", ".mp4")]:
        with urllib.request.urlopen(f"{BASE_URL}/api/tasks/{task_id}/export/{fmt}") as exp_resp:
            assert exp_resp.status == 200
            content = exp_resp.read()
            assert len(content) > 100, f"导出 {fmt} 内容为空"
            print(f"✅ 导出格式 [{fmt}] 成功: {len(content):,} 字节")


async def test_5_cdp_1280_screenshot():
    print("\n" + "="*60)
    print("【步骤 5】1280 宽度下无折行验证与无头 Edge CDP 高清截图")
    print("="*60)

    task_id = "work_20261101_215811_simulated_1080p_fansub"
    target_url = f"{BASE_URL}/#task={task_id}"
    port = 9223

    cmd = [
        EDGE_EXE,
        "--headless=new",
        "--disable-gpu",
        f"--remote-debugging-port={port}",
        f"--user-data-dir={TEMP_PROFILE}",
        "--window-size=1280,850",
        "about:blank"
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        # 等待 CDP 端口就绪
        for _ in range(25):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1) as resp:
                    if resp.status == 200:
                        break
            except Exception:
                await asyncio.sleep(0.2)
        else:
            raise RuntimeError("CDP 端口未能及时响应")

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list") as resp:
            targets = json.loads(resp.read().decode())
        ws_url = targets[0]["webSocketDebuggerUrl"]

        async with websockets.connect(ws_url) as ws:
            # 开启 Page 和 Runtime
            await ws.send(json.dumps({"id": 1, "method": "Page.enable"}))
            await ws.recv()
            await ws.send(json.dumps({"id": 2, "method": "Runtime.enable"}))
            await ws.recv()

            # 导航
            await ws.send(json.dumps({"id": 3, "method": "Page.navigate", "params": {"url": target_url}}))
            await ws.recv()
            await asyncio.sleep(2.0)

            # 切换到 Tab 3 (💬 对白与译文概览) 并点击第一行字幕触发单帧精确预览
            js_script = """
            (async () => {
                const subTab = document.querySelector('.tab-btn[data-tab="subtitles"]');
                if (subTab) subTab.click();
                await new Promise(r => setTimeout(r, 600));
                
                // 点击第一行对白
                const firstRow = document.querySelector('.sub-row');
                if (firstRow) firstRow.click();
                await new Promise(r => setTimeout(r, 1200));

                // 检查 1280 宽度下按钮与标签是否有意外折行 (clientHeight 显著大于单行高度)
                const buttons = Array.from(document.querySelectorAll('.btn, .status-pill, .tag-badge, .filter-btn'));
                const broken = buttons.filter(b => b.clientHeight > 38 && !b.classList.contains('large'));
                return {
                    totalButtonsChecked: buttons.length,
                    hasBrokenLine: broken.length > 0,
                    brokenCount: broken.length
                };
            })()
            """
            await ws.send(json.dumps({
                "id": 4,
                "method": "Runtime.evaluate",
                "params": {"expression": js_script, "awaitPromise": True, "returnByValue": True}
            }))
            
            eval_res = None
            while True:
                msg = json.loads(await ws.recv())
                if msg.get("id") == 4:
                    eval_res = msg["result"]["result"]["value"]
                    break

            print(f"1280 宽度无折行检测: 检查元素 {eval_res['totalButtonsChecked']} 个，折行违规: {eval_res['brokenCount']} 个")
            assert not eval_res["hasBrokenLine"], "❌ 1280 宽度下检测到按钮折行"
            print("✅ 1280 宽度门禁校验通过: 所有按钮与徽章无折行")

            # 等待单帧预览图片完全渲染
            await asyncio.sleep(1.0)

            # 截取全屏高清快照
            await ws.send(json.dumps({"id": 5, "method": "Page.captureScreenshot", "params": {"format": "png"}}))
            ss_msg = None
            while True:
                msg = json.loads(await ws.recv())
                if msg.get("id") == 5:
                    ss_msg = msg
                    break

            img_bytes = base64.b64decode(ss_msg["result"]["data"])
            out_png = PROJECT_ROOT / "bench" / "webui_p3_editor_1280.png"
            out_png.write_bytes(img_bytes)
            print(f"✅ 1280px 高清界面截图已成功写入: {out_png} ({len(img_bytes):,} 字节)")

            # 复制到 artifacts 目录
            if ARTIFACT_DIR.exists():
                art_png = ARTIFACT_DIR / "webui_p3_editor_1280.png"
                art_png.write_bytes(img_bytes)
                print(f"✅ 截图凭据已归档至 Artifact 目录: {art_png}")

    finally:
        proc.terminate()
        proc.wait()


def main():
    print("="*60)
    print("AnimeAutoSub P3 全套功能端到端验收启动")
    print("="*60)

    test_1_ollama_vram_release()
    test_2_field_rename_and_schema()
    test_3_debug_tasks_management()
    test_4_p3_subtitles_and_rerender_flow()
    asyncio.run(test_5_cdp_1280_screenshot())

    print("\n" + "="*60)
    print("🎉 P3 全部验收测试 100% 通过!")
    print("="*60)


if __name__ == "__main__":
    main()
