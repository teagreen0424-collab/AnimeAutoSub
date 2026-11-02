"""
AnimeAutoSub: M2 时序多数投票与 M3 异常退化帧过滤/拒识评测流水线
================================================================
执行 N3(b)(c)、N4、N5、M2 全量重测，并在 15 帧短集与 12 帧长集上同时报数。

产物：bench/m2_m3_final_report.json
"""

import sys
import json
import re
import random
import subprocess
from pathlib import Path
from difflib import SequenceMatcher
from collections import Counter
import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import animeautosub._env
from rapidocr import RapidOCR
from animeautosub.core.comparator import levenshtein_distance, calculate_cer

FFMPEG_BIN = r"D:\Dev\ffmpeg\bin\ffmpeg.exe"

def normalize_text(text: str) -> str:
    """去除所有空白字符"""
    return re.sub(r'\s+', '', text)

def extract_crop_ffmpeg(video_path: str, sec: float, height_ratio: float = 0.28) -> np.ndarray:
    """抽取底部 28% 裁图"""
    cmd = [
        FFMPEG_BIN, "-y", "-ss", f"{sec:.3f}", "-i", video_path,
        "-vframes", "1", "-f", "image2pipe", "-vcodec", "rawvideo",
        "-pix_fmt", "bgr24", "-"
    ]
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if len(p.stdout) == 1280 * 720 * 3:
        frame = np.frombuffer(p.stdout, dtype=np.uint8).reshape((720, 1280, 3))
        h, w, _ = frame.shape
        crop_y = int(h * (1.0 - height_ratio))
        return frame[crop_y:h, 0:w]
    return None

def align_and_vote(candidates: list) -> str:
    """
    M2 时序多数投票算法：
    1. 选出与其他候选总编辑距离最小的参考串 (Medoid)；
    2. 将其他候选回溯对齐到 Medoid；
    3. 逐列进行多数表决；无绝对多数时保留 Medoid 字符。
    """
    if not candidates:
        return ""
    if len(candidates) == 1:
        return candidates[0]

    # 1. 寻找 Medoid
    min_dist_sum = float("inf")
    medoid_idx = 0
    for i, c1 in enumerate(candidates):
        dist_sum = sum(levenshtein_distance(c1, c2) for j, c2 in enumerate(candidates) if i != j)
        if dist_sum < min_dist_sum:
            min_dist_sum = dist_sum
            medoid_idx = i
    medoid = candidates[medoid_idx]

    # 2. 对齐矩阵构建 (以 Medoid 为基准列)
    # 对每个候选串，进行 Needleman-Wunsch / Levenshtein 回溯对齐
    aligned_matrix = [] # 每行对应一个候选串对齐后的 token 列表

    for cand in candidates:
        if cand == medoid:
            aligned_matrix.append(list(medoid))
            continue
        # 回溯对齐 cand 到 medoid
        m, n = len(medoid), len(cand)
        dp = [[0] * (n + 1) for _ in range(m + 1)]
        for i in range(m + 1):
            dp[i][0] = i
        for j in range(n + 1):
            dp[0][j] = j
        for i in range(1, m + 1):
            for j in range(1, n + 1):
                cost = 0 if medoid[i - 1] == cand[j - 1] else 1
                dp[i][j] = min(dp[i - 1][j] + 1, dp[i][j - 1] + 1, dp[i - 1][j - 1] + cost)

        # 回溯
        i, j = m, n
        aligned_cand = []
        while i > 0 or j > 0:
            if i > 0 and j > 0 and (dp[i][j] == dp[i - 1][j - 1] or dp[i][j] == dp[i - 1][j - 1] + 1):
                aligned_cand.append(cand[j - 1])
                i -= 1
                j -= 1
            elif i > 0 and dp[i][j] == dp[i - 1][j] + 1:
                # cand 缺失该字符 (对应 medoid 的空缺)
                aligned_cand.append(None)
                i -= 1
            else:
                # cand 多出的字符，合并到前一个字符或跳过
                j -= 1
        aligned_cand.reverse()
        aligned_matrix.append(aligned_cand)

    # 3. 逐列多数投票
    voted_chars = []
    for col_idx in range(len(medoid)):
        votes = []
        for row in aligned_matrix:
            if col_idx < len(row) and row[col_idx] is not None:
                votes.append(row[col_idx])
        if not votes:
            voted_chars.append(medoid[col_idx])
            continue
        counts = Counter(votes)
        top_char, top_count = counts.most_common(1)[0]
        # 若出现严格多数（> 50% 存活投票数）则采纳多数，否则信任 medoid
        if top_count > len(candidates) / 2.0:
            voted_chars.append(top_char)
        else:
            voted_chars.append(medoid[col_idx])

    return "".join(voted_chars)

