import re

with open("scripts/chunks/199.a399ea9c530b6c43.js", "r", encoding="utf-8") as f:
    c199 = f.read()

idx = 368815
# Search for selector or route in Chunk 199
selectors = [m.start() for m in re.finditer(r'selectors:\s*\[\["([^"]+)"\]\]', c199)]
print(f"Selectors in Chunk 199: {len(selectors)}")
for s in selectors:
    match = re.search(r'selectors:\s*\[\["([^"]+)"\]\]', c199[s:s+100])
    if match:
        print("  - Selector:", match.group(1))

# Find the method that calls FetchTranscripts
ft_matches = [m.start() for m in re.finditer(r'FetchTranscripts', c199)]
for m in ft_matches:
    print("\n--- FetchTranscripts match context ---")
    print(c199[max(0, m-200):min(len(c199), m+600)])
