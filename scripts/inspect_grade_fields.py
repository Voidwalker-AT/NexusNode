import re

for chunk_path in ["scripts/chunks/630.71c4a8a843deaa55.js", "scripts/chunks/199.a399ea9c530b6c43.js"]:
    with open(chunk_path, "r", encoding="utf-8") as f:
        text = f.read()
    
    for term in ["GradePoints", "GradeObtained", "GradeMasterDimensionId", "CourseCredit", "SGPA", "CGPA"]:
        matches = [m.start() for m in re.finditer(re.escape(term), text)]
        print(f"\nTerm '{term}' in {chunk_path}: {len(matches)} occurrences")
        for idx in matches[:3]:
            print("  Context:", text[max(0, idx-80):min(len(text), idx+120)].replace('\n', ' '))
