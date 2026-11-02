import os
import subprocess
import time
import requests
from pathlib import Path

def ensure_ollama_running() -> bool:
    try:
        r = requests.get("http://127.0.0.1:11434/api/tags", timeout=1)
        if r.status_code == 200:
            return True
    except Exception:
        pass

    ollama_exe = Path(r"D:\Dev\ollama\ollama.exe")
    if not ollama_exe.exists():
        return False

    env = os.environ.copy()
    env["OLLAMA_MODELS"] = r"D:\Dev\ollama\models"
    DETACHED = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(
        [str(ollama_exe), "serve"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=DETACHED
    )
    for _ in range(10):
        time.sleep(1)
        try:
            r = requests.get("http://127.0.0.1:11434/api/tags", timeout=1)
            if r.status_code == 200:
                return True
        except Exception:
            pass
    return False

if __name__ == "__main__":
    ok = ensure_ollama_running()
    print("Ollama running:", ok)
    if ok:
        r = requests.get("http://127.0.0.1:11434/api/tags").json()
        print("Models:", [m["name"] for m in r.get("models", [])])
