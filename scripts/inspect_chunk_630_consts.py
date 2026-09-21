with open("scripts/chunks/630.71c4a8a843deaa55.js", "r", encoding="utf-8") as f:
    text = f.read()

# Look for consts: [...] in Chunk 630
idx = text.find("consts:")
print("=== CONSTS ARRAY IN CHUNK 630 ===")
print(text[idx:idx+2500])
