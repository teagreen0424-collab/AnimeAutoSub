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

def run_part1_capture_running():
    print("=" * 60)
    print("▶ 任务 A: 启动并精确捕获「跑动中的进度」截图 (Screenshot 2)")
    print("=" * 60)

    payload = {
        "video_path": "ocr_input/simulated_1080p_fansub.mp4",
        "lang": "ja",
        "mode": "ocr",
        "title": "P2_E2E_Running_Progress_Capture",
        "auto_start": True
    }
    res = post_json(f"{BASE_URL}/api/tasks", payload)
    task_id = res["data"]["task_id"]
    print(f"  ✓ 任务已创建: {task_id}")

    # 等待 OCR 正在进行中 (第 3 秒左右)
    time.sleep(3.5)
    detail = get_json(f"{BASE_URL}/api/tasks/{task_id}")["data"]
    print(f"  ✓ 当前状态: {detail['status']} | 阶段: {detail.get('current_stage')} | 进度: {detail.get('total_pct')}%")

    shot_url = f"{BASE_URL}/?snapshot=1#task={task_id}"
    shot2_path = "E:/translate/bench/webui_p2_2_running_progress.png"
    take_screenshot(shot_url, shot2_path)
    print(f"  ✓ Screenshot 2 捕获完成: {shot2_path}")

    # 等待任务完成释放 GPU
    print("  ⏳ 等待任务完成以释放独占 GPU 租约...")
    while True:
        d = get_json(f"{BASE_URL}/api/tasks/{task_id}")["data"]
        if d["status"] in ("done", "failed", "canceled"):
            print(f"  ✓ 任务 A 已就绪，最终状态: {d['status']}")
            break
        time.sleep(2.0)

if __name__ == "__main__":
    run_part1_capture_running()
