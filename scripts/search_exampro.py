with open("scripts/main_bundle.js", "r", encoding="utf-8") as f:
    content = f.read()

import re

keywords = ["exam-pro", "examprointegrations", "DownloadTranscript", "isTranscript", "dimensionId", "transcript"]

for kw in keywords:
    matches = [m.start() for m in re.finditer(re.escape(kw), content, re.IGNORECASE)]
    print(f"\n==================================================")
    print(f"KEYWORD: '{kw}' (Found {len(matches)} occurrences)")
    print(f"==================================================")
    for i, idx in enumerate(matches):
        start = max(0, idx - 200)
        end = min(len(content), idx + 400)
        snippet = content[start:end].replace('\n', ' ')
        print(f"\n--- Match {i+1} at index {idx} ---")
        print(snippet)
