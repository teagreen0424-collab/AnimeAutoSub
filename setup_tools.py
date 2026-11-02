"""
自动下载与初始化工具及模型
===========================
1. 下载并安装 FFmpeg -> D:\Dev\ffmpeg (已完成)
2. 预下载 Whisper ASR 模型 -> D:\Dev\huggingface (已完成)
3. 预下载 Demucs 人声分离模型 -> D:\Dev\huggingface (已完成)
4. 下载并配置 Ollama -> D:\Dev\ollama
5. 下载 Sakura-7B 翻译模型 -> D:\Dev\ollama\models
"""

import os
import sys
import time
import shutil
import zipfile
import subprocess
import requests
from pathlib import Path

# 确保环境变量指向 D:\Dev
os.environ["HF_HOME"] = r"D:\Dev\huggingface"
os.environ["HF_HUB_CACHE"] = r"D:\Dev\huggingface\hub"
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
os.environ["TORCH_HOME"] = r"D:\Dev\torch"
os.environ["OLLAMA_MODELS"] = r"D:\Dev\ollama\models"

DEV_DIR = Path(r"D:\Dev")
FFMPEG_DIR = DEV_DIR / "ffmpeg"
OLLAMA_DIR = DEV_DIR / "ollama"
MODELS_DIR = OLLAMA_DIR / "models"

def download_file(url: str, dest_path: Path, desc: str):
    """健壮的带进度下载函数"""
    print(f"\n[开始下载] {desc}")
    print(f"来源: {url}")
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = dest_path.with_suffix(dest_path.suffix + ".part")
    
    downloaded = 0
    headers = {}
    if temp_path.exists():
        downloaded = temp_path.stat().st_size
        if downloaded > 0:
            headers["Range"] = f"bytes={downloaded}-"
            print(f"  检测到已下载: {downloaded / 1024**2:.1f} MB，支持断点续传")

    with requests.get(url, stream=True, headers=headers, timeout=60) as r:
        if r.status_code == 416:  # 已经全部下载完
            pass
        else:
            r.raise_for_status()
            total = int(r.headers.get("content-length", 0)) + downloaded
            
            mode = "ab" if downloaded > 0 else "wb"
            with open(temp_path, mode) as f:
                last_time = time.time()
                last_bytes = downloaded
                for chunk in r.iter_content(chunk_size=1024 * 1024):  # 1MB 块
                    if chunk:
                        f.write(chunk)
                        f.flush()
                        downloaded += len(chunk)
                        
                        now = time.time()
                        if now - last_time >= 3:  # 每 3 秒打印一次进度
                            speed = (downloaded - last_bytes) / (now - last_time) / 1024**2
                            mb = downloaded / 1024**2
                            total_mb = total / 1024**2 if total > 0 else 0
                            pct = f"{(downloaded / total) * 100:.1f}%" if total > 0 else "??%"
                            print(f"  进度: {pct} ({mb:.1f} / {total_mb:.1f} MB) | 速度: {speed:.2f} MB/s", flush=True)
                            last_time = now
                            last_bytes = downloaded

    if temp_path.exists():
        if dest_path.exists():
            dest_path.unlink()
        temp_path.rename(dest_path)
    print(f"[下载完成] {desc} -> {dest_path}", flush=True)

def install_ollama():
    """下载并解压 Ollama 独立便携版"""
    ollama_exe = OLLAMA_DIR / "ollama.exe"
    if ollama_exe.exists():
        print(f"✓ Ollama 已经就绪: {ollama_exe}")
        return

    url = "https://github.com/ollama/ollama/releases/download/v0.40.13/ollama-windows-amd64.zip"
    zip_path = DEV_DIR / "ollama.zip"
    download_file(url, zip_path, "Ollama Windows 独立包 (约 1.5 GB)")

    print("  解压 Ollama 到 D:\\Dev\\ollama ...", flush=True)
    OLLAMA_DIR.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, 'r') as zf:
        zf.extractall(OLLAMA_DIR)
        
    if zip_path.exists():
        zip_path.unlink()
        
    # 创建 start_ollama.bat
    bat_content = (
        "@echo off\r\n"
        "chcp 65001 >nul\r\n"
        "set OLLAMA_MODELS=D:\\Dev\\ollama\\models\r\n"
        "echo 启动 Ollama 服务 (模型目录: D:\\Dev\\ollama\\models)...\r\n"
        f"\"{OLLAMA_DIR}\\ollama.exe\" serve\r\n"
    )
    with open(OLLAMA_DIR / "start_ollama.bat", "w", encoding="gbk") as f:
        f.write(bat_content)

    print(f"✓ Ollama 安装就绪: {ollama_exe}", flush=True)

def download_sakura():
    """下载 Sakura-7B GGUF 并生成 Modelfile"""
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    
    gguf_name = "sakura-7b-qwen2.5-v1.0-iq4xs.gguf"
    gguf_path = MODELS_DIR / gguf_name
    
    if not gguf_path.exists():
        url = f"https://hf-mirror.com/SakuraLLM/Sakura-7B-Qwen2.5-v1.0-GGUF/resolve/main/{gguf_name}"
        download_file(url, gguf_path, "Sakura-7B Qwen2.5 GGUF 翻译模型 (约 3.9 GB)")
    else:
        print(f"✓ Sakura 模型权重已存在: {gguf_path}")

    # 写 Modelfile
    modelfile = MODELS_DIR / "Modelfile"
    content = (
        f"FROM {gguf_path.as_posix()}\n\n"
        "PARAMETER temperature 0.1\n"
        "PARAMETER top_p 0.3\n"
        "PARAMETER num_ctx 2048\n\n"
        "SYSTEM \"你是一个轻小说翻译模型，可以流畅通顺地以日本轻小说的风格将日文翻译成简体中文，并联系上下文正确使用人称代词，不擅自添加原文中没有的代词。\"\n"
    )
    with open(modelfile, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"✓ Modelfile 已创建: {modelfile}", flush=True)

def register_model_in_ollama():
    """在 Ollama 中注册 sakura 模型"""
    ollama_exe = OLLAMA_DIR / "ollama.exe"
    modelfile = MODELS_DIR / "Modelfile"
    
    if not ollama_exe.exists() or not modelfile.exists():
        print("未检测到 ollama 或 Modelfile，跳过注册")
        return

    print("  启动临时 Ollama 进程以注册模型...", flush=True)
    env = os.environ.copy()
    env["OLLAMA_MODELS"] = str(MODELS_DIR)
    
    proc = subprocess.Popen([str(ollama_exe), "serve"], env=env)
    time.sleep(3)
    
    try:
        print("  执行: ollama create sakura -f Modelfile ...", flush=True)
        r = subprocess.run([str(ollama_exe), "create", "sakura", "-f", str(modelfile)], env=env, capture_output=True, text=True)
        print(r.stdout)
        if r.returncode == 0:
            print("✓ Sakura 翻译模型已成功导入 Ollama！模型名称: sakura")
        else:
            print("注册输出:", r.stderr)
    finally:
        proc.terminate()

if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "all"
    if action in ("all", "ollama"):
        install_ollama()
    if action in ("all", "sakura"):
        download_sakura()
    if action in ("all", "register"):
        register_model_in_ollama()
