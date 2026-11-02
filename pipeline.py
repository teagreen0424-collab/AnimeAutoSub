"""
日漫全自动中文字幕流水线
========================
用法：
  1. 把视频放入 input/ 文件夹
  2. 双击 run.bat（或命令行运行 python pipeline.py）
  3. 从 output/ 文件夹取走成品

管线流程：
  输入视频 → 音频提取 → 人声分离 → 日语识别 → 中文翻译 → 字幕生成 → 封装/压制

每个阶段都有中间文件保存，中断后重新运行会自动从断点继续。
"""

import animeautosub._env  # 必须在最顶层导入，注入 D:\Dev 路径约束与 Windows DLL 绑定

import subprocess
import json
import sys
import os
import gc
import re
import time
import shutil
import logging
import requests
from pathlib import Path
from datetime import datetime

from config import (
    PROJECT_DIR, INPUT_DIR, OUTPUT_DIR, GLOSSARY_DIR,
    FFMPEG_PATH,
    DEMUCS_MODEL,
    WHISPER_MODEL, WHISPER_COMPUTE_TYPE, WHISPER_BEAM_SIZE, WHISPER_VAD_ENABLED,
    WHISPER_INITIAL_PROMPT, WHISPER_CONDITION_ON_PREV, WHISPER_TEMPERATURE,
    VAD_MIN_SILENCE_MS, VAD_SPEECH_PAD_MS,
    MERGE_SHORT_SEGMENTS, MERGE_MAX_GAP_SEC, MERGE_MAX_LEN_CHARS, MERGE_MAX_DURATION_SEC,
    AUTO_WRAP_SUBTITLE, SUBTITLE_MAX_LINE_CHARS,
    OLLAMA_API_URL, SAKURA_MODEL_NAME, CONTEXT_LINES,
    TEMPERATURE, TOP_P, MAX_RETRIES, SAKURA_SYSTEM_PROMPT,
    OUTPUT_MODE,
    SUBTITLE_FONT, SUBTITLE_FONTSIZE, SUBTITLE_BOLD,
    SUBTITLE_OUTLINE, SUBTITLE_SHADOW, SUBTITLE_MARGIN_V,
    HARDCODED_CRF, HARDCODED_PRESET,
    VIDEO_EXTENSIONS,
)


# ======================================================================
#                              日志配置
# ======================================================================

def setup_logging():
    """配置日志：同时输出到控制台和文件"""
    log_dir = PROJECT_DIR / "logs"
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / f"{datetime.now():%Y%m%d_%H%M%S}.log"

    formatter = logging.Formatter(
        "%(asctime)s │ %(message)s", datefmt="%H:%M:%S"
    )

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(file_handler)
    root.addHandler(console_handler)

    return log_file


# ======================================================================
#                            依赖检查
# ======================================================================

