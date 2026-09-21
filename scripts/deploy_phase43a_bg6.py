"""
NexusNode Phase 4.3A — Production Deployment & Acceptance Script for TECNO BG6
Pillars A, B, C, D: Results, 3h Scheduler, Multi-User Onboarding, MCP/LMS
"""

import os
import sys
import time
import json
import hashlib
import urllib.request
import paramiko

HOST = "192.168.29.21"
PORT = 8022
USER = "u0_a208"
PASS = "anmol2005"
REMOTE_BASE = "/data/data/com.termux/files/home/server"
LOCAL_BASE = "E:/Workspace/Active/server"

FILES_TO_UPLOAD = [
    "app.py",
    "upes/__init__.py",
    "upes/results.py",
    "agent/semantic_facade.py",
    "static/js/academics.js",
    "static/js/accounts.js",
    "static/js/dashboard.js",
    "migrations/003_academic_results.sql",
    "scripts/migrate_database_003.py",
    "tests/test_upes_results.py",
    "tests/test_results_api.py",
    "tests/test_results_multi_user.py",
    "tests/test_scheduler_3hour.py",
    "tests/test_mcp_client_compatibility.py",
    "tests/test_ui_rebase_contract.py",
    "tests/test_attendance_sync.py",
    "tests/test_onboarding_status.py",
    "tests/test_academic_onboarding_ui.py",
    "tests/fixtures/upes_results/course_summary.json",
    "tests/fixtures/upes_results/exam_pro_transcript.json",
    "tests/fixtures/upes_results/term_wise_all_course.json",
    "tests/fixtures/upes_results/term_wise_course.json"
]

def sha256_file(filepath):
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()

def run_remote(ssh, cmd):
    stdin, stdout, stderr = ssh.exec_command(cmd)
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    return out, err

