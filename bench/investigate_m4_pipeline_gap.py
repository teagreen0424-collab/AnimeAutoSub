import sys
import json
from pathlib import Path
import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import animeautosub._env
from rapidocr import RapidOCR
from pipeline_ocr import clean_ocr_text, is_timecode_or_noise
from animeautosub.core.comparator import compare_texts, calculate_cer

def main():
    with open("bench/truth_frames/truth_manual.json", "r", encoding="utf-8") as f:
        truth_data = json.load(f)

    sub_items = [item for item in truth_data["items"] if item["kind"] == "subtitle"]

    # 1. 默认直接调用 RapidOCR
    ocr_direct = RapidOCR(params={"EngineConfig.onnxruntime.use_cuda": True})

    print("=" * 100)
    print("                     M4: 直接 RapidOCR vs pipeline_ocr 行为全面比对")
    print("=" * 100)

    comparison = []
    tot_truth = 0
    direct_dist_tot = 0
    pipeline_dist_tot = 0

    for item in sub_items:
        fid = item["id"]
        truth = item["truth"]
        recorded_ocr = item["ocr"] # truth_manual.json 里记录的 ocr 结果

        img_path = f"bench/truth_frames/frame_{fid:03d}.jpg"
        img = cv2.imread(img_path)

        # (a) 直接调用: 纯拼接
        out = ocr_direct(img)
        direct_raw_txts = list(out.txts) if (out and out.txts) else []
        direct_txt = "".join([t.strip() for t in direct_raw_txts if t.strip()])

        # (b) 走 pipeline_ocr.py 的 clean_ocr_text
        pipeline_txt = clean_ocr_text(direct_raw_txts) if direct_raw_txts else ""

        d_direct, _ = compare_texts(truth, direct_txt)
        d_pipeline, _ = compare_texts(truth, pipeline_txt)
        d_recorded, _ = compare_texts(truth, recorded_ocr)

        tot_truth += len(truth)
        direct_dist_tot += d_direct
        pipeline_dist_tot += d_pipeline

        boxes = [b.tolist() for b in out.boxes] if (out and out.boxes is not None) else []

        print(f"Frame {fid:03d} (真值 {len(truth)} 字):")
        print(f"  Truth:       {truth}")
        print(f"  Direct OCR:  {direct_txt} (dist={d_direct})")
        print(f"  Pipeline:    {pipeline_txt} (dist={d_pipeline})")
        print(f"  Recorded:    {recorded_ocr} (dist={d_recorded})")
        if d_direct != d_pipeline or d_direct != d_recorded:
            print(f"  [差异发现]: raw_txts={direct_raw_txts}")
        print("-" * 100)

        comparison.append({
            "id": fid,
            "truth": truth,
            "direct_ocr": direct_txt,
            "pipeline_ocr": pipeline_txt,
            "recorded_ocr": recorded_ocr,
            "direct_dist": d_direct,
            "pipeline_dist": d_pipeline,
            "recorded_dist": d_recorded,
            "raw_txts": direct_raw_txts,
            "boxes_count": len(boxes)
        })

    cer_direct = calculate_cer(direct_dist_tot, tot_truth)
    cer_pipeline = calculate_cer(pipeline_dist_tot, tot_truth)
    cer_recorded = calculate_cer(sum(c["recorded_dist"] for c in comparison), tot_truth)

    print("=" * 100)
    print(f"总字符数:            {tot_truth}")
    print(f"直接调用 (Direct):    编辑距离 {direct_dist_tot} | CER = {cer_direct*100:.2f}%")
    print(f"走 pipeline 处理:     编辑距离 {pipeline_dist_tot} | CER = {cer_pipeline*100:.2f}%")
    print(f"truth_manual 记录值:  编辑距离 {sum(c['recorded_dist'] for c in comparison)} | CER = {cer_recorded*100:.2f}%")
    print("=" * 100)

    report = {
        "total_truth_chars": tot_truth,
        "direct_dist_tot": direct_dist_tot,
        "direct_cer": round(cer_direct * 100, 2),
        "pipeline_dist_tot": pipeline_dist_tot,
        "pipeline_cer": round(cer_pipeline * 100, 2),
        "recorded_cer": round(cer_recorded * 100, 2),
        "comparison": comparison
    }
    with open("bench/m4_pipeline_gap_investigation.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print("报告已保存至 bench/m4_pipeline_gap_investigation.json")

if __name__ == "__main__":
    main()
