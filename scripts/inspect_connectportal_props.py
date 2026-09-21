with open("scripts/main_bundle.js", "r", encoding="utf-8") as f:
    content = f.read()

import re

for prop in ["ProgramprogressCourseSmmary", "ProgramprogressTermwise", "TermwiseAllCourse", "ProgramprogressStreamWise"]:
    idx = content.find(prop)
    if idx != -1:
        start = max(0, idx - 100)
        end = min(len(content), idx + 200)
        print(f"\n--- {prop} at index {idx} ---")
        print(content[start:end])
