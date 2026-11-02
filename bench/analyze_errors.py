import json

with open('bench/m2_m3_final_report.json', 'r', encoding='utf-8') as f:
    d = json.load(f)['short_15_frames']['frames']

print("帧号 | 真值长 | 识别长 | 编辑距 | 尾部缺失 | 错误分类与现象")
print("-" * 75)
truncation_edits = 0
noise_edits = 0
subst_edits = 0

for f in d:
    txt = f['voted_text']
    truth = f['truth']
    dist = f['voted_dist']
    diff_len = len(truth) - len(txt)
    
    # 分类
    category = []
    if diff_len > 0:
        category.append(f"尾部截断(-{diff_len}字)")
        truncation_edits += diff_len
    if any(c in txt for c in "0123456789&"):
        category.append("含乱码/数字")
        noise_edits += 3
    if not category:
        category.append("形近字/错别字")
        subst_edits += dist

    cat_str = ", ".join(category)
    print(f"{f['id']:02d}   | {len(truth):2d}     | {len(txt):2d}     | {dist:2d}     | {diff_len:+2d}       | {cat_str}")
    print(f"       真值: {truth}")
    print(f"       识别: {txt}")

print("-" * 75)
print(f"总真值: 439 字符 | 总编辑距离: {sum(f['voted_dist'] for f in d)} (CER: {sum(f['voted_dist'] for f in d)/439*100:.2f}%)")
