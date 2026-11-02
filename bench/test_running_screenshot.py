import os
import sys
import time
import json
import subprocess
import urllib.request
from pathlib import Path

BASE_URL = "http://127.0.0.1:8000"
EDGE_EXE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

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
    temp_prof = Path(f"C:/Users/10932/AppData/Local/Temp/edge_prof_{int(time.time()*1000)}")
    temp_prof.mkdir(parents=True, exist_ok=True)
    cmd = [
        EDGE_EXE,
        "--headless=new",
        "--disable-gpu",
        "--virtual-time-budget=2000",
        f"--user-data-dir={temp_prof}",
        f"--screenshot={out_png}",
        "--window-size=1400,900",
        url
    ]
    subprocess.run(cmd, check=True)
    print(f"[截图成功] 已保存至: {out_png}")

def main():
    print("▶ 创建任务并捕获真实 RUNNING 截图...")
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

    # 等待 4 秒，进入 OCR 或翻译运行态
    time.sleep(4.0)
    detail = get_json(f"{BASE_URL}/api/tasks/{task_id}")["data"]
    print(f"  ✓ 任务状态: {detail['status']} | 阶段: {detail.get('current_stage')} | 进度: {detail.get('total_pct')}%")

    shot_url = f"{BASE_URL}/?no_sse=1#task={task_id}"
    shot2_path = "E:/translate/bench/webui_p2_2_running_progress.png"
    take_screenshot(shot_url, shot2_path)

    # 等待完成
    while True:
        d = get_json(f"{BASE_URL}/api/tasks/{task_id}")["data"]
        if d["status"] in ("done", "failed", "canceled"):
            print(f"  ✓ 任务结束: {d['status']}")
            break
        time.sleep(2.0)

if __name__ == "__main__":
    main()
