"""
OCR 确定性测试 (F5 门禁验证)
==========================
对真实视频抽取 100 帧，使用 RapidOCR (CUDA) 运行两次完整推理，
统计两轮输出在文本内容上的字符级错误率 (CER) 与精确匹配率。
"""

import sys
import os
from pathlib import Path

# 将项目根目录推入 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 确保环境加载
import animeautosub._env
import cv2
import numpy as np
from rapidocr import RapidOCR

def levenshtein_distance(s1: str, s2: str) -> int:
    """计算两字符串编辑距离"""
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

def main():
    video_path = Path("ocr_input/114877-720p.mp4")
    if not video_path.exists():
        print(f"Error: {video_path} not found")
        sys.exit(1)

    cap = cv2.VideoCapture(str(video_path))
    # 定位到一个字幕密集的区间 (例如 42.6 秒开始，对应前述枝弥台词)
    fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    start_frame = int(42.6 * fps)
    cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

    frames = []
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    roi_top = int(h * (1.0 - 0.28))

    print(f"抽取 100 帧 (分辨率 {w}x{h}, 截取底部 28% y={roi_top}:{h}, 起始时间 42.6s)...")
    for _ in range(100):
        ret, frame = cap.read()
        if not ret:
            break
        # 裁剪底部 28%
        roi = frame[roi_top:h, 0:w]
        frames.append(roi)
    cap.release()

    print(f"成功获取 {len(frames)} 帧。初始化 RapidOCR (CUDA)...")
    from rapidocr.utils.log import logger as rapidocr_logger
    rapidocr_logger.setLevel(50)
    ocr_params = {
        "EngineConfig.onnxruntime.use_cuda": True,
        "Rec.lang_type": "japan"
    }
    ocr = RapidOCR(params=ocr_params)

    print("执行 Pass 1...")
    results_pass1 = []
    for f in frames:
        out = ocr(f)
        text = ""
        if out and out.txts:
            text = "".join(out.txts)
        results_pass1.append(text)

    print("执行 Pass 2...")
    results_pass2 = []
    for f in frames:
        out = ocr(f)
        text = ""
        if out and out.txts:
            text = "".join(out.txts)
        results_pass2.append(text)

    # 统计差异
    exact_matches = 0
    total_chars = 0
    total_dist = 0
    diff_count = 0

    for i, (t1, t2) in enumerate(zip(results_pass1, results_pass2)):
        if t1 == t2:
            exact_matches += 1
        else:
            diff_count += 1
            d = levenshtein_distance(t1, t2)
            total_dist += d
            print(f"Frame {i} 差异: Pass1='{t1}' vs Pass2='{t2}', dist={d}")
        total_chars += len(t1)

    cer = (total_dist / total_chars) if total_chars > 0 else 0.0
    exact_rate = exact_matches / len(frames) * 100

    print("=" * 60)
    print("           RapidOCR (CUDA) 确定性测试报告")
    print("=" * 60)
    print(f"测试总帧数:        {len(frames)}")
    print(f"识别总字符数:      {total_chars}")
    print(f"帧文本完全一致数:  {exact_matches} / {len(frames)} ({exact_rate:.2f}%)")
    print(f"产生差异帧数:      {diff_count}")
    print(f"累计字符编辑距离:  {total_dist}")
    print(f"字符级错误率 (CER): {cer * 100:.4f}%")
    print("=" * 60)

    if diff_count == 0:
        print("结论: RapidOCR 在 CUDA 下具备 100% 逐字符确定性。")
        print("门禁建议: G1a parity 对 japanese.json 可采用 SHA256 精确哈希比对。")
    else:
        print(f"结论: 存在浮点/核函数非确定性，CER 为 {cer * 100:.4f}%。")
        print("门禁建议: G1a parity 对 japanese.json 必须采用 CER 阈值 (如 CER < 0.001) 判定。")

if __name__ == "__main__":
    main()
