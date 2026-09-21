import paramiko
import os
import json
import base64

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("192.168.29.21", port=8022, username="u0_a208", password=os.environ.get("BG6_SSH_PASSWORD", "anmol2005"))

py_code = """
import sqlite3, json, time
conn = sqlite3.connect('/data/data/com.termux/files/home/server/storage_vault/nexus_unified.db')
conn.row_factory = sqlite3.Row
rows = [dict(r) for r in conn.execute('SELECT id, name, job_type, interval_seconds, enabled, last_run, next_run, last_status FROM scheduled_jobs').fetchall()]
now = time.time()
for r in rows:
    r['due_in_seconds'] = round(r['next_run'] - now, 1) if r['next_run'] else None
print(json.dumps(rows, indent=2))
"""
b64 = base64.b64encode(py_code.encode('utf-8')).decode('ascii')
cmd = f"python -c \"import base64; exec(base64.b64decode('{b64}').decode('utf-8'))\""

stdin, stdout, stderr = ssh.exec_command(cmd)
out = stdout.read().decode()
err = stderr.read().decode()
print("STDOUT:\n", out)
if err:
    print("STDERR:\n", err)

ssh.close()
