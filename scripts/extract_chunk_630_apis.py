with open("scripts/chunks/630.71c4a8a843deaa55.js", "r", encoding="utf-8") as f:
    chunk_630 = f.read()

import re

# Look for URL strings or service calls
urls = re.findall(r'[\'"`](/[a-zA-Z0-9_/-]+)[\'"`]', chunk_630)
print(f"Discovered {len(urls)} URLs/paths in Chunk 630:")
for u in sorted(set(urls)):
    print(" *", u)

# Also look for method definitions: fetchProgram...
methods = re.findall(r'(fetch[a-zA-Z0-9_]+)\s*\([^)]*\)\s*\{', chunk_630)
print(f"\nDiscovered methods: {set(methods)}")

for m in set(methods):
    idx = chunk_630.find(m)
    print(f"\n--- Method {m} ---")
    print(chunk_630[idx:idx+500])
