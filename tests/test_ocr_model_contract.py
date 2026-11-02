import pytest
from pathlib import Path
import numpy as np
import animeautosub._env
from pipeline_ocr import build_ocr_engine


def test_production_ocr_model_contract():
    """
    断言生产环境 OCR 引擎契约（防止误切 japan 模型导致 CER 暴跌 10pt）：
    1. 实际加载的 rec 模型必须为 PP-OCRv6 多语种模型 (pp-ocrv6_rec_small.onnx)；
    2. 词表规模必须为 18710 字符（涵盖常用汉字、假名及符号）。
    """
    engine = build_ocr_engine(use_cuda=False)
    # 预热推理触发按需加载模型
    engine(np.zeros((48, 300, 3), dtype=np.uint8), use_det=False)

    session = getattr(engine.text_rec.session, "session", None)
    assert session is not None, "未获取到 ONNX 推理会话"

    model_path = getattr(session, "_model_path", "")
    model_name = Path(model_path).name.lower()

    # 1. 断言实际模型文件名 == pp-ocrv6_rec_small.onnx
    assert model_name == "pp-ocrv6_rec_small.onnx", (
        f"生产 rec 模型异常: 实际加载了 {model_name}，预期必须为 pp-ocrv6_rec_small.onnx！"
        "切勿随意切换为 japan_PP-OCRv4_rec_mobile.onnx（实测 CER 27.44%，显著更差）。"
    )

    # 2. 断言词表规模 == 18710
    vocab_size = len(engine.text_rec.postprocess_op.character)
    assert vocab_size == 18710, (
        f"生产 rec 词表大小异常: 实际为 {vocab_size}，预期必须为 18710！"
    )


def test_production_ocr_cuda_provider():
    """
    R3 专项断言：断言生产 OCR 引擎启用 CUDA 时，Det 与 Rec 推理会话首选 Provider 均为 CUDAExecutionProvider。
    杜绝因 DLL 加载错误静默回退 CPU。
    """
    engine = build_ocr_engine(use_cuda=True)
    det_session = getattr(engine.text_det.session, "session", None)
    rec_session = getattr(engine.text_rec.session, "session", None)

    assert det_session is not None, "Det 会话未建立"
    assert rec_session is not None, "Rec 会话未建立"

    det_providers = det_session.get_providers()
    rec_providers = rec_session.get_providers()

    assert len(det_providers) > 0 and det_providers[0] == "CUDAExecutionProvider", (
        f"Det session 首选 Provider 异常: {det_providers}"
    )
    assert len(rec_providers) > 0 and rec_providers[0] == "CUDAExecutionProvider", (
        f"Rec session 首选 Provider 异常: {rec_providers}"
    )
