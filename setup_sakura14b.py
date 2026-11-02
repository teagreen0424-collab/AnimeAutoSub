"""
下载 Sakura-14B 旗舰模型并注册到 Ollama
======================================
模型: Sakura-14B-Qwen2.5-v1.0-GGUF (iq4xs 7.62GB)
"""

import os
import sys
import time
import subprocess
import requests
from pathlib import Path

os.environ["OLLAMA_MODELS"] = r"D:\Dev\ollama\models"

DEV_DIR = Path(r"D:\Dev")
OLLAMA_DIR = DEV_DIR / "ollama"
MODELS_DIR = OLLAMA_DIR / "models"
MODELS_DIR.mkdir(parents=True, exist_ok=True)

GGUF_NAME = "sakura-14b-qwen2.5-v1.0-iq4xs.gguf"
GGUF_PATH = MODELS_DIR / GGUF_NAME
MODELFILE_PATH = MODELS_DIR / "Modelfile-14b"
MODEL_NAME = "sakura-14b"

def download_sakura14b():
    url = f"https://hf-mirror.com/SakuraLLM/Sakura-14B-Qwen2.5-v1.0-GGUF/resolve/main/{GGUF_NAME}"
    print(f"\n[开始下载] Sakura-14B 旗舰翻译模型 (7.62 GB)")
    print(f"来源: {url}")
    
    temp_path = GGUF_PATH.with_suffix(GGUF_PATH.suffix + ".part")
    downloaded = 0
    headers = {}
    if temp_path.exists():
        downloaded = temp_path.stat().st_size
        if downloaded > 0:
            headers["Range"] = f"bytes={downloaded}-"
            print(f"  检测到历史下载: {downloaded / 1024**2:.1f} MB，继续断点续传...")

    with requests.get(url, stream=True, headers=headers, timeout=60) as r:
        if r.status_code == 416:
            pass
        else:
            r.raise_for_status()
            total = int(r.headers.get("content-length", 0)) + downloaded
            
            mode = "ab" if downloaded > 0 else "wb"
            with open(temp_path, mode) as f:
                last_time = time.time()
                last_bytes = downloaded
                for chunk in r.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        f.write(chunk)
                        f.flush()
                        downloaded += len(chunk)
                        now = time.time()
                        if now - last_time >= 3:
                            speed = (downloaded - last_bytes) / (now - last_time) / 1024**2
                            mb = downloaded / 1024**2
                            total_mb = total / 1024**2 if total > 0 else 0
                            pct = f"{(downloaded / total) * 100:.1f}%" if total > 0 else "??%"
                            print(f"  进度: {pct} ({mb:.1f} / {total_mb:.1f} MB) | 速度: {speed:.2f} MB/s", flush=True)
                            last_time = now
                            last_bytes = downloaded

    if temp_path.exists():
        if GGUF_PATH.exists():
            GGUF_PATH.unlink()
        temp_path.rename(GGUF_PATH)
    print(f"[下载完成] Sakura-14B 模型已就绪 -> {GGUF_PATH}", flush=True)

def register_model():
    print("\n[注册模型] 在 Ollama 中构建 sakura-14b ...")
    content = (
        f"FROM {GGUF_PATH.as_posix()}\n\n"
        "PARAMETER temperature 0.1\n"
        "PARAMETER top_p 0.3\n"
        "PARAMETER num_ctx 2048\n\n"
        "SYSTEM \"你是一个轻小说翻译模型，可以流畅通顺地以日本轻小说的风格将日文翻译成简体中文，并联系上下文正确使用人称代词，不擅自添加原文中没有的代词。\"\n"
    )
    with open(MODELFILE_PATH, "w", encoding="utf-8") as f:
        f.write(content)

    env = os.environ.copy()
    env["OLLAMA_MODELS"] = str(MODELS_DIR)

    ollama_exe = OLLAMA_DIR / "ollama.exe"
    # 确保后台有 serve 在运行
    proc = None
    try:
        requests.get("http://127.0.0.1:11434/api/tags", timeout=2)
    except Exception:
        proc = subprocess.Popen([str(ollama_exe), "serve"], env=env)
        time.sleep(3)

    try:
        r = subprocess.run([str(ollama_exe), "create", MODEL_NAME, "-f", str(MODELFILE_PATH)], env=env, capture_output=True, text=True)
        print(r.stdout)
        if r.returncode == 0:
            print(f"✓ 成功注册旗舰模型: {MODEL_NAME}")
        else:
            print("注册输出:", r.stderr)
    finally:
        if proc:
            proc.terminate()

if __name__ == "__main__":
    download_sakura14b()
    register_model()