def check_degraded_reasons(text: str, box_width: float, median_len: float) -> list:
    """N4/N5 退化帧多维度判据检测"""
    reasons = []
    # a) 拉丁/数字乱码与异常字符 (N4a)
    if re.search(r'[A-Z]{3,}|\d{3,}|[&#@$%^~]{2,}', text):
        reasons.append("latin_digits_symbols_garbage")
    # N5 尾部退化签名 (如 SLC972M192「LOEUACES, &225115?, 88がさ)
    if re.search(r'[A-Za-z0-9&]{3,}$', text):
        reasons.append("tail_latin_num_degradation")
    # b) 长度异常 (输出长度 < 检测框宽度/30 * 0.5) (N4b)
    if box_width > 0 and len(text) < (box_width / 30.0) * 0.5:
        reasons.append("length_under_ratio_threshold")
    # c) 与同组中位数长度偏差 > 50% (N4c)
    if median_len > 0 and abs(len(text) - median_len) / max(1.0, median_len) > 0.50:
        reasons.append("deviation_from_median_gt_50pct")
    return reasons

def process_dataset(
    dataset_name: str,
    meta_path: Path,
    truth_path: Path,
    video_path: str,
    ocr_engine,
    offsets: list = [-0.50, -0.25, 0.00, 0.25, 0.50]
) -> dict:
    with open(meta_path, "r", encoding="utf-8") as f:
        meta_items = json.load(f)
    with open(truth_path, "r", encoding="utf-8") as f:
        truth_data = json.load(f)

    # 建立 truth 映射
    truth_map = {}
    for item in truth_data["items"]:
        if item.get("kind") != "watermark":
            truth_map[item["id"]] = normalize_text(item["truth"])

    # 过滤出有真值的元数据项
    valid_metas = [m for m in meta_items if m["id"] in truth_map]

    print(f"\n=======================================================")
    print(f"正在全量提取与评测: {dataset_name} ({len(valid_metas)} 帧)")
    print(f"=======================================================")

    frames_data = []

    # 1. 抽取 5 帧并运行 OCR
    for m in valid_metas:
        fid = m["id"]
        v_ts = m.get("verified_ts")
        if v_ts is None:
            v_ts = m.get("clip_timestamp_sec", m.get("timestamp_sec"))
        truth_str = truth_map[fid]

        candidates = []
        for off in offsets:
            ts = round(v_ts + off, 3)
            crop = extract_crop_ffmpeg(video_path, ts)
            out = ocr_engine(crop) if crop is not None else None
            txt = ""
            box_width = 0.0
            if out and out.txts:
                # 修复后的拼接 (不插入空格)
                txt = normalize_text("".join([t.strip() for t in out.txts if t.strip()]))
                if out.boxes is not None and len(out.boxes) > 0:
                    widths = [np.linalg.norm(b[1] - b[0]) for b in out.boxes]
                    box_width = max(widths) if widths else 0.0

            candidates.append({
                "offset": off,
                "ts": ts,
                "text": txt,
                "box_width": float(box_width),
                "dist_to_truth": levenshtein_distance(txt, truth_str)
            })

        # 计算同组中位数长度
        lens = [len(c["text"]) for c in candidates if len(c["text"]) > 0]
        median_len = float(np.median(lens)) if lens else 0.0

        # 获取中心帧文本 (offset=0.0)
        center_cand = next(c for c in candidates if c["offset"] == 0.0)
        center_text = center_cand["text"]

        # 2. 执行 N4/N5 过滤判断
        valid_candidates = []
        discarded_candidates = []

        for c in candidates:
            sim_to_center = SequenceMatcher(None, c["text"], center_text).ratio() if center_text else 1.0
            degraded_reasons = check_degraded_reasons(c["text"], c["box_width"], median_len)
            
            # 邻帧有效性过滤 (相似度 < 0.60 则认为已切换台词)
            if c["offset"] != 0.0 and sim_to_center < 0.60:
                degraded_reasons.append("similarity_to_center_lt_0.60")

            c["sim_to_center"] = round(sim_to_center, 3)
            c["degraded_reasons"] = degraded_reasons

            if degraded_reasons:
                discarded_candidates.append(c)
            else:
                valid_candidates.append(c)

        # 3. M2 时序多数投票
        valid_texts = [c["text"] for c in valid_candidates if c["text"]]
        is_low_confidence = len(valid_texts) < 2

        if valid_texts:
            voted_text = align_and_vote(valid_texts)
        else:
            voted_text = center_text # 无法投票时回退到中心帧

        dist_voted = levenshtein_distance(voted_text, truth_str)

        # 4. N5 拒识三档策略度量
        # 检测中心帧是否命中拒识签名
        center_reasons = center_cand["degraded_reasons"]
        is_center_rejected = len(center_reasons) > 0

        # 档位 1: drop (若中心帧被拒识则留空)
        text_drop = "" if is_center_rejected else center_text
        dist_drop = levenshtein_distance(text_drop, truth_str)

        # 档位 2: retry (若中心帧被拒识，重试采用邻帧最优候选)
        if is_center_rejected and valid_texts:
            text_retry = valid_texts[0]
        else:
            text_retry = center_text
        dist_retry = levenshtein_distance(text_retry, truth_str)

        # 档位 3: vote (交给 M2 时序投票)
        text_vote = voted_text
        dist_vote = dist_voted

        frames_data.append({
            "id": fid,
            "verified_ts": v_ts,
            "truth": truth_str,
            "truth_len": len(truth_str),
            "candidates": candidates,
            "valid_candidates_count": len(valid_candidates),
            "discarded_candidates_count": len(discarded_candidates),
            "is_low_confidence": is_low_confidence,
            "center_text": center_text,
            "center_dist": center_cand["dist_to_truth"],
            "voted_text": voted_text,
            "voted_dist": dist_voted,
            "center_rejected": is_center_rejected,
            "rejection_strategies": {
                "drop": {"text": text_drop, "dist": dist_drop},
                "retry": {"text": text_retry, "dist": dist_retry},
                "vote": {"text": text_vote, "dist": dist_vote}
            }
        })

    # ==============================================================
    # 汇总计算指标
    # ==============================================================
    total_truth_chars = sum(f["truth_len"] for f in frames_data)

    # 1. 中心帧基线
    center_dist_total = sum(f["center_dist"] for f in frames_data)
    center_cer = calculate_cer(center_dist_total, total_truth_chars)
    center_correct = sum(1 for f in frames_data if f["center_dist"] == 0)

    # 2. 随机取 1 帧基线 (10000 次 Monte Carlo)
    rng = random.Random(42)
    mc_runs = 10000
    mc_dists = []
    for _ in range(mc_runs):
        run_dist = 0
        for f in frames_data:
            pick = rng.choice(f["candidates"])
            run_dist += pick["dist_to_truth"]
        mc_dists.append(run_dist)
    mc_expected_dist = float(np.mean(mc_dists))
    mc_expected_cer = calculate_cer(mc_expected_dist, total_truth_chars)

    # seed 42 固定单次随机
    rng_fixed = random.Random(42)
    seed42_dist = sum(rng_fixed.choice(f["candidates"])["dist_to_truth"] for f in frames_data)
    seed42_cer = calculate_cer(seed42_dist, total_truth_chars)

    # 3. 各单一时间偏移指标
    offset_stats = {}
    for off in offsets:
        off_dists = []
        for f in frames_data:
            c = next(cand for cand in f["candidates"] if cand["offset"] == off)
            off_dists.append(c["dist_to_truth"])
        tot_d = sum(off_dists)
        offset_stats[f"offset_{off:+.2f}s"] = {
            "total_dist": tot_d,
            "cer_percent": round(calculate_cer(tot_d, total_truth_chars) * 100, 2)
        }

    # 4. M2 时序投票指标
    voted_dist_total = sum(f["voted_dist"] for f in frames_data)
    voted_cer = calculate_cer(voted_dist_total, total_truth_chars)
    voted_correct = sum(1 for f in frames_data if f["voted_dist"] == 0)

    # 5. N5 拒识策略指标
    drop_dist_total = sum(f["rejection_strategies"]["drop"]["dist"] for f in frames_data)
    retry_dist_total = sum(f["rejection_strategies"]["retry"]["dist"] for f in frames_data)
    vote_dist_total = sum(f["rejection_strategies"]["vote"]["dist"] for f in frames_data)
    rejected_count = sum(1 for f in frames_data if f["center_rejected"])
    rejection_rate = rejected_count / len(frames_data)

    summary = {
        "dataset": dataset_name,
        "frames_count": len(frames_data),
        "total_truth_chars": total_truth_chars,
        "center_frame_baseline": {
            "edit_distance": center_dist_total,
            "cer_percent": round(center_cer * 100, 2),
            "fully_correct_count": center_correct
        },
        "random_pick_baseline": {
            "monte_carlo_expected_dist": round(mc_expected_dist, 2),
            "monte_carlo_expected_cer_percent": round(mc_expected_cer * 100, 2),
            "seed42_dist": seed42_dist,
            "seed42_cer_percent": round(seed42_cer * 100, 2)
        },
        "individual_offsets": offset_stats,
        "m2_temporal_voting": {
            "edit_distance": voted_dist_total,
            "cer_percent": round(voted_cer * 100, 2),
            "fully_correct_count": voted_correct,
            "improvement_over_center_cer_percent": round((center_cer - voted_cer) * 100, 2),
            "improvement_over_random_cer_percent": round((mc_expected_cer - voted_cer) * 100, 2)
        },
        "n5_rejection_strategies": {
            "rejected_frames_count": rejected_count,
            "rejection_rate_percent": round(rejection_rate * 100, 2),
            "drop_strategy": {
                "edit_distance": drop_dist_total,
                "cer_percent": round(calculate_cer(drop_dist_total, total_truth_chars) * 100, 2)
            },
            "retry_strategy": {
                "edit_distance": retry_dist_total,
                "cer_percent": round(calculate_cer(retry_dist_total, total_truth_chars) * 100, 2)
            },
            "vote_strategy": {
                "edit_distance": vote_dist_total,
                "cer_percent": round(calculate_cer(vote_dist_total, total_truth_chars) * 100, 2)
            }
        },
        "frames": frames_data
    }

    print(f"--- {dataset_name} 汇总结果 ---")
    print(f"总真值字符: {total_truth_chars}")
    print(f"中心帧基线 (verified_ts): 编辑距离 {center_dist_total} | CER: {summary['center_frame_baseline']['cer_percent']}% | 全对: {center_correct}/{len(frames_data)}")
    print(f"5 帧随机取 1 帧期望值:   期望距离 {summary['random_pick_baseline']['monte_carlo_expected_dist']} | CER: {summary['random_pick_baseline']['monte_carlo_expected_cer_percent']}%")
    print(f"M2 多数投票后:           编辑距离 {voted_dist_total} | CER: {summary['m2_temporal_voting']['cer_percent']}% | 全对: {voted_correct}/{len(frames_data)}")
    print(f"N5 拒识率:               {summary['n5_rejection_strategies']['rejection_rate_percent']}% ({rejected_count}/{len(frames_data)})")

    return summary

def main():
    ocr_engine = RapidOCR(params={"EngineConfig.onnxruntime.use_cuda": True})

    # 1. 12 帧长集 (truth_frames)
    long_summary = process_dataset(
        dataset_name="12_frames_long_set",
        meta_path=Path("bench/truth_frames/truth_metadata.json"),
        truth_path=Path("bench/truth_frames/truth_manual.json"),
        video_path="ocr_input/114877-720p.mp4",
        ocr_engine=ocr_engine
    )

    # 2. 15 帧短集 (truth_short)
    short_summary = process_dataset(
        dataset_name="15_frames_short_set",
        meta_path=Path("bench/truth_short/truth_metadata.json"),
        truth_path=Path("bench/truth_short/truth_manual.json"),
        video_path="ocr_input/test_3min.mp4",
        ocr_engine=ocr_engine
    )

    final_report = {
        "title": "AnimeAutoSub M2/M3 Full Pipeline Benchmark Report",
        "long_12_frames": long_summary,
        "short_15_frames": short_summary
    }

    out_path = Path("bench/m2_m3_final_report.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(final_report, f, ensure_ascii=False, indent=2)

    print(f"\n✓ 完整最终测试报告已写入 {out_path}")

if __name__ == "__main__":
    main()
