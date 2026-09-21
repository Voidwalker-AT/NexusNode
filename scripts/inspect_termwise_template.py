with open("scripts/chunks/630.71c4a8a843deaa55.js", "r", encoding="utf-8") as f:
    text = f.read()

idx = text.find("TermWiseSummary")
print("=== TEMPLATE AROUND TermWiseSummary ===")
print(text[max(0, idx-1000):min(len(text), idx+2000)])
