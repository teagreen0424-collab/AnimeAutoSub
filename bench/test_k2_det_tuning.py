import sys
import json
from pathlib import Path
import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import animeautosub._env
from rapidocr import RapidOCR
from rapidocr.utils.typings import OCRVersion, ModelType, LangRec
from animeautosub.core.comparator import compare_texts, calculate_cer

def clean_txt(out) -> str:
    if not out or not out.txts:
        return ""
    return "".join([t.strip() for t in out.txts if t.strip()])

def main():
    with open("bench/truth_frames/truth_manual.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    sub_items = [item for item in data["items"] if item["kind"] == "subtitle"]

    configs = [
        ("Default (unclip=1.6, box=0.5)", 1.6, 0.5),
        ("unclip=2.0, box=0.3", 2.0, 0.3),
        ("unclip=2.2, box=0.3", 2.2, 0.3),
        ("unclip=2.5, box=0.2", 2.5, 0.2),
    ]

    for label, unclip, box_thresh in configs:
        ocr = RapidOCR(params={
            "Rec.ocr_version": OCRVersion.PPOCRV4,
            "Rec.model_type": ModelType.MOBILE,
            "Rec.lang_type": LangRec.JAPAN,
            "Det.unclip_ratio": unclip,
            "Det.box_thresh": box_thresh,
            "EngineConfig.onnxruntime.use_cuda": True
        })
        tot_truth = 0
        tot_dist = 0
        for item in sub_items:
            fid = item["id"]
            img = cv2.imread(f"bench/truth_frames/frame_{fid:03d}.jpg")
            out = ocr(img)
            txt = clean_txt(out)
            d, _ = compare_texts(item["truth"], txt)
            tot_truth += len(item["truth"])
            tot_dist += d
        cer = calculate_cer(tot_dist, tot_truth)
        print(f"{label:<30} -> Dist: {tot_dist:2d}/{tot_truth} | CER: {cer*100:.2f}%")

if __name__ == "__main__":
    main()
