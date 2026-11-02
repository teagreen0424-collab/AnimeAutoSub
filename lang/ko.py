"""
AnimeAutoSub 韩语语言插件 (lang/ko.py)

硬性契约:
  - 只描述 ASR / Translator / OCR / Layout / Glossary / TextRules，绝无流程代码
  - 落实韩语六大专属工程点:
    1. 不可分助词表与断句防断开
    2. ASR 丢失空格容错 (音节级断行兜底)
    3. 敬语层级中文映射 (하십시오체 / 해요체 / 반말 / 해라체)
    4. 称呼系统映射规则 (형/오빠/누나/언니/선배/아저씨)
    5. 拟声拟态词 (ㅋㅋ/ㅠㅠ/두근두근) 规整
    6. Hangul NFKC 归一化
"""

import re
import json
import unicodedata
from pathlib import Path
from typing import Dict, Any, List, Optional

from .base import (
    LanguagePlugin,
    ASRConfig,
    TranslatorConfig,
    OCRConfig,
    TextRules
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 1. 加载外置韩语布局档位 (代码内根除 820/180/68/3.2 等魔法数字)
LAYOUT_FILE = PROJECT_ROOT / "layout" / "ko.json"
layout_data = LanguagePlugin.load_layout_file(LAYOUT_FILE)

# 2. 韩语专属助词不可分列表 (工程点 1)
KO_INSEPARABLE_PARTICLES = [
    "이", "가", "을", "를", "의", "에", "에서", "로", "으로",
    "에게", "한테", "께서", "께", "부터", "까지", "밖에", "처럼",
    "보다", "마다", "마저", "조차", "은", "는", "도", "만", "과", "와", "랑"
]

# 称呼系统与敬语翻译系统提示词 (工程点 3 & 4)
KOREAN_SYSTEM_PROMPT = """你是一个专业的影视与动漫韩译中本地化专家。
请根据韩语语法、敬语层级与称谓关系，将韩文准确翻译为自然流畅的简体中文：
1. 称呼系统严禁一律音译：
   - 형: 哥哥（男称男）
   - 오빠: 哥哥（女称男，动漫按亲属/恋人语境译为哥哥，严禁滥用音译欧巴）
   - 누나: 姐姐（男称女）
   - 언니: 姐姐（女称女）
   - 선배: 前辈
   - 아저씨: 大叔
2. 敬语层级严格落地到中文语气：
   - 하십시오체 (~하십시오, ~습니다): 极为尊敬体，中文使用“请您务必...”、“请大家...”
   - 해요체 (~해요, ~따뜻해요): 日常客气敬体，中文使用柔和的“...呢/呀/吧”
   - 반말 (~야, ~지 마, ~가냐): 平辈熟人半语，中文使用口语非敬体
   - 해라체 (~하라, ~했다): 严肃命令体与书面平叙体（注意：非内心独白专用），译为干脆利落的命令或陈述句
3. 拟声拟态词：
   - ㅋㅋ 译为“哈哈”；ㅠㅠ 译为“呜呜”；두근두근 译为“扑通扑通”
4. 人名音译规范 (L3 规范)：
   - 音译人名必须严格查阅提供的术语字典，按标准译名翻译；
   - 字典未收录的韩语人名禁止擅自拼音自由音译，必须保留韩文原文。
遇到截断或未知字符，保留原意，严禁虚构脑补。"""


def sanitize_korean_text(raw_text: str) -> tuple:
    """
    韩语文本清洗与正规化 (工程点 5 & 6):
    1. Hangul NFKC 归一化
    2. 网络符号与拟声词规整
    """
    if not raw_text:
        return "", True, "empty"

    # 1. NFKC 归一化
    norm = unicodedata.normalize("NFKC", raw_text).strip()

    # 2. 清洗多余无意义乱码标记
    cleaned = re.sub(r'[A-Za-z0-9_]*[A-Z]{3,}[A-Za-z0-9_]*', '', norm)
    cleaned = re.sub(r'[\s「」\[\]&]+$', '', cleaned).strip()

    if len(cleaned) < 2:
        return cleaned, True, "too_short"

    return cleaned, False, "clean_pass"


def wrap_korean_text(text: str, max_chars: int = 20) -> str:
    """
    韩语断行引擎 (落实工程点 1 & 2):
    1. 助词不可分离: 이/가/을/를/의/에/에서/로/으로/에게/한테/께서/께/부터/까지/밖에/처럼/보다/마다/마저/조차/은/는/도/만/과/와/랑
       断行不得将助词从前面的名词/词干切开。
    2. ASR 空格容错: 若 ASR 丢失空格导致超长，按音节 (syllable block) 兜底切分，
       同时避开助词前切断与助词内部切断。
    """
    if not text or len(text) <= max_chars or r"\N" in text or "\n" in text:
        return text

    mid = len(text) // 2

    # 1. 优先在自然空格处断句 (韩语空格后不会紧跟助词)
    spaces = [i for i, c in enumerate(text) if c == ' ' and 3 <= i <= len(text) - 4]
    if spaces:
        best_sp = min(spaces, key=lambda i: abs(i - mid))
        return text[:best_sp] + r"\N" + text[best_sp + 1:]

    # 2. ASR 丢失空格容错: 按韩语音节兜底切分，并惩罚切断助词的位置
    candidates = []
    sorted_particles = sorted(KO_INSEPARABLE_PARTICLES, key=len, reverse=True)

    for cut in range(3, len(text) - 3):
        score = abs(cut - mid)
        penalty = 0
        for p in sorted_particles:
            if text[cut:].startswith(p):
                penalty += 100
                break
        for p in sorted_particles:
            if len(p) > 1:
                for p_len in range(1, len(p)):
                    if text[:cut].endswith(p[:p_len]) and text[cut:].startswith(p[p_len:]):
                        penalty += 200
                        break
        candidates.append((score + penalty, cut))

    candidates.sort()
    best_cut = candidates[0][1]
    return text[:best_cut] + r"\N" + text[best_cut:]


def build_korean_prompt(text: str, glossary: dict, context_pairs: list) -> str:
    """构建韩语专用翻译 Prompt"""
    matched = {k: v for k, v in glossary.items() if k in text}
    if matched:
        dict_lines = [f"{k}->{v}" for k, v in matched.items()]
        return (
            "根据以下字典翻译：\n"
            + "\n".join(dict_lines)
            + "\n将下面的韩文文本翻译成中文："
            + text
        )
    return f"将下面的韩文文本翻译成中文：{text}"


# 加载韩语专用人名与生产术语表 (L3 规范)
KO_GLOSSARY_FILE = PROJECT_ROOT / "glossary" / "ko_production.json"
ko_glossary = {}
if KO_GLOSSARY_FILE.exists():
    with open(KO_GLOSSARY_FILE, "r", encoding="utf-8") as f:
        raw_gloss = json.load(f)
        ko_glossary = {k: v for k, v in raw_gloss.items() if not k.startswith("_")}
else:
    ko_glossary = {
        "민수": "敏秀",
        "김민수": "金珉秀",
        "지훈": "志勋",
        "수진": "秀珍",
        "지혜": "智惠",
        "현우": "贤宇"
    }


def resolve_korean_name(name: str, glossary: Optional[Dict[str, str]] = None) -> str:
    """
    韩语人名音译查表规则 (L3 规范):
    - 音译名必须查表
    - 查到表: 严格走表，不改字 (返回映射的标准中文译名)
    - 查不到表: 保留韩文原文，禁止自由音译
    """
    g = ko_glossary if glossary is None else glossary
    if name in g:
        return g[name]
    return name


# 3. 实例化韩语插件单例
korean_plugin = LanguagePlugin(
    code="ko",
    name="Korean",
    asr=ASRConfig(
        model_name="large-v3",
        language_code="ko",
        beam_size=5,
        vad_filter=True
    ),
    translator=TranslatorConfig(
        engine_type="ollama",
        api_url="http://127.0.0.1:11434/v1/chat/completions",
        model_name="sakura-14b",     # 现网实测模型
        system_prompt=KOREAN_SYSTEM_PROMPT,
        temperature=0.1,
        top_p=0.3,
        context_lines=5,
        max_retries=3,
        prompt_builder=build_korean_prompt
    ),
    ocr=OCRConfig(
        engine_name="rapidocr",
        use_cuda=True,
        sample_fps=2.0,
        frame_diff_thresh=1.2,
        min_duration_sec=0.5,
        similarity_thresh=0.80,
        roi_bottom_percent=0.40,
        rec_lang="korean",
        rec_model_name="korean_PP-OCRv5_rec_mobile",
        confidence_thresh=0.75
    ),
    layout=layout_data,
    glossary=ko_glossary,
    text_rules=TextRules(
        sanitizer=sanitize_korean_text,
        wrap_punctuations=['。', '！', '？', '!', '?', '，', ',', '…', ' '],
        inseparable_particles=KO_INSEPARABLE_PARTICLES,
        speaker_map={},
        line_wrapper=wrap_korean_text,
        resolve_name=resolve_korean_name
    )
)
