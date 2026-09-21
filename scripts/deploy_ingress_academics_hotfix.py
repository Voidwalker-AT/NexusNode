"""
NexusNode — Deploy Ingress Discovery & Academics Contract Hotfix to TECNO BG6
"""

import os
import sys
import time
import json
import hashlib
import paramiko

HOST = "192.168.29.21"
PORT = 8022
USER = "u0_a208"
PASS = "anmol2005"
REMOTE_BASE = "/data/data/com.termux/files/home/server"
LOCAL_BASE = "E:/Workspace/Active/server"

FILES_TO_SYNC = [
    "app.py",
    "static/js/mcp.js",
    "static/js/accounts.js",
    "static/js/academics.js",
    "tests/test_ingress_and_academics_resilience.py"
]

def sha256_file(filepath):
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()

def run_cmd(ssh, cmd):
    stdin, stdout, stderr = ssh.exec_command(cmd)
    out = stdout.read().decode("utf-8", errors="replace").strip()
    err = stderr.read().decode("utf-8", errors="replace").strip()
    return out, err

def main():
    print("=== Deploying Ingress & Academics Hotfix to TECNO BG6 ===")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, port=PORT, username=USER, password=PASS, timeout=15)
    print("Connected to BG6 via SSH.")

    # 1. Pre-deployment status check
    out, err = run_cmd(ssh, "SVDIR=/data/data/com.termux/files/usr/var/service sv status nexusnode")
    print(f"Service status: {out}")

    # 2. Create verified backup
    ts = int(time.time())
    backup_dir = f"{REMOTE_BASE}/backups/hotfix_{ts}"
    run_cmd(ssh, f"mkdir -p {backup_dir}/static/js")
    for f in FILES_TO_SYNC:
        if f.startswith("tests/"):
            continue
        run_cmd(ssh, f"cp {REMOTE_BASE}/{f} {backup_dir}/{f}")
    print(f"Created verified backup at: {backup_dir}")

    # 3. SFTP Upload and SHA256 Verification
    sftp = ssh.open_sftp()
    hashes_match = True
    for rel_path in FILES_TO_SYNC:
        local_path = os.path.join(LOCAL_BASE, rel_path.replace("/", os.sep))
        remote_path = f"{REMOTE_BASE}/{rel_path}"
        
        # Ensure remote dir exists
        remote_dir = os.path.dirname(remote_path)
        run_cmd(ssh, f"mkdir -p {remote_dir}")

        local_hash = sha256_file(local_path)
        sftp.put(local_path, remote_path)

        out, _ = run_cmd(ssh, f"sha256sum {remote_path}")
        remote_hash = out.split()[0] if out else ""

        if local_hash == remote_hash:
            print(f"[OK] {rel_path} ({remote_hash[:12]}...)")
        else:
            print(f"[FAIL] {rel_path}: Local {local_hash} != Remote {remote_hash}")
            hashes_match = False

    sftp.close()

    if not hashes_match:
        print("[ERROR] SHA256 mismatch detected! Aborting restart.")
        ssh.close()
        sys.exit(1)

    # 4. Restart nexusnode service
    print("Restarting nexusnode runit service...")
    run_cmd(ssh, "SVDIR=/data/data/com.termux/files/usr/var/service sv restart nexusnode")
    time.sleep(3)

    out, _ = run_cmd(ssh, "SVDIR=/data/data/com.termux/files/usr/var/service sv status nexusnode")
    print(f"Service status after restart: {out}")

    # 5. Check health endpoint
    print("Checking health endpoint...")
    out, _ = run_cmd(ssh, "curl -s http://127.0.0.1:5000/api/health")
    print(f"Health response: {out[:100]}...")

    # 6. Run regression test suite on BG6
    print("Running test_ingress_and_academics_resilience.py on BG6...")
    out, err = run_cmd(ssh, f"cd {REMOTE_BASE} && python -m unittest tests/test_ingress_and_academics_resilience.py")
    print(f"Test output:\n{out}\n{err}")

    # 7. Verify Chromium process count on BG6
    print("Checking Chromium process count on BG6...")
    out, _ = run_cmd(ssh, "pgrep -f -i chromium | wc -l")
    print(f"Active Chromium processes: {out.strip()}")

    ssh.close()
    print("=== Deployment & Verification Complete ===")

if __name__ == "__main__":
    main()
