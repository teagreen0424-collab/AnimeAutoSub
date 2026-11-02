import re
import json

# Japanese counters and units that commonly follow numbers
JP_UNITS = r'[人つ円回日月年分秒時点個番歳才倍割度本枚匹頭台万億千百％%kmgM]'
KANA = r'[\u3040-\u309F\u30A0-\u30FF]'

def is_garbled_number(match, full_text):
    """
    判断匹配到的数字是否为乱码：
    数字仅在孤立出现且前后无假名（或前后非合法日语数量搭配）时判为乱码。
    长数字（>=5位）直接判定为乱码水印/时间码。
    """
    num_str = match.group()
    start, end = match.span()
    
    # 5位及以上纯数字在动画台词中绝非正常口语 -> 乱码
    if len(num_str) >= 5:
        return True
    
    # 前后字符上下文
    prev_char = full_text[start - 1] if start > 0 else ""
    next_char = full_text[end] if end < len(full_text) else ""
    
    # 如果紧邻假名或单位 -> 属于正常词汇（如 300メートル, 100人, 3日）
    if re.match(KANA, next_char) or re.match(JP_UNITS, next_char):
        return False
    if re.match(KANA, prev_char) and not re.match(r'[っッ]', prev_char):
        return False
        
    # 否则（孤立出现、或与标点/英文字母相邻）判定为乱码
    return True

def sanitize_japanese_text(raw_text: str):
    """
    U2: 切除乱码片段、保留前后文本后拼接。
    规则：
      1. 匹配字母/符号混杂乱码（如 LC972M192「LOEUACES, [L972432, &22c115）
      2. 匹配孤立/非假名数字（如 97211112, 80080）
      3. 切除乱码片段并拼接前后文本
      4. 仅当剩余有效文本长度 < 原长度 40% 时整句拒识
    """
    if not raw_text:
        return "", True, "empty"
        
    orig_len = len(raw_text)
    
    # 1. 查找混合乱码片段 (含大写字母序列、符号乱码、括号带英文字符等)
    # 例如: LC972M192「LOEUACES, [L972432, &22c115?, 80080, 97211112
    # 模式A: 含有大写英文字母3个以上，或符号串2个以上，或括号紧随英数字
    garble_patterns = [
        r'[A-Za-z0-9_]*[A-Z]{2,}[A-Za-z0-9_「」]*',  # 如 LC972M192「LOEUACES, TLOEUZCES
        r'\[[A-Za-z0-9_]+',                         # 如 [L972432
        r'[&#@$%^~+=*|/\\<>]{1,}[A-Za-z0-9_?]*',     # 如 &22c115?
        r'\d{5,}',                                  # 5位以上长数字如 97211112, 80080
    ]
    combined_pattern = re.compile('|'.join(garble_patterns))
    
    cleaned = raw_text
    removed_snippets = []
    
    # 切除匹配到的片段
    for m in combined_pattern.finditer(raw_text):
        snippet = m.group()
        if snippet:
            removed_snippets.append(snippet)
            
    # 执行替换删除
    cleaned = combined_pattern.sub('', raw_text)
    
    # 进一步检查孤立 3-4 位数字
    def replace_isolated_digits(m):
        if is_garbled_number(m, cleaned):
            removed_snippets.append(m.group())
            return ""
        return m.group()
        
    cleaned = re.sub(r'\d{3,4}', replace_isolated_digits, cleaned)
    
    # 整理标点：去除末尾不闭合的悬空符号，并 strip
    cleaned = re.sub(r'[\s「」\[\]]+$', '', cleaned).strip()
    
    rem_len = len(cleaned)
    rem_ratio = rem_len / max(1, orig_len)
    
    # 判定是否整句拒识 (剩余长度 < 40%)
    if rem_ratio < 0.40 or rem_len < 3:
        return cleaned, True, f"remaining_ratio_{rem_ratio:.2f}_lt_0.40"
    
    return cleaned, False, removed_snippets

with open('ocr_output/test_3min/japanese.json', 'r', encoding='utf-8') as f:
    segs = json.load(f)

print(f"Total sentences: {len(segs)}")
rejected_count = 0
for idx, s in enumerate(segs):
    raw = s["text"]
    cleaned, is_rej, reason = sanitize_japanese_text(raw)
    if is_rej:
        rejected_count += 1
        print(f"\n[REJECTED #{rejected_count}] Idx {idx+1}:")
        print(f"  Raw:     '{raw}'")
        print(f"  Cleaned: '{cleaned}' (len {len(cleaned)} / {len(raw)} = {len(cleaned)/len(raw):.1%})")
        print(f"  Reason:  {reason}")
    elif reason: # had snippets removed
        print(f"\n[SALVAGED] Idx {idx+1}:")
        print(f"  Raw:     '{raw}'")
        print(f"  Cleaned: '{cleaned}' (len {len(cleaned)} / {len(raw)} = {len(cleaned)/len(raw):.1%})")
        print(f"  Cut:     {reason}")

rej_pct = (rejected_count / len(segs)) * 100
print(f"\nSummary: {rejected_count}/{len(segs)} rejected ({rej_pct:.2f}%). Target <= 3.0%")
