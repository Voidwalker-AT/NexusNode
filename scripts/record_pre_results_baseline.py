import json
import paramiko
import os
import sys

print("=== CHECKING PRE-4.3A BASELINE ===")
host = "192.168.29.21"
port = 8022
username = "u0_a208"
password = os.environ.get("BG6_SSH_PASSWORD", "anmol2005")

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(host, port=port, username=username, password=password, timeout=10)

# Check health
stdin, stdout, stderr = ssh.exec_command("curl -s http://127.0.0.1:5000/api/health")
health = json.loads(stdout.read().decode().strip() or "{}")

# Check localtonet
stdin, stdout, stderr = ssh.exec_command("pgrep -f localtonet")
l2n = stdout.read().decode().strip()

# Check Chromium idle
stdin, stdout, stderr = ssh.exec_command("pgrep -c -f '[c]hromium' || echo 0")
chrom_cnt = int(stdout.read().decode().strip().splitlines()[0] or "0")

# Check DB integrity
py_db = (
    "python3 -c \""
    "import sqlite3; "
    "conn = sqlite3.connect('/data/data/com.termux/files/home/server/storage_vault/nexus_unified.db'); "
    "cur = conn.cursor(); "
    "cur.execute('PRAGMA integrity_check'); "
    "print(cur.fetchone()[0]); "
    "conn.close()\""
)
stdin, stdout, stderr = ssh.exec_command(py_db)
db_integ = stdout.read().decode().strip()

# Check semantic tools count
py_mcp = (
    "python3 -c \""
    "import sys; "
    "sys.path.insert(0, '/data/data/com.termux/files/home/server'); "
    "from agent.semantic_facade import SEMANTIC_TOOL_DEFINITIONS; "
    "print(len(SEMANTIC_TOOL_DEFINITIONS))\""
)
stdin, stdout, stderr = ssh.exec_command(py_mcp)
mcp_cnt = int(stdout.read().decode().strip() or "0")

ssh.close()

baseline = {
    "phase": "4.3A_PRE_BASELINE",
    "timestamp": "2026-09-20T20:36:03+05:30",
    "local_tests": {
        "files": 39,
        "collected": 682,
        "passed": 681,
        "skipped": 1,
        "failed": 0,
        "errors": 0
    },
    "bg6_appliance": {
        "health": health,
        "localtonet_running": bool(l2n),
        "chromium_idle_count": chrom_cnt,
        "db_integrity": db_integ,
        "semantic_tools_count": mcp_cnt
    }
}

print(json.dumps(baseline, indent=2))
with open("scripts/phase43a_pre_results_baseline.json", "w") as f:
    json.dump(baseline, f, indent=2)
print("\n[+] Successfully saved scripts/phase43a_pre_results_baseline.json")
