import os
import sys
import re
import json
import logging
import subprocess
import numpy as np
import cv2
from pathlib import Path

# 确保导入路径
sys.path.insert(0, ".")

from lang import get_language
from core.context import PipelineContext
from core.stages.layout_ass import LayoutAssStage
import pipeline_ocr

FFMPEG_PATH = r"D:\Dev\ffmpeg\bin\ffmpeg.exe"

def parse_ass_dialogues(ass_content: str):
    """解析 ASS 中的所有事件行：提取文本、坐标、遮罩几何"""
    mask_pat = re.compile(r'\\pos\((\d+),(\d+)\)[^}]*\}m 0 0 l (\d+) 0 l (\d+) (\d+) l 0 (\d+)\{\\p0\}')
    text_pat = re.compile(r'\\pos\((\d+),(\d+)\)\}(.*)$')
    
    masks = []
    texts = []
    
    for line in ass_content.splitlines():
        line = line.strip()
        if not line.startswith("Dialogue:"):
            continue
        parts = line.split(",", 9)
        if len(parts) < 10:
            continue
        style = parts[3]
        payload = parts[9]
        start = parts[1]
        end = parts[2]
        
        if style == "Mask":
            m = mask_pat.search(payload)
            if m:
                masks.append({
                    "start": start, "end": end,
                    "x": int(m.group(1)), "y": int(m.group(2)),
                    "w": int(m.group(3)), "h": int(m.group(5))
                })
        else:
            m = text_pat.search(payload)
            if m:
                texts.append({
                    "start": start, "end": end,
                    "x": int(m.group(1)), "y": int(m.group(2)),
                    "text": m.group(3)
                })
            else:
                texts.append({
                    "start": start, "end": end,
                    "x": None, "y": None,
                    "text": payload
                })
    return masks, texts

def compare_ass_structures(old_ass_path: Path, new_ass_path: Path, desc: str):
    with open(old_ass_path, "r", encoding="utf-8") as f:
        old_content = f.read()
    with open(new_ass_path, "r", encoding="utf-8") as f:
        new_content = f.read()
        
    old_masks, old_texts = parse_ass_dialogues(old_content)
    new_masks, new_texts = parse_ass_dialogues(new_content)
    
    print(f"\n[{desc}] ASS 结构比对:")
    print(f"  旧版遮罩数: {len(old_masks)}, 新版遮罩数: {len(new_masks)}")
    print(f"  旧版对白数: {len(old_texts)}, 新版对白数: {len(new_texts)}")
    
    assert len(old_texts) == len(new_texts), f"对白行数不一致: {len(old_texts)} vs {len(new_texts)}"
    assert len(old_masks) == len(new_masks), f"遮罩行数不一致: {len(old_masks)} vs {len(new_masks)}"
    
    # 1. 文本逐条一致性
    text_mismatches = 0
    for i, (ot, nt) in enumerate(zip(old_texts, new_texts)):
        if ot["text"] != nt["text"]:
            text_mismatches += 1
            print(f"  ❌ 文本不一致 #{i}: '{ot['text']}' vs '{nt['text']}'")
    
    print(f"  ✓ 文本一致性: {len(old_texts) - text_mismatches}/{len(old_texts)} 逐条一致 (差异数: {text_mismatches})")
    assert text_mismatches == 0, f"文本存在 {text_mismatches} 条不一致！"
    
    # 2. 对白坐标误差
    max_coord_diff = 0
    for i, (ot, nt) in enumerate(zip(old_texts, new_texts)):
        if ot["x"] is not None and nt["x"] is not None:
            dx = abs(ot["x"] - nt["x"])
            dy = abs(ot["y"] - nt["y"])
            max_coord_diff = max(max_coord_diff, dx, dy)
            if max(dx, dy) > 2:
                print(f"  ❌ 对白坐标偏差超标 #{i}: dx={dx}, dy={dy}")
                
    # 3. 遮罩坐标与尺寸误差
    max_mask_diff = 0
    for i, (om, nm) in enumerate(zip(old_masks, new_masks)):
        dx = abs(om["x"] - nm["x"])
        dy = abs(om["y"] - nm["y"])
        dw = abs(om["w"] - nm["w"])
        dh = abs(om["h"] - nm["h"])
        max_mask_diff = max(max_mask_diff, dx, dy, dw, dh)
        if max(dx, dy, dw, dh) > 2:
            print(f"  ❌ 遮罩几何偏差超标 #{i}: dx={dx}, dy={dy}, dw={dw}, dh={dh}")
            
    print(f"  ✓ 对白坐标最大偏差: {max_coord_diff} px (门槛 <= 2px)")
    print(f"  ✓ 遮罩几何最大偏差: {max_mask_diff} px (门槛 <= 2px)")
    assert max_coord_diff <= 2, f"对白坐标偏差超标: {max_coord_diff}px > 2px"
    assert max_mask_diff <= 2, f"遮罩几何偏差超标: {max_mask_diff}px > 2px"
    return True

