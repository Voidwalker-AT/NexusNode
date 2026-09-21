with open("scripts/chunks/199.a399ea9c530b6c43.js", "r", encoding="utf-8") as f:
    c199 = f.read()

import re

matches = [m.start() for m in re.finditer(r'GetStudentTerms', c199)]
for idx in matches:
    print("\n--- GetStudentTerms Context ---")
    print(c199[max(0, idx-400):min(len(c199), idx+600)])
