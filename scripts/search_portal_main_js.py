import requests
import re
import os
import json

base_url = "https://myupes-beta.upes.ac.in/connectportal/"
main_js_url = base_url + "main.24f924852ff4e0dd.js"

headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

cache_file = "scripts/main_bundle.js"
if os.path.exists(cache_file):
    print(f"Loading cached {cache_file}...")
    with open(cache_file, "r", encoding="utf-8") as f:
        js_content = f.read()
else:
    print(f"Downloading {main_js_url}...")
    resp = requests.get(main_js_url, headers=headers, timeout=30)
    print(f"Status: {resp.status_code}, Length: {len(resp.text)} bytes")
    js_content = resp.text
    with open(cache_file, "w", encoding="utf-8") as f:
        f.write(js_content)

print(f"Total JS bundle size: {len(js_content) / (1024*1024):.2f} MB")

# 1. Search for apigateway endpoints
print("\n=== 1. API GATEWAY ENDPOINTS DISCOVERY ===")
api_endpoints = set(re.findall(r'[\'"`](/apigateway/[^\'"`]+)[\'"`]', js_content))
print(f"Found {len(api_endpoints)} /apigateway endpoints:")
for ep in sorted(api_endpoints):
    if any(k in ep.lower() for k in ['result', 'grade', 'exam', 'transcript', 'mark', 'attend', 'time', 'student', 'cgpa', 'sgpa']):
        print(f"  * {ep}")

# 2. Search for routes related to results/examination/grades/transcript
print("\n=== 2. ROUTE DEFINITIONS DISCOVERY ===")
routes = set(re.findall(r'path:\s*[\'"]([^\'"]+)[\'"]', js_content))
print(f"Found {len(routes)} routes. Relevant routes:")
for r in sorted(routes):
    if any(k in r.lower() for k in ['result', 'grade', 'exam', 'transcript', 'mark', 'hall', 'card']):
        print(f"  * {r}")

# 3. Search for keyword contexts: transcript, gradecard, sgpa, cgpa
print("\n=== 3. KEYWORD CONTEXTS ===")
for kw in ['transcript', 'gradecard', 'sgpa', 'cgpa', 'examination', 'grade-card']:
    matches = [m.start() for m in re.finditer(re.escape(kw), js_content, re.IGNORECASE)]
    print(f"\nKeyword '{kw}': {len(matches)} occurrences")
    for idx in matches[:5]:
        start = max(0, idx - 100)
        end = min(len(js_content), idx + 150)
        snippet = js_content[start:end].replace('\n', ' ')
        print(f"  [{idx}]: ... {snippet} ...")
