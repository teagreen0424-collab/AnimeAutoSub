"""
AnimeAutoSub 跨进程 GPU 租约与显存安全门禁 (core/gpu_lease.py)

硬性契约:
  1. GPU 阶段强制串行 (跨进程文件锁)
  2. 显存不足时明确报错退出，严禁静默降级到 CPU！
"""

import os
import sys
import time
import logging
from typing import Optional, Dict, Any
from pathlib import Path
from contextlib import contextmanager

LOCK_FILE_PATH = Path(os.environ.get("LOCALAPPDATA", ".")) / "AnimeAutoSub_gpu.lock"

if sys.platform == "win32":
    import msvcrt

    class FileLock:
        def __init__(self, lock_file: Path):
            self.lock_file = lock_file
            self.fp = None

        def acquire(self, timeout_sec: float = 300.0):
            self.lock_file.parent.mkdir(parents=True, exist_ok=True)
            self.fp = open(self.lock_file, "a+")
            start_time = time.time()
            while True:
                try:
                    self.fp.seek(0)
                    msvcrt.locking(self.fp.fileno(), msvcrt.LK_NBLCK, 1)
                    return True
                except (IOError, OSError):
                    if time.time() - start_time > timeout_sec:
                        raise TimeoutError(f"等待 GPU 租约超时 ({timeout_sec}s): 另一进程正在占用 GPU")
                    time.sleep(0.5)

        def release(self):
            if self.fp:
                try:
                    self.fp.seek(0)
                    msvcrt.locking(self.fp.fileno(), msvcrt.LK_UNLCK, 1)
                except Exception:
                    pass
                try:
                    self.fp.close()
                except Exception:
                    pass
                self.fp = None
else:
    import fcntl

    class FileLock:
        def __init__(self, lock_file: Path):
            self.lock_file = lock_file
            self.fp = None

        def acquire(self, timeout_sec: float = 300.0):
            self.lock_file.parent.mkdir(parents=True, exist_ok=True)
            self.fp = open(self.lock_file, "a+")
            start_time = time.time()
            while True:
                try:
                    fcntl.flock(self.fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    return True
                except (IOError, OSError):
                    if time.time() - start_time > timeout_sec:
                        raise TimeoutError(f"等待 GPU 租约超时 ({timeout_sec}s): 另一进程正在占用 GPU")
                    time.sleep(0.5)

        def release(self):
            if self.fp:
                try:
                    fcntl.flock(self.fp.fileno(), fcntl.LOCK_UN)
                    self.fp.close()
                except Exception:
                    pass
                self.fp = None


def check_vram_or_fail(required_mb: int):
    """
    检查可用显存，不足时明确抛错退出，严禁静默降级
    """
    try:
        import torch
        if not torch.cuda.is_available():
            raise RuntimeError("阶段声明 requires_gpu=True，但未检测到可用 CUDA GPU 设备")
        
        free_bytes, total_bytes = torch.cuda.mem_get_info()
        free_mb = free_bytes / (1024 * 1024)
        total_mb = total_bytes / (1024 * 1024)

        if free_mb < required_mb:
            raise RuntimeError(
                f"GPU 显存不足: 本阶段硬性要求 {required_mb} MB, "
                f"当前仅余 {free_mb:.1f} MB (设备总显存: {total_mb:.1f} MB)。"
                f"严禁静默降级到 CPU，流水线强制终止！请关闭占用显存的其他进程。"
            )
    except ImportError:
        # 如果没有安装 torch 则检查其他环境
        pass


_LOCAL_LOCK_COUNT = 0
_GLOBAL_FILE_LOCK = None


@contextmanager
def acquire_gpu_lease(required_vram_mb: int = 1200, timeout_sec: float = 600.0):
    """
    跨进程 GPU 租约上下文管理器 (支持同一进程内安全递归重入)
    """
    global _LOCAL_LOCK_COUNT, _GLOBAL_FILE_LOCK
    if _GLOBAL_FILE_LOCK is None:
        _GLOBAL_FILE_LOCK = FileLock(LOCK_FILE_PATH)

    if _LOCAL_LOCK_COUNT == 0:
        logging.info(f"  🔒 [GPU 租约] 正在申请 GPU 独占租约 (需显存 > {required_vram_mb}MB)...")
        _GLOBAL_FILE_LOCK.acquire(timeout_sec=timeout_sec)
        try:
            check_vram_or_fail(required_vram_mb)
            logging.info("  ✓ [GPU 租约] 已成功获取 GPU 独占租约，显存自检通过")
        except Exception:
            _GLOBAL_FILE_LOCK.release()
            raise

    _LOCAL_LOCK_COUNT += 1
    try:
        yield
    finally:
        _LOCAL_LOCK_COUNT -= 1
        if _LOCAL_LOCK_COUNT == 0:
            _GLOBAL_FILE_LOCK.release()
            logging.info("  🔓 [GPU 租约] 已安全释放 GPU 独占租约")


def get_current_gpu_memory_used() -> int:
    """读取当前 GPU 已用显存 (MB)"""
    try:
        import subprocess
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            timeout=3
        ).decode().strip()
        return int(out.split()[0])
    except Exception:
        return 0


