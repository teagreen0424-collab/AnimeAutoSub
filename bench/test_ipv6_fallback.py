import requests
import time

url_localhost = "http://localhost:11434/api/tags"
url_ip = "http://127.0.0.1:11434/api/tags"

print("--- Testing fresh requests.get to localhost vs 127.0.0.1 ---")
for i in range(3):
    t0 = time.time()
    requests.get(url_localhost)
    print(f"  Fresh GET localhost #{i+1}: {(time.time() - t0)*1000:.1f}ms")

for i in range(3):
    t0 = time.time()
    requests.get(url_ip)
    print(f"  Fresh GET 127.0.0.1 #{i+1}: {(time.time() - t0)*1000:.1f}ms")
