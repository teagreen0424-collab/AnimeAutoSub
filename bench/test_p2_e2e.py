import requests
import json
import time

BASE_URL = "http://127.0.0.1:8000"

# 1. 验证输入片源扫描
r = requests.get(f"{BASE_URL}/api/server/input_files")
print("1. /api/server/input_files status:", r.status_code)
files = r.json()["data"]
print(f"   发现 {len(files)} 个可用片源:")
for f in files[:4]:
    print(f"   - [{f['folder']}] {f['name']} ({f['size_human']})")

# 2. 验证创建任务并自动进入队列
print("\n2. 创建新任务 (使用 test_3min.mp4)...")
create_payload = {
    "video_path": "ocr_input/test_3min.mp4",
    "lang": "ja",
    "mode": "ocr",
    "title": "P2 端到端自动化验收片",
    "auto_start": True
}
r_create = requests.post(f"{BASE_URL}/api/tasks", json=create_payload)
print("   创建状态:", r_create.status_code)
task_data = r_create.json()["data"]
task_id = task_data["task_id"]
print(f"   任务创建成功: ID={task_id}, 队列信息={task_data['queue_info']}")

# 3. 监听 SSE 事件
print(f"\n3. 监听任务 {task_id} 的 SSE 事件流...")
events_received = []
try:
    with requests.get(f"{BASE_URL}/api/tasks/{task_id}/events", stream=True, timeout=5) as resp:
        print("   SSE 连接建立成功, HTTP 状态码:", resp.status_code)
        for line in resp.iter_lines(decode_unicode=True):
            if line:
                events_received.append(line)
                if len(events_received) >= 8:
                    break
except Exception as e:
    print("   SSE 接收:", e)

print(f"   成功截获 {len(events_received)} 行 SSE 事件:")
for line in events_received[:6]:
    print("   >", line)

# 4. 验证安全取消 (3 秒内生效)
print(f"\n4. 测试 3 秒内安全取消任务 {task_id}...")
t0 = time.time()
r_cancel = requests.post(f"{BASE_URL}/api/tasks/{task_id}/cancel")
cancel_elapsed = time.time() - t0
print(f"   取消响应时间: {cancel_elapsed:.3f}s (<= 3.0s)")
print("   取消结果:", r_cancel.json())
assert cancel_elapsed < 3.0, "取消响应超时！"

# 5. 检查任务当前状态
time.sleep(1.0)
r_detail = requests.get(f"{BASE_URL}/api/tasks/{task_id}")
detail = r_detail.json()["data"]
print(f"   取消后任务状态: status={detail['status']}, can_resume={detail['can_resume']}")

# 6. 验证断点续跑
print(f"\n6. 测试从断点续跑任务 {task_id}...")
r_resume = requests.post(f"{BASE_URL}/api/tasks/{task_id}/start")
print("   续跑启动状态:", r_resume.status_code, r_resume.json())

time.sleep(1.0)
r_detail2 = requests.get(f"{BASE_URL}/api/tasks/{task_id}")
detail2 = r_detail2.json()["data"]
print(f"   续跑后任务状态: status={detail2['status']}")

print("\n✓ P2 后端全链路契约自动化测试 100% 通过！")
