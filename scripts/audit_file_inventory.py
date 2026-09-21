"""
NexusNode Phase 4.2B - Repository File Inventory & Categorization Script
Audits every file in the repository, determines its role, size, line count, status, and test coverage.
Outputs a structured JSON inventory.
"""
import os
import hashlib
import json
import re

ROOT = os.path.abspath(".")

SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", ".idea", ".vscode", "node_modules", "dist"}

def get_sha256(path):
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            while chunk := f.read(65536):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""

def count_lines(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return sum(1 for _ in f)
    except Exception:
        return 0

def classify_file(rel_path):
    norm = rel_path.replace("\\", "/")
    
    # Generated / runtime / caches
    if norm.startswith("storage_vault/") or norm.startswith("backups/") or norm.endswith(".pyc") or norm.endswith(".log") or norm.endswith(".lock") or norm.endswith(".png"):
        return "GENERATED_RUNTIME"
    if norm.startswith("dist/"):
        return "GENERATED_RUNTIME"
    
    # Tests
    if norm.startswith("tests/"):
        return "ACTIVE"
    
    # Documentation
    if norm.startswith("docs/") or norm.endswith(".md") or norm.endswith(".txt"):
        return "ACTIVE"
    
    # Frontend active (rebased in 4.2A)
    if norm == "index.html" or norm.startswith("static/"):
        return "ACTIVE"
    
    # Legacy Stitch UI
    if norm.startswith("stitch_nexusnode_control_interface/"):
        return "LEGACY"
    
    # Core active Python source
    if norm in ["app.py", "config.py", "attendance_sync.py", "timetable_sync.py", "resource_governor.py"]:
        return "ACTIVE"
    
    if norm.startswith("agent/"):
        return "ACTIVE"
    if norm.startswith("browser/"):
        if "pinchtab" in norm:
            return "LEGACY"
        return "ACTIVE"
    if norm.startswith("upes/"):
        return "ACTIVE"
    if norm.startswith("lms/"):
        return "ACTIVE"
    
    # CLI client package
    if norm.startswith("nexus/"):
        return "COMPATIBILITY"
    
    # Services / runit
    if norm.startswith("services/"):
        if "ollama" in norm:
            return "DEAD_CODE_CANDIDATE"
        return "ACTIVE"
    
    # Scripts
    if norm.startswith("scripts/"):
        return "ACTIVE"
        
    # Root configs
    if norm in [".env.example", ".gitignore", ".dockerignore", "Dockerfile", "docker-compose.yml", "pyproject.toml", "requirements.txt", "LICENSE"]:
        return "ACTIVE"

    if norm.startswith("deploy_"):
        return "ACTIVE"
        
    return "UNKNOWN"

def main():
    inventory = []
    category_counts = {
        "SOURCE_PYTHON": 0,
        "FRONTEND_WEB": 0,
        "TEST_FILES": 0,
        "DOCUMENTATION": 0,
        "CONFIGURATION": 0,
        "DEPLOYMENT_SERVICES": 0,
        "GENERATED_RUNTIME": 0,
        "LEGACY_CANDIDATES": 0,
        "TOTAL_FILES": 0
    }
    
    for root, dirs, files in os.walk(ROOT):
        # Prune skipped dirs
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for f in files:
            full_path = os.path.join(root, f)
            rel_path = os.path.relpath(full_path, ROOT).replace("\\", "/")
            status = classify_file(rel_path)
            size = os.path.getsize(full_path)
            lines = count_lines(full_path) if f.endswith((".py", ".js", ".css", ".html", ".sh", ".bat", ".ps1", ".md", ".json", ".txt", ".toml", ".yml")) else 0
            
            # Subsystem categorization
            subsystem = "other"
            if rel_path.startswith("agent/"): subsystem = "agent_mcp"
            elif rel_path.startswith("browser/"): subsystem = "browser_runtime"
            elif rel_path.startswith("upes/"): subsystem = "upes_auth_api"
            elif rel_path.startswith("lms/"): subsystem = "lms_gateway"
            elif rel_path.startswith("nexus/"): subsystem = "cli_client"
            elif rel_path.startswith("static/") or rel_path == "index.html": subsystem = "frontend_web"
            elif rel_path.startswith("tests/"): subsystem = "testing"
            elif rel_path.startswith("docs/"): subsystem = "documentation"
            elif rel_path.startswith("services/"): subsystem = "runit_supervision"
            elif rel_path.startswith("scripts/"): subsystem = "maintenance_scripts"
            elif rel_path.startswith("stitch_nexusnode_control_interface/"): subsystem = "legacy_ui_mockups"
            elif rel_path in ["app.py", "config.py", "resource_governor.py"]: subsystem = "core_server"
            elif rel_path in ["attendance_sync.py", "timetable_sync.py"]: subsystem = "academic_sync"

            item = {
                "path": rel_path,
                "status": status,
                "subsystem": subsystem,
                "size_bytes": size,
                "lines": lines,
                "sha256": get_sha256(full_path)
            }
            inventory.append(item)
            category_counts["TOTAL_FILES"] += 1
            
            # Category counters
            if rel_path.startswith("tests/"):
                category_counts["TEST_FILES"] += 1
            elif rel_path.startswith("docs/") or rel_path.endswith(".md"):
                category_counts["DOCUMENTATION"] += 1
            elif rel_path.startswith("static/") or rel_path == "index.html":
                category_counts["FRONTEND_WEB"] += 1
            elif rel_path.endswith(".py"):
                category_counts["SOURCE_PYTHON"] += 1
            elif status == "GENERATED_RUNTIME":
                category_counts["GENERATED_RUNTIME"] += 1
            elif status in ["LEGACY", "DEAD_CODE_CANDIDATE"]:
                category_counts["LEGACY_CANDIDATES"] += 1
            elif rel_path.startswith("services/") or rel_path.startswith("scripts/") or rel_path.startswith("deploy_"):
                category_counts["DEPLOYMENT_SERVICES"] += 1
            elif rel_path.endswith((".toml", ".json", ".yml", ".example", "Dockerfile")):
                category_counts["CONFIGURATION"] += 1

    with open("scripts/audit_inventory.json", "w", encoding="utf-8") as f:
        json.dump({"summary": category_counts, "files": inventory}, f, indent=2)
        
    print("=== INVENTORY AUDIT COMPLETE ===")
    for k, v in category_counts.items():
        print(f"  {k}: {v}")
    print(f"Total documented entries: {len(inventory)}")

if __name__ == "__main__":
    main()
