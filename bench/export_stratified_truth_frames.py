"""
K4: 全片等分 30 段均匀分层抽样与真值帧导出工具
==============================================
1. 按全片时长等分 30 段 (每段约 138.5 秒)；
2. 每段挑选 1 句台词，自动分类：叙述句 / 对白句 / 多行句；
3. 采用 K3 精准定位机制 (多点抽帧 + OCR 校验) 截取最佳画面；
4. 导出画面至 bench/truth_frames/stratified/frame_001.jpg ~ frame_030.jpg；
5. 生成配套真值标注模板 stratified_truth_template.md。
"""

import sys
import json
import random
from pathlib import Path
import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import animeautosub._env
from rapidocr import RapidOCR
from bench.fix_k3_frames import find_best_subtitle_frame

def classify_sentence(text: str, duration: float) -> str:
    """分类: 叙述句 / 对白句 / 多行句"""
    clean = text.strip()
    if "\n" in clean or len(clean) >= 32:
        return "多行句"
    if "「" in clean or "」" in clean or "『" in clean or "』" in clean or "：" in clean or ":" in clean:
        return "对白句"
    return "叙述句"

def main():
    ja_ref_path = Path("ocr_output/114877-720p/japanese.json")
    if not ja_ref_path.exists():
        ja_ref_path = Path("bench/fixtures/reference/ocr_720p/japanese.json")

    with open(ja_ref_path, "r", encoding="utf-8") as f:
        subs = json.load(f)

    video_duration = 4155.54  # 69分15秒
    num_segments = 30
    seg_len = video_duration / float(num_segments)

    out_dir = Path("bench/truth_frames/stratified")
    out_dir.mkdir(parents=True, exist_ok=True)

    ocr = RapidOCR(params={"EngineConfig.onnxruntime.use_cuda": True})

    # 固定随机种子确保抽样确定性
    rng = random.Random(42)

    selected_samples = []
    for i in range(num_segments):
        t_start = i * seg_len
        t_end = (i + 1) * seg_len

        # 找出落在此区间的台词
        in_seg = [s for s in subs if (s["start"] >= t_start and s["start"] < t_end) or (s["end"] > t_start and s["end"] <= t_end)]
        if not in_seg:
            # 若为空，找距离区间中心最近的台词
            mid = (t_start + t_end) / 2.0
            in_seg = sorted(subs, key=lambda s: abs((s["start"] + s["end"]) / 2.0 - mid))[:1]

        # 随机挑选 1 句
        chosen = rng.choice(in_seg)
        kind = classify_sentence(chosen["text"], chosen["end"] - chosen["start"])
        selected_samples.append({
            "seg_id": i + 1,
            "seg_time": f"{t_start:.1f}s - {t_end:.1f}s",
            "start": chosen["start"],
            "end": chosen["end"],
            "ref_text": chosen["text"],
            "kind": kind
        })

    print(f"=== 开始全片 30 段分层抽样导出 (共 {len(selected_samples)} 帧) ===")
    counts = {"叙述句": 0, "对白句": 0, "多行句": 0}
    for s in selected_samples:
        counts[s["kind"]] += 1
    print(f"类型分布: 叙述句={counts['叙述句']}, 对白句={counts['对白句']}, 多行句={counts['多行句']}")

    template_lines = [
        "# AnimeAutoSub · 30 帧全片均匀分层真值标注模板 (K4)",
        "",
        "> 按 69 分钟等分 30 段均匀采样，覆盖全片各类叙事与对话场景。",
        f"> 分类分布: 叙述句: {counts['叙述句']} 帧 | 对白句: {counts['对白句']} 帧 | 多行句: {counts['多行句']} 帧",
        "",
        "| 序号 | 图像文件 | 视频时间戳 | 类型 | 参考文本 (ref_text) | 回测OCR文本 | 【PO 人工转写真值】 |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |"
    ]

    exported_meta = []
    for i, item in enumerate(selected_samples):
        fid = i + 1
        fname = f"frame_{fid:03d}.jpg"
        fpath = out_dir / fname

        best_sec, best_roi, best_txt, best_sim, alert = find_best_subtitle_frame(
            item["start"], item["end"], item["ref_text"], ocr
        )

        if best_roi is not None:
            cv2.imwrite(str(fpath), best_roi)

        mm = int(best_sec // 60)
        ss = best_sec % 60
        time_str = f"{mm:02d}:{ss:05.2f}"

        ref_clean = item["ref_text"].replace("\n", " ").replace("|", " ")
        best_clean = best_txt.replace("\n", " ").replace("|", " ")
        alert_flag = " ⚠" if alert else ""

        template_lines.append(
            f"| {fid:03d} | [{fname}](stratified/{fname}) | `{time_str}` | {item['kind']} | {ref_clean} | {best_clean}{alert_flag} |  |"
        )

        exported_meta.append({
            "id": fid,
            "filename": fname,
            "timestamp_sec": best_sec,
            "time_str": time_str,
            "kind": item["kind"],
            "ref_text": item["ref_text"],
            "verified_ocr": best_txt,
            "ocr_sim": best_sim,
            "alert": alert
        })

        print(f"[{fid:02d}/30] {item['kind']:<4} | `{time_str}` | sim={best_sim*100:5.1f}% | ref: {ref_clean[:25]}")

    md_path = out_dir / "stratified_truth_template.md"
    md_path.write_text("\n".join(template_lines), encoding="utf-8")

    json_path = out_dir / "stratified_truth_metadata.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(exported_meta, f, ensure_ascii=False, indent=2)

    print("=" * 80)
    print(f"✓ 30 帧分层真值画面导出完成: {out_dir}/")
    print(f"✓ 模板文件已生成: {md_path}")
    print("=" * 80)

if __name__ == "__main__":
    main()
