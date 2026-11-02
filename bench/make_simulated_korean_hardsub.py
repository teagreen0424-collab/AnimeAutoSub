import os
import json
import subprocess
from pathlib import Path

FFMPEG = r"D:\Dev\ffmpeg\bin\ffmpeg.exe"
SRC_VIDEO = Path("input/408309-1080p.mp4")

with open("bench/fixtures/korean_40_ground_truth.json", "r", encoding="utf-8") as f:
    items = json.load(f)

def format_ass_time(sec: float) -> str:
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    cs = int(round((sec - int(sec)) * 100))
    if cs >= 100:
        cs = 99
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

# 1. 编排时间轴 (每句 3.5s ~ 5.5s，间隔 1.0s)
cur_t = 2.0
timed_items = []

ass_events_1080p = []
ass_events_720p = []

for item in items:
    text = item["ko"]
    # 双行换行处理
    dur = 4.0 if len(text) < 25 else 6.0
    start_sec = cur_t
    end_sec = cur_t + dur
    cur_t = end_sec + 1.0
    
    start_str = format_ass_time(start_sec)
    end_str = format_ass_time(end_sec)
    
    timed_items.append({
        "id": item["id"],
        "category": item["category"],
        "start": round(start_sec, 2),
        "end": round(end_sec, 2),
        "ko": text,
        "zh": item["zh"]
    })
    
    ass_events_1080p.append(f"Dialogue: 0,{start_str},{end_str},Default,,0,0,0,,{text}")
    ass_events_720p.append(f"Dialogue: 0,{start_str},{end_str},Default,,0,0,0,,{text}")

total_duration_sec = int(cur_t + 2.0)
print(f"总时长: {total_duration_sec} 秒 ({total_duration_sec/60:.2f} 分钟)")

# 保存带时间戳真值
with open("bench/fixtures/korean_40_ground_truth_timed.json", "w", encoding="utf-8") as f:
    json.dump(timed_items, f, ensure_ascii=False, indent=2)

# 2. 生成 1080p ASS
header_1080p = f"""[Script Info]
Title: Korean Hardsub Simulation 1080p
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
PlayResX: 1920
PlayResY: 1080

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Malgun Gothic,58,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3.5,0.8,2,30,30,55,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
""" + "\n".join(ass_events_1080p) + "\n"

# 3. 生成 720p ASS
header_720p = f"""[Script Info]
Title: Korean Hardsub Simulation 720p
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
PlayResX: 1280
PlayResY: 720

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Malgun Gothic,39,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,2.5,0.5,2,20,20,36,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
""" + "\n".join(ass_events_720p) + "\n"

ass_path_1080p = Path("bench/fixtures/korean_simulated_1080p.ass")
ass_path_720p = Path("bench/fixtures/korean_simulated_720p.ass")

ass_path_1080p.write_text(header_1080p, encoding="utf-8")
ass_path_720p.write_text(header_720p, encoding="utf-8")
print(f"已生成 1080p 与 720p 韩语 ASS 模板")

# 4. 执行 FFmpeg 合成 1080p 与 720p 视频
out_1080p = Path("ocr_input/simulated_ko_1080p.mp4")
out_720p = Path("ocr_input/simulated_ko_720p.mp4")
out_1080p.parent.mkdir(parents=True, exist_ok=True)

# 1080p
esc_1080p = str(ass_path_1080p.resolve()).replace("\\", "/").replace(":", "\\:")
cmd_1080p = [
    FFMPEG, "-y",
    "-ss", "00:00:15",
    "-i", str(SRC_VIDEO),
    "-t", str(total_duration_sec),
    "-vf", f"subtitles='{esc_1080p}',smartblur=lr=0.5:ls=0.5",
    "-c:v", "libx264", "-preset", "fast", "-crf", "20",
    "-c:a", "aac", "-b:a", "128k",
    str(out_1080p)
]

print("正在渲染 1080p 韩语合成硬字幕视频 (预计 15~20 秒)...")
r1 = subprocess.run(cmd_1080p, capture_output=True, text=True)
if r1.returncode != 0:
    print("1080p 渲染失败:", r1.stderr[:500])
    exit(1)
print(f"✓ 1080p 视频生成成功: {out_1080p} ({out_1080p.stat().st_size / 1e6:.1f} MB)")

# 720p
esc_720p = str(ass_path_720p.resolve()).replace("\\", "/").replace(":", "\\:")
cmd_720p = [
    FFMPEG, "-y",
    "-ss", "00:00:15",
    "-i", str(SRC_VIDEO),
    "-t", str(total_duration_sec),
    "-vf", f"scale=1280:720,subtitles='{esc_720p}',smartblur=lr=0.5:ls=0.5",
    "-c:v", "libx264", "-preset", "fast", "-crf", "21",
    "-c:a", "aac", "-b:a", "128k",
    str(out_720p)
]

print("正在渲染 720p 韩语合成硬字幕视频 (预计 10~15 秒)...")
r2 = subprocess.run(cmd_720p, capture_output=True, text=True)
if r2.returncode != 0:
    print("720p 渲染失败:", r2.stderr[:500])
    exit(1)
print(f"✓ 720p 视频生成成功: {out_720p} ({out_720p.stat().st_size / 1e6:.1f} MB)")
