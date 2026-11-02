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

    # 1. 实例化真正的日语 OCR 引擎
    ocr_params_ja = {
        "Rec.ocr_version": OCRVersion.PPOCRV4,
        "Rec.model_type": ModelType.MOBILE,
        "Rec.lang_type": LangRec.JAPAN,
        "EngineConfig.onnxruntime.use_cuda": True,
        "Det.limit_side_len": 960
    }
    ocr_ja = RapidOCR(params=ocr_params_ja)
    ocr_ja(np.zeros((48, 300, 3), dtype=np.uint8), use_det=False)

    model_path = ocr_ja.text_rec.session.session._model_path
    vocab_size = len(ocr_ja.text_rec.postprocess_op.character)
    print(f"Loaded rec model: {model_path}")
    print(f"Vocab size: {vocab_size}")

    print("\n" + "=" * 90)
    print("                    K2 日语模型 OCR 识别前后对照")
    print("=" * 90)

    tot_truth_len = 0
    old_tot_dist = 0
    new_tot_dist = 0
    new_correct_count = 0

    results = []

    for item in sub_items:
        fid = item["id"]
        truth = item["truth"]
        old_ocr = item["ocr"]
        img_path = f"bench/truth_frames/frame_{fid:03d}.jpg"
        img = cv2.imread(img_path)
        if img is None:
            print(f"Error: 无法读取 {img_path}")
            continue

        out = ocr_ja(img)
        new_ocr = clean_txt(out)

        old_d, _ = compare_texts(truth, old_ocr)
        new_d, _ = compare_texts(truth, new_ocr)

        tot_truth_len += len(truth)
        old_tot_dist += old_d
        new_tot_dist += new_d
        if new_d == 0:
            new_correct_count += 1

        print(f"Frame {fid:03d} | 真值({len(truth)}字): {truth}")
        print(f"         | 旧OCR:       {old_ocr} (dist={old_d})")
        print(f"         | 新日语OCR:   {new_ocr} (dist={new_d})")
        print("-" * 90)

        results.append({
            "id": fid,
            "truth": truth,
            "old_ocr": old_ocr,
            "new_ocr": new_ocr,
            "old_dist": old_d,
            "new_dist": new_d
        })

    old_cer = calculate_cer(old_tot_dist, tot_truth_len)
    new_cer = calculate_cer(new_tot_dist, tot_truth_len)

    print("=" * 90)
    print(f"总真值字符数:   {tot_truth_len}")
    print(f"旧模型编辑距离: {old_tot_dist} | 旧 CER: {old_cer*100:.2f}% | 完全正确: 2/{len(sub_items)}")
    print(f"新模型编辑距离: {new_tot_dist} | 新 CER: {new_cer*100:.2f}% | 完全正确: {new_correct_count}/{len(sub_items)}")
    print(f"CER 相对改善幅度: {((old_cer - new_cer)/old_cer)*100:.2f}%")
    print("=" * 90)

if __name__ == "__main__":
    main()
