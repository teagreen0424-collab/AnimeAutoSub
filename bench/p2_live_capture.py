import os
import sys
import time
import json
import subprocess
import urllib.request
from pathlib import Path

BASE_URL = "http://127.0.0.1:8000"
EDGE_EXE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
TEMP_PROFILE = r"C:\Users\10932\AppData\Local\Temp\edge_temp_profile"

def post_json(url, data):
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))

def get_json(url):
    with urllib.request.urlopen(url) as resp:
        return json.loads(resp.read().decode("utf-8"))

def take_screenshot(url, out_png):
    cmd = [
        EDGE_EXE,
        "--headless=new",
        "--disable-gpu",
        "--virtual-time-budget=3000",
        f"--user-data-dir={TEMP_PROFILE}",
        f"--screenshot={out_png}",
        "--window-size=1400,900",
        url
    ]
    subprocess.run(cmd, check=True)
    print(f"[截图成功] 已保存至: {out_png}")

def main():
    print("=" * 60)
    print("▶ 启动 P2 阶段实测: 全程通过 WebUI / API 驱动一条片子")
    print("=" * 60)

    # 1. 提交新建任务
    payload = {
        "video_path": "ocr_input/simulated_1080p_fansub.mp4",
        "lang": "ja",
        "mode": "ocr",
        "title": "1080p_Fansub_P2_E2E_FullRun",
        "auto_start": True
    }
    create_res = post_json(f"{BASE_URL}/api/tasks", payload)
    assert create_res["code"] == 0, f"创建任务失败: {create_res}"
    task = create_res["data"]
    task_id = task["task_id"]
    print(f"[1/4] 任务创建并入队成功: {task_id}")

    # 2. 等待片刻让流水线进入 running 状态 (OCR 或翻译执行中)
    time.sleep(2.5)

    # 检查状态
    detail_res = get_json(f"{BASE_URL}/api/tasks/{task_id}")
    task_info = detail_res["data"]
    print(f"[2/4] 当前任务状态: {task_info['status']}, 当前阶段: {task_info.get('current_stage')}, 进度: {task_info.get('total_pct')}%")

    # 截取「跑动中的进度」 (Screenshot 2)
    shot2_path = Path("E:/translate/bench/webui_p2_2_running_progress.png")
    take_screenshot(f"{BASE_URL}/#task={task_id}", str(shot2_path))

    # 3. 轮询等待任务完成 (大约 20~40 秒)
    print("[3/4] 正在实时跟进任务完成状态...")
    start_time = time.time()
    while True:
        detail_res = get_json(f"{BASE_URL}/api/tasks/{task_id}")
        st = detail_res["data"]["status"]
        pct = detail_res["data"].get("total_pct", 0)
        c_stg = detail_res["data"].get("current_stage", "-")
        elapsed = time.time() - start_time
        print(f"  [+{elapsed:.1f}s] 状态: {st} | 阶段: {c_stg} | 总进度: {pct}%")

        if st == "done":
            print(f"🎉 任务已成功完成！耗时: {elapsed:.2f}s")
            break
        elif st in ["failed", "canceled"]:
            raise RuntimeError(f"任务异常终止: {st}")

        time.sleep(3.0)

    # 4. 截取「完成后的成片详情」 (Screenshot 3)
    shot3_path = Path("E:/translate/bench/webui_p2_3_completed_detail.png")
    take_screenshot(f"{BASE_URL}/#task={task_id}", str(shot3_path))
    print(f"[4/4] 成片详情页截图已完成: {shot3_path}")

    # 验证成片及关键四件套
    work_dir = Path("E:/translate/work_tasks") / task_id
    video_out = work_dir / "output.mp4"
    ass_out = work_dir / "subtitle.ass"
    zh_out = work_dir / "chinese.json"
    mf_out = work_dir / "manifest.json"

    print("\n[产物校验账本]:")
    for p in [video_out, ass_out, zh_out, mf_out]:
        assert p.exists(), f"产物缺失: {p}"
        print(f"  ✓ {p.name} ({p.stat().st_size:,} 字节)")

    print("\n✅ P2 全链路实测执行完毕！全部截图与四件套均已就绪。")

if __name__ == "__main__":
    main()
