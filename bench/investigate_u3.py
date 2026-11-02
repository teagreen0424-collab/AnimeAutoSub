import os
import sys
import time
import socket
import urllib.request
import requests
import json

def check_proxies():
    print("=== 1. Proxy Environment Variables ===")
    proxy_keys = [
        "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
        "http_proxy", "https_proxy", "all_proxy", "no_proxy"
    ]
    found = False
    for k in proxy_keys:
        v = os.environ.get(k)
        if v:
            print(f"  {k} = {v}")
            found = True
    if not found:
        print("  No proxy environment variables set.")

    print("\n=== 2. urllib.request.getproxies() ===")
    sys_proxies = urllib.request.getproxies()
    print(f"  System proxies: {sys_proxies}")

def test_raw_socket():
    print("\n=== 3. Low-level TCP Connect Timing ===")
    for host in ["localhost", "127.0.0.1"]:
        # Resolve timing
        t0 = time.time()
        try:
            addr_info = socket.getaddrinfo(host, 11434, socket.AF_UNSPEC, socket.SOCK_STREAM)
            t_resolve = (time.time() - t0) * 1000
            print(f"  {host} resolve: {t_resolve:.2f}ms -> {addr_info[0][4]}")
        except Exception as e:
            print(f"  {host} resolve failed: {e}")
            continue

        # Connect timing for each resolved address
        for res in addr_info[:2]:
            family, socktype, proto, canonname, sockaddr = res
            t0 = time.time()
            s = socket.socket(family, socktype, proto)
            s.settimeout(3.0)
            try:
                s.connect(sockaddr)
                t_conn = (time.time() - t0) * 1000
                print(f"    Connect to {sockaddr}: {t_conn:.2f}ms")
            except Exception as e:
                t_conn = (time.time() - t0) * 1000
                print(f"    Connect to {sockaddr} FAILED in {t_conn:.2f}ms: {e}")
            finally:
                s.close()

def test_ollama_caching_and_detailed_timings():
    print("\n=== 4. Ollama Request & Token Caching Audit ===")
    url = "http://localhost:11434/api/chat"
    system_prompt = "你是一个轻小说翻译家。请将日文翻译为中文。"
    
    # Request 1
    req1 = {
        "model": "sakura-14b:latest",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": "将下面的日文文本翻译成中文：おはようございます。"}
        ],
        "stream": False,
        "options": {"num_predict": 128}
    }
    # Request 2 (only changing the last line)
    req2 = {
        "model": "sakura-14b:latest",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": "将下面的日文文本翻译成中文：こんにちは。"}
        ],
        "stream": False,
        "options": {"num_predict": 128}
    }

    session = requests.Session()

    print("\n--- Testing with Reused Session ---")
    for idx, payload in enumerate([req1, req2, req2], 1):
        t0 = time.time()
        resp = session.post(url, json=payload)
        t_total = time.time() - t0
        data = resp.json()
        print(f"  Session Req {idx}: total={t_total:.3f}s")
        print(f"    prompt_eval_count: {data.get('prompt_eval_count')}")
        print(f"    prompt_eval_duration: {data.get('prompt_eval_duration', 0) / 1e9:.3f}s")
        print(f"    eval_count: {data.get('eval_count')}")
        print(f"    eval_duration: {data.get('eval_duration', 0) / 1e9:.3f}s")
        print(f"    total_duration (server-side): {data.get('total_duration', 0) / 1e9:.3f}s")
        print(f"    load_duration: {data.get('load_duration', 0) / 1e9:.3f}s")
        print(f"    response text: {data.get('message', {}).get('content', '').strip()}")

    print("\n--- Testing with Fresh requests.post (No Session) ---")
    for idx, payload in enumerate([req1, req2], 1):
        t0 = time.time()
        resp = requests.post(url, json=payload)
        t_total = time.time() - t0
        data = resp.json()
        print(f"  Fresh Req {idx}: total={t_total:.3f}s")
        print(f"    prompt_eval_count: {data.get('prompt_eval_count')}")
        print(f"    prompt_eval_duration: {data.get('prompt_eval_duration', 0) / 1e9:.3f}s")
        print(f"    eval_count: {data.get('eval_count')}")
        print(f"    eval_duration: {data.get('eval_duration', 0) / 1e9:.3f}s")
        print(f"    total_duration (server-side): {data.get('total_duration', 0) / 1e9:.3f}s")

if __name__ == "__main__":
    check_proxies()
    test_raw_socket()
    test_ollama_caching_and_detailed_timings()
