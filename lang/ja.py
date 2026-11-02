"""
AnimeAutoSub 日语语言插件 (lang/ja.py)

描述日语的 ASR、翻译器、OCR、布局档位、术语表与文本清洗规则。
严禁包含任何流程控制代码。
"""

import json
import re
from pathlib import Path
from .base import (
    LanguagePlugin,
    ASRConfig,
    TranslatorConfig,
    OCRConfig,
    TextRules
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 1. 加载外置布局档位
LAYOUT_FILE = PROJECT_ROOT / "layout" / "ja.json"
layout_data = LanguagePlugin.load_layout_file(LAYOUT_FILE)

# 2. 加载日语术语表
glossary_dict = {}
glossary_file = PROJECT_ROOT / "glossary" / "anime_production.json"
if glossary_file.exists():
    with open(glossary_file, "r", encoding="utf-8") as f:
        raw_gloss = json.load(f)
        glossary_dict = {k: v for k, v in raw_gloss.items() if not k.startswith("_")}


# 3. 文本清洗与规整规则 (基于 Z 阶段冻结的生产标准)
JP_UNITS_PATTERN = r'[人つ円回日月年分秒時点個番歳才倍割度本枚匹頭台万億千百％%kmgM]'
KANA_PATTERN = r'[\u3040-\u309F\u30A0-\u30FF]'

def is_garbled_number(match, full_text: str) -> bool:
    num_str = match.group()
    start, end = match.span()
    if len(num_str) >= 5:
        return True
    prev_char = full_text[start - 1] if start > 0 else ""
    next_char = full_text[end] if end < len(full_text) else ""
    if re.match(KANA_PATTERN, next_char) or re.match(JP_UNITS_PATTERN, next_char):
        return False
    if re.match(KANA_PATTERN, prev_char) and not re.match(r'[っッ]', prev_char):
        return False
    return True

def sanitize_japanese_text(raw_text: str) -> tuple:
    """
    日语专用文本清洗规则:
    1. 乱码片段过滤 (N5/U2)
    2. 助词浊点误识正规化 (Z3: 誰がに -> 誰かに)
    3. 整理标点与未闭合截断
    返回: (cleaned_text: str, is_rejected: bool, action_info: str)
    """
    if not raw_text:
        return "", True, "empty"

    orig_len = len(raw_text)

    # 1. 查找混合乱码片段
    garble_patterns = [
        r'[A-Za-z0-9_]*[A-Z]{2,}[A-Za-z0-9_「」]*',
        r'\[[A-Za-z0-9_]+',
        r'[&#@$%^~+=*|/\\<>]{1,}[A-Za-z0-9_?]*',
        r'\d{5,}'
    ]
    combined_pattern = re.compile('|'.join(garble_patterns))

    removed_snippets = []
    for m in combined_pattern.finditer(raw_text):
        s = m.group()
        if s:
            removed_snippets.append(s)

    cleaned = combined_pattern.sub('', raw_text)

    # 2. 切除孤立 3-4 位数字
    def replace_isolated_digits(m):
        if is_garbled_number(m, cleaned):
            removed_snippets.append(m.group())
            return ""
        return m.group()

    cleaned = re.sub(r'\d{3,4}', replace_isolated_digits, cleaned)

    # 3. 整理标点与助词浊点纠偏 (Z3: 誰がに -> 誰かに)
    cleaned = re.sub(r'誰がに', '誰かに', cleaned)
    cleaned = re.sub(r'[\s「」\[\]&]+$', '', cleaned).strip()

    rem_len = len(cleaned)
    rem_ratio = rem_len / max(1, orig_len)

    if rem_ratio < 0.45:
        return cleaned, True, f"remaining_ratio_{rem_ratio:.2f}_lt_0.45"
    if rem_len < 3:
        return cleaned, True, f"rem_len_{rem_len}_lt_3"

    action = f"cut_{','.join(removed_snippets)}" if removed_snippets else "clean_pass"
    return cleaned, False, action


def build_japanese_prompt(text: str, glossary: dict, context_pairs: list) -> str:
    """构建 SakuraLLM 官方标准字典 Prompt"""
    matched = {k: v for k, v in glossary.items() if k in text}
    if matched:
        dict_lines = [f"{k}->{v}" for k, v in matched.items()]
        return (
            "根据以下字典翻译：\n"
            + "\n".join(dict_lines)
            + "\n将下面的日文文本翻译成中文："
            + text
        )
    return f"将下面的日文文本翻译成中文：{text}"


# 4. 构建日语语言插件单例
japanese_plugin = LanguagePlugin(
    code="ja",
    name="Japanese",
    asr=ASRConfig(
        model_name="large-v3",
        language_code="ja",
        beam_size=5,
        vad_filter=True
    ),
    translator=TranslatorConfig(
        engine_type="ollama",
        api_url="http://127.0.0.1:11434/v1/chat/completions",
        model_name="sakura-14b",
        system_prompt=(
            "你是一个轻小说翻译模型，可以流畅通顺地以日本轻小说的风格将日文翻译成简体中文，"
            "并联系上下文正确使用人称代词，不擅自添加原文中没有的代词。"
        ),
        temperature=0.1,
        top_p=0.3,
        context_lines=5,
        max_retries=3,
        prompt_builder=build_japanese_prompt
    ),
    ocr=OCRConfig(
        engine_name="rapidocr",
        use_cuda=True,
        sample_fps=2.0,
        frame_diff_thresh=8.0,
        min_duration_sec=0.5,
        similarity_thresh=0.82,
        roi_bottom_percent=0.40,
        rec_lang="japan",
        confidence_thresh=0.75
    ),
    layout=layout_data,
    glossary=glossary_dict,
    text_rules=TextRules(
        sanitizer=sanitize_japanese_text,
        wrap_punctuations=['。', '！', '？', '!', '?', '，', ',', '…', '、', ' '],
        speaker_map={"枝彌": "枝弥"}
    )
)
