"""
NexusNode Phase 4.2B - Non-Destructive Database Fingerprint
Captures safe row counts from local and remote BG6 databases.
No secret values or personal data are read or output.
"""
import sqlite3
import os
import paramiko

LOCAL_DB = "storage_vault/nexus_unified.db"
REMOTE_HOST = "192.168.29.21"
REMOTE_PORT = 8022
REMOTE_USER = "u0_a208"
REMOTE_PASS = "anmol2005"
REMOTE_DB = "/data/data/com.termux/files/home/server/storage_vault/nexus_unified.db"

def get_db_counts(db_path):
    if not os.path.exists(db_path):
        return {"ERROR": f"Database file not found at {db_path}"}
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    counts = {}
    for t in sorted(tables):
        if t.startswith("sqlite_"):
            continue
        try:
            cnt = c.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0]
            counts[t] = cnt
        except Exception as e:
            counts[t] = f"ERR: {e}"
    conn.close()
    return counts

def get_remote_db_counts():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect(REMOTE_HOST, port=REMOTE_PORT, username=REMOTE_USER, password=REMOTE_PASS, timeout=10)
    except Exception as e:
        return {"ERROR": f"Failed to connect to BG6: {e}"}
    
    script = f"""
import sqlite3, os, json
db_path = '{REMOTE_DB}'
if not os.path.exists(db_path):
    print(json.dumps({{'ERROR': 'DB not found'}}))
    exit()
conn = sqlite3.connect(db_path)
c = conn.cursor()
tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")]
counts = {{}}
for t in sorted(tables):
    if t.startswith('sqlite_'): continue
    try:
        counts[t] = c.execute(f'SELECT count(*) FROM "{{t}}"').fetchone()[0]
    except Exception as e:
        counts[t] = str(e)
conn.close()
print(json.dumps(counts))
"""
    stdin, stdout, stderr = ssh.exec_command('python -u')
    stdin.write(script)
    stdin.channel.shutdown_write()
    out = stdout.read().decode().strip()
    ssh.close()
    import json
    try:
        return json.loads(out)
    except Exception:
        return {"RAW": out}

if __name__ == "__main__":
    print("=== LOCAL DATABASE FINGERPRINT ===")
    local_counts = get_db_counts(LOCAL_DB)
    for k, v in local_counts.items():
        print(f"  {k}: {v}")

    print("\n=== REMOTE BG6 DATABASE FINGERPRINT ===")
    remote_counts = get_remote_db_counts()
    for k, v in remote_counts.items():
        print(f"  {k}: {v}")
