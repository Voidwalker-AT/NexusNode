"""
NexusNode Phase 4.2B - Local vs Remote BG6 Source Drift Audit
Compares SHA-256 hashes of all deployed Python, frontend, and configuration files.
Categorizes each as: MATCH, LOCAL AHEAD, BG6 AHEAD, or DIFFERENT.
"""
import os
import hashlib
import paramiko
import json

HOST = "192.168.29.21"
PORT = 8022
USER = "u0_a208"
PASS = "anmol2005"
REMOTE_BASE = "/data/data/com.termux/files/home/server"
LOCAL_BASE = "E:/Workspace/Active/server"

FILES_TO_CHECK = [
    # Core Server
    "app.py",
    "config.py",
    "attendance_sync.py",
    "timetable_sync.py",
    "resource_governor.py",
    
    # Frontend
    "index.html",
    "static/css/index.css",
    "static/js/api.js",
    "static/js/ui.js",
    "static/js/dashboard.js",
    "static/js/academics.js",
    "static/js/accounts.js",
    "static/js/vault.js",
    "static/js/mcp.js",
    "static/js/diagnostics.js",
    "static/js/settings.js",
    "static/js/app.js",
    
    # Agent & MCP
    "agent/__init__.py",
    "agent/semantic_facade.py",
    "agent/mcp_server.py",
    "agent/mcp_client.py",
    "agent/mcp_auth.py",
    "agent/oauth_provider.py",
    "agent/execution_router.py",
    "agent/policy.py",
    "agent/consequential.py",
    "agent/registry.py",
    "agent/models.py",
    "agent/errors.py",
    "agent/sanitizer.py",
    "agent/rate_limiter.py",
    "agent/status_service.py",
    "agent/vault_service.py",
    "agent/lms_service.py",
    "agent/browser_service.py",
    
    # Browser Runtime
    "browser/__init__.py",
    "browser/base.py",
    "browser/bg6_cdp.py",
    "browser/camofox.py",
    "browser/cdp_client.py",
    "browser/chromium_runtime.py",
    "browser/observation.py",
    "browser/profile_manager.py",
    "browser/pinchtab.py",
    
    # UPES Subsystem
    "upes/__init__.py",
    "upes/auth.py",
    "upes/credentials.py",
    "upes/crypto.py",
    "upes/models.py",
    "upes/router.py",
    "upes/session.py",
    "upes/tracker.py",
    "upes/validators.py",
    
    # LMS Subsystem
    "lms/__init__.py",
    "lms/base.py",
    "lms/errors.py",
    "lms/models.py",
    "lms/moodle.py"
]

def sha256_local(rel_path):
    p = os.path.join(LOCAL_BASE, rel_path)
    if not os.path.exists(p):
        return None
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()

def main():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, port=PORT, username=USER, password=PASS, timeout=10)
    
    # Query remote hashes in batches
    remote_hash_map = {}
    batch_size = 25
    for i in range(0, len(FILES_TO_CHECK), batch_size):
        batch = FILES_TO_CHECK[i:i+batch_size]
        paths = " ".join([f"{REMOTE_BASE}/{f}" for f in batch])
        stdin, stdout, stderr = ssh.exec_command(f"sha256sum {paths} 2>/dev/null")
        for line in stdout.read().decode().strip().split("\n"):
            if not line.strip(): continue
            parts = line.strip().split()
            if len(parts) >= 2:
                r_hash = parts[0]
                r_file = parts[1].replace(REMOTE_BASE + "/", "")
                remote_hash_map[r_file] = r_hash

    ssh.close()
    
    results = {"MATCH": [], "LOCAL_AHEAD": [], "BG6_AHEAD": [], "MISSING_ON_BG6": [], "MISSING_LOCAL": []}
    
    for f in FILES_TO_CHECK:
        l_hash = sha256_local(f)
        r_hash = remote_hash_map.get(f)
        
        if l_hash and r_hash:
            if l_hash == r_hash:
                results["MATCH"].append(f)
            else:
                results["LOCAL_AHEAD"].append(f)
        elif l_hash and not r_hash:
            results["MISSING_ON_BG6"].append(f)
        elif not l_hash and r_hash:
            results["MISSING_LOCAL"].append(f)
            
    print("=== LOCAL VS BG6 DRIFT SUMMARY ===")
    print(f"  MATCH: {len(results['MATCH'])} files")
    print(f"  LOCAL_AHEAD / DIFFERENT: {len(results['LOCAL_AHEAD'])} files")
    print(f"  MISSING_ON_BG6: {len(results['MISSING_ON_BG6'])} files")
    
    if results["LOCAL_AHEAD"]:
        print("\nFiles with hash differences (Local vs BG6):")
        for f in results["LOCAL_AHEAD"]:
            print(f"  - {f}")
            
    if results["MISSING_ON_BG6"]:
        print("\nFiles missing on BG6:")
        for f in results["MISSING_ON_BG6"]:
            print(f"  - {f}")

    with open("scripts/drift_results.json", "w") as out_f:
        json.dump(results, out_f, indent=2)

if __name__ == "__main__":
    main()
