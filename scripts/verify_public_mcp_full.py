import time
import json
import base64
import hashlib
import secrets
import urllib.parse
import requests
import paramiko

BASE_PUBLIC = "https://k09oezeyib.localto.net"
HEADERS_SKIP = {"localtonet-skip-warning": "true"}

def run_public_mcp_tests():
    print("=" * 60)
    print("PHASE 4.3A-R3: SECTIONS 6, 7, 8, 9, 10 (PUBLIC MCP & OAUTH)")
    print("=" * 60)

    # -------------------------------------------------------------
    # SECTION 6: PUBLIC MCP DISCOVERY
    # -------------------------------------------------------------
    print("\n--- [Section 6] Public MCP Discovery ---")

    # 6.1 HEAD /api/mcp
    t0 = time.time()
    r_head = requests.head(f"{BASE_PUBLIC}/api/mcp", headers=HEADERS_SKIP, timeout=10)
    lat_head = round((time.time() - t0) * 1000, 1)
    www_auth = r_head.headers.get("WWW-Authenticate", "")
    proto_head = r_head.headers.get("MCP-Protocol-Version", "")
    print(f"HEAD /api/mcp: HTTP {r_head.status_code} ({lat_head}ms)")
    print(f"   WWW-Authenticate: {www_auth}")
    print(f"   MCP-Protocol-Version: {proto_head}")
    assert r_head.status_code == 401, f"Expected 401, got {r_head.status_code}"
    assert "resource_metadata=" in www_auth
    assert "192.168.29.21" not in www_auth and "localhost" not in www_auth

    # 6.2 GET /.well-known/oauth-protected-resource/api/mcp
    r_res = requests.get(f"{BASE_PUBLIC}/.well-known/oauth-protected-resource/api/mcp", headers=HEADERS_SKIP, timeout=10)
    print(f"GET /.well-known/oauth-protected-resource/api/mcp: HTTP {r_res.status_code}")
    res_data = r_res.json()
    print(f"   Resource: {res_data.get('resource')}")
    print(f"   Auth Servers: {res_data.get('authorization_servers')}")
    assert res_data.get("resource") == f"{BASE_PUBLIC}/api/mcp"
    assert res_data.get("authorization_servers") == [BASE_PUBLIC]

    # 6.3 GET /.well-known/oauth-authorization-server
    r_auth_meta = requests.get(f"{BASE_PUBLIC}/.well-known/oauth-authorization-server", headers=HEADERS_SKIP, timeout=10)
    print(f"GET /.well-known/oauth-authorization-server: HTTP {r_auth_meta.status_code}")
    auth_meta = r_auth_meta.json()
    print(f"   Issuer: {auth_meta.get('issuer')}")
    print(f"   Token Endpoint: {auth_meta.get('token_endpoint')}")
    print(f"   Auth Endpoint: {auth_meta.get('authorization_endpoint')}")
    assert auth_meta.get("issuer") == BASE_PUBLIC
    assert auth_meta.get("authorization_endpoint") == f"{BASE_PUBLIC}/oauth/authorize"
    assert auth_meta.get("token_endpoint") == f"{BASE_PUBLIC}/oauth/token"

    # 6.4 Unauthenticated POST /api/mcp
    r_unauth_post = requests.post(f"{BASE_PUBLIC}/api/mcp", headers=HEADERS_SKIP, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, timeout=10)
    print(f"Unauthenticated POST /api/mcp: HTTP {r_unauth_post.status_code}")
    assert r_unauth_post.status_code == 401

    # -------------------------------------------------------------
    # SECTION 7: PUBLIC MCP AUTHENTICATED HANDSHAKE
    # -------------------------------------------------------------
    print("\n--- [Section 7] Public MCP Authenticated Handshake ---")

    # Generate PKCE verifier and challenge
    verifier = secrets.token_urlsafe(32)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode('ascii')).digest()).decode('ascii').rstrip('=')

    # Mint OAuth code for client 'gemini-spark' on BG6
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect('192.168.29.21', port=8022, username='u0_a208', password='anmol2005', timeout=10)

    client_id = "test_pub_acceptance"
    client_secret = "secret_pub_acceptance_999"
    redirect_uri = "https://oauth-redirect.googleusercontent.com/r/test_live"

    mint_code_py = f"""python3 -c "
import sqlite3, config, time
from agent.oauth_provider import OAuthProvider

conn_factory = lambda: sqlite3.connect(config.DB_PATH)
provider = OAuthProvider(conn_factory=conn_factory)
provider.register_client(
    client_id='{client_id}',
    client_secret='{client_secret}',
    client_name='Public Acceptance Client',
    redirect_uris=['{redirect_uri}']
)
code, _ = provider.create_authorization_code(
    client_id='{client_id}',
    redirect_uri='{redirect_uri}',
    user_id='admin',
    scope='mcp',
    code_challenge='{challenge}',
    code_challenge_method='S256'
)
print('AUTH_CODE:' + code)
"
"""
    stdin, stdout, stderr = ssh.exec_command(f"export PATH=/data/data/com.termux/files/usr/bin:$PATH; cd ~/server && {mint_code_py}")
    code_out = stdout.read().decode().strip()
    ssh.close()

    auth_code = None
    for l in code_out.splitlines():
        if l.startswith("AUTH_CODE:"):
            auth_code = l.split(":", 1)[1].strip()

    assert auth_code is not None, f"Failed to mint auth code: {code_out}"
    print(f"Obtained Auth Code for user 'admin': {auth_code[:15]}...")

    # Exchange auth_code for access_token over PUBLIC INTERNET
    basic_auth = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    token_req_data = {
        "grant_type": "authorization_code",
        "code": auth_code,
        "redirect_uri": redirect_uri,
        "code_verifier": verifier
    }
    t0 = time.time()
    r_token = requests.post(
        f"{BASE_PUBLIC}/oauth/token",
        data=token_req_data,
        headers={
            "Authorization": f"Basic {basic_auth}",
            "Content-Type": "application/x-www-form-urlencoded",
            "localtonet-skip-warning": "true"
        },
        timeout=10
    )
    lat_token = round((time.time() - t0) * 1000, 1)
    print(f"POST /oauth/token: HTTP {r_token.status_code} ({lat_token}ms)")
    token_json = r_token.json()
    access_token = token_json.get("access_token")
    assert access_token is not None, f"Token exchange failed: {token_json}"
    print(f"Received OAuth Access Token: {access_token[:15]}... (expires_in: {token_json.get('expires_in')}s)")

    # 7.1 MCP initialize
    mcp_headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "localtonet-skip-warning": "true"
    }
    init_msg = {
        "jsonrpc": "2.0",
        "id": "init-1",
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "clientInfo": {"name": "PublicAcceptanceTest", "version": "1.0"},
            "capabilities": {}
        }
    }
    t0 = time.time()
    r_init = requests.post(f"{BASE_PUBLIC}/api/mcp", headers=mcp_headers, json=init_msg, timeout=10)
    lat_init = round((time.time() - t0) * 1000, 1)
    print(f"MCP initialize: HTTP {r_init.status_code} ({lat_init}ms)")
    init_res = r_init.json()
    proto_negotiated = init_res.get("result", {}).get("protocolVersion")
    server_info = init_res.get("result", {}).get("serverInfo")
    print(f"   Negotiated Protocol: {proto_negotiated}")
    print(f"   Server Info: {server_info}")
    assert r_init.status_code == 200
    assert proto_negotiated in ["2024-11-05", "2026-07-28"]

    # 7.2 notifications/initialized
    notif_msg = {
        "jsonrpc": "2.0",
        "method": "notifications/initialized",
        "params": {}
    }
    r_notif = requests.post(f"{BASE_PUBLIC}/api/mcp", headers=mcp_headers, json=notif_msg, timeout=10)
    print(f"MCP notifications/initialized: HTTP {r_notif.status_code}")
    assert r_notif.status_code in [200, 204]

    # 7.3 tools/list
    tools_msg = {"jsonrpc": "2.0", "id": "tools-1", "method": "tools/list", "params": {}}
    t0 = time.time()
    r_tools = requests.post(f"{BASE_PUBLIC}/api/mcp", headers=mcp_headers, json=tools_msg, timeout=10)
    lat_tools = round((time.time() - t0) * 1000, 1)
    print(f"MCP tools/list: HTTP {r_tools.status_code} ({lat_tools}ms)")
    tools_res = r_tools.json()
    tools = tools_res.get("result", {}).get("tools", [])
    tool_names = [t["name"] for t in tools]
    print(f"   Catalog Tools Count: {len(tool_names)}")
    print(f"   Tool Names: {tool_names}")
    assert len(tool_names) == 11, f"Expected exactly 11 tools, got {len(tool_names)}: {tool_names}"

    # -------------------------------------------------------------
    # SECTION 8: PUBLIC MCP READ-ONLY TOOL EXECUTION
    # -------------------------------------------------------------
    print("\n--- [Section 8] Public MCP Read-Only Tool Execution ---")

    def call_mcp_tool(name, args={}):
        req = {
            "jsonrpc": "2.0",
            "id": f"call-{name}-{int(time.time()*1000)}",
            "method": "tools/call",
            "params": {
                "name": name,
                "arguments": args
            }
        }
        t0 = time.time()
        res = requests.post(f"{BASE_PUBLIC}/api/mcp", headers=mcp_headers, json=req, timeout=15)
        lat = round((time.time() - t0) * 1000, 1)
        assert res.status_code == 200, f"Tool call {name} failed: HTTP {res.status_code}"
        data = res.json()
        content = data.get("result", {}).get("content", [])
        text_payload = content[0].get("text", "") if content else ""
        parsed = json.loads(text_payload) if text_payload.startswith("{") else text_payload
        return parsed, lat

    # 8.1 nexus.status
    stat_res, lat_stat = call_mcp_tool("nexus.status")
    print(f"nexus.status ({lat_stat}ms): status={stat_res.get('status')}, version={stat_res.get('appliance_version')}, governor={stat_res.get('thermal_state')}")

    # 8.2 academic.query: next_classes
    nc_res, lat_nc = call_mcp_tool("academic.query", {"operation": "next_classes"})
    print(f"academic.query: next_classes ({lat_nc}ms):")
    nc_data = nc_res.get("data", {}) if isinstance(nc_res, dict) else {}
    print(f"   Operation: {nc_res.get('operation') if isinstance(nc_res, dict) else 'raw'}")
    print(f"   Next Class: {nc_data.get('next_class')}")
    print(f"   Today Total Classes: {nc_data.get('today_total_classes')}")

    # 8.3 academic.query: attendance
    att_res, lat_att = call_mcp_tool("academic.query", {"operation": "attendance"})
    print(f"academic.query: attendance ({lat_att}ms):")
    att_data = att_res.get("data", {}) if isinstance(att_res, dict) else {}
    print(f"   Overall %: {att_data.get('overall_percentage')}%")
    print(f"   Conducted: {att_data.get('total_conducted')}, Attended: {att_data.get('total_attended')}")
    print(f"   Safe Bunks: {att_data.get('total_safe_bunks')}")
    print(f"   Subjects Count: {len(att_data.get('subjects', []))}")

    # 8.4 academic.query: results
    res_res, lat_res = call_mcp_tool("academic.query", {"operation": "results"})
    print(f"academic.query: results ({lat_res}ms):")
    res_data = res_res.get("data", {}) if isinstance(res_res, dict) else {}
    print(f"   Calculated CGPA: {res_data.get('calculated_cgpa')}")
    print(f"   Semester Count: {res_data.get('semester_count')}")

    # 8.5 lms.query: courses
    lms_res, lat_lms = call_mcp_tool("lms.query", {"operation": "courses"})
    print(f"lms.query: courses ({lat_lms}ms):")
    lms_data = lms_res.get("data", {}) if isinstance(lms_res, dict) else {}
    courses = lms_data.get("courses", [])
    print(f"   Courses Count: {len(courses)} (Truthful empty state: {len(courses) == 0})")
    print(f"   Provenance: {lms_res.get('provenance') if isinstance(lms_res, dict) else 'none'}")

    # -------------------------------------------------------------
    # SECTION 9: MCP PAGE PRESENTATION
    # -------------------------------------------------------------
    print("\n--- [Section 9] MCP Page Presentation Verification ---")
    login_sess = requests.post(f"{BASE_PUBLIC}/api/auth/login", headers={"Content-Type": "application/json", "localtonet-skip-warning": "true"}, json={"user_id": "testadmin", "password": "Admin@1234"}, timeout=10)
    sess_tok = login_sess.json()["token"]
    sess_headers = {"Authorization": f"Bearer {sess_tok}", "localtonet-skip-warning": "true"}

    r_summary = requests.get(f"{BASE_PUBLIC}/api/mcp/summary", headers=sess_headers, timeout=10)
    mcp_sum = r_summary.json()
    print(f"MCP Summary Ingress: {mcp_sum.get('ingress')}")
    print(f"Primary Public MCP Endpoint: {mcp_sum.get('public_mcp_url')}")
    print(f"Secondary LAN Diagnostic Endpoint: {mcp_sum.get('lan_mcp_url')}")
    assert mcp_sum.get("public_mcp_url") == f"{BASE_PUBLIC}/api/mcp"
    assert mcp_sum.get("lan_mcp_url") == "http://192.168.29.21:5000/api/mcp"

    # -------------------------------------------------------------
    # SECTION 10: GOOGLE OAUTH PUBLIC CALLBACK
    # -------------------------------------------------------------
    print("\n--- [Section 10] Google OAuth Public Callback ---")
    r_google = requests.get(f"{BASE_PUBLIC}/api/admin/google-oauth/status", headers=sess_headers, timeout=10)
    google_data = r_google.json()
    computed_cb = google_data.get("computed_callback_url")
    registered_cb = google_data.get("redirect_uri")
    preflight = google_data.get("preflight_status")
    print(f"Computed Public Callback URI: {computed_cb}")
    print(f"Registered Callback URI:     {registered_cb}")
    print(f"Preflight Status:            {preflight}")
    assert computed_cb == f"{BASE_PUBLIC}/api/auth/google/callback"
    assert registered_cb == f"{BASE_PUBLIC}/api/auth/google/callback"
    assert preflight == "READY"

    print("\n" + "=" * 60)
    print("ALL SECTIONS 6 - 10 ACCEPTANCE TESTS PASSED SUCCESSFULLY!")
    print("=" * 60)

if __name__ == "__main__":
    run_public_mcp_tests()
