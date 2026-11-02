import json
from pathlib import Path

# 读取 Z 阶段验证过的 60 句 scored final 结果
with open("bench/audit_60_scored_final.json", "r", encoding="utf-8") as f:
    data = json.load(f)

records = data["records"]

fixture_items = []
for r in records:
    fixture_items.append({
        "start": r["start"],
        "end": r["end"],
        "ja": r["cleaned_ja"],
        "ja_raw": r["ocr_ja"],
        "zh": r["new_zh"],
        "rejected": False,
        "box": [288, 864, 1632, 1026],  # 标准字幕区域 (1080p)
        "video_w": 1920,
        "video_h": 1080
    })

fixture_dir = Path("bench/fixtures")
fixture_dir.mkdir(parents=True, exist_ok=True)
fixture_file = fixture_dir / "60_sentences_frozen_fixture.json"

with open(fixture_file, "w", encoding="utf-8") as f:
    json.dump(fixture_items, f, ensure_ascii=False, indent=2)

print(f"Created frozen fixture with {len(fixture_items)} items at {fixture_file}")
