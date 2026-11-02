"""
AnimeAutoSub 文本比对与编辑距离度量模块
========================================
提供严格的 Levenshtein 编辑距离算法与一致性判据。
"""

from typing import Tuple

def levenshtein_distance(s1: str, s2: str) -> int:
    """计算两个字符串之间的 Levenshtein 最小编辑距离。"""
    m, n = len(s1), len(s2)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(m + 1):
        dp[i][0] = i
    for j in range(n + 1):
        dp[0][j] = j
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if s1[i - 1] == s2[j - 1]:
                dp[i][j] = dp[i - 1][j - 1]
            else:
                dp[i][j] = 1 + min(dp[i - 1][j], dp[i][j - 1], dp[i - 1][j - 1])
    return dp[m][n]

def compare_texts(s1: str, s2: str) -> Tuple[int, str]:
    """比对两个文本字符串。
    
    返回:
        (edit_distance, status_label)
        当 edit_distance == 0 时，status_label 必须为 'MATCH'
        当 edit_distance > 0 时，status_label 必须为 'DIFF(<dist>)'
    """
    dist = levenshtein_distance(s1, s2)
    if dist == 0:
        return 0, "MATCH"
    else:
        return dist, f"DIFF({dist})"

def calculate_cer(total_edit_distance: int, total_reference_chars: int) -> float:
    """计算字符错误率 CER (Character Error Rate)。"""
    if total_reference_chars <= 0:
        return 0.0
    return total_edit_distance / total_reference_chars
