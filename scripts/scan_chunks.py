import requests
import re
import os

base_url = "https://myupes-beta.upes.ac.in/connectportal/"
headers = {"User-Agent": "Mozilla/5.0"}

with open("scripts/runtime_bundle.js", "r", encoding="utf-8") as f:
    runtime = f.read()

# Parse the chunk filename template
# Typically: e + "." + {70:"e3fd...", ...}[e] + ".js"
pairs = re.findall(r'(\d+):["\']([0-9a-f]+)["\']', runtime)
print(f"Found {len(pairs)} chunks.")

chunk_files = [f"{k}.{v}.js" for k, v in pairs]

os.makedirs("scripts/chunks", exist_ok=True)

findings = []

for c in chunk_files:
    path = os.path.join("scripts/chunks", c)
    if not os.path.exists(path):
        resp = requests.get(base_url + c, headers=headers, timeout=15)
        if resp.status_code == 200:
            with open(path, "w", encoding="utf-8") as f:
                f.write(resp.text)
        else:
            print(f"Failed to fetch {c}: HTTP {resp.status_code}")
            continue
    
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    
    # Check keywords
    keywords = ["transcript", "grade", "sgpa", "cgpa", "exam", "result", "mark", "backlog", "back-log"]
    matched_kws = [kw for kw in keywords if re.search(r'\b' + re.escape(kw), content, re.IGNORECASE)]
    if matched_kws:
        print(f"Chunk {c} ({len(content)} bytes) matched keywords: {matched_kws}")
        findings.append((c, matched_kws, content))

print(f"\nTotal matching chunks: {len(findings)}")