def run_regression_60():
    print("=" * 60)
    print("  回归项 1: 60 句评测集纯确定性回归")
    print("=" * 60)
    
    fixture_path = Path("bench/fixtures/60_sentences_frozen_fixture.json")
    with open(fixture_path, "r", encoding="utf-8") as f:
        frozen_data = json.load(f)
        
    out_dir = Path("bench/fixtures/regression_60")
    out_dir.mkdir(parents=True, exist_ok=True)
    
    # 1. 旧逻辑生成
    old_ass, old_srt = pipeline_ocr.generate_subtitles(
        frozen_data, out_dir, video_width=1920, video_height=1080
    )
    old_ass_target = out_dir / "old_subtitle.ass"
    if old_ass_target.exists():
        old_ass_target.unlink()
    if old_ass.exists():
        old_ass.rename(old_ass_target)
        
    # 2. 新逻辑生成
    # 将 frozen_data 写入新目录作为 chinese.json
    new_dir = out_dir / "new_stage"
    new_dir.mkdir(parents=True, exist_ok=True)
    with open(new_dir / "chinese.json", "w", encoding="utf-8") as f:
        json.dump(frozen_data, f, ensure_ascii=False, indent=2)
        
    ctx = PipelineContext(
        video_path=Path("ocr_input/simulated_1080p_fansub.mp4"),
        work_dir=new_dir,
        output_dir=new_dir,
        lang=get_language("ja"),
        mode="ocr"
    )
    
    stage = LayoutAssStage()
    stage.run(ctx, logging.getLogger("Test"))
    
    new_ass_target = new_dir / "subtitle.ass"
    compare_ass_structures(old_ass_target, new_ass_target, "60 句评测集")
    print("  🎉 60 句评测集回归通过！")

