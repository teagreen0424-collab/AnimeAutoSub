import sys
import json
from pathlib import Path
import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import animeautosub._env
from rapidocr import RapidOCR
from rapidocr.utils.typings import OCRVersion, ModelType, LangRec
from animeautosub.core.comparator import compare_texts

def main():
    with open("bench/truth_frames/truth_manual.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    sub_items = [item for item in data["items"] if item["kind"] == "subtitle"]

    ocr = RapidOCR(params={
        "Rec.ocr_version": OCRVersion.PPOCRV4,
        "Rec.model_type": ModelType.MOBILE,
        "Rec.lang_type": LangRec.JAPAN,
        "EngineConfig.onnxruntime.use_cuda": True,
    })

    print(f"{'ID':<4} | {'Dist':<4} | {'Truth':<40} | {'OCR (japan_v4)':<40}")
    print("-" * 90)
    for item in sub_items:
        fid = item["id"]
        truth = item["truth"]
        img = cv2.imread(f"bench/truth_frames/frame_{fid:03d}.jpg")
        out = ocr(img)
        txt = "".join([t.strip() for t in out.txts if t.strip()]) if (out and out.txts) else ""
        d, _ = compare_texts(truth, txt)
        print(f"{fid:03d}  | {d:2d}   | {truth[:38]:<40} | {txt[:38]:<40}")

if __name__ == "__main__":
    main()
