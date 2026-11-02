import asyncio
import json
import subprocess
from pathlib import Path
import edge_tts

FFMPEG = r"D:\Dev\ffmpeg\bin\ffmpeg.exe"
VOICE = "ko-KR-SunHiNeural"

with open("bench/fixtures/korean_40_ground_truth.json", "r", encoding="utf-8") as f:
    items = json.load(f)[:20]  # 取前 20 句

temp_dir = Path("bench/fixtures/ko_tts_temp")
temp_dir.mkdir(parents=True, exist_ok=True)

out_audio = Path("input/simulated_ko_asr_20.mp3")
out_audio.parent.mkdir(parents=True, exist_ok=True)

async def generate_all():
    print(f"使用 Edge TTS ({VOICE}) 生成 20 句韩语基准音频...")
    segment_files = []
    
    for i, item in enumerate(items, 1):
        text = item["ko"]
        seg_path = temp_dir / f"seg_{i:02d}.mp3"
        comm = edge_tts.Communicate(text, VOICE)
        await comm.save(str(seg_path))
        segment_files.append((seg_path, text))
        print(f" [{i:02d}/20] TTS 生成完毕: '{text[:15]}...'")

    # 获取每段时长并拼接 (中间加 1.5 秒静音)
    # 用 FFmpeg 探测每个片段的时长
    timed_asr_records = []
    current_time = 1.0
    
    concat_list = temp_dir / "concat_list.txt"
    # 创建 1.5 秒静音 mp3
    silence_mp3 = temp_dir / "silence.mp3"
    subprocess.run([
        FFMPEG, "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", "1.5",
        "-c:a", "libmp3lame", "-b:a", "128k", str(silence_mp3)
    ], check=True, capture_output=True)

    concat_lines = []
    for i, (seg_file, text) in enumerate(segment_files, 1):
        # 探测时长
        probe = subprocess.run([
            FFMPEG, "-i", str(seg_file), "-hide_banner"
        ], capture_output=True, text=True, errors="replace")
        dur = 2.5
        for line in probe.stderr.splitlines():
            if "Duration:" in line:
                import re
                m = re.search(r'Duration:\s*(\d+):(\d+):(\d+\.\d+)', line)
                if m:
                    dur = int(m.group(1))*3600 + int(m.group(2))*60 + float(m.group(3))
                    break
        
        timed_asr_records.append({
            "id": i,
            "start": round(current_time, 2),
            "end": round(current_time + dur, 2),
            "ko": text
        })
        concat_lines.append(f"file '{silence_mp3.resolve()}'")
        concat_lines.append(f"file '{seg_file.resolve()}'")
        current_time += dur + 1.5

    concat_lines.append(f"file '{silence_mp3.resolve()}'")
    concat_list.write_text("\n".join(concat_lines), encoding="utf-8")

    # 拼接最终音频
    cmd_concat = [
        FFMPEG, "-y", "-f", "concat", "-safe", "0",
        "-i", str(concat_list),
        "-c:a", "libmp3lame", "-b:a", "128k",
        str(out_audio)
    ]
    subprocess.run(cmd_concat, check=True, capture_output=True)
    print(f"\n✓ 成功生成 20 句韩语 ASR 合成音频: {out_audio} (时长: {current_time:.1f} 秒)")

    # 保存真值标注
    truth_file = Path("bench/fixtures/korean_asr_20_ground_truth.json")
    with open(truth_file, "w", encoding="utf-8") as f:
        json.dump(timed_asr_records, f, ensure_ascii=False, indent=2)
    print(f"✓ 成功保存带时间轴参考转写: {truth_file}")

if __name__ == "__main__":
    asyncio.run(generate_all())