def check_ffmpeg():
    """检查 FFmpeg 是否可用"""
    try:
        r = subprocess.run(
            [FFMPEG_PATH, "-version"],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode == 0:
            version_line = r.stdout.split("\n")[0]
            logging.info(f"  ✓ FFmpeg: {version_line.strip()}")
            return True
    except FileNotFoundError:
        pass
    except Exception:
        pass
    logging.error("  ✗ 未检测到 FFmpeg！")
    logging.error("    下载: https://www.gyan.dev/ffmpeg/builds/")
    logging.error("    解压后把 bin 目录加入系统 PATH 环境变量")
    return False


def check_ollama():
    """检查 Ollama 是否在运行、模型是否已加载；若未启动则自动在后台静默拉起"""
    ollama_exe = Path(r"D:\Dev\ollama\ollama.exe")
    
    # 先探测当前是否已经有 Ollama 服务在监听 (统一使用 127.0.0.1 避免 IPv6 超时)
    try:
        r = requests.get("http://127.0.0.1:11434/api/tags", timeout=3)
        if r.status_code == 200:
            models = [m["name"] for m in r.json().get("models", [])]
            if any(SAKURA_MODEL_NAME in m for m in models):
                logging.info(f"  ✓ Ollama 服务运行中，模型 [{SAKURA_MODEL_NAME}] 已就绪")
                return True
    except Exception:
        pass

    # 若未启动且本地存在 ollama.exe，自动在后台拉起
    if ollama_exe.exists():
        logging.info("  → 检测到本地 Ollama 服务未运行，正在自动启动后台服务...")
        env = os.environ.copy()
        env["OLLAMA_MODELS"] = r"D:\Dev\ollama\models"
        DETACHED_PROCESS = 0x00000008
        subprocess.Popen(
            [str(ollama_exe), "serve"],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=DETACHED_PROCESS if os.name == 'nt' else 0
        )
        # 等待服务就绪（最多等待 15 秒）
        for _ in range(15):
            time.sleep(1)
            try:
                r = requests.get("http://127.0.0.1:11434/api/tags", timeout=2)
                if r.status_code == 200:
                    models = [m["name"] for m in r.json().get("models", [])]
                    if any(SAKURA_MODEL_NAME in m for m in models):
                        logging.info(f"  ✓ Ollama 后台服务已自动拉起，模型 [{SAKURA_MODEL_NAME}] 已就绪")
                        return True
                    else:
                        logging.error(f"  ✗ Ollama 已启动，但未找到模型 [{SAKURA_MODEL_NAME}]（已有模型: {models}）")
                        return False
            except Exception:
                continue

    logging.error("  ✗ 无法连接 Ollama (127.0.0.1:11434)，且未能自动拉起")
    return False


def check_gpu():
    """检查 GPU 可用性"""
    try:
        import torch
        if torch.cuda.is_available():
            name = torch.cuda.get_device_name(0)
            vram = torch.cuda.get_device_properties(0).total_memory / (1024**3)
            logging.info(f"  ✓ GPU: {name} ({vram:.1f} GB)")
            return "cuda"
        else:
            logging.warning("  ⚠ 未检测到 CUDA GPU，将使用 CPU 模式（速度会很慢）")
            return "cpu"
    except ImportError:
        logging.warning("  ⚠ PyTorch 未安装 CUDA 版本，将使用 CPU 模式")
        return "cpu"


def check_dependencies():
    """运行前检查所有依赖"""
    logging.info("=" * 50)
    logging.info("  环境检查")
    logging.info("=" * 50)

    ok = True
    device = check_gpu()
    if not check_ffmpeg():
        ok = False
    if not check_ollama():
        ok = False

    # 检查 Python 包
    missing = []
    for pkg in ["faster_whisper", "demucs", "pysubs2"]:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)
    if missing:
        logging.error(f"  ✗ 缺少 Python 包: {missing}")
        logging.error("    请运行: pip install " + " ".join(missing))
        ok = False
    else:
        logging.info("  ✓ Python 依赖齐全")

    if not ok:
        logging.error("")
        logging.error("  依赖检查未通过，请修复上述问题后重新运行")
        sys.exit(1)

    logging.info("")
    return device


# ======================================================================
#                     Stage 1: 音频提取 (FFmpeg)
# ======================================================================

def extract_audio(video_path: Path, work_dir: Path) -> Path:
    """从视频中提取音频为 16kHz 单声道 WAV（ASR 所需格式）"""
    audio_path = work_dir / "audio.wav"
    if audio_path.exists():
        logging.info("    ✓ 音频文件已存在，跳过")
        return audio_path

    logging.info("    → 提取音频中...")
    cmd = [
        FFMPEG_PATH,
        "-i", str(video_path),
        "-vn",                       # 丢弃视频流
        "-acodec", "pcm_s16le",      # 16-bit PCM
        "-ar", "16000",              # 16 kHz（Whisper 标准输入采样率）
        "-ac", "1",                  # 单声道
        "-y",                        # 覆盖已有文件
        str(audio_path),
    ]
    env = os.environ.copy()
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg 音频提取失败:\n{result.stderr[-800:]}")

    size_mb = audio_path.stat().st_size / (1024 * 1024)
    logging.info(f"    ✓ 音频提取完成 ({size_mb:.1f} MB)")
    return audio_path


# ======================================================================
#                  Stage 2: 人声分离 (Demucs)
# ======================================================================

