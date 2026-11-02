"""
配置文件 - 视频硬字幕 OCR 识别与翻译流水线
=============================================
专为语音无台词（如 ASMR、音效、心理独白、视觉小说游戏画面）
但画面底部烧录了日文硬字幕的视频定制。
"""

from pathlib import Path

# ======================== 路径配置 ========================
PROJECT_DIR = Path(__file__).parent
OCR_INPUT_DIR = PROJECT_DIR / "ocr_input"
OCR_OUTPUT_DIR = PROJECT_DIR / "ocr_output"
GLOSSARY_DIR = PROJECT_DIR / "glossary"

# FFmpeg 路径
_LOCAL_FFMPEG = Path(r"D:\Dev\ffmpeg\bin\ffmpeg.exe")
FFMPEG_PATH = str(_LOCAL_FFMPEG) if _LOCAL_FFMPEG.exists() else "ffmpeg"

# ======================== 视频 OCR 视觉参数 ========================
# 画面底部字幕区域高度占比（0.25 表示只扫描画面底部 25% 的区域，避免背景人物画面干扰）
OCR_ROI_BOTTOM_PERCENT = 0.28

# 视频抽帧采样率 (帧/秒)。字幕通常停留 1.5~4 秒，2 fps 既不漏句又兼顾性能
OCR_SAMPLE_FPS = 2.0

# 帧差变动检测阈值（字幕区域变化低于此值 → 帧间无新字幕，直接跳过 OCR 引擎调用）
OCR_FRAME_DIFF_THRESH = 0.025

# 是否启用 GPU (CUDA) 加速 OCR 推理（RTX 显卡推荐开启，速度提升 3~5 倍）
OCR_USE_CUDA = True

# 最短字幕持续时间（秒，低于此时长的识别视作画面杂点闪烁直接丢弃）
OCR_MIN_DURATION_SEC = 0.8

# 文字相似度判定阈值（同一句话在不同帧识别可能有微小字差，相似度高于此值合并为同一句）
OCR_SIMILARITY_THRESH = 0.80

# ======================== 字幕排版模式 ========================
# 可选模式:
#   "replace_mask" - 【推荐·同等大小精准覆盖】字体与原日文 1:1 等大（68号白字黑边），精准遮盖原位置，高度仅120px不遮胸口人物
#   "below"        - 贴在原日文正下方（底部仅剩68px空隙，字体会被迫变小）
#   "above"        - 悬浮在原日文正上方
SUBTITLE_OVERLAY_STYLE = "replace_mask"

# 智能换行
AUTO_WRAP_SUBTITLE = True
SUBTITLE_MAX_LINE_CHARS = 18

# 自适应贴合遮罩参数（R1 规范: 逐句 OCR 检测框并集 + 8px padding 自适应，废除 MASK_TOP/MASK_HEIGHT 全局常量）
# MASK_PADDING: 遮罩外扩 padding (8px)
# MASK_GRID_QUANT: 遮罩高度与 Y 轴 8px 网格量化（保证同一场景内高度方差 <= 8px）
# MASK_OPACITY: 不透明度（"00" 为纯黑）
MASK_PADDING = 8
MASK_GRID_QUANT = 8
MASK_OPACITY = "00"

# ASS 样式配置：与原日文字体完全 1:1 对齐
SUBTITLE_FONT = "Microsoft YaHei"
SUBTITLE_FONTSIZE = 68    # 68 号大字，与原日文大小 100% 一致！
SUBTITLE_BOLD = True
SUBTITLE_OUTLINE = 3.2    # 原汁原味的黑边，白字黑描边
SUBTITLE_SHADOW = 0.5
SUBTITLE_MARGIN_V = 16

# ======================== 翻译 (Sakura-14B via Ollama) ========================
# 强制使用 127.0.0.1 彻底根除 Windows loopback IPv6 [::1] 2.0s 超时 (V3)
OLLAMA_API_URL = "http://127.0.0.1:11434/v1/chat/completions"
SAKURA_MODEL_NAME = "sakura-14b"
CONTEXT_LINES = 5
TEMPERATURE = 0.1
TOP_P = 0.3
MAX_RETRIES = 3

SAKURA_SYSTEM_PROMPT = (
    "你是一个轻小说翻译模型，可以流畅通顺地以符合二次元风格的日本轻小说语言将日文翻译成简体中文，"
    "并联系上下文正确使用词汇。请直接给出翻译结果，不要做任何解释、不要输出多余内容。"
)

# ======================== 输出设置 ========================
OUTPUT_MODE = "both"  # "mkv" (内封内嵌) / "mp4" (压制硬字幕) / "both" (两者都生成)
HARDCODED_CRF = 19
HARDCODED_PRESET = "fast"
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".flv", ".webm", ".ts"}
