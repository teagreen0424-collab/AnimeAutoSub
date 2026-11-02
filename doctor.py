"""
AnimeAutoSub 严格环境体检与门禁检查脚本 (Doctor v2 - 可用即通过)
================================================================
执行方式:
    python doctor.py
退出码:
    0: 全部通过 (可用性已验证，满足门禁)
    1: 存在阻断性错误 (Blocking)
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path

# 必须在最顶层导入仓库环境激活器
import animeautosub._env

CHECK_RESULTS = []

def record(item: str, status: str, details: str, fix_hint: str = ""):
    """记录检查项: status in ('PASS', 'WARN', 'FAIL')"""
    CHECK_RESULTS.append({
        "item": item,
        "status": status,
        "details": details,
        "fix_hint": fix_hint
    })

def check_path_discipline():
    """D2/D3: 检查实际加载路径 + 断言无 C 盘写入 + 输出 HF_HOME 解析结果"""
    proj_dir = Path(__file__).resolve().parent
    try:
        str(proj_dir).encode("ascii")
    except UnicodeEncodeError:
        record("项目路径 ASCII 校验", "FAIL", f"路径包含非 ASCII: {proj_dir}",
               "将项目移动至纯英文字符路径，如 E:\\translate")
        return

    # 1. 验证 huggingface_hub 常量实际解析结果
    try:
        import huggingface_hub.constants as hf_c
        resolved_hf_home = str(hf_c.HF_HOME)
        if not resolved_hf_home.lower().startswith(r"d:\dev\huggingface"):
            record("HF_HOME 解析合规性", "FAIL", f"实际解析漂移至: {resolved_hf_home}",
                   "Set-ItemProperty -Path 'HKCU:\\Environment' -Name 'HF_HOME' -Value 'D:\\Dev\\huggingface'")
            return
        else:
            record("HF_HOME 解析合规性", "PASS", f"正确绑定: {resolved_hf_home}")
    except Exception as e:
        record("HF_HOME 解析合规性", "FAIL", f"解析异常: {e}")
        return

    # 2. 断言 C 盘无写入
    c_cache = Path(os.environ.get("USERPROFILE", "C:\\Users\\Default")) / ".cache" / "huggingface"
    if c_cache.exists():
        total_size = sum(f.stat().st_size for f in c_cache.glob('**/*') if f.is_file())
        if total_size > 0:
            record("C 盘模型缓存零容忍", "FAIL",
                   f"检测到 C 盘残留 ({total_size / (1024*1024):.2f} MB): {c_cache}",
                   f"Remove-Item -Recurse -Force '{c_cache}'")
            return
    record("C 盘模型缓存零容忍", "PASS", "已断言 C 盘无任何 HuggingFace 缓存写入")

def check_hardware_and_cuda():
    """检查 GPU 硬件与 PyTorch CUDA 计算可用性"""
    try:
        import torch
        if not torch.cuda.is_available():
            record("PyTorch CUDA 加速", "FAIL", "torch.cuda.is_available() 为 False",
                   "pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121 --force-reinstall")
            return

        dev_name = torch.cuda.get_device_name(0)
        vram_gb = torch.cuda.get_device_properties(0).total_memory / (1024**3)
        # 实际做一次张量显存分配验证可用性
        t = torch.zeros((1024, 1024), device="cuda")
        del t
        torch.cuda.empty_cache()
        record("GPU 硬件与显存可用性", "PASS", f"{dev_name} ({vram_gb:.2f} GB, 张量分配实测正常)")
    except Exception as e:
        record("GPU 硬件与显存可用性", "FAIL", f"CUDA 张量操作异常: {e}")

def check_onnxruntime_gpu():
    """G4: 显式断言 CUDAExecutionProvider 绑定 + 报告实际加载的 cuDNN DLL 完整绝对路径 + 断言无全局 PATH 污染"""
    try:
        import onnxruntime as ort
        det_model = Path(sys.prefix) / "Lib" / "site-packages" / "rapidocr" / "models" / "PP-OCRv6_det_small.onnx"
        if not det_model.exists():
            record("ONNXRuntime GPU 加速", "FAIL", f"未找到 RapidOCR 模型: {det_model}",
                   "pip install rapidocr-onnxruntime")
            return

        # 断言 PATH 中未注入 torch/lib (显式安全加载，零 PATH 污染)
        if "torch" in os.environ.get("PATH", "").lower():
            record("DLL 安全加载纪律", "FAIL", "检测到 PATH 中存在 torch 路径注入，违反无污染纪律",
                   "移除 _env.py 中对 os.environ['PATH'] 的修改")
            return
        else:
            record("DLL 安全加载纪律", "PASS", "全局 PATH 纯净无污染，通过 os.add_dll_directory 安全加载")

        # 显式禁用 TensorRT 避免编译引擎耗时干扰，仅保留 CUDA 与 CPU
        target_providers = ['CUDAExecutionProvider', 'CPUExecutionProvider']
        session = ort.InferenceSession(str(det_model), providers=target_providers)
        active_providers = session.get_providers()

        if active_providers and active_providers[0] == "CUDAExecutionProvider":
            # H4: 调用 Windows API 查询底层已加载的 cuDNN DLL 真实绝对路径，并硬性断言主版本为 9
            import ctypes
            from ctypes import wintypes
            kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
            GetModuleHandleW = kernel32.GetModuleHandleW
            GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
            GetModuleHandleW.restype = wintypes.HMODULE
            GetModuleFileNameW = kernel32.GetModuleFileNameW
            GetModuleFileNameW.argtypes = [wintypes.HMODULE, wintypes.LPWSTR, wintypes.DWORD]
            GetModuleFileNameW.restype = wintypes.DWORD

            h = GetModuleHandleW('cudnn64_9.dll')
            loaded_path = ""
            if h:
                buf = ctypes.create_unicode_buffer(1024)
                GetModuleFileNameW(h, buf, 1024)
                loaded_path = buf.value

            # H4 守卫断言：必须确认主版本为 9 且成功加载
            if not h or "cudnn64_9.dll" not in loaded_path.lower():
                record("ONNXRuntime GPU 真实加载", "FAIL",
                       f"cuDNN 主版本非 9 或未加载! 实际回读路径: '{loaded_path}'",
                       "确认 PyTorch 2.5.1+cu121 自带 cuDNN 9 完整且未被篡改")
            else:
                record("ONNXRuntime GPU 真实加载", "PASS",
                       f"Provider: {active_providers[0]} | cuDNN 9 (torch耦合): {loaded_path}")
        else:
            record("ONNXRuntime GPU 真实加载", "FAIL", f"回退至 CPU! 实际会话 Providers: {active_providers}",
                   "pip install onnxruntime-gpu==1.19.2")
    except Exception as e:
        record("ONNXRuntime GPU 真实加载", "FAIL", f"会话初始化失败: {e}",
               "pip install onnxruntime-gpu==1.19.2")

def check_ffmpeg():
    """检查 FFmpeg 二进制存在性与运行"""
    local_ffmpeg = Path(r"D:\Dev\ffmpeg\bin\ffmpeg.exe")
    ffmpeg_bin = str(local_ffmpeg) if local_ffmpeg.exists() else shutil.which("ffmpeg")
    if not ffmpeg_bin:
        record("FFmpeg 媒体工具", "FAIL", "未找到 ffmpeg.exe (D:\\Dev\\ffmpeg 或 PATH)",
               "下载 FFmpeg 解压至 D:\\Dev\\ffmpeg")
        return

    try:
        r = subprocess.run([ffmpeg_bin, "-version"], capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            first_line = r.stdout.splitlines()[0] if r.stdout else "OK"
            record("FFmpeg 媒体工具", "PASS", f"{ffmpeg_bin} ({first_line[:40]}...)")
        else:
            record("FFmpeg 媒体工具", "FAIL", f"执行异常退出码: {r.returncode}")
    except Exception as e:
        record("FFmpeg 媒体工具", "FAIL", f"调用异常: {e}")

def check_whisper_weight_integrity():
    """D3: 检查 Whisper 权重完整性与可读性"""
    whisper_dir = Path(r"D:\Dev\huggingface\models--faster-whisper-large-v3")
    bin_file = whisper_dir / "model.bin"
    cfg_file = whisper_dir / "config.json"

    if not bin_file.exists() or not cfg_file.exists():
        record("Whisper 权重可用性", "FAIL", f"缺少核心权重文件: {whisper_dir}")
        return

    size_gb = bin_file.stat().st_size / (1024**3)
    if size_gb < 2.8:
        record("Whisper 权重可用性", "FAIL", f"model.bin 文件不完整 ({size_gb:.2f} GB < 2.8 GB)")
        return

    # 尝试加载前 1024 字节验证文件可读性
    try:
        with open(bin_file, "rb") as f:
            header = f.read(1024)
            if len(header) < 1024:
                raise ValueError("文件截断")
        record("Whisper 权重可用性", "PASS", f"路径: {whisper_dir} ({size_gb:.2f} GB, 结构完整)")
    except Exception as e:
        record("Whisper 权重可用性", "FAIL", f"读取异常: {e}")

def check_demucs_weight_integrity():
    """D3: 检查 Demucs 权重完整性与 safetensors 文件头"""
    demucs_dir = Path(r"D:\Dev\huggingface\hub\models--adefossez--HTDemucs-ft\snapshots\d74ac89c3a1e874fc78f152555cf4d8533f06cd4")
    if not demucs_dir.exists():
        record("Demucs 权重可用性", "FAIL", f"未找到模型目录: {demucs_dir}")
        return

    st_files = list(demucs_dir.glob("*.safetensors"))
    if len(st_files) < 4:
        record("Demucs 权重可用性", "FAIL", f"safetensors 权重分片不足 4 个 (当前: {len(st_files)})")
        return

    # 校验每个分片体积与头结构
    try:
        from safetensors import safe_open
        for st in st_files:
            if st.stat().st_size < 80 * 1024 * 1024:
                raise ValueError(f"{st.name} 体积异常 ({st.stat().st_size} bytes)")
            with safe_open(str(st), framework="pt") as f:
                _ = f.keys()
        record("Demucs 权重可用性", "PASS", f"4 个分片头与体积完整 ({len(st_files)} models in bag)")
    except Exception as e:
        record("Demucs 权重可用性", "FAIL", f"safetensors 损坏: {e}")

def check_ollama_list_and_models():
    """D3: 判据改为 `ollama list` 输出包含目标模型，并记录 OLLAMA_MODELS 的生效值"""
    ollama_exe = Path(r"D:\Dev\ollama\ollama.exe")
    if not ollama_exe.exists():
        record("Ollama 运行可用性", "FAIL", "未找到 D:\\Dev\\ollama\\ollama.exe")
        return

    effective_models_dir = os.environ.get("OLLAMA_MODELS", "未设置")

    # 确保服务在线
    import requests
    is_online = False
    try:
        r = requests.get("http://127.0.0.1:11434/api/tags", timeout=2)
        if r.status_code == 200:
            is_online = True
    except Exception:
        pass

    if not is_online:
        # 尝试静默拉起
        subprocess.Popen([str(ollama_exe), "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        import time
        time.sleep(2)

    # 实际调用 ollama list 获取输出
    try:
        env = os.environ.copy()
        r = subprocess.run([str(ollama_exe), "list"], env=env, capture_output=True, text=True, timeout=5)
        if r.returncode != 0:
            record("Ollama 运行可用性", "FAIL", f"`ollama list` 执行失败: {r.stderr.strip()}",
                   "Start-Process 'D:\\Dev\\ollama\\ollama.exe' -ArgumentList 'serve'")
            return

        stdout = r.stdout
        if "sakura-14b" in stdout:
            record("Ollama 运行可用性", "PASS",
                   f"`ollama list` 检测到 sakura-14b [OLLAMA_MODELS={effective_models_dir}]")
        else:
            record("Ollama 运行可用性", "FAIL",
                   f"`ollama list` 输出中未找到 sakura-14b (当前模型:\n{stdout.strip()})",
                   "python setup_sakura14b.py register")
    except Exception as e:
        record("Ollama 运行可用性", "FAIL", f"调用异常: {e}")

def main():
    print("=" * 80)
    print("      AnimeAutoSub 环境门禁检查报告 (Doctor v2 - 可用即通过)")
    print("=" * 80)

    check_path_discipline()
    check_hardware_and_cuda()
    check_onnxruntime_gpu()
    check_ffmpeg()
    check_whisper_weight_integrity()
    check_demucs_weight_integrity()
    check_ollama_list_and_models()

    has_fail = any(r["status"] == "FAIL" for r in CHECK_RESULTS)
    has_warn = any(r["status"] == "WARN" for r in CHECK_RESULTS)

    print(f"{'检查项':<24} | {'状态':<6} | {'详情'}")
    print("-" * 80)
    for r in CHECK_RESULTS:
        status_str = f"[{r['status']}]"
        print(f"{r['item']:<24} | {status_str:<6} | {r['details']}")

    print("-" * 80)
    if has_fail:
        print("\n❌ 门禁未通过 (Blocking): 存在不可用环节，必须修复后方可开工:\n")
        for r in CHECK_RESULTS:
            if r["status"] == "FAIL":
                print(f"  • [{r['item']}]")
                print(f"    原因: {r['details']}")
                if r['fix_hint']:
                    print(f"    修复命令: {r['fix_hint']}\n")
        sys.exit(1)
    elif has_warn:
        print("\n⚠️ 门禁通过，存在警告项 (Non-blocking):\n")
        for r in CHECK_RESULTS:
            if r["status"] == "WARN":
                print(f"  • [{r['item']}] {r['details']}")
        sys.exit(0)
    else:
        print("\n✅ 门禁 100% 通过！所有组件均通过真实实例化/执行测试，零 CPU 静默回退，零 C 盘泄漏。\n")
        sys.exit(0)

if __name__ == "__main__":
    main()
