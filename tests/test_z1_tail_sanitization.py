"""
AnimeAutoSub 测试: Z1 尾部乱码切除与样本验证 (tests/test_z1_tail_sanitization.py)

验收标准:
  a) 在 sanitize_japanese_text 的翻译前清洗里，切除尾部连续拉丁/希腊字母/数字/点号混杂乱码；
  b) 切除后若剩余长度 < 原长度 50%，才整句拒识；
  c) 喂入真实坏样本，断言输出不含任何拉丁/希腊字符；
  d) 保证合法片名 (如 The Motion Anime) 不被误杀拒识。
"""

import re
import pytest
from lang.ja import sanitize_japanese_text
import pipeline_ocr


# 4 个核心真实退化样本 (来自 21684-720p 真实任务)
SAMPLES = [
    # #65 (~490s)
    "百合「はあ、んぐ、んつ、ちゅ、はあっ、はあっ……こ、これでいいの？ちゆば、ぢゆば、...Cy....cg",
    # #67 (~493s)
    "百合「はあ、んぐ、んつ、ちゅ、はあっ、はあっ……こ、これでいいの？ちゅば、ぢゅば、.....cγ.....cg",
    # #115 (~866s)
    "百合「ここで、こんなことしてたら、絶対に……あ、ああっ、起きて……雄一さんが…i...cyy.....c",
    # #191 (~1421s)
    "青葉「僕もだよ、姉さん……もう、おかしくなり過ぎて、何がなんだかわからないよ、「....cflff1"
]

# 额外真实退化样本 (#150, #158, #160)
EXTENDED_SAMPLES = [
    # #150 (~1148s)
    "百合「あなたより先にイって、ごめんなさ……ああん！はあ、はあ、こんなの、いけi……C……?…………",
    # #158 (~1189s)
    "百合「はあ、ふう、はあつ、はあつ……こんな……こんなこと……どうして……私、な……2なγ2ユ7にス……2γ",
    # #160 (~1195s)
    "百合「はあ、ふう、はあっ、はあつ……こんな……こんなこと……どうして……私、な「……2なγ2ユ7にス……2γ"
]


@pytest.mark.parametrize("raw_sample", SAMPLES)
def test_z1_four_real_samples_contain_no_latin_or_greek(raw_sample):
    """验证 4 个真实坏样本经清洗后，输出绝不含任何拉丁或希腊字符且不被误拒识"""
    cleaned, is_rej, act = sanitize_japanese_text(raw_sample)

    assert not is_rej, f"样本不应被拒识: {raw_sample} -> {cleaned} ({act})"
    latin_greek = re.findall(r'[A-Za-zα-ωΑ-Ω]', cleaned)
    assert len(latin_greek) == 0, f"清洗后仍残留拉丁/希腊字符 {latin_greek} 在 '{cleaned}' 中"
    assert len(cleaned) >= 10, f"清洗后文本长度应保留主体: {cleaned}"


@pytest.mark.parametrize("raw_sample", EXTENDED_SAMPLES)
def test_z1_extended_samples_contain_no_latin_or_greek(raw_sample):
    """验证包含希腊字母与截断问号尾巴的样本也得到彻底净化"""
    cleaned, is_rej, act = sanitize_japanese_text(raw_sample)

    assert not is_rej, f"样本不应被拒识: {raw_sample} -> {cleaned} ({act})"
    latin_greek = re.findall(r'[A-Za-zα-ωΑ-Ω]', cleaned)
    assert len(latin_greek) == 0, f"清洗后仍残留拉丁/希腊字符 {latin_greek} 在 '{cleaned}' 中"


def test_z1_tail_cut_rejection_boundary():
    """验证切除规则 b: 切除后剩余长度 < 原长度 50% 时整句拒识"""
    # 构造尾部乱码超过 50% 的短句 (总长 20，有效 5，乱码 15)
    noise_heavy = "百合「あ」...Cy....cg..cflff1"
    cleaned, is_rej, act = sanitize_japanese_text(noise_heavy)
    assert is_rej is True, "剩余长度 < 50% 必须整句拒识"
    assert "remaining_ratio" in act or "lt_0.50" in act


def test_z1_english_title_preservation():
    """验证片名 (The Motion Anime) 等纯英文章节卡不被误杀"""
    title = "The Motion Anime"
    cleaned, is_rej, act = sanitize_japanese_text(title)
    assert is_rej is False
    assert cleaned == "The Motion Anime"


def test_z1_pipeline_ocr_parity():
    """验证 pipeline_ocr.py 与 lang/ja.py 保持完全一致的清洗表现"""
    for sample in SAMPLES + EXTENDED_SAMPLES:
        c1, rej1, _ = sanitize_japanese_text(sample)
        c2, rej2, _ = pipeline_ocr.sanitize_japanese_text(sample)
        assert c1 == c2
        assert rej1 == rej2
