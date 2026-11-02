import sys
sys.path.insert(0, ".")
from web.task_manager import TaskManager

tm = TaskManager()
print(f"Total tasks scanned: {len(tm.tasks)}")
for tid, t in tm.tasks.items():
    print(f"[{t['status']}] {tid} | {t['title']} | is_legacy={t['is_legacy']} | has_video={t['has_video']}")