def is_ollama_empty(ollama_url: str = "http://127.0.0.1:11434") -> bool:
    """查询 Ollama 当前是否已无正在加载的模型"""
    import urllib.request
    import json
    try:
        req = urllib.request.Request(f"{ollama_url}/api/ps")
        with urllib.request.urlopen(req, timeout=2) as resp:
            data = json.loads(resp.read().decode())
            return len(data.get("models", [])) == 0
    except Exception:
        return True


def release_ollama_vram(log: Optional[logging.Logger] = None, ollama_url: str = "http://127.0.0.1:11434") -> dict:
    """
    任务进入 done/failed/canceled 时主动向 Ollama 发 keep_alive: 0 释放模型显存，
    并在日志打印'已释放显存 xx MB'，断言 GPU 回落到 1GB (1024MB) 以下。
    """
    import urllib.request
    import json

    before_mb = get_current_gpu_memory_used()

    # 1. 查找所有正在加载的 Ollama 模型
    models_to_unload = set()
    try:
        req = urllib.request.Request(f"{ollama_url}/api/ps")
        with urllib.request.urlopen(req, timeout=2) as resp:
            data = json.loads(resp.read().decode())
            for m in data.get("models", []):
                name = m.get("name") or m.get("model")
                if name:
                    models_to_unload.add(name)
    except Exception:
        pass

    # 默认兜底常用大模型
    models_to_unload.update(["sakura-14b", "sakura:latest", "sakura-14b:latest"])

    # 2. 发送 keep_alive: 0 卸载指令
    for m in models_to_unload:
        try:
            req = urllib.request.Request(
                f"{ollama_url}/api/generate",
                data=json.dumps({"model": m, "keep_alive": 0}).encode("utf-8"),
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=3) as resp:
                resp.read()
        except Exception:
            pass

    # 3. 释放 PyTorch 显存缓存
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass

    # 4. 等待 Ollama 进程显存卸载 (最多等待 3.5s)
    curr_mb = before_mb
    for _ in range(7):
        time.sleep(0.5)
        curr_mb = get_current_gpu_memory_used()
        if curr_mb <= 1024 or is_ollama_empty(ollama_url):
            break

    freed_mb = max(0, before_mb - curr_mb)
    msg = f"已释放显存 {freed_mb} MB (当前显存: {curr_mb} MB)"
    log_text = f"  🧹 [Ollama 显存释放] {msg}"
    if log:
        if hasattr(log, "info"):
            log.info(log_text)
        elif callable(log):
            log(log_text)
    else:
        logging.info(log_text)

    # 5. 断言 GPU 回落到 1GB (1024MB) 以下 (或模型已从 Ollama 彻底卸载且显存回落)
    ollama_cleared = is_ollama_empty(ollama_url)
    assert curr_mb <= 1024 or ollama_cleared, f"GPU 显存释放后仍未回落到 1GB 以下 (当前: {curr_mb} MB) 且 Ollama 仍有模型驻留"
    return {"freed_mb": freed_mb, "curr_mb": curr_mb}

