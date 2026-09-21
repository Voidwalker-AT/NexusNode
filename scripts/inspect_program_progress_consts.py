with open("scripts/chunks/630.71c4a8a843deaa55.js", "r", encoding="utf-8") as f:
    text = f.read()

import re

for match in re.finditer(r'selectors:\s*\[\["app-student-program-progress"\]\]', text):
    idx = match.start()
    print("Found app-student-program-progress at:", idx)
    # Search forward for consts:
    c_idx = text.find("consts:", idx)
    print("Consts for program-progress at:", c_idx)
    print(text[c_idx:c_idx+3500])
