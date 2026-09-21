with open("scripts/main_bundle.js", "r", encoding="utf-8") as f:
    content = f.read()

idx = content.find("x-applicationname")
print("=== INTERCEPTOR COMPLETE CODE ===")
print(content[max(0, idx-400):min(len(content), idx+1000)])
