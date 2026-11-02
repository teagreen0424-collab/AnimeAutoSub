"""
AnimeAutoSub 根环境配置与路径纪律注入器 (_env.py)
===================================================
所有入口脚本必须在最顶层（任何第三方库导入前）执行：
    import animeautosub._env
保证 D:\Dev 路径约束与 Windows DLL 绑定在任何调用场景下 100% 成立。
"""

import os
import sys
from pathlib import Path

# 1. 强制设定模型、缓存与执行工具根目录到 D:\Dev
DEV_DIR = Path(r"D:\Dev")
HF_HOME = DEV_DIR / "huggingface"
HF_HUB_CACHE = HF_HOME / "hub"
TORCH_HOME = DEV_DIR / "torch"
OLLAMA_MODELS = DEV_DIR / "ollama" / "models"
FFMPEG_BIN = DEV_DIR / "ffmpeg" / "bin"

os.environ["HF_HOME"] = str(HF_HOME)
os.environ["HF_HUB_CACHE"] = str(HF_HUB_CACHE)
os.environ["TORCH_HOME"] = str(TORCH_HOME)
os.environ["OLLAMA_MODELS"] = str(OLLAMA_MODELS)

# 确保 D:\Dev\ffmpeg\bin 在 PATH 优先位
current_path = os.environ.get("PATH", "")
if str(FFMPEG_BIN) not in current_path:
    os.environ["PATH"] = f"{FFMPEG_BIN};{current_path}"

# 2. 显式配置 CUDA 12 与 cuDNN 9 动态库目录（严禁向全局 PATH 注入）
# 优先检查独立的 nvidia-cudnn-cu12 / nvidia-cublas-cu12，兜底检测 torch/lib
_site_packages = Path(sys.prefix) / "Lib" / "site-packages"
_candidate_dirs = [
    _site_packages / "nvidia" / "cudnn" / "bin",
    _site_packages / "nvidia" / "cublas" / "bin",
    _site_packages / "torch" / "lib",
    _site_packages / "onnxruntime" / "capi",
]

_loaded_cookies = []
for _d in _candidate_dirs:
    if _d.exists() and hasattr(os, "add_dll_directory"):
        try:
            _loaded_cookies.append(os.add_dll_directory(str(_d)))
        except Exception:
            pass

# 显式预加载核心 CUDA 与 cuDNN 9 动态库，确保即使不污染全局 PATH，Windows PE 加载器也能就绪
import ctypes
_REQUIRED_CUDA_DLLS = [
    "cudart64_12.dll",
    "cublasLt64_12.dll",
    "cublas64_12.dll",
    "cufft64_11.dll",
    "cudnn_ops64_9.dll",
    "cudnn_cnn64_9.dll",
    "cudnn_adv64_9.dll",
    "cudnn_graph64_9.dll",
    "cudnn_heuristic64_9.dll",
    "cudnn_engines_runtime_compiled64_9.dll",
    "cudnn_engines_precompiled64_9.dll",
    "cudnn64_9.dll",
    "onnxruntime_providers_shared.dll",
]

for _dll_name in _REQUIRED_CUDA_DLLS:
    for _d in _candidate_dirs:
        _dll_path = _d / _dll_name
        if _dll_path.exists():
            try:
                ctypes.CDLL(str(_dll_path))
                break
            except Exception:
                pass
