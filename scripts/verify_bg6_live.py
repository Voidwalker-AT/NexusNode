import paramiko
import os
import json
import time

host = "192.168.29.21"
port = 8022
username = "u0_a208"
password = os.environ.get("BG6_SSH_PASSWORD", "anmol2005")

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(host, port=port, username=username, password=password, timeout=10)

print("=== 1. PROCESS AND RUNTIME CHECK ===")
stdin, stdout, stderr = ssh.exec_command("pgrep -f 'python.*app.py'")
pids = stdout.read().decode().strip()
print("APP PIDS:", pids)

stdin, stdout, stderr = ssh.exec_command("pgrep -f 'localtonet'")
l2n_pids = stdout.read().decode().strip()
print("LOCALTONET PIDS:", l2n_pids)

print("\n=== 2. HTTP HEALTH CHECK ===")
stdin, stdout, stderr = ssh.exec_command("curl -s http://127.0.0.1:5000/api/health")
health_json = stdout.read().decode().strip()
print("HEALTH RESPONSE:", health_json)

print("\n=== 3. RETIRED ARTIFACTS PURGE VERIFICATION ===")
stdin, stdout, stderr = ssh.exec_command("ls -d /data/data/com.termux/files/home/server/stitch_nexusnode_control_interface /data/data/com.termux/files/home/server/services/ollama /data/data/com.termux/files/home/server/nexus/commands/ai.py 2>&1")
ls_out = stdout.read().decode().strip()
print("PURGE CHECK (Should report No such file or directory):")
print(ls_out)

print("\n=== 4. DATABASE INTEGRITY AND TABLE COUNT ===")
py_cmd = (
    "python3 -c \""
    "import sqlite3; "
    "conn = sqlite3.connect('/data/data/com.termux/files/home/server/storage_vault/nexus_unified.db'); "
    "cur = conn.cursor(); "
    "cur.execute('SELECT name FROM sqlite_master WHERE type=\\'table\\' ORDER BY name'); "
    "tbls = [r[0] for r in cur.fetchall()]; "
    "cur.execute('PRAGMA integrity_check'); "
    "integ = cur.fetchone()[0]; "
    "cur.execute('SELECT count(*) FROM users'); "
    "users_cnt = cur.fetchone()[0]; "
    "cur.execute('SELECT count(*) FROM action_approvals'); "
    "apps_cnt = cur.fetchone()[0]; "
    "cur.execute('SELECT count(*) FROM consequential_audit_log'); "
    "conseq_cnt = cur.fetchone()[0]; "
    "print(f'TOTAL_TABLES: {len(tbls)}, INTEGRITY: {integ}, USERS: {users_cnt}, APPROVALS: {apps_cnt}, CONSEQ_AUDIT: {conseq_cnt}'); "
    "print('ALL_TABLES:', tbls); "
    "conn.close()\""
)
stdin, stdout, stderr = ssh.exec_command(py_cmd)
db_res = stdout.read().decode().strip()
db_err = stderr.read().decode().strip()
print("DATABASE STATUS:", db_res)
if db_err:
    print("DATABASE ERROR:", db_err)

print("\n=== 5. SEMANTIC MCP TOOLS VERIFICATION (EXACT 11 TOOLS) ===")
py_mcp = (
    "python3 -c \""
    "import sys; "
    "sys.path.insert(0, '/data/data/com.termux/files/home/server'); "
    "from agent.semantic_facade import SEMANTIC_TOOL_DEFINITIONS; "
    "names = sorted([t['name'] for t in SEMANTIC_TOOL_DEFINITIONS]); "
    "expected = ['academic.analyze', 'academic.query', 'academic.sync', 'action.status', 'browser.interact', 'document.process', 'lms.fetch', 'lms.prepare', 'lms.query', 'nexus.status', 'vault.manage']; "
    "print('TOOL COUNT:', len(names)); "
    "print('TOOLS MATCH EXACT 11:', names == expected); "
    "print('LIVE TOOLS:', names)\""
)
stdin, stdout, stderr = ssh.exec_command(py_mcp)
mcp_res = stdout.read().decode().strip()
mcp_err = stderr.read().decode().strip()
print("MCP STATUS:", mcp_res)
if mcp_err:
    print("MCP ERROR:", mcp_err)

print("\n=== 6. LIVE ENDPOINT CONTRACT CHECK ===")
stdin, stdout, stderr = ssh.exec_command("curl -s http://127.0.0.1:5000/api/mcp/summary")
mcp_summary = stdout.read().decode().strip()
print("MCP SUMMARY ENDPOINT:", mcp_summary[:200])

ssh.close()
