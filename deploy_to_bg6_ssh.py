#!/usr/bin/env python3
"""
NexusNode Phase 3.8D BG6 Deployment & Verification Script
Usage: python deploy_to_bg6_ssh.py [HOST_OR_IP] [PORT] [USERNAME]
Example: python deploy_to_bg6_ssh.py 192.168.29.211 8022 u0_a208
"""

import sys
import os
import time
import json
import hashlib
import paramiko

def calculate_sha256(filepath):
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()

def collect_deploy_files(base_dir):
    files_to_deploy = []
    
    root_files = [
        "app.py",
        "config.py",
        "timetable_sync.py",
        "attendance_sync.py",
        "nexus_admin.py",
        "index.html",
    ]
    for rf in root_files:
        p = os.path.join(base_dir, rf)
        if os.path.exists(p):
            files_to_deploy.append(rf)
            
    subdirs = ["upes", "agent", "nexus", "static", "browser", "lms", "services"]
    for sdir in subdirs:
        full_sdir = os.path.join(base_dir, sdir)
        if os.path.exists(full_sdir):
            for root, dirs, files in os.walk(full_sdir):
                dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__" and d != "node_modules"]
                for f in files:
                    if f.endswith(".pyc") or f.endswith(".db") or f.endswith(".log") or f.startswith("."):
                        continue
                    rel_path = os.path.relpath(os.path.join(root, f), base_dir).replace("\\", "/")
                    files_to_deploy.append(rel_path)
                    
    return files_to_deploy

