import pytest
from animeautosub.core.comparator import levenshtein_distance, compare_texts, calculate_cer

def test_ocr_comparator_diff_cases():
    # PO 指出的两个真实用例
    s1_a = "恵麻は私と夫のたった一人の娘だ。"
    s2_a = "恵麻は私と夫のたった一人的娘だ。"
    dist_a, label_a = compare_texts(s1_a, s2_a)
    assert dist_a == 1
    assert label_a == "DIFF(1)"
    assert label_a != "MATCH"

    s1_b = "帰ってきた晴斗には、しばらくここで生活することは話してあ"
    s2_b = "帰ってきた晴斗には、しばらくここで生活することは话してあ"
    dist_b, label_b = compare_texts(s1_b, s2_b)
    assert dist_b == 1
    assert label_b == "DIFF(1)"
    assert label_b != "MATCH"

def test_ocr_comparator_match_cases():
    s1 = "恵麻は私と夫のたった一人の娘だ。"
    s2 = "恵麻は私と夫のたった一人の娘だ。"
    dist, label = compare_texts(s1, s2)
    assert dist == 0
    assert label == "MATCH"

def test_ocr_comparator_edge_cases():
    assert compare_texts("", "") == (0, "MATCH")
    assert compare_texts("abc", "") == (3, "DIFF(3)")
    assert compare_texts("", "hello") == (5, "DIFF(5)")

def test_calculate_cer():
    assert calculate_cer(0, 100) == 0.0
    assert calculate_cer(2, 100) == 0.02
    assert calculate_cer(5, 0) == 0.0

def test_clean_ocr_text_preserves_semantics_and_handles_spaces():
    from pipeline_ocr import clean_ocr_text
    # 1. 日语拼接：不插入多余空格
    ja_boxes = ["熱が広", "がった。"]
    assert clean_ocr_text(ja_boxes, lang="japan") == "熱が広がった。"
    
    # 2. 换行语义保留：\\N 或 \\n 不被吞掉
    multiline_boxes = [r"第一行\N", "第二行"]
    assert clean_ocr_text(multiline_boxes, lang="japan") == r"第一行\N第二行"
    
    # 3. 英文依然保留空格拼接
    en_boxes = ["Hello", "World"]
    assert clean_ocr_text(en_boxes, lang="en") == "Hello World"

def test_select_stable_midpoint_text():
    from pipeline_ocr import select_stable_midpoint_text
    # 模拟包含淡入残片、稳定平原区、淡出残片的采样序列
    samples = [
        (1.0, "2"),                       # 淡入残片
        (1.2, "拓斗「えー？じゃあ、手伝"),     # 淡入半句
        (1.4, "拓斗「えー？じゃあ、手伝ったらお昼ご飯」"), # 稳定平原帧 1
        (1.6, "拓斗「えー？じゃあ、手伝ったらお昼ご飯」"), # 稳定平原帧 2 (中点)
        (1.8, "拓斗「えー？じゃあ、手伝ったらお昼ご飯」"), # 稳定平原帧 3
        (2.0, "拓斗「えー？じゃあ、")          # 淡出残片
    ]
    res = select_stable_midpoint_text(samples, min_stable_frames=2, sim_thresh=0.80)
    assert res == "拓斗「えー？じゃあ、手伝ったらお昼ご飯」"


def test_n5_rejection_pattern_and_logic():
    r"""U2: 智能切除修复与拒识门禁校验 (切除局部乱码，保留前后有效文本)"""
    import pipeline_ocr

    # 1. 局部乱码但主体有效 -> 成功切除并保留前后文本 (is_rejected == False)
    c1, rej1, act1 = pipeline_ocr.sanitize_japanese_text("枝彌「いい加減にしなさい。あなた、もう何日も帰LC972M192「LOEUACES")
    assert rej1 is False
    assert "いい加減にしなさい" in c1
    assert "LC972" not in c1

    c2, rej2, act2 = pipeline_ocr.sanitize_japanese_text("惠麻どこだっ97211112お母さんには関係ないんだがら」")
    assert rej2 is False
    assert "お母さんには関係ない" in c2
    assert "97211112" not in c2

    c3, rej3, act3 = pipeline_ocr.sanitize_japanese_text("惠麻うっざ。別にいいでしよ、私がどうしよう80080がさ」")
    assert rej3 is False
    assert "別にいいでしよ" in c3
    assert "80080" not in c3

    # 2. 纯垃圾或有效长度 < 40% -> 整句拒识 (is_rejected == True)
    assert pipeline_ocr.is_n5_rejected("TYAGOAL")[0] is True
    assert pipeline_ocr.is_n5_rejected("枝彌一えっ、ど「&22c115?")[0] is True

    # 3. 正常台词及合法数字严禁误拒或误删
    c4, rej4, _ = pipeline_ocr.sanitize_japanese_text("あと300メートルだ！")
    assert rej4 is False
    assert "300メートル" in c4

    c5, rej5, _ = pipeline_ocr.sanitize_japanese_text("100人が集まった")
    assert rej5 is False
    assert "100人" in c5

    assert pipeline_ocr.is_n5_rejected("枝彌「はいはい。二人とも、気を付けて行ってらっしゃいね」")[0] is False
    assert pipeline_ocr.is_n5_rejected("拓斗「そんなの後でいいじゃん。それより俺と遊ぼうぜ」")[0] is False
    assert pipeline_ocr.is_n5_rejected("留下来的只有我和三男拓斗。")[0] is False
