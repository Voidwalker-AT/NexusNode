import os
import re
import json

PATTERNS = {
    "ollama": re.compile(r"ollama", re.I),
    "11434": re.compile(r"11434"),
    "GGUF": re.compile(r"GGUF", re.I),
    "local model": re.compile(r"local model", re.I),
    "model download": re.compile(r"model download", re.I),
    "ai/start": re.compile(r"ai/start", re.I),
    "ai/stop": re.compile(r"ai/stop", re.I),
    "ai/models": re.compile(r"ai/models", re.I),
    "rag/index": re.compile(r"rag/index", re.I),
    "rag/compact": re.compile(r"rag/compact", re.I)
}

results = []

for root, dirs, files in os.walk("."):
    if any(x in root for x in [".git", ".pytest_cache", "__pycache__", "storage_vault/backups"]):
        continue
    for f in files:
        if not f.endswith((".py", ".html", ".js", ".css", ".json", ".md", ".sh", ".toml")):
            continue
        p = os.path.join(root, f)
        norm_p = p.replace("\\", "/")
        try:
            with open(p, "r", encoding="utf-8", errors="ignore") as fp:
                for line_no, line in enumerate(fp, 1):
                    for pat_name, pat in PATTERNS.items():
                        if pat.search(line):
                            # Classify
                            classification = "UNKNOWN"
                            if "/docs/" in norm_p or norm_p.startswith("./docs/"):
                                classification = "HISTORICAL DOCUMENTATION"
                            elif norm_p.startswith("./nexus/commands/"):
                                classification = "DEAD_CODE_CANDIDATE (CLI retired in Stage 3)"
                            elif norm_p.startswith("./tests/"):
                                classification = "COMPATIBILITY / TEST"
                            elif norm_p == "./app.py":
                                classification = "DEAD_CODE_CANDIDATE (Backend Route - Phase 4.2C analysis)"
                            elif norm_p == "./config.py":
                                classification = "COMPATIBILITY (Default config flags)"
                            elif norm_p == "./resource_governor.py":
                                classification = "ACTIVE / COMPATIBILITY (Safe governor threshold)"
                            
                            results.append({
                                "file": norm_p,
                                "line": line_no,
                                "pattern": pat_name,
                                "snippet": line.strip()[:100],
                                "classification": classification
                            })
        except Exception:
            pass

summary_counts = {}
for r in results:
    c = r["classification"]
    summary_counts[c] = summary_counts.get(c, 0) + 1

print(f"Total residue matches: {len(results)}")
print("Summary by classification:")
for k, v in sorted(summary_counts.items()):
    print(f"  {k}: {v}")

with open("scripts/residue_audit_results.json", "w", encoding="utf-8") as fp:
    json.dump({"total": len(results), "summary": summary_counts, "matches": results}, fp, indent=2)

print("Saved detailed results to scripts/residue_audit_results.json")
