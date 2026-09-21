with open("scripts/main_bundle.js", "r", encoding="utf-8") as f:
    content = f.read()

import re

for term in ["HTTP_INTERCEPTORS", "intercept(", "x-applicationname", "x-appsecret", "x-studentUniqueId"]:
    matches = [m.start() for m in re.finditer(re.escape(term), content, re.IGNORECASE)]
    print(f"\nTerm '{term}': {len(matches)} occurrences")
    for idx in matches[:3]:
        print("--- Context ---")
        print(content[max(0, idx-100):min(len(content), idx+250)].replace('\n', ' '))
