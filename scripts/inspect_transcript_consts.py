with open("scripts/chunks/199.a399ea9c530b6c43.js", "r", encoding="utf-8") as f:
    text = f.read()

import re

for match in re.finditer(r'selectors:\s*\[\["app-transcript"\]\]', text):
    idx = match.start()
    print("Found app-transcript at:", idx)
    c_idx = text.find("consts:", idx)
    print("Consts for app-transcript at:", c_idx)
    print(text[c_idx:c_idx+2500])
