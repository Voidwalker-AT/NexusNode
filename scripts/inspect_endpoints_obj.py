with open("scripts/main_bundle.js", "r", encoding="utf-8") as f:
    content = f.read()

# Inspect around offset 3328
start = max(0, 3328 - 1500)
end = min(len(content), 3328 + 2500)
snippet = content[start:end]
print("=== CONFIGURATION / ENDPOINT OBJECT SNIPPET ===")
print(snippet)
