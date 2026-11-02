import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import time
import json
import http.client
import requests
import pipeline_ocr

# Patch http.client.HTTPConnection.connect to track every actual TCP connection
original_connect = http.client.HTTPConnection.connect
connect_events = []

def patched_connect(self):
    t0 = time.time()
    try:
        res = original_connect(self)
        dt = (time.time() - t0) * 1000
        connect_events.append({
            "host": self.host,
            "port": self.port,
            "duration_ms": round(dt, 2),
            "timestamp": time.time()
        })
        return res
    except Exception as e:
        dt = (time.time() - t0) * 1000
        connect_events.append({
            "host": self.host,
            "port": self.port,
            "duration_ms": round(dt, 2),
            "error": str(e),
            "timestamp": time.time()
        })
        raise

http.client.HTTPConnection.connect = patched_connect

def test_38_sentences(url: str, mode_name: str):
    global connect_events
    connect_events.clear()

    with open("ocr_output/test_3min/japanese.json", "r", encoding="utf-8") as f:
        segs = json.load(f)

    session = requests.Session()
    # Test first 10 sentences to measure connect count and timing accurately
    test_segs = segs[:10]
    total = len(test_segs)
    print(f"\n--- Testing {mode_name} with {url} ({total} sentences) ---")
    
    t_start = time.time()
    timings = []
    
    for idx, s in enumerate(test_segs):
        t0 = time.time()
        payload = {
            "model": "sakura-14b:latest",
            "messages": [
                {"role": "system", "content": "你是一个轻小说翻译模型。"},
                {"role": "user", "content": f"将下面的日文文本翻译成中文：{s['text']}"}
            ],
            "stream": False,
            "options": {"num_predict": 128}
        }
        resp = session.post(url, json=payload, timeout=60)
        dt = time.time() - t0
        timings.append(dt)
        print(f"  Sentence #{idx+1}: {dt:.3f}s (Total TCP connects so far: {len(connect_events)})")

    t_total = time.time() - t_start
    print(f"\nResult for {mode_name}:")
    print(f"  Total wall time: {t_total:.2f}s")
    print(f"  Average per sentence: {t_total/total:.3f}s")
    print(f"  Actual TCP connect calls: {len(connect_events)}")
    for i, ev in enumerate(connect_events, 1):
        print(f"    Connect #{i}: host={ev['host']}, port={ev['port']}, duration={ev['duration_ms']}ms")

if __name__ == "__main__":
    # Test 1: Using http://localhost:11434 with Session
    test_38_sentences("http://localhost:11434/v1/chat/completions", "Session + localhost")
    # Test 2: Using http://127.0.0.1:11434 with Session
    test_38_sentences("http://127.0.0.1:11434/v1/chat/completions", "Session + 127.0.0.1")
