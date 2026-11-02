"""
韩语专属工程点单元测试 (tests/test_korean_text_rules.py)
覆盖六大工程点:
1. 不可分助词表与断句防断开
2. ASR 丢失空格容错 (音节级断行兜底)
3. 敬语层级 Prompt 结构
4. 称呼系统映射
5. 拟声拟态词规整与保留
6. Hangul NFKC 归一化
"""

import pytest
import unicodedata
from lang.ko import (
    korean_plugin,
    KO_INSEPARABLE_PARTICLES,
    wrap_korean_text,
    sanitize_korean_text,
    KOREAN_SYSTEM_PROMPT
)


def test_korean_inseparable_particles_completeness():
    """验证不可分助词列表是否包含全部指定助词"""
    required_particles = [
        "이", "가", "을", "를", "의", "에", "에서", "로", "으로",
        "에게", "한테", "께서", "께", "부터", "까지", "밖에", "처럼",
        "보다", "마다", "마저", "조차", "은", "는", "도", "만", "과", "와", "랑"
    ]
    for p in required_particles:
        assert p in KO_INSEPARABLE_PARTICLES, f"缺少助词: {p}"


def test_korean_line_wrapping_with_spaces():
    """验证含空格的长句在自然空格处折行，不破坏词义"""
    text = "안녕하세요 오늘도 정말 좋은 하루 되세요"
    wrapped = wrap_korean_text(text, max_chars=12)
    assert r"\N" in wrapped
    parts = wrapped.split(r"\N")
    assert len(parts) == 2
    # 验证没有助词在第二行开头单独出现
    assert not parts[1].startswith("을")
    assert not parts[1].startswith("를")


def test_korean_asr_missing_spaces_syllable_wrap_protects_particles():
    """验证 ASR 丢失空格时按音节兜底断行，且绝对不断开助词"""
    # 包含多字助词 '에서'
    text1 = "학교에서공부하고있습니다"
    wrapped1 = wrap_korean_text(text1, max_chars=7)
    assert r"\N" in wrapped1
    # 绝对不能断成 '학교\N에서...'
    assert not wrapped1.startswith(r"학교\N에서")
    # '학교에서' 必须紧密相连
    assert "학교에서" in wrapped1

    # 包含助词 '으로'
    text2 = "오른쪽으로걸어가세요"
    wrapped2 = wrap_korean_text(text2, max_chars=6)
    assert r"\N" in wrapped2
    assert "오른쪽으로" in wrapped2


def test_korean_nfkc_normalization_and_onomatopoeia():
    """验证 Hangul NFKC 归一化与拟声词保留"""
    # 分离型 Jamo 组合 ᄀ + ᅡ + ᆼ (강)
    decomposed = "\u1100\u1161\u11BC\uB0A8"  # 강남
    cleaned, is_rej, reason = sanitize_korean_text(decomposed)
    assert cleaned == "강남"
    assert not is_rej

    # 拟声词 ㅋㅋ, ㅠㅠ, 두근두근 (NFKC 下兼容 Jamo 归一化)
    text_ono = "두근두근 정말 웃겨요 ㅋㅋ ㅠㅠ"
    cleaned_ono, is_rej_ono, _ = sanitize_korean_text(text_ono)
    assert "두근두근" in cleaned_ono
    assert unicodedata.normalize("NFKC", "ㅋㅋ") in cleaned_ono
    assert unicodedata.normalize("NFKC", "ㅠㅠ") in cleaned_ono
    assert not is_rej_ono


def test_korean_noise_sanitization():
    """验证尾部 ASCII 乱码尾巴被清洗"""
    noisy_text = "오늘 뭐 해? TYAGOAL"
    cleaned, is_rej, action = sanitize_korean_text(noisy_text)
    assert "TYAGOAL" not in cleaned
    assert "오늘 뭐 해" in cleaned
    assert not is_rej


def test_korean_system_prompt_covers_honorifics_and_kinship():
    """验证 System Prompt 严格覆盖 4 级敬语与 6 大称呼映射"""
    # 4 级敬语
    assert "하십시오체" in KOREAN_SYSTEM_PROMPT
    assert "해요체" in KOREAN_SYSTEM_PROMPT
    assert "반말" in KOREAN_SYSTEM_PROMPT
    assert "해라체" in KOREAN_SYSTEM_PROMPT

    # 6 大称呼
    assert "형" in KOREAN_SYSTEM_PROMPT
    assert "오빠" in KOREAN_SYSTEM_PROMPT
    assert "누나" in KOREAN_SYSTEM_PROMPT
    assert "언니" in KOREAN_SYSTEM_PROMPT
    assert "선배" in KOREAN_SYSTEM_PROMPT
    assert "아저씨" in KOREAN_SYSTEM_PROMPT


def test_korean_name_glossary_enforcement():
    """
    L3 规范单测: 给定 5 个人名，断言走表不改字、缺表时保留原文，禁止自由音译
    测试样本:
      1. 민수 -> 走表映射为标准译名 '敏秀' (绝非自由音译 '民数')
      2. 지훈 -> 走表映射为 '志勋'
      3. 수진 -> 走表映射为 '秀珍'
      4. 영희 -> 缺表，严格保留韩文原文 '영희' (禁止擅自音译为 永姬/英姬)
      5. 철수 -> 缺表，严格保留韩文原文 '철수' (禁止擅自音译为 哲秀/澈秀)
    """
    test_names = [
        ("민수", "敏秀", True),
        ("지훈", "志勋", True),
        ("수진", "秀珍", True),
        ("영희", "영희", False),
        ("철수", "철수", False),
    ]

    # 1. 验证插件挂载的 resolve_name 规则接口存在
    assert hasattr(korean_plugin.text_rules, "resolve_name")
    assert callable(korean_plugin.text_rules.resolve_name)

    # 2. 逐条断言 5 个人名
    for raw_name, expected, in_glossary in test_names:
        actual = korean_plugin.text_rules.resolve_name(raw_name)
        assert actual == expected, f"人名转换不符: 输入={raw_name}, 期望={expected}, 实际={actual}"
        if in_glossary:
            assert actual != raw_name, f"表内人名未被查表映射: {raw_name}"
        else:
            assert actual == raw_name, f"缺表人名未保留韩文原文: {raw_name} -> {actual}"

