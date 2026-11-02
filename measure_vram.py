import os
import time
import subprocess
import requests

def get_vram():
    r = subprocess.run(['nvidia-smi', '--query-gpu=memory.used', '--format=csv,noheader,nounits'], capture_output=True, text=True)
    return int(r.stdout.strip())

base = get_vram()
print(f"Base VRAM: {base} MB")

# Check if Ollama is running
try:
    requests.get("http://127.0.0.1:11434/api/tags", timeout=2)
except Exception:
    print("Starting Ollama serve in background...")
    subprocess.Popen([r"D:\Dev\ollama\ollama.exe", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(3)

print("Invoking Sakura-14B inference...")
t0 = time.time()
r = requests.post("http://127.0.0.1:11434/api/generate", json={"model": "sakura-14b", "prompt": "こんにちは、世界！", "stream": False}, timeout=120)
t1 = time.time()
print(f"Inference complete in {t1-t0:.2f}s, status: {r.status_code}")

after_load = get_vram()
delta = after_load - base
print(f"Total VRAM used: {after_load} MB (Delta: {delta} MB)")

ps = subprocess.run([r"D:\Dev\ollama\ollama.exe", "ps"], capture_output=True, text=True)
print("--- ollama ps output ---")
print(ps.stdout)

# Release model from VRAM
print("Unloading model (keep_alive=0)...")
requests.post("http://127.0.0.1:11434/api/generate", json={"model": "sakura-14b", "keep_alive": 0})
time.sleep(2)
after_unload = get_vram()
print(f"VRAM after unload: {after_unload} MB (Freed: {after_load - after_unload} MB)")
