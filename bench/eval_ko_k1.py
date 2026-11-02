"""
K1 阶段评测与 CER 统计脚本 (bench/eval_ko_k1.py)
"""

import json
from pathlib import Path
from difflib import SequenceMatcher
import unicodedata

def calculate_cer(reference: str, hypothesis: str) -> float:
    """按字符计算编辑距离与 CER"""
    ref_chars = list(unicodedata.normalize("NFKC", reference).replace(" ", "").replace("\\N", ""))
    hyp_chars = list(unicodedata.normalize("NFKC", hypothesis).replace(" ", "").replace("\\N", ""))
    if not ref_chars:
        return 0.0 if not hyp_chars else 1.0

    # 动态规划编辑距离
    dp = [[0] * (len(hyp_chars) + 1) for _ in range(len(ref_chars) + 1)]
    for i in range(len(ref_chars) + 1):
        dp[i][0] = i
    for j in range(len(hyp_chars) + 1):
        dp[0][j] = j

    for i in range(1, len(ref_chars) + 1):
        for j in range(1, len(hyp_chars) + 1):
            if ref_chars[i - 1] == hyp_chars[j - 1]:
                dp[i][j] = dp[i - 1][j - 1]
            else:
                dp[i][j] = min(
                    dp[i - 1][j] + 1,      # 删除
                    dp[i][j - 1] + 1,      # 插入
                    dp[i - 1][j - 1] + 1   # 替换
                )
    dist = dp[len(ref_chars)][len(hyp_chars)]
    return dist / len(ref_chars)

def evaluate_ocr(ground_truth_path: str, ocr_raw_path: str):
    with open(ground_truth_path, "r", encoding="utf-8") as f:
        gt_data = json.load(f)
    with open(ocr_raw_path, "r", encoding="utf-8") as f:
        ocr_data = json.load(f)

    print(f"=== 韩语 OCR (K1 合成素材) 评测对齐 ===")
    print(f"真值句数: {len(gt_data)}, OCR检出句数: {len(ocr_data)}")

    results = []
    total_ref_len = 0
    total_edit_dist = 0

    for gt_item in gt_data:
        gt_id = gt_item["id"]
        gt_text = gt_item["ko"]
        gt_start = gt_item["start"]
        gt_end = gt_item["end"]

        # 在时间轴范围内寻找最匹配的 OCR 检出
        candidates = []
        for ocr_item in ocr_data:
            o_start = ocr_item["start"]
            o_end = ocr_item["end"]
            o_text = ocr_item["text"]
            # 时间轴有交集
            overlap = max(0.0, min(gt_end, o_end) - max(gt_start, o_start))
            if overlap > 0.3:
                candidates.append((overlap, o_text, ocr_item))

        if candidates:
            # 选重叠时间最长的候选
            candidates.sort(key=lambda x: x[0], reverse=True)
            best_match_text = candidates[0][1]
            box = candidates[0][2].get("box")
        else:
            best_match_text = ""
            box = None

        cer = calculate_cer(gt_text, best_match_text)
        ref_len = len(list(unicodedata.normalize("NFKC", gt_text).replace(" ", "").replace("\\N", "")))
        hyp_len = len(list(unicodedata.normalize("NFKC", best_match_text).replace(" ", "").replace("\\N", "")))
        edit_dist = round(cer * ref_len)

        total_ref_len += ref_len
        total_edit_dist += edit_dist

        results.append({
            "id": gt_id,
            "category": gt_item.get("category", "日常"),
            "ground_truth": gt_text,
            "ocr_hyp": best_match_text,
            "cer": round(cer * 100, 2),
            "edit_dist": edit_dist,
            "ref_len": ref_len,
            "box": box
        })

    overall_cer = (total_edit_dist / max(1, total_ref_len)) * 100
    print(f"总参考字符: {total_ref_len}, 累计编辑距离: {total_edit_dist}")
    print(f"总平均 CER: {overall_cer:.2f}% (标明: 合成素材乐观上限)")

    print("\n--- 逐句比对详情 (全部 40 句) ---")
    for r in results:
        print(f"#{r['id']:02d} [{r['category']}] CER: {r['cer']}%, dist: {r['edit_dist']}/{r['ref_len']}")
        print(f"  REF: {r['ground_truth']}")
        print(f"  HYP: {r['ocr_hyp']}")

    return results, overall_cer

if __name__ == "__main__":
    gt = "bench/fixtures/korean_40_ground_truth_timed.json"
    ocr = "work_simulated_ko_1080p_ocr/ocr_raw.json"
    if Path(ocr).exists():
        evaluate_ocr(gt, ocr)
    else:
        print("未找到 OCR 产物:", ocr)
