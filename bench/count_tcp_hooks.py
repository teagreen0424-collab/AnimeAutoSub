import urllib3.connection
import requests
import time

connect_count = 0

orig_connect = urllib3.connection.HTTPConnection.connect

def counting_connect(self):
    global connect_count
    connect_count += 1
    t0 = time.time()
    res = orig_connect(self)
    dt = (time.time() - t0) * 1000
    print(f"  [TCP CONNECT #{connect_count}] to {self.host}:{self.port} took {dt:.1f}ms")
    return res

urllib3.connection.HTTPConnection.connect = counting_connect

print("=== 1. Testing Session with http://127.0.0.1:11434 ===")
connect_count = 0
s = requests.Session()
for i in range(5):
    s.get("http://127.0.0.1:11434/api/tags")
print(f"Total connects in 5 requests: {connect_count}")

print("\n=== 2. Testing Session with http://localhost:11434 ===")
connect_count = 0
s = requests.Session()
for i in range(5):
    s.get("http://localhost:11434/api/tags")
print(f"Total connects in 5 requests: {connect_count}")

print("\n=== 3. Testing Fresh requests (No Session) with http://localhost:11434 ===")
connect_count = 0
for i in range(3):
    requests.get("http://localhost:11434/api/tags")
print(f"Total connects in 3 requests: {connect_count}")