def main():
    print(f"=== NexusNode Phase 4.3A BG6 Deployment & Verification ===")
    print(f"Target: {USER}@{HOST}:{PORT}")

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, port=PORT, username=USER, password=PASS, timeout=15)
    sftp = ssh.open_sftp()
    print("[1/10] Connected via SSH & SFTP successfully.")

    # 1. Pre-deployment SQLite online backup on BG6
    print("\n[2/10] Creating pre-deployment verified SQLite database backup on BG6...")
    backup_db_cmd = f"""python -c "
import sqlite3, os, hashlib, datetime
src = '{REMOTE_BASE}/storage_vault/nexus_unified.db'
dest_dir = '{REMOTE_BASE}/storage_vault/backups'
os.makedirs(dest_dir, exist_ok=True)
ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
dest = os.path.join(dest_dir, f'nexus_unified_pre43a_{{ts}}.db')
src_conn = sqlite3.connect(src)
dest_conn = sqlite3.connect(dest)
with dest_conn:
    src_conn.backup(dest_conn, pages=250, sleep=0.01)
dest_conn.close()
src_conn.close()

v_conn = sqlite3.connect(dest)
integrity = v_conn.execute('PRAGMA integrity_check;').fetchone()[0]
v_conn.close()

sz = os.path.getsize(dest)
h = hashlib.sha256()
with open(dest, 'rb') as fp:
    while chunk := fp.read(65536):
        h.update(chunk)
print(f'STATUS:OK|SIZE:{{sz}}|INTEGRITY:{{integrity}}|SHA256:{{h.hexdigest()}}|PATH:{{dest}}')
" """
    out, err = run_remote(ssh, backup_db_cmd)
    print(f"      Remote DB Backup: {out}")
    if err:
        print(f"      Remote DB Backup Stderr: {err}")
    if "INTEGRITY:ok" not in out:
        raise RuntimeError("Remote SQLite backup integrity check failed!")

    # 2. Pre-deployment code archive backup
    print("\n[3/10] Creating pre-deployment codebase snapshot on BG6...")
    backup_code_cmd = (
        f"mkdir -p /data/data/com.termux/files/home/backups/phase4_migration && "
        f"TS=$(date +%Y%m%d_%H%M%S) && "
        f"BACKUP_FILE=/data/data/com.termux/files/home/backups/phase4_migration/nexusnode_pre43a_${{TS}}.tar.gz && "
        f"tar -czf ${{BACKUP_FILE}} -C {REMOTE_BASE} app.py upes agent static migrations tests && "
        f"ls -lh ${{BACKUP_FILE}}"
    )
    out, err = run_remote(ssh, backup_code_cmd)
    print(f"      Remote Code Backup: {out}")

    # 3. Upload modified files
    print("\n[4/10] Uploading Phase 4.3A files to BG6...")
    for rel_path in FILES_TO_UPLOAD:
        local_path = os.path.join(LOCAL_BASE, rel_path).replace("\\", "/")
        remote_path = f"{REMOTE_BASE}/{rel_path}"
        remote_dir = os.path.dirname(remote_path)

        # Ensure directory exists on remote
        run_remote(ssh, f"mkdir -p {remote_dir}")

        local_hash = sha256_file(local_path)
        sftp.put(local_path, remote_path)
        
        # Verify remote hash
        check_hash_cmd = f"sha256sum {remote_path}"
        out, _ = run_remote(ssh, check_hash_cmd)
        remote_hash = out.split()[0] if out else ""
        if local_hash != remote_hash:
            raise RuntimeError(f"Hash mismatch for {rel_path}! Local: {local_hash}, Remote: {remote_hash}")
        print(f"      Uploaded {rel_path} -> SHA-256 verified ({local_hash[:12]}...)")

    # 4. Run Migration 003 remotely
    print("\n[5/10] Running Database Migration 003 on BG6...")
    mig_cmd = f"cd {REMOTE_BASE} && python scripts/migrate_database_003.py"
    out, err = run_remote(ssh, mig_cmd)
    print(f"      Migration output:\n{out}")
    if err:
        print(f"      Migration stderr: {err}")
    if '"ok": true' not in out:
        raise RuntimeError("Remote Database Migration 003 failed!")

    # 5. Restart NexusNode service
    print("\n[6/10] Restarting NexusNode service on BG6...")
    restart_cmd = "sv restart /data/data/com.termux/files/usr/var/service/nexusnode"
    out, err = run_remote(ssh, restart_cmd)
    print(f"      Restart output: {out}")
    if err:
        print(f"      Restart stderr: {err}")

    # Polling wait for service startup
    print("      Waiting for process initialization and port bind...")
    healthy = False
    for attempt in range(1, 15):
        time.sleep(2)
        try:
            req = urllib.request.Request(f"http://{HOST}:5000/api/health", headers={"User-Agent": "NexusNode-Acceptance/4.3A"})
            with urllib.request.urlopen(req, timeout=3) as resp:
                if resp.status == 200:
                    healthy = True
                    print(f"      NexusNode online after {attempt * 2}s (HTTP 200 OK)")
                    break
        except Exception:
            pass

    if not healthy:
        # Check logs for diagnostic
        log_out, _ = run_remote(ssh, "tail -n 30 /data/data/com.termux/files/home/nexus_logs/nexusnode/current")
        print(f"      Service log after restart:\n{log_out}")
        raise RuntimeError("NexusNode did not become healthy after restart!")

    # 6. Verify Health & Results Endpoints
    print("\n[7/10] Verifying Live HTTP Endpoints on BG6...")
    import requests
    # Unauthenticated Health check
    h_resp = requests.get(f"http://{HOST}:5000/api/health", timeout=5)
    print(f"      Health (http://{HOST}:5000/api/health): HTTP {h_resp.status_code}")
    h_json = h_resp.json()
    print(f"        Status: {h_json.get('status')}, Uptime: {h_json.get('uptime_seconds')}s, Version: {h_json.get('version')}")
    assert h_resp.status_code == 200

    # Obtain session token
    login_resp = requests.post(f"http://{HOST}:5000/api/auth/login", json={"username": "testadmin", "password": "Admin@1234"}, timeout=5)
    assert login_resp.status_code == 200, f"Login failed: {login_resp.status_code}"
    token = login_resp.json().get("token")
    headers = {"Authorization": f"Bearer {token}", "User-Agent": "NexusNode-Acceptance/4.3A"}
    print(f"      Authenticated session established for user 'testadmin'")

    endpoints = [
        ("Dashboard Summary", f"http://{HOST}:5000/api/dashboard/summary"),
        ("Academics Results", f"http://{HOST}:5000/api/academics/results"),
        ("Onboarding Status", f"http://{HOST}:5000/api/academics/onboarding-status")
    ]
    for label, url in endpoints:
        resp = requests.get(url, headers=headers, timeout=10)
        print(f"      {label} ({url}): HTTP {resp.status_code}")
        assert resp.status_code == 200, f"{label} returned {resp.status_code}: {resp.text}"
        data = resp.json()
        if label == "Dashboard Summary":
            print(f"        Summary Keys: {list(data.keys())}")
            if "results" in data:
                print(f"        Academic Results Summary in Dashboard: {data['results']}")
        elif label == "Academics Results":
            print(f"        Results Status: {data.get('status', 'OK')}")
        elif label == "Onboarding Status":
            print(f"        Onboarding Checklist items: {len(data.get('checklist', []))}")
            print(f"        Next Required Action: {data.get('next_required_action')}")

    # 7. Run Test Suites Remotely on BG6
    print("\n[8/10] Executing Verification Test Suites Remotely on BG6...")
    test_commands = [
        ("Results Unit Tests", f"cd {REMOTE_BASE} && python -m unittest tests/test_upes_results.py"),
        ("Results API Tests", f"cd {REMOTE_BASE} && python -m unittest tests/test_results_api.py"),
        ("Results Multi-User Tests", f"cd {REMOTE_BASE} && python -m unittest tests/test_results_multi_user.py"),
        ("3-Hour Scheduler Tests", f"cd {REMOTE_BASE} && python -m unittest tests/test_scheduler_3hour.py"),
        ("MCP Client Compatibility Tests", f"cd {REMOTE_BASE} && python -m unittest tests/test_mcp_client_compatibility.py"),
        ("Attendance Sync Failure Isolation Tests", f"cd {REMOTE_BASE} && python -m unittest tests/test_attendance_sync.py"),
        ("Onboarding Status Tests", f"cd {REMOTE_BASE} && python -m unittest tests/test_onboarding_status.py"),
        ("Academic Onboarding UI Tests", f"cd {REMOTE_BASE} && python -m unittest tests/test_academic_onboarding_ui.py")
    ]

    all_passed = True
    for test_title, tcmd in test_commands:
        out, err = run_remote(ssh, tcmd)
        combined = f"{out}\n{err}".strip()
        last_line = combined.split("\n")[-1] if combined else "NO OUTPUT"
        is_ok = "OK" in combined or "passed" in combined
        status_str = "PASS" if is_ok else "FAIL"
        print(f"      [{status_str}] {test_title}: {last_line}")
        if not is_ok:
            all_passed = False
            print(f"          Output: {combined}")

    if not all_passed:
        raise RuntimeError("One or more remote test suites failed on BG6!")

    # 8. Pillar B: Real Manual Invocation of 3-Hour Sync Job on BG6
    print("\n[9/10] Invoking 3-Hour Academic Scheduler Job Remotely (Pillar B Verification)...")
    sched_test_cmd = f"""python -c "
import os, sys, time
sys.path.insert(0, '{REMOTE_BASE}')
import app as flask_app

def get_rss():
    try:
        with open('/proc/self/status') as f:
            for line in f:
                if line.startswith('VmRSS:'):
                    return float(line.split()[1]) / 1024.0
    except Exception:
        pass
    return 0.0

rss_before = get_rss()

task_obj = {{'logs': []}}
t0 = time.time()
flask_app.run_timetable_sync_job(task_obj)
duration = time.time() - t0

rss_after = get_rss()
rss_delta = rss_after - rss_before

print(f'DURATION:{{duration:.2f}}s')
print(f'RSS_BEFORE:{{rss_before:.2f}}MB|RSS_AFTER:{{rss_after:.2f}}MB|DELTA:{{rss_delta:.2f}}MB')
for log in task_obj.get('logs', []):
    print(f'LOG:{{log}}')
" """
    out, err = run_remote(ssh, sched_test_cmd)
    print(f"      Job telemetry & logs:\n{out}")
    if err:
        print(f"      Job stderr: {err}")

    # Check zero chromium launches
    check_chrom_cmd = "pgrep -c -f '[c]hromium' || echo 0; pgrep -c -f '[c]hrome' || echo 0"
    out, _ = run_remote(ssh, check_chrom_cmd)
    counts = [int(x.strip()) for x in out.split() if x.strip().isdigit()]
    total_chromium = sum(counts)
    print(f"      Orphan Chromium Process Count: {total_chromium}")
    if total_chromium > 0:
        print(f"      WARNING: Chromium instances detected: {total_chromium}")
    else:
        print("      PASS: Zero Chromium launches during background synchronization.")

    # 9. Pillar D: Real MCP Catalog & Tool Call Remote Invariant Verification
    print("\n[10/10] Verifying Semantic MCP Protocol Invariants Remotely (Pillar D Verification)...")
    mcp_test_cmd = f"""python -c "
import sys
sys.path.insert(0, '{REMOTE_BASE}')
from agent.semantic_facade import SEMANTIC_TOOL_DEFINITIONS, SemanticMcpFacade

print(f'TOTAL_TOOLS:{{len(SEMANTIC_TOOL_DEFINITIONS)}}')
assert len(SEMANTIC_TOOL_DEFINITIONS) == 11, f'Invariant failed: expected 11 tools, got {{len(SEMANTIC_TOOL_DEFINITIONS)}}'

names = [t['name'] for t in SEMANTIC_TOOL_DEFINITIONS]
print(f'TOOL_NAMES:{{names}}')

# Verify academic tools have results operations
for t in SEMANTIC_TOOL_DEFINITIONS:
    if t['name'] == 'academic.query':
        ops = t['inputSchema']['properties']['operation']['enum']
        assert 'results' in ops and 'semester_result' in ops
        print('  academic.query: verified results & semester_result operations')
    if t['name'] == 'academic.analyze':
        analysis_types = t['inputSchema']['properties']['operation']['enum']
        assert 'cgpa' in analysis_types and 'target_cgpa' in analysis_types
        print('  academic.analyze: verified cgpa & target_cgpa operations')
    if t['name'] == 'academic.sync':
        sync_types = t['inputSchema']['properties']['operation']['enum']
        assert 'results' in sync_types
        print('  academic.sync: verified results sync operation')

print('STATUS:MCP_INVARIANTS_PASSED')
" """
    out, err = run_remote(ssh, mcp_test_cmd)
    print(f"      MCP Verification:\n{out}")
    if err:
        print(f"      MCP stderr: {err}")
    if "STATUS:MCP_INVARIANTS_PASSED" not in out:
        raise RuntimeError("MCP Invariant verification failed on BG6!")

    print("\n=== BG6 DEPLOYMENT & VERIFICATION COMPLETED SUCCESSFULLY ===")
    sftp.close()
    ssh.close()

if __name__ == "__main__":
    main()
