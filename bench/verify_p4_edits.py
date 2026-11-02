import json

def get_edits(s1, s2):
    """
    s1: ocr (hyp)
    s2: truth (ref)
    Returns: list of (op, char_s1, char_s2)
    where op is 'match', 'sub', 'del' (s1 has extra, or deletion from s1 to match s2 -> insertion from s2), 'ins' (s2 has extra -> deletion from truth to hyp)
    """
    m, n = len(s1), len(s2)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(m + 1):
        dp[i][0] = i
    for j in range(n + 1):
        dp[0][j] = j
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            cost = 0 if s1[i - 1] == s2[j - 1] else 1
            dp[i][j] = min(dp[i - 1][j] + 1, dp[i][j - 1] + 1, dp[i - 1][j - 1] + cost)

    i, j = m, n
    ops = []
    while i > 0 or j > 0:
        if i > 0 and j > 0 and dp[i][j] == dp[i - 1][j - 1] + (0 if s1[i - 1] == s2[j - 1] else 1):
            if s1[i - 1] == s2[j - 1]:
                ops.append(('match', s1[i - 1], s2[j - 1]))
            else:
                ops.append(('sub', s1[i - 1], s2[j - 1]))
            i -= 1
            j -= 1
        elif i > 0 and dp[i][j] == dp[i - 1][j] + 1:
            ops.append(('ins_in_hyp', s1[i - 1], '')) # extra char in ocr
            i -= 1
        else:
            ops.append(('del_in_hyp', '', s2[j - 1])) # missing char in ocr
            j -= 1
    ops.reverse()
    return dp[m][n], ops

with open('bench/m2_m3_final_report.json', 'r', encoding='utf-8') as f:
    frames = json.load(f)['short_15_frames']['frames']

print("=== 逐帧编辑距离详细对齐 ===")
total_edits = 0
for f in frames:
    fid = f['id']
    hyp = f['center_text']
    ref = f['truth']
    dist, ops = get_edits(hyp, ref)
    total_edits += dist
    print(f"\n--- 帧 {fid:02d} (编辑距离: {dist}) ---")
    print(f"HYP: {hyp}")
    print(f"REF: {ref}")
    edit_ops = [op for op in ops if op[0] != 'match']
    for op in edit_ops:
        print(f"  {op[0]:10s}: hyp='{op[1]}' vs ref='{op[2]}'")

print(f"\n总编辑距离检验: {total_edits} (应等于 98)")
