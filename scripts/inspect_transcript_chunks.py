for c_name in ["scripts/chunks/199.a399ea9c530b6c43.js", "scripts/chunks/393.c423e064fbf6875b.js"]:
    with open(c_name, "r", encoding="utf-8") as f:
        c_text = f.read()
    
    for kw in ["exam-pro", "DownloadTranscript", "isTranscript", "examprointegrations"]:
        idx = c_text.find(kw)
        if idx != -1:
            print(f"\nFound {kw} in {c_name} at index {idx}!")
            print(c_text[max(0, idx-150):min(len(c_text), idx+300)])