def separate_vocals(audio_path: Path, work_dir: Path, device: str) -> Path:
    """用 Demucs 将人声从 BGM/音效中分离出来"""
    vocals_path = work_dir / "vocals.wav"
    if vocals_path.exists():
        logging.info("    ✓ 人声文件已存在，跳过")
        return vocals_path

    logging.info("    → 分离人声中（约需 30~90 秒）...")
    demucs_out = work_dir / "_demucs_temp"

    cmd = [
        sys.executable, "-m", "demucs",
        "-n", DEMUCS_MODEL,
        "--two-stems", "vocals",     # 只分人声 + 伴奏两轨
        "-d", device,
        "-o", str(demucs_out),
        str(audio_path),
    ]
    env = os.environ.copy()
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if result.returncode != 0:
        raise RuntimeError(f"Demucs 人声分离失败:\n{result.stderr[-800:]}")

    # Demucs 输出路径: _demucs_temp/<model>/<filename>/vocals.wav
    found = None
    for p in demucs_out.rglob("vocals.wav"):
        found = p
        break

    if found is None:
        raise RuntimeError("Demucs 完成但未找到 vocals.wav 输出文件")

    shutil.move(str(found), str(vocals_path))
    shutil.rmtree(str(demucs_out), ignore_errors=True)

    logging.info("    ✓ 人声分离完成")
    return vocals_path


# ======================================================================
#              Stage 3: 日语 ASR 识别 (faster-whisper)
# ======================================================================

def clean_repetitive_audio_screams(text: str) -> tuple:
    """
    清洗并规范长字符尖叫/呻吟字符墙（如 あああああああ...）：
    返回: (处理后的文本, 是否为纯尖叫)
    如果整句几乎全是纯尖叫，直接返回 ("（呻吟/喘息）", True)，后续翻译直接短路返回，永不超时！
    如果是长句夹杂拉长音，把重复压缩为 2 次。
    """
    stripped = text.strip()
    if not stripped:
        return text, False

    # 匹配连续 5 个以上相同的日文字符
    repeat_pattern = re.compile(r'([あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほまみむめもやゆよらりるれろわをんアイウエオカキクケコサシスセソタチツテトナニヌネノハヒフヘホマミムメモヤユヨラリルレロワヲンぁぃぅぇぉっゃゅょァィゥェォッャュョ])\1{4,}')

    matches = repeat_pattern.findall(stripped)
    if matches or (len(set(stripped)) <= 3 and len(stripped) >= 8):
        # 如果整句长度很长（>=8字）但用字极其单一，属于狂暴尖叫/呻吟字符墙
        if len(stripped) >= 8 and (len(set(stripped)) <= 4 or len(repeat_pattern.sub('', stripped)) <= 3):
            return "（呻吟/喘息）", True

        # 否则把超过 3 次的重复压缩为 2 次（例如“あああ、ダメ…”压缩为“ああ、ダメ…”）
        compressed = re.sub(r'([^\s0-9A-Za-z])\1{3,}', r'\1\1', stripped)
        return compressed, False

    return stripped, False


def auto_wrap_subtitle(text: str, max_chars: int = SUBTITLE_MAX_LINE_CHARS) -> str:
    """
    智能字幕双行折行排版（日漫/美剧字幕组黄金标准）：
    当单句中文字数超过 max_chars 时，优先寻找最靠近正中位置的标点符号断行。
    """
    if not AUTO_WRAP_SUBTITLE or len(text) <= max_chars or "\\N" in text or "\n" in text:
        return text

    puncts = ['。', '！', '？', '!', '?', '，', ',', '…', '、', ' ']
    mid = len(text) // 2
    best_idx = -1
    best_dist = 999

    for i, ch in enumerate(text):
        if ch in puncts:
            dist = abs(i - mid)
            if dist < best_dist:
                best_dist = dist
                best_idx = i + 1  # 断在标点之后

    # 如果找到合适合理的断点（两边都至少有 4 个字）
    if best_idx != -1 and 4 <= best_idx <= len(text) - 4:
        first_line = text[:best_idx].strip()
        second_line = text[best_idx:].strip()
        return f"{first_line}\\N{second_line}"

    # 如果整句话没有任何标点符号，且极长，则在正中间安全切开
    if len(text) >= max_chars + 4:
        return f"{text[:mid]}\\N{text[mid:]}"

    return text


