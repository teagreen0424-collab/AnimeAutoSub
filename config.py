"""
配置文件 - 日漫全自动中文字幕流水线
====================================
修改此文件来调整管线行为
首次使用前请根据你的硬件情况调整 ASR 和翻译模型参数
"""

from pathlib import Path

# ======================== 路径配置 ========================
PROJECT_DIR = Path(__file__).parent
INPUT_DIR = PROJECT_DIR / "input"
OUTPUT_DIR = PROJECT_DIR / "output"
GLOSSARY_DIR = PROJECT_DIR / "glossary"

# ======================== FFmpeg ========================
# 优先查找 D:\Dev\ffmpeg\bin\ffmpeg.exe，否则使用系统 PATH 中的 ffmpeg
_LOCAL_FFMPEG = Path(r"D:\Dev\ffmpeg\bin\ffmpeg.exe")
FFMPEG_PATH = str(_LOCAL_FFMPEG) if _LOCAL_FFMPEG.exists() else "ffmpeg"

# ======================== 人声分离 (Demucs) ========================
DEMUCS_MODEL = "htdemucs_ft"    # htdemucs_ft = 质量最好; htdemucs = 速度更快

# ======================== ASR 语音识别 (faster-whisper) ========================
_LOCAL_WHISPER = Path(r"D:\Dev\huggingface\models--faster-whisper-large-v3")
WHISPER_MODEL = str(_LOCAL_WHISPER) if _LOCAL_WHISPER.exists() else "large-v3"
WHISPER_COMPUTE_TYPE = "float16" # 满血无损半精度 (float16)，微弱音听觉极限提升
WHISPER_BEAM_SIZE = 5            # beam search 宽度，越大越准但越慢
WHISPER_VAD_ENABLED = True       # 启用 VAD 过滤静音段（强烈建议开启，防幻觉）

# ASR 二次元/动漫场景深度调优参数
WHISPER_INITIAL_PROMPT = (
    "アニメの日本語セリフ、日常会話、掛け合い、愛の告白、エッチな言葉、吐息、喘ぎ声、スラング。"
    "聞き取れない声や喘ぎ声を無理に変なカタカナに変換しないでください。句読点を適切につけてください。"
)
WHISPER_CONDITION_ON_PREV = False  # 关闭前文条件依赖，防止前句听错导致后句连锁幻觉
WHISPER_TEMPERATURE = [0.0, 0.2]   # 限制升温采样，减少脑补胡编
VAD_MIN_SILENCE_MS = 800          # 允许角色喘气或停顿 800ms，不轻易切断整句话
VAD_SPEECH_PAD_MS = 400           # 前后各垫 400ms，保留微弱气声与尾音

# ======================== 文本断句重组与排版优化 ========================
MERGE_SHORT_SEGMENTS = True       # 启用智能短句合并（解决碎句、半句话被切断问题）
MERGE_MAX_GAP_SEC = 0.8           # 两句话间隔小于 0.8 秒且未结束则自动拼接
MERGE_MAX_LEN_CHARS = 45          # 合并后单句最大字数限制
MERGE_MAX_DURATION_SEC = 7.0      # 合并后单句最大持续时长（秒）

# 字幕智能换行排版参数
AUTO_WRAP_SUBTITLE = True         # 是否自动将长字幕折行为优雅双行
SUBTITLE_MAX_LINE_CHARS = 18      # 单行最大汉字数（超过此长度自动在标点处折行）

# ======================== 翻译 (Sakura via Ollama) ========================
# 使用 127.0.0.1 彻底规避 Windows 下 localhost 优先尝试 IPv6 [::1] 造成的 2.0s 连接超时 (U3)
OLLAMA_API_URL = "http://127.0.0.1:11434/v1/chat/completions"
SAKURA_MODEL_NAME = "sakura-14b"  # 升级为 14B 旗舰模型
CONTEXT_LINES = 5                # 翻译时携带前 N 句作为上下文（提高连贯性）
TEMPERATURE = 0.1                # 越低越稳定，0.1~0.3 推荐
TOP_P = 0.3
MAX_RETRIES = 3                  # 单句翻译失败重试次数

# Sakura 系统提示词（匹配 Sakura v0.9/v1.0 官方格式，请勿随意修改）
SAKURA_SYSTEM_PROMPT = (
    "你是一个轻小说翻译模型，可以流畅通顺地以日本轻小说的风格将日文翻译成简体中文，"
    "并联系上下文正确使用人称代词，不擅自添加原文中没有的代词。"
    "遇到 OCR 明显损毁或无法识别的噪点字符（如带有孤立字母数字如 T、2C、片假名混拉丁等），"
    "请用「□」占位或保留原文，严禁胡乱猜测脑补填充。"
)

# ======================== 字幕输出 ========================
# 输出模式:
#   "soft"     → MKV 软字幕封装（无损，可开关字幕）
#   "hard"     → MP4 硬字幕压制（烧入画面，兼容性最好）
#   "both"     → 同时输出软字幕 MKV + 硬字幕 MP4
#   "subtitle" → 仅导出 ASS + SRT 字幕文件，不生成视频
OUTPUT_MODE = "both"

# ASS 字幕样式
SUBTITLE_FONT = "Microsoft YaHei"   # 字体（确保系统已安装）
SUBTITLE_FONTSIZE = 22              # 字号
SUBTITLE_BOLD = True                # 粗体
SUBTITLE_OUTLINE = 2.0              # 描边粗细
SUBTITLE_SHADOW = 1.0               # 阴影
SUBTITLE_MARGIN_V = 30              # 距底部距离（像素）

# 硬字幕压制参数
HARDCODED_CRF = 20                  # 视频质量（18=高质量大文件, 23=标准, 28=低质量小文件）
HARDCODED_PRESET = "medium"         # 编码速度: ultrafast / fast / medium / slow（越慢文件越小）

# ======================== 文件格式 ========================
VIDEO_EXTENSIONS = {".mkv", ".mp4", ".avi", ".webm", ".flv", ".mov", ".ts"}
