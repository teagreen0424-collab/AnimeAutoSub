import os
import subprocess
from pathlib import Path

FFMPEG = r"D:\Dev\ffmpeg\bin\ffmpeg.exe"

# 1. 编写 1080p 压制组风格 ASS 字幕
ass_content = """[Script Info]
Title: Fansub 1080p Hardsub Simulation
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709
PlayResX: 1920
PlayResY: 1080

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Meiryo,54,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,4,1,2,30,30,50,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:02.00,0:00:07.00,Default,,0,0,0,,今夜の風は、ずいぶんと冷たいですね。
Dialogue: 0,0:00:08.00,0:00:14.00,Default,,0,0,0,,私たちはいつだって、本当の気持ちを隠して笑っているんだ。
Dialogue: 0,0:00:16.00,0:00:23.00,Default,,0,0,0,,たとえ世界中が君の敵になったとしても、\\N私はずっと君の味方でいると誓うよ。
Dialogue: 0,0:00:25.00,0:00:32.00,Default,,0,0,0,,あの日の約束を覚えていますか？\\N桜が散る頃に、もう一度ここで会おうと言ったことを。
Dialogue: 0,0:00:34.00,0:00:40.00,Default,,0,0,0,,そんな顔をしないでくれ、頼むから！
Dialogue: 0,0:00:42.00,0:00:50.00,Default,,0,0,0,,「これで終わりじゃない、ここからが始まりだ」\\Nそう強く自分に言い聞かせていた。
Dialogue: 0,0:00:52.00,0:00:58.00,Default,,0,0,0,,明日になれば、きっとすべてが変わるはずだから。
"""

ass_path = Path("bench/fixtures/fansub_1080p.ass")
ass_path.parent.mkdir(parents=True, exist_ok=True)
ass_path.write_text(ass_content, encoding="utf-8")
print(f"已生成 1080p 压制组 ASS 字幕: {ass_path}")

# 2. 从 input/408309-1080p.mp4 截取 60 秒，并压制硬字幕与轻微模糊
src_video = Path("input/408309-1080p.mp4")
out_video = Path("ocr_input/simulated_1080p_fansub.mp4")
out_video.parent.mkdir(parents=True, exist_ok=True)

# FFmpeg 滤镜字符串处理 (Windows 路径反斜杠转义)
escaped_ass = str(ass_path.resolve()).replace("\\", "/").replace(":", "\\:")
vf_filter = f"subtitles='{escaped_ass}',smartblur=lr=0.5:ls=0.5"

cmd = [
    FFMPEG, "-y",
    "-ss", "00:00:10",
    "-i", str(src_video),
    "-t", "60",
    "-vf", vf_filter,
    "-c:v", "libx264",
    "-preset", "fast",
    "-crf", "19",
    "-c:a", "aac",
    "-b:a", "192k",
    str(out_video)
]

print(f"正在执行 FFmpeg 合成 1080p 压制组硬字幕素材...")
res = subprocess.run(cmd, capture_output=True, text=True)
if res.returncode != 0:
    print(f"FFmpeg 失败:\n{res.stderr}")
    exit(1)

print(f"成功生成 1080p 压制组素材: {out_video} (大小: {out_video.stat().st_size / 1024 / 1024:.2f} MB)")
