import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import json
import time
import pipeline_ocr

with open('ocr_output/test_3min/japanese.json', encoding='utf-8') as f:
    ja_data = json.load(f)

glossary = pipeline_ocr.load_glossary()
context = []
times = []

print(">>> Testing pipeline_ocr.translate_one on 38 sentences...")
for idx, seg in enumerate(ja_data):
    t0 = time.time()
    zh = pipeline_ocr.translate_one(seg['text'], glossary, context)
    dt = time.time() - t0
    context.append((seg['text'], zh))
    times.append(dt)
    print(f"[{idx+1:02d}/38] dt={dt:.2f}s: {seg['text'][:20]} -> {zh[:20]}")

print("\n" + "=" * 50)
print(f"Total time: {sum(times):.2f}s, Mean: {sum(times)/len(times):.2f}s/sentence")
print(f"Max: {max(times):.2f}s, Min: {min(times):.2f}s")
