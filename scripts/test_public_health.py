import urllib.request
import time
import json

url = 'https://k09oezeyib.localto.net/api/health'
headers = {
    'localtonet-skip-warning': 'true',
    'User-Agent': 'NexusNode-Internet-Acceptance/1.0'
}

print("=== PUBLIC INTERNET HEALTH CHECK ===")
latencies = []
for i in range(5):
    t0 = time.time()
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            elapsed = (time.time() - t0) * 1000
            latencies.append(elapsed)
            ct = resp.headers.get('Content-Type', '')
            raw = resp.read()
            data = json.loads(raw.decode('utf-8'))
            print(f"Attempt {i+1}: HTTP {resp.status} in {elapsed:.1f}ms | Content-Type: {ct} | status: {data.get('status')} | version: {data.get('version')} | device: {data.get('device')}")
    except Exception as e:
        print(f"Attempt {i+1} FAILED: {e}")
    time.sleep(0.3)

if latencies:
    print(f"\nAverage Latency: {sum(latencies)/len(latencies):.1f}ms (Min: {min(latencies):.1f}ms, Max: {max(latencies):.1f}ms)")
