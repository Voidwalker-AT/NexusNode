import os
import sys
import sqlite3
import hashlib
import datetime
import paramiko
import zipfile

def hash_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fp:
        while chunk := fp.read(65536):
            h.update(chunk)
    return h.hexdigest()

def backup_local_db():
    src = "storage_vault/nexus_unified.db"
    dest_dir = "storage_vault/backups"
    os.makedirs(dest_dir, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = os.path.join(dest_dir, f"nexus_unified_pre42c_{ts}.db")
    
    print(f"Backing up local database to {dest}...")
    src_conn = sqlite3.connect(src)
    dest_conn = sqlite3.connect(dest)
    with dest_conn:
        src_conn.backup(dest_conn, pages=250, sleep=0.01)
    dest_conn.close()
    src_conn.close()
    
    # Verify backup integrity
    v_conn = sqlite3.connect(dest)
    res = v_conn.execute("PRAGMA integrity_check;").fetchone()
    v_conn.close()
    
    sz = os.path.getsize(dest)
    sha = hash_file(dest)
    print(f"Local backup complete: size={sz} bytes, integrity={res[0]}, sha256={sha}")
    return {"path": dest, "size_bytes": sz, "integrity": res[0], "sha256": sha}

def backup_bg6_db():
    print("Connecting to remote BG6 to trigger safe online backup...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect('192.168.29.21', port=8022, username='u0_a208', password='anmol2005')
    
    backup_cmd = """python -c "
import sqlite3, os, hashlib
src = '/data/data/com.termux/files/home/server/storage_vault/nexus_unified.db'
dest_dir = '/data/data/com.termux/files/home/server/storage_vault/backups'
os.makedirs(dest_dir, exist_ok=True)
dest = os.path.join(dest_dir, 'nexus_unified_pre42c_remote.db')
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
print(f'STATUS:OK|SIZE:{sz}|INTEGRITY:{integrity}|SHA256:{h.hexdigest()}|PATH:{dest}')
" """
    stdin, stdout, stderr = ssh.exec_command(backup_cmd)
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    ssh.close()
    print("Remote BG6 backup output:", out)
    if err:
        print("Remote BG6 backup stderr:", err)
    return out

def backup_source_tree():
    dest_dir = "storage_vault/backups"
    os.makedirs(dest_dir, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_path = os.path.join(dest_dir, f"source_tree_pre42c_{ts}.zip")
    print(f"Creating pre-cleanup source snapshot: {zip_path}...")
    
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk("."):
            if any(x in root for x in [".git", ".pytest_cache", "__pycache__", "storage_vault/backups"]):
                continue
            for f in files:
                p = os.path.join(root, f)
                zf.write(p, p)
                
    sz = os.path.getsize(zip_path)
    sha = hash_file(zip_path)
    print(f"Source snapshot created: size={sz} bytes, sha256={sha}")
    return {"path": zip_path, "size_bytes": sz, "sha256": sha}

if __name__ == "__main__":
    local_db_info = backup_local_db()
    remote_db_info = backup_bg6_db()
    source_snap_info = backup_source_tree()
