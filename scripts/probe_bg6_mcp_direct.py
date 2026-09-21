import paramiko
import os

def run_probe():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect('192.168.29.21', port=8022, username='u0_a208', password=os.environ.get('BG6_SSH_PASSWORD', 'anmol2005'), timeout=10)

    probe_py = """
import requests, json

base = "http://127.0.0.1:5000"
endpoints = [
    "/mcp",
    "/api/mcp",
    "/mcp/health",
    "/api/mcp/health",
    "/.well-known/oauth-protected-resource",
    "/.well-known/oauth-protected-resource/api/mcp",
    "/.well-known/oauth-protected-resource/mcp",
    "/.well-known/oauth-authorization-server",
    "/.well-known/openid-configuration"
]

print("=== DIRECT FLASK ROUTES PROBE ON BG6 ===")
for ep in endpoints:
    r = requests.get(base + ep)
    proto = r.headers.get("MCP-Protocol-Version", "none")
    ct = r.headers.get("Content-Type", "")
    print(f"{ep:45} -> HTTP {r.status_code} | proto: {proto} | {ct[:30]}")
    if r.status_code == 200 and "json" in ct:
        data = r.json()
        if "resource" in data:
            print(f"   Resource: {data['resource']} | Auth servers: {data.get('authorization_servers')}")
        if "issuer" in data:
            print(f"   Issuer: {data['issuer']}")
        if "server_name" in data:
            print(f"   Server: {data.get('server_name')} | Status: {data.get('status')} | Version: {data.get('server_version')}")
"""

    stdin, stdout, stderr = client.exec_command('python3')
    stdin.write(probe_py)
    stdin.channel.shutdown_write()
    print(stdout.read().decode())
    err = stderr.read().decode()
    if err:
        print("STDERR:", err)
    client.close()

if __name__ == "__main__":
    run_probe()
