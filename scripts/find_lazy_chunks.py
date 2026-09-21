with open("scripts/main_bundle.js", "r", encoding="utf-8") as f:
    content = f.read()

import re

# Look for lazy chunk filenames or import() calls
chunks = re.findall(r'[\'"`]([0-9a-zA-Z_-]+\.[0-9a-f]{16}\.js)[\'"`]', content)
print(f"Discovered {len(chunks)} chunks in main bundle:")
for c in sorted(set(chunks)):
    print(" -", c)

# Search for transcript or grade or result in lazy routes
matches = re.findall(r'\{[^{}]*path:[^{}]*\}', content)
print(f"\nFound {len(matches)} path objects:")
for m in matches:
    if any(k in m.lower() for k in ['transcript', 'grade', 'result', 'exam', 'student']):
        print(" ->", m)

# Let's search for "Transcript" or "transcript" with case variations
t_matches = re.finditer(r'transcript', content, re.IGNORECASE)
for m in t_matches:
    idx = m.start()
    print("\nTranscript occurrence context:", content[max(0, idx-100):min(len(content), idx+100)])
