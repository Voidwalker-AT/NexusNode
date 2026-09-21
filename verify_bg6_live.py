"""
Verify Live Deployment of NexusNode on TECNO BG6
"""
import requests
import json
import time
import paramiko

BASE_URL = "http://192.168.29.21:5000"
SSH_HOST = "192.168.29.21"
SSH_PORT = 8022
SSH_USER = "u0_a208"
SSH_PASS = "anmol2005"

def run_remote(cmd):
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(SSH_HOST, port=SSH_PORT, username=SSH_USER, password=SSH_PASS, timeout=10)
    stdin, stdout, stderr = ssh.exec_command(cmd)
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    ssh.close()
    return out, err

def main():
    print("==================================================")
    print("LIVE BG6 APPLIANCE VERIFICATION")
    print("==================================================")

    # 1. Check HTTP Index
    print("\n[1/7] Testing GET / (HTML shell)...")
    r = requests.get(f"{BASE_URL}/", timeout=5)
    assert r.status_code == 200, f"Expected 200, got {r.status_code}"
    html = r.text
    assert "<title>NexusNode — Academic MCP Server Appliance</title>" in html
    assert "tab-dashboard" in html
    assert "tab-academics" in html
    assert "tab-accounts" in html
    assert "tab-vault" in html
    assert "tab-mcp" in html
    assert "tab-diagnostics" in html
    assert "tab-settings" in html
    
    # Confirm obsolete features are GONE from HTML
    assert "ai-studio" not in html.lower()
    assert "ollama" not in html.lower()
    assert "tab-media" not in html.lower()
    print(f"      HTML size: {len(html)} bytes (contract validated)")

    # 2. Check Static Assets
    print("\n[2/7] Testing Static Assets...")
    static_files = [
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
    ]
    for sf in static_files:
        r = requests.get(f"{BASE_URL}/{sf}", timeout=5)
        assert r.status_code == 200, f"Asset {sf} returned {r.status_code}"
        print(f"      OK: /{sf} ({len(r.content)} bytes)")

    # 3. Check DB Users on BG6
    print("\n[3/7] Querying users from DB on BG6...")
    py_script = (
        "import sqlite3\n"
        "conn = sqlite3.connect('/data/data/com.termux/files/home/server/storage_vault/nexus_unified.db')\n"
        "rows = conn.execute('SELECT user_id, role, is_disabled FROM users').fetchall()\n"
        "print('USERS:', rows)\n"
    )
    out, err = run_remote(f"python -c \"{py_script}\"")
    print(f"      Users in DB: {out}")
    if err:
        print(f"      Remote Error: {err}")

    # 4. Authenticate
    print("\n[4/7] Testing Authentication on BG6...")
    login_res = requests.post(f"{BASE_URL}/api/auth/login", json={"username": "testadmin", "password": "Admin@1234"}, timeout=5)
    assert login_res.status_code == 200, f"Login failed: {login_res.status_code} - {login_res.text}"
    token = login_res.json().get("token")
    assert token, "No token returned from login"
    print("      Logged in successfully as 'testadmin'!")
    headers = {"Authorization": f"Bearer {token}"}

    # 5. Test First-Party REST Endpoints
    print("\n[5/7] Testing First-Party REST Endpoints on BG6...")
    
    # Dashboard summary
    t0 = time.time()
    r_dash = requests.get(f"{BASE_URL}/api/dashboard/summary", headers=headers, timeout=5)
    elapsed = (time.time() - t0) * 1000
    print(f"      GET /api/dashboard/summary: {r_dash.status_code} in {elapsed:.1f}ms")
    assert r_dash.status_code == 200
    dash_data = r_dash.json()
    print(f"        Device: {dash_data.get('appliance', {}).get('device')}")
    print(f"        State: {dash_data.get('appliance', {}).get('state')}")
    print(f"        MCP Tools: {dash_data.get('mcp', {}).get('tools_count')}")

    # MCP summary
    r_mcp = requests.get(f"{BASE_URL}/api/mcp/summary", headers=headers, timeout=5)
    print(f"      GET /api/mcp/summary: {r_mcp.status_code}")
    assert r_mcp.status_code == 200
    mcp_data = r_mcp.json()
    print(f"        Status: {mcp_data.get('status')}")
    print(f"        Catalog: {mcp_data.get('catalog_version')}")
    print(f"        Tools: {len(mcp_data.get('tools', []))}")
    assert mcp_data.get("tools_count") == 11
    assert mcp_data.get("catalog_version") == "nexus-semantic-v1"

    # Vault files list
    r_vault = requests.get(f"{BASE_URL}/files", headers=headers, timeout=5)
    print(f"      GET /files: {r_vault.status_code}")
    assert r_vault.status_code == 200
    vault_data = r_vault.json()
    print(f"        Files in Vault: {len(vault_data.get('files', []))}")

    # 6. Memory & Governor Check on BG6
    print("\n[6/7] Checking BG6 System Resources & Governor...")
    mem_out, _ = run_remote("free -m; uptime")
    print(f"      Memory status:\n{mem_out}")

    # 7. Chromium Process Check (MUST BE 0)
    print("\n[7/7] Verifying Zero Chromium Processes on BG6...")
    ps_out, _ = run_remote("ps aux | grep -i chromium | grep -v grep || true")
    if ps_out.strip():
        print(f"      WARNING: Chromium running!\n{ps_out}")
        assert False, "Chromium process should NOT be running!"
    else:
        print("      PASS: 0 Chromium processes running. Zero browser launch invariant holds!")

    print("\n==================================================")
    print("ALL LIVE BG6 APPLIANCE VERIFICATIONS PASSED!")
    print("==================================================")

if __name__ == "__main__":
    main()