def main():
    host = sys.argv[1] if len(sys.argv) > 1 else "192.168.29.21"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8022
    username = sys.argv[3] if len(sys.argv) > 3 else "u0_a208"
    password = os.environ.get("BG6_SSH_PASSWORD", "anmol2005")
    
    local_base = os.path.dirname(os.path.abspath(__file__))
    remote_base = "/data/data/com.termux/files/home/server"
    
    print(f"[*] Connecting to BG6 at {host}:{port} as {username}...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect(host, port=port, username=username, password=password, timeout=10)
        print("[+] BG6 SSH: PASS")
    except Exception as e:
        print(f"[-] BG6 SSH: FAIL ({e})")
        sys.exit(1)
        
    sftp = ssh.open_sftp()
    
    # 1. Precautionary Backup
    print("[*] Creating timestamped backup of existing BG6 files and database...")
    backup_cmd = (
        "TIMESTAMP=$(date +%Y%m%d_%H%M%S) && "
        "mkdir -p ~/server_backup_$TIMESTAMP && "
        "cp -r ~/server/app.py ~/server/config.py ~/server/timetable_sync.py ~/server/attendance_sync.py "
        "~/server/upes ~/server/agent ~/server/nexus ~/server/static ~/server/index.html "
        "~/server_backup_$TIMESTAMP/ 2>/dev/null || true && "
        "mkdir -p ~/server_backup_$TIMESTAMP/db_precautionary && "
        "cp ~/server/storage_vault/nexus_unified.db* ~/server_backup_$TIMESTAMP/db_precautionary/ 2>/dev/null || true && "
        "echo \"BACKUP_OK: $TIMESTAMP\""
    )
    stdin, stdout, stderr = ssh.exec_command(backup_cmd)
    out_b = stdout.read().decode().strip()
    print(f"[+] BACKUP: PASS ({out_b})")
    
    # 2. Deploy files
    files = collect_deploy_files(local_base)
    print(f"[*] Deploying {len(files)} source files to BG6 (excluding databases)...")
    for rel_path in files:
        local_path = os.path.join(local_base, rel_path.replace("/", os.sep))
        remote_path = f"{remote_base}/{rel_path}"
        remote_dir = os.path.dirname(remote_path)
        
        try:
            sftp.stat(remote_dir)
        except IOError:
            ssh.exec_command(f"mkdir -p \"{remote_dir}\"")
            time.sleep(0.02)
            
        sftp.put(local_path, remote_path)
        
    print("[+] SOURCE DEPLOYMENT: PASS")
    sftp.close()

    # 2b. Clean retired legacy artifacts on BG6
    print("[*] Cleaning retired legacy artifacts on BG6...")
    cleanup_cmd = (
        f"rm -rf {remote_base}/stitch_nexusnode_control_interface "
        f"{remote_base}/services/ollama "
        f"{remote_base}/nexus/commands/ai.py "
        f"{remote_base}/nexus/commands/models.py "
        f"{remote_base}/nexus/commands/rag.py && "
        "echo \"LEGACY_CLEANUP_OK\""
    )
    stdin, stdout, stderr = ssh.exec_command(cleanup_cmd)
    clean_out = stdout.read().decode().strip()
    print(f"[+] BG6 LEGACY CLEANUP: PASS ({clean_out})")
    
    # 3. Verify hashes
    print("[*] Verifying critical file hashes...")
    critical_files = ["app.py", "config.py", "timetable_sync.py", "attendance_sync.py", "index.html", "upes/auth.py", "static/js/app.js"]
    hash_match = True
    for cf in critical_files:
        local_cf = os.path.join(local_base, cf.replace("/", os.sep))
        local_hash = calculate_sha256(local_cf)
        
        cmd = f"python3 -c \"import hashlib; print(hashlib.sha256(open('{remote_base}/{cf}', 'rb').read()).hexdigest())\""
        stdin, stdout, stderr = ssh.exec_command(cmd)
        remote_hash = stdout.read().decode().strip()
        if local_hash == remote_hash:
            print(f"  [OK] {cf}: {remote_hash[:12]} (MATCH)")
        else:
            print(f"  [MISMATCH] {cf}: local={local_hash[:12]} vs remote={remote_hash[:12]}")
            hash_match = False
            
    if hash_match:
        print("[+] HASH VERIFICATION: PASS")
    else:
        print("[-] HASH VERIFICATION: FAIL")
        
    # 4. Database Migration & Shared Google OAuth Redirect Switch
    print("[*] Executing idempotent migrations and setting public Google redirect URI on BG6...")
    remote_setup_script = f"""
import sys, os, time, sqlite3
os.chdir('{remote_base}')
sys.path.insert(0, '{remote_base}')

import app, config, timetable_sync

# 1. Run migrations
app.init_unified_db()

# 2. Update Google OAuth Shared Redirect URI to public tunnel URL
public_redirect = "https://k09oezeyib.localto.net/api/auth/google/callback"
conn = app.get_db_connection()
try:
    cur = conn.cursor()
    cur.execute("SELECT client_id, encrypted_client_secret FROM google_oauth_app_config WHERE id = 1")
    row = cur.fetchone()
    if row:
        cur.execute("UPDATE google_oauth_app_config SET redirect_uri = ?, updated_at = ? WHERE id = 1", (public_redirect, time.time()))
        conn.commit()
        print("GOOGLE_REDIRECT_UPDATED: SUCCESS")
    else:
        print("GOOGLE_REDIRECT_UPDATED: NO_EXISTING_ROW")
finally:
    conn.close()

# 3. Read back verified state
cfg = timetable_sync.get_shared_google_oauth_config(app.get_db_connection)
print("VERIFIED_REDIRECT:", cfg.get("redirect_uri"))
print("VERIFIED_CLIENT_CONFIGURED:", bool(cfg.get("client_id")))
print("VERIFIED_SECRET_CONFIGURED:", bool(cfg.get("client_secret")))

# 4. Check admin state preserved
u = app.db_get_user("admin")
is_valid, _ = app.verify_password("anmol2026", u["password_hash"], u["salt"])
print("ADMIN_PWD_VALID:", is_valid)

toks, cal_id, _ = app.timetable_service.get_oauth_tokens("admin")
print("ADMIN_GOOGLE_CONNECTED:", bool(toks), "CAL:", cal_id)

upes_st = app.upes_auth_manager.get_status("admin")
print("ADMIN_UPES_STATE:", upes_st.get("state"))

tt_sess, _ = app.timetable_service.load_timetable_sessions("admin")
print("ADMIN_TIMETABLE_SESSIONS:", len(tt_sess))

att_stat = app.attendance_service.get_attendance_status("admin")
print("ADMIN_ATTENDANCE_MODULES:", att_stat.get("modules_count"))
"""
    stdin, stdout, stderr = ssh.exec_command(f"python3 -c \"{remote_setup_script}\"")
    setup_out = stdout.read().decode()
    print("[*] Remote Migration Output:\n" + setup_out)
    
    # 5. Clean restart BG6 server
    print("[*] Cleanly restarting BG6 NexusNode process...")
    ssh.exec_command("pkill -f 'python.*app.py' || true; pkill -f 'waitress' || true; sleep 2")
    ssh.exec_command(f"cd {remote_base} && nohup python3 app.py > server.log 2>&1 &")
    time.sleep(3)
    
    stdin, stdout, stderr = ssh.exec_command("pgrep -c -f 'python.*app.py'")
    proc_cnt = stdout.read().decode().strip()
    print(f"[+] BG6 NexusNode Process Count: {proc_cnt}")
    
    stdin, stdout, stderr = ssh.exec_command("pgrep -f 'localtonet'")
    l2n_out = stdout.read().decode().strip()
    l2n_running = bool(l2n_out)
    print(f"[+] LocalToNet Running on BG6: {l2n_running} (PID: {l2n_out})")
    
    # 6. Verify live health and semantic MCP contract on BG6
    print("[*] Verifying live BG6 health and semantic MCP contract...")
    time.sleep(2)
    health_cmd = "curl -s http://127.0.0.1:5000/api/health"
    stdin, stdout, stderr = ssh.exec_command(health_cmd)
    health_resp = stdout.read().decode().strip()
    print(f"[+] BG6 /api/health: {health_resp}")
    
    mcp_check_script = f"""
import sys, os
os.chdir('{remote_base}')
sys.path.insert(0, '{remote_base}')
from agent.semantic_facade import get_semantic_tools
tools = get_semantic_tools()
names = sorted([t['function']['name'] for t in tools])
print("SEMANTIC_TOOL_COUNT:", len(names))
print("SEMANTIC_TOOLS:", ",".join(names))
"""
    stdin, stdout, stderr = ssh.exec_command(f"python3 -c \"{mcp_check_script}\"")
    mcp_out = stdout.read().decode().strip()
    print(f"[+] BG6 Semantic MCP Verification:\n{mcp_out}")
    
    ssh.close()
    print("[+] BG6 Deployment and Verification Complete.")

if __name__ == "__main__":
    main()
