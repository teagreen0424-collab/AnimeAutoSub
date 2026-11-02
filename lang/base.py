"""
AnimeAutoSub 语言插件基类契约 (lang/base.py)

硬性契约:
  每份语言插件只描述: asr / translator / ocr / layout / glossary / text_rules，
  绝对禁止编写流程控制代码。流程由 core/pipeline 和 core/stage 统一驱动。
"""

from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Callable
from pathlib import Path
import json


@dataclass
class ASRConfig:
    """ASR 识别配置声明"""
    model_name: str
    language_code: str
    beam_size: int = 5
    vad_filter: bool = True
    initial_prompt: Optional[str] = None


@dataclass
class TranslatorConfig:
    """翻译器配置声明"""
    engine_type: str                  # "ollama" / "api"
    api_url: str
    model_name: str
    system_prompt: str
    temperature: float = 0.1
    top_p: float = 0.3
    context_lines: int = 5
    max_retries: int = 3
    # 格式化针对该语言的 prompt
    prompt_builder: Optional[Callable[[str, Dict[str, str], List[tuple]], str]] = None


@dataclass
class OCRConfig:
    """OCR 检测与识别配置声明"""
    engine_name: str                  # "rapidocr"
    use_cuda: bool = True
    sample_fps: float = 2.0
    frame_diff_thresh: float = 8.0
    min_duration_sec: float = 0.5
    similarity_thresh: float = 0.82
    roi_bottom_percent: float = 0.40
    rec_lang: str = "japan"           # 引擎内部识别语言代号
    rec_model_name: Optional[str] = None
    confidence_thresh: float = 0.75   # 置信度门限


@dataclass
class TextRules:
    """文本清洗与语法规整规则"""
    # 乱码与噪声清洗函数
    sanitizer: Callable[[str], tuple]
    # 标点符号与折行断句字符
    wrap_punctuations: List[str] = field(default_factory=lambda: ['。', '！', '？', '!', '?', '，', ',', '…', '、', ' '])
    # 不可分离助词表 (韩语等特有)
    inseparable_particles: List[str] = field(default_factory=list)
    # 说话人/专有名词映射字典
    speaker_map: Dict[str, str] = field(default_factory=dict)
    # 语言专属折行/断句函数 (可选)
    line_wrapper: Optional[Callable[[str, int], str]] = None
    # 专有名词/音译名查表解析 (可选, 未查到则保留原文, 禁止自由音译)
    resolve_name: Optional[Callable[[str, Optional[Dict[str, str]]], str]] = None


@dataclass
class LanguagePlugin:
    """语言插件聚合对象"""
    code: str                         # "ja", "ko"
    name: str                         # "Japanese", "Korean"
    asr: ASRConfig
    translator: TranslatorConfig
    ocr: OCRConfig
    layout: Dict[str, Any]
    glossary: Dict[str, str]
    text_rules: TextRules

    @classmethod
    def load_layout_file(cls, path: Path) -> Dict[str, Any]:
        """从外置 layout/<lang>.json 加载布局档位"""
        if not path.exists():
            raise FileNotFoundError(f"布局配置文件不存在: {path}")
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
