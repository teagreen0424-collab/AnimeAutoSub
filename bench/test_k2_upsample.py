import sys
import json
from pathlib import Path
import cv2
import numpy as np

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

    ocr_params = {
        "Rec.ocr_version": OCRVersion.PPOCRV4,
        "Rec.model_type": ModelType.MOBILE,
        "Rec.lang_type": LangRec.JAPAN,
        "EngineConfig.onnxruntime.use_cuda": True,
    }
    ocr = RapidOCR(params=ocr_params)

    for scale, interp in [(1.0, None), (1.5, cv2.INTER_CUBIC), (2.0, cv2.INTER_CUBIC), (2.0, cv2.INTER_LANCZOS4)]:
        tot_truth = 0
        tot_dist = 0
        correct = 0

        for item in sub_items:
            fid = item["id"]
            truth = item["truth"]
            img = cv2.imread(f"bench/truth_frames/frame_{fid:03d}.jpg")
            if scale != 1.0:
                h, w = img.shape[:2]
                img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=interp)

            out = ocr(img)
            txt = clean_txt(out)
            d, _ = compare_texts(truth, txt)
            tot_truth += len(truth)
            tot_dist += d
            if d == 0:
                correct += 1

        cer = calculate_cer(tot_dist, tot_truth)
        interp_name = "None" if interp is None else ("CUBIC" if interp == cv2.INTER_CUBIC else "LANCZOS4")
        print(f"Scale: {scale:.1f}x ({interp_name:<8}) | Dist: {tot_dist:2d}/{tot_truth} | Correct: {correct:2d}/12 | CER: {cer*100:.2f}%")

if __name__ == "__main__":
    main()
