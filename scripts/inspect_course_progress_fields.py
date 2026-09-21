with open("scripts/chunks/630.71c4a8a843deaa55.js", "r", encoding="utf-8") as f:
    text = f.read()

import re

for term in ["TermWiseCourseProgress", "TermWiseAllCourseDetails", "CourseProgressSummery", "TaggedSemesters"]:
    matches = [m.start() for m in re.finditer(re.escape(term), text)]
    print(f"\n==================================================")
    print(f"KEYWORD: '{term}' in Chunk 630 (Found {len(matches)} occurrences)")
    print(f"==================================================")
    for idx in matches:
        print("--- Match ---")
        print(text[max(0, idx-150):min(len(text), idx+300)].replace('\n', ' '))
