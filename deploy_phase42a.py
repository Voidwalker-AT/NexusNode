"""
Deploy Phase 4.2A Product Rebase to TECNO BG6
"""
import os
import time
import hashlib
import paramiko

HOST = "192.168.29.21"
PORT = 8022
USER = "u0_a208"
PASS = "anmol2005"
REMOTE_BASE = "/data/data/com.termux/files/home/server"
LOCAL_BASE = "E:/Workspace/Active/server"

FILES_TO_UPLOAD = [
    "app.py",
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
    "tests/test_ui_rebase_contract.py",
    "tests/test_phase42a_endpoints.py"
]

def sha256_file(filepath):
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()

def main():
    print(f"[1/6] Connecting to BG6 at {HOST}:{PORT}...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, port=PORT, username=USER, password=PASS, timeout=10)
    sftp = ssh.open_sftp()
    print("      Connected successfully.")

    # 1. Clean pre-deployment backup
    print("[2/6] Creating pre-deployment backup...")
    backup_cmd = (
        "mkdir -p /data/data/com.termux/files/home/backups/phase4_migration && "
        "TS=$(date +%Y%m%d_%H%M%S) && "
        "BACKUP_FILE=/data/data/com.termux/files/home/backups/phase4_migration/nexusnode_phase42a_pre_deploy_${TS}.tar.gz && "
        "tar -czf ${BACKUP_FILE} -C /data/data/com.termux/files/home/server app.py index.html static && "
        "ls -lh ${BACKUP_FILE}"
    )
    stdin, stdout, stderr = ssh.exec_command(backup_cmd)
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    print(f"      Backup created: {out}")
    if err:
        print(f"      Notice: {err}")

    # 2. Upload files via SFTP
    print("[3/6] Uploading Phase 4.2A files via SFTP...")
    # Ensure remote dirs exist
    for rel_path in ["static/css", "static/js", "tests"]:
        remote_dir = f"{REMOTE_BASE}/{rel_path}"
        try:
            sftp.stat(remote_dir)
        except IOError:
            sftp.mkdir(remote_dir)

    local_hashes = {}
    for rel_path in FILES_TO_UPLOAD:
        local_path = os.path.join(LOCAL_BASE, rel_path).replace("\\", "/")
        remote_path = f"{REMOTE_BASE}/{rel_path}"
        local_hash = sha256_file(local_path)
        local_hashes[rel_path] = local_hash
        print(f"      Uploading {rel_path} ({os.path.getsize(local_path)} bytes)...")
        sftp.put(local_path, remote_path)

    # 3. Verify SHA-256 hashes
    print("[4/6] Verifying remote SHA-256 checksums...")
    hash_cmd = "sha256sum " + " ".join([f"{REMOTE_BASE}/{f}" for f in FILES_TO_UPLOAD])
    stdin, stdout, stderr = ssh.exec_command(hash_cmd)
    remote_out = stdout.read().decode().strip().split("\n")
    all_matched = True
    for line in remote_out:
        if not line.strip():
            continue
        parts = line.strip().split()
        r_hash = parts[0]
        r_file = parts[1].replace(REMOTE_BASE + "/", "")
        l_hash = local_hashes.get(r_file)
        if r_hash == l_hash:
            print(f"      MATCH: {r_file} ({r_hash[:12]}...)")
        else:
            print(f"      MISMATCH! {r_file}: local={l_hash} remote={r_hash}")
            all_matched = False

    if not all_matched:
        raise RuntimeError("SHA-256 checksum verification failed!")

    # 4. Run tests on BG6
    print("[5/6] Executing contract and endpoint tests on BG6...")
    test_cmd = (
        "cd /data/data/com.termux/files/home/server && "
        "python -m pytest tests/test_ui_rebase_contract.py tests/test_phase42a_endpoints.py -v"
    )
    stdin, stdout, stderr = ssh.exec_command(test_cmd)
    test_stdout = stdout.read().decode()
    test_stderr = stderr.read().decode()
    print(test_stdout)
    if "failed" in test_stdout.lower() and not "0 failed" in test_stdout.lower():
        raise RuntimeError("Remote test suite failed on BG6!")

    # 5. Restart server on BG6
    print("[6/6] Restarting NexusNode Waitress service on BG6...")
    restart_cmd = (
        "pkill -f 'python app.py' || true; "
        "sleep 2; "
        "cd /data/data/com.termux/files/home/server && "
        "nohup python app.py > server.log 2>&1 & "
        "sleep 3; "
        "ps aux | grep 'python app.py' | grep -v grep"
    )
    stdin, stdout, stderr = ssh.exec_command(restart_cmd)
    print("      Active process:")
    print(stdout.read().decode().strip())

    sftp.close()
    ssh.close()
    print("\nDeployment completed successfully!")

if __name__ == "__main__":
    main()