def merge_and_clean_segments(raw_segments: list) -> list:
    """
    智能合并被 ASR/VAD 切得过碎的相邻日语句子：
    1. 过滤纯拟声词/极短喘息声残余
    2. 如果上一句末尾没有句意终结符（。！？!?…），且与下一句的时间间隔小于阈值，
       且合并后总时长与字数合理，则自动合并为完整的一句话。
    """
    if not raw_segments or not MERGE_SHORT_SEGMENTS:
        return raw_segments

    END_PUNCT = {"。", "！", "？", "!", "?", "…"}
    noise_tokens = {"あっ", "ん", "うっ", "はぁ", "ふぅ", "くっ", "あ", "え", "お"}

    cleaned = []
    for seg in raw_segments:
        text = seg["text"].strip()
        if not text:
            continue
        # 极短且内容仅为叹气声的片段，避免单独产生翻译幻觉
        if text in noise_tokens and (seg["end"] - seg["start"] < 0.35):
            continue
        cleaned.append(dict(seg))

    if not cleaned:
        return raw_segments

    merged = [cleaned[0]]
    for curr in cleaned[1:]:
        prev = merged[-1]
        gap = curr["start"] - prev["end"]
        duration = curr["end"] - prev["start"]
        combined_len = len(prev["text"]) + len(curr["text"])

        prev_has_end = any(prev["text"].endswith(p) for p in END_PUNCT)

        # 满足以下条件时执行合并：
        # 1. 时间间隔紧凑 (<= MERGE_MAX_GAP_SEC)
        # 2. 前一句尚未结束，或者前句短于4个字（如连词、感叹）
        # 3. 合并后单句长度和时长在合适字幕范围内
        should_merge = (
            gap <= MERGE_MAX_GAP_SEC
            and (not prev_has_end or len(prev["text"]) <= 3)
            and duration <= MERGE_MAX_DURATION_SEC
            and combined_len <= MERGE_MAX_LEN_CHARS
        )

        if should_merge:
            # 拼接文本
            if not prev["text"].endswith(("、", " ", "，")):
                prev["text"] = prev["text"] + " " + curr["text"]
            else:
                prev["text"] = prev["text"] + curr["text"]
            prev["end"] = curr["end"]
        else:
            merged.append(curr)

    return merged


def transcribe_audio(vocals_path: Path, work_dir: Path, device: str) -> list:
    """用 faster-whisper 将人声音频转录为带时间戳的日语文本"""
    ja_path = work_dir / "japanese.json"
    if ja_path.exists():
        logging.info("    ✓ 日语转录已存在，跳过")
        with open(ja_path, "r", encoding="utf-8") as f:
            return json.load(f)

    logging.info(f"    → 加载 Whisper {WHISPER_MODEL} ({WHISPER_COMPUTE_TYPE})...")

    from faster_whisper import WhisperModel

    model = WhisperModel(
        WHISPER_MODEL,
        device=device,
        compute_type=WHISPER_COMPUTE_TYPE if device == "cuda" else "int8",
    )

    logging.info("    → 识别日语语音中 (启用二次元 Prompt 引导与防幻觉调优)...")
    segments_iter, info = model.transcribe(
        str(vocals_path),
        language="ja",
        beam_size=WHISPER_BEAM_SIZE,
        initial_prompt=WHISPER_INITIAL_PROMPT,
        condition_on_previous_text=WHISPER_CONDITION_ON_PREV,
        temperature=WHISPER_TEMPERATURE,
        vad_filter=WHISPER_VAD_ENABLED,
        vad_parameters=dict(
            min_silence_duration_ms=VAD_MIN_SILENCE_MS,
            speech_pad_ms=VAD_SPEECH_PAD_MS,
        ),
    )

    raw_segments = []
    for seg in segments_iter:
        text = seg.text.strip()
        if text and text not in ("。", "、", "...", "…"):  # 跳过空/纯标点段
            raw_segments.append({
                "start": round(seg.start, 3),
                "end":   round(seg.end, 3),
                "text":  text,
            })

    # 智能断句合并与去噪
    segments = merge_and_clean_segments(raw_segments)

    # 释放 GPU 显存（为翻译模型腾空间）
    del model
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass
    gc.collect()

    # 保存中间结果
    with open(ja_path, "w", encoding="utf-8") as f:
        json.dump(segments, f, ensure_ascii=False, indent=2)

    logging.info(f"    ✓ 识别完成：原始 {len(raw_segments)} 句，优化合并后共 {len(segments)} 句")
    return segments


# ======================================================================
#             Stage 4: 中文翻译 (Sakura via Ollama)
# ======================================================================

