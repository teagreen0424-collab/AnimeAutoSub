import json
with open('ocr_output/test_3min/japanese.json', 'r', encoding='utf-8') as f:
    segs = json.load(f)

for idx in [12, 13, 15, 16, 17, 20, 22, 24, 29, 30, 32]:
    s = segs[idx-1]
    box = s.get('box', [])
    h = box[3] - box[1] if box else 0
    w = box[2] - box[0] if box else 0
    print(f"Seg #{idx} ({s['start']}~{s['end']}): orig text: {s['text'][:30]} | box: w={w:.1f}, h={h:.1f}")
