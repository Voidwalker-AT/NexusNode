with open("scripts/chunks/199.a399ea9c530b6c43.js", "r", encoding="utf-8") as f:
    c199 = f.read()

idx = 368815
start = max(0, idx - 1000)
end = min(len(c199), idx + 2500)
print("=== CHUNK 199 TRANSCRIPT COMPONENT SNIPPET ===")
print(c199[start:end])