def load_glossary() -> dict:
    """加载 glossary/ 目录下所有 .json 术语表，合并为一个字典"""
    glossary = {}
    if not GLOSSARY_DIR.exists():
        return glossary

    for gf in GLOSSARY_DIR.glob("*.json"):
        try:
            with open(gf, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                # 跳过以 _ 开头的说明性字段
                for k, v in data.items():
                    if not k.startswith("_"):
                        glossary[k] = v
        except Exception as e:
            logging.warning(f"    ⚠ 术语表 {gf.name} 加载失败: {e}")

    return glossary


_PIPELINE_SESSION = None

def get_pipeline_session() -> requests.Session:
    """复用 TCP 连接池，避免每次单句请求重新握手 (T3)"""
    global _PIPELINE_SESSION
    if _PIPELINE_SESSION is None:
        _PIPELINE_SESSION = requests.Session()
    return _PIPELINE_SESSION


def translate_one(text: str, glossary: dict, context_pairs: list) -> str:
    """调用 Sakura 翻译单句日语 → 中文"""
    # 纯呻吟/喘息/尖叫检测（彻底避免字符墙导致 LLM 卡死超时）
    cleaned_ja, is_pure_scream = clean_repetitive_audio_screams(text)
    if is_pure_scream:
        return "（呻吟/喘息）"
    text = cleaned_ja

    # 构建多轮对话（上下文 + 当前句）
    messages = [{"role": "system", "content": SAKURA_SYSTEM_PROMPT}]

    # 添加上下文（前 N 句的翻译记录，模拟多轮对话）
    for ja, zh in context_pairs:
        messages.append({"role": "user",      "content": f"将下面的日文文本翻译成中文：{ja}"})
        messages.append({"role": "assistant", "content": zh})

    # 构建当前句的 prompt
    prompt_parts = []

    # 如果术语表中有匹配项，附加提示
    relevant = {k: v for k, v in glossary.items() if k in text}
    if relevant:
        terms = "、".join(f"{k}->{v}" for k, v in relevant.items())
        prompt_parts.append(f"根据以下术语表翻译：{terms}")

    # 防幻觉/防复读提示：针对极短词（如“最後”、“おい”、“うん”等）
    stripped_text = text.strip()
    is_very_short = len(stripped_text) <= 5
    if is_very_short:
        prompt_parts.append("注意：本句非常短促，请直接准确意译，严禁复读上一句的译文或编造多余对话。")

    prompt_parts.append(f"将下面的日文文本翻译成中文：{text}")
    messages.append({"role": "user", "content": "\n".join(prompt_parts)})

    session = get_pipeline_session()

    # 请求 Ollama
    for attempt in range(MAX_RETRIES):
        try:
            resp = session.post(
                OLLAMA_API_URL,
                json={
                    "model":       SAKURA_MODEL_NAME,
                    "messages":    messages,
                    "temperature": TEMPERATURE,
                    "top_p":       TOP_P,
                    "stream":      False,
                },
                timeout=180,
            )
            resp.raise_for_status()
            result = resp.json()["choices"][0]["message"]["content"].strip()

            # 自检：如果是超短词，但模型输出了超长句子或完全复制了上一句译文，进行独立无上下文纠偏
            if is_very_short and context_pairs:
                last_zh = context_pairs[-1][1].strip()
                if result == last_zh or len(result) > 20:
                    # 剥除多轮上下文单独再问一次，彻底阻断复读
                    solo_messages = [
                        {"role": "system", "content": SAKURA_SYSTEM_PROMPT},
                        {"role": "user", "content": f"将下面的日文文本翻译成中文：{text}"}
                    ]
                    solo_resp = session.post(
                        OLLAMA_API_URL,
                        json={
                            "model": SAKURA_MODEL_NAME,
                            "messages": solo_messages,
                            "temperature": 0.1,
                            "top_p": 0.3,
                            "stream": False,
                        },
                        timeout=60,
                    )
                    if solo_resp.status_code == 200:
                        solo_result = solo_resp.json()["choices"][0]["message"]["content"].strip()
                        if len(solo_result) < len(result):
                            result = solo_result

            return result

        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                logging.warning(f"    ⚠ 翻译重试 ({attempt+1}/{MAX_RETRIES}): {e}")
                time.sleep(3)
            else:
                logging.error(f"    ✗ 翻译最终失败: {e}")
                return f"[翻译失败] {text}"


def translate_all(ja_segments: list, work_dir: Path) -> list:
    """
    批量翻译所有日语段落为中文。
    支持断点续传：进度每 10 句保存一次，中断后重跑自动从断点继续。
    """
    zh_path = work_dir / "chinese.json"

    # 加载已有进度
    zh_segments = []
    start_idx = 0
    if zh_path.exists():
        with open(zh_path, "r", encoding="utf-8") as f:
            zh_segments = json.load(f)
        start_idx = len(zh_segments)
        if start_idx >= len(ja_segments):
            logging.info("    ✓ 翻译已完成，跳过")
            return zh_segments
        logging.info(f"    ↻ 检测到历史进度，从第 {start_idx + 1}/{len(ja_segments)} 句继续")

    # 加载术语表
    glossary = load_glossary()
    if glossary:
        logging.info(f"    📖 已加载 {len(glossary)} 条术语")

    total = len(ja_segments)
    logging.info(f"    → 开始翻译（共 {total} 句，预计 {total * 3 // 60}~{total * 8 // 60} 分钟）...")

    t_start = time.time()
    for i in range(start_idx, total):
        seg = ja_segments[i]

        # 收集上下文（前 N 句的原文+译文对）
        ctx_start = max(0, i - CONTEXT_LINES)
        context_pairs = []
        for j in range(ctx_start, i):
            if j < len(zh_segments):
                context_pairs.append((
                    ja_segments[j]["text"],
                    zh_segments[j]["text"],
                ))

        # 翻译
        zh_text = translate_one(seg["text"], glossary, context_pairs)

        zh_segments.append({
            "start": seg["start"],
            "end":   seg["end"],
            "ja":    seg["text"],
            "text":  zh_text,
        })

        # 每 10 句保存一次进度 + 打印状态
        if (i + 1) % 10 == 0 or i == total - 1:
            with open(zh_path, "w", encoding="utf-8") as f:
                json.dump(zh_segments, f, ensure_ascii=False, indent=2)

            elapsed = time.time() - t_start
            done = i - start_idx + 1
            speed = elapsed / done if done else 0
            remaining = (total - i - 1) * speed
            logging.info(
                f"    📝 {i+1}/{total} "
                f"({(i+1)*100//total}%) "
                f"[{speed:.1f}s/句, 剩余约 {remaining/60:.0f} 分钟]"
            )

    logging.info(f"    ✓ 翻译完成")
    return zh_segments


# ======================================================================
#                Stage 5: 字幕文件生成 (pysubs2)
# ======================================================================

def generate_subtitles(zh_segments: list, work_dir: Path) -> tuple:
    """生成 ASS 和 SRT 字幕文件"""
    ass_path = work_dir / "subtitle.ass"
    srt_path = work_dir / "subtitle.srt"

    if ass_path.exists() and srt_path.exists():
        logging.info("    ✓ 字幕文件已存在，跳过")
        return ass_path, srt_path

    logging.info("    → 生成字幕文件...")
    import pysubs2

    subs = pysubs2.SSAFile()

    # 配置 ASS 样式
    style = subs.styles["Default"]
    style.fontname  = SUBTITLE_FONT
    style.fontsize  = SUBTITLE_FONTSIZE
    style.bold      = SUBTITLE_BOLD
    style.outline   = SUBTITLE_OUTLINE
    style.shadow    = SUBTITLE_SHADOW
    style.marginv   = SUBTITLE_MARGIN_V
    style.alignment = 2                         # 底部居中
    style.primarycolor  = pysubs2.Color(255, 255, 255, 0)    # 白色文字
    style.outlinecolor  = pysubs2.Color(0, 0, 0, 0)          # 黑色描边
    style.backcolor     = pysubs2.Color(0, 0, 0, 128)        # 半透明阴影

    # 写入字幕事件
    for seg in zh_segments:
        start_ms = int(seg["start"] * 1000)
        end_ms   = int(seg["end"]   * 1000)
        
        # 智能双行折行排版
        formatted_text = auto_wrap_subtitle(seg["text"]).replace("\n", "\\N")

        event = pysubs2.SSAEvent(
            start=start_ms,
            end=end_ms,
            text=formatted_text,
        )
        subs.append(event)

    # 导出 ASS
    subs.save(str(ass_path), encoding="utf-8")
    # 导出 SRT
    subs.save(str(srt_path), format_="srt", encoding="utf-8")

    logging.info(f"    ✓ 字幕生成完成（{len(zh_segments)} 条）")
    return ass_path, srt_path


# ======================================================================
#            Stage 6: 字幕封装 / 压制 (FFmpeg)
# ======================================================================

def mux_soft_subtitle(video_path: Path, ass_path: Path, output_path: Path):
    """软字幕封装：将 ASS 字幕作为字幕轨封入 MKV 容器（零质量损耗）"""
    if output_path.exists():
        logging.info("    ✓ 软字幕 MKV 已存在，跳过")
        return

    logging.info("    → 封装软字幕 MKV...")
    cmd = [
        FFMPEG_PATH,
        "-i", str(video_path),
        "-i", str(ass_path),
        "-map", "0",                  # 拷贝源视频所有流
        "-map", "1",                  # 加入字幕流
        "-c", "copy",                 # 全部流直接复制（不重编码）
        "-c:s", "ass",                # 字幕编码为 ASS
        "-metadata:s:s:0", "language=chi",
        "-metadata:s:s:0", "title=中文字幕",
        "-disposition:s:0", "default",# 设为默认字幕轨，播放器打开自动激活
        "-y",
        str(output_path),
    ]
    env = os.environ.copy()
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg 软字幕封装失败:\n{result.stderr[-800:]}")

    size_mb = output_path.stat().st_size / (1024 * 1024)
    logging.info(f"    ✓ 软字幕 MKV 完成 ({size_mb:.1f} MB)")


def burn_hard_subtitle(video_path: Path, ass_path: Path, output_path: Path):
    """硬字幕压制：将 ASS 字幕烧入视频画面（需重编码，耗时较长）"""
    if output_path.exists():
        logging.info("    ✓ 硬字幕 MP4 已存在，跳过")
        return

    logging.info("    → 压制硬字幕 MP4（耗时较长，请耐心等待）...")

    # Windows 路径中的反斜杠和冒号需要转义给 libass 滤镜
    ass_filter_path = str(ass_path).replace("\\", "/").replace(":", "\\:")

    cmd = [
        FFMPEG_PATH,
        "-i", str(video_path),
        "-vf", f"ass='{ass_filter_path}'",
        "-c:v", "libx264",
        "-crf", str(HARDCODED_CRF),
        "-preset", HARDCODED_PRESET,
        "-c:a", "copy",              # 音频直接复制
        "-y",
        str(output_path),
    ]
    env = os.environ.copy()
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg 硬字幕压制失败:\n{result.stderr[-800:]}")

    size_mb = output_path.stat().st_size / (1024 * 1024)
    logging.info(f"    ✓ 硬字幕 MP4 完成 ({size_mb:.1f} MB)")


# ======================================================================
#                       单视频完整处理
# ======================================================================

def process_one_video(video_path: Path, device: str):
    """对单个视频文件执行完整管线"""
    name = video_path.stem
    work_dir = OUTPUT_DIR / name
    work_dir.mkdir(parents=True, exist_ok=True)

    logging.info("")
    logging.info(f"{'=' * 50}")
    logging.info(f"  📺 {video_path.name}")
    logging.info(f"{'=' * 50}")

    t0 = time.time()
    stage_times = {}

    try:
        # Stage 1
        t_s = time.time()
        logging.info("  [1/6] 音频提取")
        audio_path = extract_audio(video_path, work_dir)
        stage_times["extract_audio_s"] = round(time.time() - t_s, 2)
        logging.info(f"    ✓ 音频提取阶段完成，耗时: {stage_times['extract_audio_s']:.2f}s")

        # Stage 2
        t_s = time.time()
        logging.info("  [2/6] 人声分离")
        vocals_path = separate_vocals(audio_path, work_dir, device)
        stage_times["demucs_s"] = round(time.time() - t_s, 2)
        logging.info(f"    ✓ 人声分离阶段完成，耗时: {stage_times['demucs_s']:.2f}s")

        # Stage 3
        t_s = time.time()
        logging.info("  [3/6] 日语语音识别")
        ja_segments = transcribe_audio(vocals_path, work_dir, device)
        stage_times["whisper_s"] = round(time.time() - t_s, 2)
        logging.info(f"    ✓ 日语识别阶段完成，耗时: {stage_times['whisper_s']:.2f}s")

        # Stage 4
        t_s = time.time()
        logging.info("  [4/6] 中文翻译")
        zh_segments = translate_all(ja_segments, work_dir)
        stage_times["translate_s"] = round(time.time() - t_s, 2)
        logging.info(f"    ✓ 中文翻译阶段完成，耗时: {stage_times['translate_s']:.2f}s")

        # Stage 5
        t_s = time.time()
        logging.info("  [5/6] 字幕生成")
        ass_path, srt_path = generate_subtitles(zh_segments, work_dir)
        stage_times["subtitles_s"] = round(time.time() - t_s, 2)
        logging.info(f"    ✓ 字幕生成阶段完成，耗时: {stage_times['subtitles_s']:.2f}s")

        # Stage 6
        logging.info("  [6/6] 字幕封装/压制")
        if OUTPUT_MODE in ("soft", "both"):
            t_s = time.time()
            mux_soft_subtitle(
                video_path, ass_path,
                work_dir / f"{name}_中文字幕.mkv",
            )
            stage_times["mux_mkv_s"] = round(time.time() - t_s, 2)
            logging.info(f"    ✓ 软字幕 MKV 封装完成，耗时: {stage_times['mux_mkv_s']:.2f}s")
        if OUTPUT_MODE in ("hard", "both"):
            t_s = time.time()
            burn_hard_subtitle(
                video_path, ass_path,
                work_dir / f"{name}_中文字幕.mp4",
            )
            stage_times["burn_mp4_s"] = round(time.time() - t_s, 2)
            logging.info(f"    ✓ 硬字幕 MP4 压制完成，耗时: {stage_times['burn_mp4_s']:.2f}s")
        if OUTPUT_MODE == "subtitle":
            logging.info("    ✓ 仅导出字幕模式，跳过视频封装")

        elapsed = time.time() - t0
        stage_times["total_elapsed_s"] = round(elapsed, 2)

        report_path = work_dir / "chain_a_execution_report.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump({
                "video": str(video_path),
                "timestamp": datetime.now().isoformat(),
                "stage_timings_sec": stage_times,
                "output_dir": str(work_dir)
            }, f, ensure_ascii=False, indent=2)

        logging.info("")
        logging.info(f"  ✅ {video_path.name} 处理完成！压制完成！总耗时 {elapsed/60:.1f} 分钟")
        logging.info(f"  📂 输出目录: {work_dir}")
        return True

    except Exception as e:
        logging.error(f"  ❌ 处理失败: {e}")
        logging.error("  中间文件已保存，修复问题后重新运行可从断点继续")
        return False


