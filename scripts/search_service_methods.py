import os
import re

files_to_check = ["scripts/main_bundle.js"] + [os.path.join("scripts/chunks", f) for f in os.listdir("scripts/chunks") if f.endswith(".js")]

for fpath in files_to_check:
    with open(fpath, "r", encoding="utf-8") as f:
        content = f.read()
    
    for term in ["GetProgramProgressSummary", "GetProgramProgressTermwise"]:
        if term in content:
            print(f"\nFound '{term}' in {fpath}!")
            # Find definition: GetProgramProgressSummary(...) { ... }
            matches = [m.start() for m in re.finditer(re.escape(term), content)]
            for idx in matches:
                start = max(0, idx - 100)
                end = min(len(content), idx + 400)
                print(f"--- Context at {idx} in {fpath} ---")
                print(content[start:end])
