import paramiko
import requests
import json

# 1. SSH to BG6 and mint an agent token
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('192.168.29.21', port=8022, username='u0_a208', password='anmol2005', timeout=10)

cmd = """python3 -c "
import sqlite3, config, agent
from agent.mcp_auth import AgentTokenManager

conn_factory = lambda: sqlite3.connect(config.DB_PATH)
mgr = AgentTokenManager(conn_factory=conn_factory)
raw_token, meta = mgr.generate_token(
    principal='spark-agent',
    capabilities=agent.DEFAULT_SPARK_CAPABILITIES,
    description='Public Acceptance Token 4.3A-R3',
    ttl_seconds=86400
)
print('RAW_TOKEN:' + raw_token)
"
"""
stdin, stdout, stderr = ssh.exec_command(f"export PATH=/data/data/com.termux/files/usr/bin:$PATH; cd ~/server && {cmd}")
out = stdout.read().decode().strip()
err = stderr.read().decode().strip()
ssh.close()

raw_token = None
for line in out.splitlines():
    if line.startswith('RAW_TOKEN:'):
        raw_token = line.split(':', 1)[1].strip()

print("Minted Token:", raw_token[:15] + "..." if raw_token else "FAILED")
if err:
    print("ERR:", err)

if not raw_token:
    exit(1)

# 2. Test MCP initialize over Public Internet URL
public_url = "https://k09oezeyib.localto.net/api/mcp"
headers = {
    "Authorization": f"Bearer {raw_token}",
    "Content-Type": "application/json",
    "localtonet-skip-warning": "true"
}

init_payload = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2024-11-05",
        "clientInfo": {"name": "AntigravityTestClient", "version": "1.0"},
        "capabilities": {}
    }
}

r = requests.post(public_url, headers=headers, json=init_payload, timeout=10)
print("Public MCP Initialize Status:", r.status_code)
print("Public MCP Initialize Response:", r.text[:300])
