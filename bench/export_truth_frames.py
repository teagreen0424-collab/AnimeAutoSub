"""
I7: 从真实 720p 素材 (114877-720p.mp4) 导出 30 帧字幕区裁图
===========================================================
从全片 782 句硬字幕中均匀挑选 30 句代表性台词的中心帧，
导出底部 28% 字幕区画面至 bench/truth_frames/frame_001.jpg ~ frame_030.jpg，
并生成 truth_template.md 供 PO 进行人工转写真值标注。
"""

import json
import cv2
from pathlib import Path

def main():
    video_path = Path("ocr_input/114877-720p.mp4")
    ja_ref_path = Path("bench/fixtures/reference/ocr_720p/japanese.json")
    if not ja_ref_path.exists():
        ja_ref_path = Path("ocr_output/114877-720p/japanese.json")

    with open(ja_ref_path, "r", encoding="utf-8") as f:
        ja_data = json.load(f)

    # 均匀挑选 30 句台词
    total_subs = len(ja_data)
    step = total_subs / 30.0
    selected_indices = [int(i * step) for i in range(30)]
    selected_subs = [ja_data[i] for i in selected_indices]

    out_dir = Path("bench/truth_frames")
    out_dir.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(str(video_path))
    video_fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    roi_top = int(h * (1.0 - 0.28))

    template_lines = [
        "# AnimeAutoSub · 30 帧硬字幕人工转写真值模板 (bench/truth_frames/)",
        "",
        "> 请 PO 在每帧对应的 `【人工转写真值】` 栏填写准确文字（包含标点符号）。",
        "",
        "| 序号 | 图像文件 | 视频时间戳 | 旧代码参考输出 | 【PO 人工转写真值】 |",
        "| :--- | :--- | :--- | :--- | :--- |"
    ]

    exported = []
    for i, item in enumerate(selected_subs):
        fid = i + 1
        mid_sec = (item["start"] + item["end"]) / 2.0
        frame_idx = int(mid_sec * video_fps)
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = cap.read()
        if not ret:
            continue
        roi = frame[roi_top:h, 0:w]

        fname = f"frame_{fid:03d}.jpg"
        fpath = out_dir / fname
        cv2.imwrite(str(fpath), roi)

        mm = int(mid_sec // 60)
        ss = mid_sec % 60
        time_str = f"{mm:02d}:{ss:05.2f}"
        ref_text = item.get("text", "")

        template_lines.append(f"| {fid:03d} | [{fname}]({fname}) | `{time_str}` ({mid_sec:.2f}s) | {ref_text} |  |")
        exported.append({
            "id": fid,
            "filename": fname,
            "timestamp_sec": mid_sec,
            "time_str": time_str,
            "ref_text": ref_text
        })

    cap.release()

    md_path = out_dir / "truth_template.md"
    md_path.write_text("\n".join(template_lines), encoding="utf-8")

    json_path = out_dir / "truth_metadata.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(exported, f, ensure_ascii=False, indent=2)

    print(f"成功导出 30 帧裁图至 {out_dir}/")
    print(f"已生成真值标注模板: {md_path}")

if __name__ == "__main__":
    main()