# ======================================================================
#                           主入口
# ======================================================================

def main():
    print()
    print("  ╔══════════════════════════════════════════╗")
    print("  ║   日漫全自动中文字幕流水线  v1.0         ║")
    print("  ║   视频 → 人声分离 → ASR → 翻译 → 字幕   ║")
    print("  ╚══════════════════════════════════════════╝")
    print()

    log_file = setup_logging()
    logging.info(f"日志文件: {log_file}")

    # 检查依赖
    device = check_dependencies()

    # 确保目录存在
    INPUT_DIR.mkdir(exist_ok=True)
    OUTPUT_DIR.mkdir(exist_ok=True)

    if len(sys.argv) > 1 and Path(sys.argv[1]).exists():
        videos = [Path(sys.argv[1])]
    else:
        # 扫描 input/ 下的视频文件
        videos = sorted([
            f for f in INPUT_DIR.iterdir()
            if f.suffix.lower() in VIDEO_EXTENSIONS
        ])

    if not videos:
        logging.warning("  ⚠ input/ 文件夹中没有找到视频文件！")
        logging.warning(f"    支持的格式: {', '.join(VIDEO_EXTENSIONS)}")
        logging.warning(f"    请把视频放入: {INPUT_DIR}")
        return

    logging.info(f"  找到 {len(videos)} 个视频文件:")
    for v in videos:
        size_mb = v.stat().st_size / (1024 * 1024)
        logging.info(f"    • {v.name} ({size_mb:.0f} MB)")

    # 逐个处理
    results = []
    for i, video in enumerate(videos, 1):
        logging.info("")
        logging.info(f"  ▶ 进度: {i}/{len(videos)}")
        ok = process_one_video(video, device)
        results.append((video.name, ok))

    # 打印汇总
    logging.info("")
    logging.info("=" * 50)
    logging.info("  处理汇总")
    logging.info("=" * 50)
    for name, ok in results:
        status = "✅ 成功" if ok else "❌ 失败"
        logging.info(f"  {status}  {name}")

    success = sum(1 for _, ok in results if ok)
    logging.info("")
    logging.info(f"  共 {len(results)} 个，成功 {success} 个，失败 {len(results) - success} 个")
    logging.info(f"  输出目录: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
