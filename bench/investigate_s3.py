import json
import numpy as np
from pathlib import Path

# Load Chain A (Audio Whisper)
with open('output/408309-1080p/japanese.json', encoding='utf-8') as f:
    ja_a = json.load(f)
with open('output/408309-1080p/chinese.json', encoding='utf-8') as f:
    zh_a = json.load(f)

# Load Chain B (Video OCR)
with open('ocr_output/test_3min/japanese.json', encoding='utf-8') as f:
    ja_b = json.load(f)
with open('ocr_output/test_3min/chinese.json', encoding='utf-8') as f:
    zh_b = json.load(f)

len_ja_a = [len(x['text']) for x in ja_a]
len_zh_a = [len(x['text']) for x in zh_a]

len_ja_b = [len(x['text']) for x in ja_b]
len_zh_b = [len(x['zh']) for x in zh_b]

print("=== Chain A (Whisper ASR, 154 sentences) ===")
print(f"JA length: mean={np.mean(len_ja_a):.1f}, min={np.min(len_ja_a)}, max={np.max(len_ja_a)}, sum={np.sum(len_ja_a)}")
print(f"ZH length: mean={np.mean(len_zh_a):.1f}, min={np.min(len_zh_a)}, max={np.max(len_zh_a)}, sum={np.sum(len_zh_a)}")

print("\n=== Chain B (Video OCR, 38 sentences) ===")
print(f"JA length: mean={np.mean(len_ja_b):.1f}, min={np.min(len_ja_b)}, max={np.max(len_ja_b)}, sum={np.sum(len_ja_b)}")
print(f"ZH length: mean={np.mean(len_zh_b):.1f}, min={np.min(len_zh_b)}, max={np.max(len_zh_b)}, sum={np.sum(len_zh_b)}")
