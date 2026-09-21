import re

with open("scripts/chunks/630.71c4a8a843deaa55.js", "r", encoding="utf-8") as f:
    chunk_630 = f.read()

print("Chunk 630 length:", len(chunk_630))

keywords = ["sgpa", "cgpa", "grade", "transcript", "term", "semester", "credit"]

for kw in keywords:
    matches = [m.start() for m in re.finditer(re.escape(kw), chunk_630, re.IGNORECASE)]
    print(f"\n==================================================")
    print(f"KEYWORD: '{kw}' in Chunk 630 (Found {len(matches)} occurrences)")
    print(f"==================================================")
    for i, idx in enumerate(matches[:5]):
        start = max(0, idx - 150)
        end = min(len(chunk_630), idx + 250)
        snippet = chunk_630[start:end].replace('\n', ' ')
        print(f"\n--- Match {i+1} at index {idx} ---")
        print(snippet)
