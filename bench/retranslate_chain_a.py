import sys
import time
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pipeline

work_dir = Path("output/408309-1080p")
with open(work_dir / "japanese.json", "r", encoding="utf-8") as f:
    segs = json.load(f)

# Test translation in a clean temp bench dir to measure pure wall time
bench_dir = Path("output/408309-1080p/bench_retranslate")
bench_dir.mkdir(parents=True, exist_ok=True)
zh_bench = bench_dir / "chinese.json"
if zh_bench.exists():
    zh_bench.unlink()

print(f"Translating {len(segs)} sentences with Session + 127.0.0.1 in {bench_dir}...")
t0 = time.time()
trans = pipeline.translate_all(segs, bench_dir)
dt = time.time() - t0
print(f"Translation complete in {dt:.2f}s ({dt/len(segs):.3f}s/sentence)!")

report = {
    "total_sentences": len(segs),
    "translate_s": round(dt, 2),
    "sec_per_sentence": round(dt/len(segs), 3),
    "previous_translate_s": 483.91,
    "time_saved_s": round(483.91 - dt, 2),
    "speedup_ratio": round(483.91 / max(0.1, dt), 2)
}

with open(work_dir / "chain_a_v5_translate_report.json", "w", encoding="utf-8") as f:
    json.dump(report, f, indent=2)

print(json.dumps(report, indent=2))