def run_regression_10min():
    print("\n" + "=" * 60)
    print("  回归项 2: 全片前 10 分钟真实视频素材回归 (114877-720p)")
    print("=" * 60)
    
    src_chinese = Path("ocr_output/114877-720p/chinese.json")
    assert src_chinese.exists(), f"未找到基准数据: {src_chinese}"
    
    with open(src_chinese, "r", encoding="utf-8") as f:
        full_data = json.load(f)
        
    # 截取前 10 分钟 (start <= 600.0)
    data_10min = [x for x in full_data if x["start"] <= 600.0]
    print(f"  截取前 10 分钟字幕条目数: {len(data_10min)} (原片共 {len(full_data)} 句)")
    
    out_dir = Path("bench/fixtures/regression_10min")
    out_dir.mkdir(parents=True, exist_ok=True)
    
    # 1. 旧逻辑生成
    old_ass, _ = pipeline_ocr.generate_subtitles(
        data_10min, out_dir, video_width=1280, video_height=720
    )
    old_ass_target = out_dir / "old_subtitle.ass"
    if old_ass_target.exists():
        old_ass_target.unlink()
    if old_ass.exists():
        old_ass.rename(old_ass_target)
        
    # 2. 新逻辑生成
    new_dir = out_dir / "new_stage"
    new_dir.mkdir(parents=True, exist_ok=True)
    with open(new_dir / "chinese.json", "w", encoding="utf-8") as f:
        json.dump(data_10min, f, ensure_ascii=False, indent=2)
        
    ctx = PipelineContext(
        video_path=Path("ocr_input/114877-720p.mp4"),
        work_dir=new_dir,
        output_dir=new_dir,
        lang=get_language("ja"),
        mode="ocr"
    )
    
    stage = LayoutAssStage()
    stage.run(ctx, logging.getLogger("Test"))
    
    new_ass_target = new_dir / "subtitle.ass"
    compare_ass_structures(old_ass_target, new_ass_target, "前 10 分钟真实素材")
    
    # 3. 抽 10 帧图像像素差检验
    print("\n  抽 10 帧图像像素差检验 (门槛 < 0.5%):")
    video_file = Path("ocr_input/114877-720p.mp4")
    
    # 选择 10 个有对白的时间戳
    sample_segs = data_10min[::max(1, len(data_10min)//10)][:10]
    sample_timestamps = [(s["start"] + s["end"]) / 2.0 for s in sample_segs]
    
    frame_diffs = []
    
    old_ass_esc = str(old_ass_target.resolve()).replace("\\", "/").replace(":", "\\:")
    new_ass_esc = str(new_ass_target.resolve()).replace("\\", "/").replace(":", "\\:")
    
    for idx, ts in enumerate(sample_timestamps, 1):
        old_img_path = out_dir / f"frame_{idx:02d}_old.png"
        new_img_path = out_dir / f"frame_{idx:02d}_new.png"
        
        # 渲染旧 ASS 单帧
        cmd_old = [
            FFMPEG_PATH, "-y", "-ss", f"{ts:.2f}", "-i", str(video_file),
            "-vf", f"subtitles='{old_ass_esc}'",
            "-vframes", "1", "-v", "error", str(old_img_path)
        ]
        subprocess.run(cmd_old, check=True)
        
        # 渲染新 ASS 单帧
        cmd_new = [
            FFMPEG_PATH, "-y", "-ss", f"{ts:.2f}", "-i", str(video_file),
            "-vf", f"subtitles='{new_ass_esc}'",
            "-vframes", "1", "-v", "error", str(new_img_path)
        ]
        subprocess.run(cmd_new, check=True)
        
        # 比较像素差异
        im_old = cv2.imread(str(old_img_path))
        im_new = cv2.imread(str(new_img_path))
        
        diff = cv2.absdiff(im_old, im_new)
        # 计算不同像素占比 (差值 > 10 的像素数量 / 总像素数)
        non_zero = np.count_nonzero(diff > 10)
        total_pixels = im_old.shape[0] * im_old.shape[1] * im_old.shape[2]
        ratio = (non_zero / total_pixels) * 100.0
        frame_diffs.append(ratio)
        print(f"    帧 #{idx:02d} at {ts:.1f}s -> 像素差异率: {ratio:.4f}%")
        
    mean_diff = float(np.mean(frame_diffs))
    max_diff = float(np.max(frame_diffs))
    print(f"\n  ✓ 10 帧均值像素差异: {mean_diff:.4f}% (门槛 < 0.5%)")
    print(f"  ✓ 10 帧最大像素差异: {max_diff:.4f}% (门槛 < 0.5%)")
    
    assert max_diff < 0.5, f"10 帧最大像素差异超标: {max_diff:.4f}% >= 0.5%"
    print("  🎉 前 10 分钟真实视频素材回归通过！")

if __name__ == "__main__":
    run_regression_60()
    run_regression_10min()
