import sys
import json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import animeautosub._env
from animeautosub.core.comparator import compare_texts, calculate_cer


def main():
    with open("bench/truth_frames/truth_manual.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    sub_items = [item for item in data["items"] if item["kind"] == "subtitle"]
    print(f"Subtitle items count: {len(sub_items)}")

    tot_truth_len = sum(len(x["truth"]) for x in sub_items)
    tot_dist = 0
    correct_count = 0

    for item in sub_items:
        d, _ = compare_texts(item["truth"], item["ocr"])
        tot_dist += d
        if d == 0:
            correct_count += 1
        fid = item["id"]
        print(f"Frame {fid:03d}: dist={d:2d} | truth_len={len(item['truth']):2d} | truth={item['truth'][:20]} | ocr={item['ocr'][:20]}")

    cer = calculate_cer(tot_dist, tot_truth_len)
    print("=" * 60)
    print(f"Total truth chars: {tot_truth_len}")
    print(f"Total distance: {tot_dist}")
    print(f"Correct frames: {correct_count}/{len(sub_items)}")
    print(f"Baseline CER: {cer*100:.2f}%")

if __name__ == "__main__":
    main()
