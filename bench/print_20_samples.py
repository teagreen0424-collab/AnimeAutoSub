import json

with open("ocr_output/114877-720p_old_1031_backup/chinese.json", "r", encoding="utf-8") as f:
    old_zh = json.load(f)
with open("ocr_output/114877-720p/chinese.json", "r", encoding="utf-8") as f:
    new_zh = json.load(f)

sample_indices = [
    0, 10, 30, 50, 80, 120, 180, 240, 300, 360,
    420, 480, 540, 600, 660, 720, 760, 800, 820, 835
]

for count, idx in enumerate(sample_indices):
    n = new_zh[idx]
    best_o = None
    best_inter = 0
    for o in old_zh:
        inter = max(0, min(n["end"], o["end"]) - max(n["start"], o["start"]))
        if inter > best_inter:
            best_inter = inter
            best_o = o
    
    print(f"[{count+1}] 样本 (新索引 #{idx}) 时间: {n['start']:.2f}s - {n['end']:.2f}s")
    print(f"  旧原文: {best_o['ja'] if best_o else '(未检出)'}")
    print(f"  新原文: {n.get('ja_raw', n.get('ja', ''))} (净化后: {n.get('ja', '')})")
    print(f"  旧译文: {best_o['zh'] if best_o else '(未检出)'}")
    print(f"  新译文: {n.get('zh', '')}")
    print("-" * 60)
