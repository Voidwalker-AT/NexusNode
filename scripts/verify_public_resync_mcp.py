"""
Verify public academic.sync tool schema and semantics via public HTTPS MCP endpoint.
"""
import paramiko
import requests
import json
import base64
import secrets
import hashlib

HOST = "192.168.29.21"
PORT = 8022
USER = "u0_a208"
PASS = "anmol2005"
PUBLIC_ORIGIN = "https://k09oezeyib.localto.net"
SKIP_HDR = {"localtonet-skip-warning": "true"}

def main():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, port=PORT, username=USER, password=PASS, timeout=10)

    # 1. Mint OAuth token on BG6
    v = secrets.token_urlsafe(32)
    chal = base64.urlsafe_b64encode(hashlib.sha256(v.encode('ascii')).digest()).decode('ascii').rstrip('=')
    mint_script = (
        "cd ~/server && python3 -c \"import sqlite3, config; "
        "from agent.oauth_provider import OAuthProvider; "
        "p = OAuthProvider(lambda: sqlite3.connect(config.DB_PATH)); "
        "p.register_client('probe_client', 'probe_secret', 'Probe', ['https://localhost']); "
        f"code, _ = p.create_authorization_code('probe_client', 'admin', 'https://localhost', 'mcp', '{chal}', 'S256'); "
        "print('CODE:' + code)\""
    )
    stdin, stdout, stderr = ssh.exec_command(mint_script)
    out = stdout.read().decode()
    err = stderr.read().decode()
    print("MINT OUT:", out)
    print("MINT ERR:", err)
    code = [l for l in out.splitlines() if l.startswith("CODE:")][0].split(":", 1)[1].strip()

    # 2. Exchange code for access token via public OAuth endpoint
    basic = base64.b64encode(b"probe_client:probe_secret").decode()
    r_tok = requests.post(
        f"{PUBLIC_ORIGIN}/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": "https://localhost",
            "code_verifier": v
        },
        headers={"Authorization": f"Basic {basic}", **SKIP_HDR},
        timeout=10
    )
    access_token = r_tok.json()["access_token"]
    print(f"[OK] Acquired MCP Access Token: {access_token[:16]}...")

    # 3. Call tools/list on public MCP endpoint
    mcp_headers = {"Authorization": f"Bearer {access_token}", **SKIP_HDR}
    r_mcp = requests.post(
        f"{PUBLIC_ORIGIN}/api/mcp",
        headers=mcp_headers,
        json={"jsonrpc": "2.0", "method": "tools/list", "id": 1},
        timeout=10
    )
    tools = r_mcp.json().get("result", {}).get("tools", [])
    sync_tool = next((t for t in tools if t["name"] == "academic.sync"), None)
    print("\n=== PUBLIC academic.sync TOOL SCHEMA ===")
    print(json.dumps(sync_tool, indent=2))

    # Assertions on tool schema
    assert sync_tool is not None, "academic.sync not found in public MCP tools!"
    assert "LIVE UPES timetable refresh only" in sync_tool["description"]
    assert "reconciliation" in sync_tool["description"]

    # 4. Check active Chromium processes on BG6
    stdin, stdout, stderr = ssh.exec_command("pgrep -f -i chromium | wc -l")
    chrom_count = stdout.read().decode().strip()
    print(f"\nActive Chromium processes on BG6: {chrom_count}")

    ssh.close()
    print("\n=== Public Verification Succeeded ===")

if __name__ == "__main__":
    main()
