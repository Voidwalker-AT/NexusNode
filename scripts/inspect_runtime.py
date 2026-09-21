import requests
import re
import os

url = "https://myupes-beta.upes.ac.in/connectportal/runtime.c46f1b9739452165.js"
headers = {"User-Agent": "Mozilla/5.0"}
resp = requests.get(url, headers=headers)
print("Runtime status:", resp.status_code, "Length:", len(resp.text))

# Search for chunk mapping in runtime.js
# Typically: { 123: "abc", 456: "def" }[e] + "." + { ... }[e] + ".js"
chunks = re.findall(r'(\d+):["\']([0-9a-f]+)["\']', resp.text)
print("Chunk map pairs found:", len(chunks))
for c in chunks[:20]:
    print(c)

with open("scripts/runtime_bundle.js", "w", encoding="utf-8") as f:
    f.write(resp.text)
