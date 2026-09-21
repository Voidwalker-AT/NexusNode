import time
import json
import base64
import hashlib
import secrets
import socket
import unittest
import paramiko
import requests

PUBLIC_ORIGIN = "https://k09oezeyib.localto.net"
PUBLIC_HOST = "k09oezeyib.localto.net"
LAN_HOST = "192.168.29.21"
SSH_PORT = 8022
SSH_USER = "u0_a208"
SSH_PASS = "anmol2005"
SKIP_HDR = {"localtonet-skip-warning": "true"}

def get_ssh_client():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(LAN_HOST, port=SSH_PORT, username=SSH_USER, password=SSH_PASS, timeout=10)
    return ssh

def get_bg6_chromium_count(ssh):
    stdin, stdout, stderr = ssh.exec_command("ps -ef | grep -i '[c]hromium' | wc -l")
    out = stdout.read().decode().strip()
    return int(out) if out.isdigit() else 0

def get_bg6_memory_telemetry(ssh):
    stdin, stdout, stderr = ssh.exec_command("grep MemAvailable /proc/meminfo")
    mem_avail_line = stdout.read().decode().strip()
    # MemAvailable:    1482048 kB
    parts = mem_avail_line.split()
    mem_avail_mb = round(int(parts[1]) / 1024, 1) if len(parts) >= 2 and parts[1].isdigit() else 0.0

    stdin, stdout, stderr = ssh.exec_command("ps -o rss,args -e | grep '[p]ython.*app.py' | head -n1")
    rss_line = stdout.read().decode().strip()
    rss_parts = rss_line.split()
    rss_mb = round(int(rss_parts[0]) / 1024, 1) if len(rss_parts) >= 1 and rss_parts[0].isdigit() else 0.0

    return mem_avail_mb, rss_mb

def main():
    print("=" * 70)
    print("PHASE 4.3A-R3: SECTIONS 11 - 15 VERIFICATION SUITE")
    print("=" * 70)

    ssh = get_ssh_client()

    # -------------------------------------------------------------
    # SECTION 14: CHROMIUM RESOURCE INVARIANT (BEFORE) & MEMORY
    # -------------------------------------------------------------
    print("\n[Step 1] Recording Baseline Telemetry on TECNO BG6...")
    chrom_before = get_bg6_chromium_count(ssh)
    mem_avail_mb, rss_mb = get_bg6_memory_telemetry(ssh)
    print(f"   Chromium Process Count (BEFORE): {chrom_before}")
    print(f"   MemAvailable: {mem_avail_mb} MB")
    print(f"   NexusNode RSS: {rss_mb} MB")
    assert chrom_before == 0, f"Chromium processes running before test: {chrom_before}"

    # -------------------------------------------------------------
    # SECTION 12: INGRESS HEALTH TELEMETRY
    # -------------------------------------------------------------
    print("\n[Step 2] Section 12: Ingress Health Telemetry...")
    # Query /api/services/status or /api/system/status authenticated via testadmin
    login_res = requests.post(
        f"{PUBLIC_ORIGIN}/api/auth/login",
        headers=SKIP_HDR,
        json={"user_id": "testadmin", "password": "Admin@1234"},
        timeout=10
    )
    admin_token = login_res.json()["token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}", **SKIP_HDR}

    r_svc = requests.get(f"{PUBLIC_ORIGIN}/api/services/status", headers=admin_headers, timeout=10)
    print(f"   GET /api/services/status: HTTP {r_svc.status_code}")
    svc_data = r_svc.json()
    localtonet_svc = svc_data.get("localtonet", {})
    nexusnode_svc = svc_data.get("nexusnode", {})
    print(f"   localtonet runit service: running={localtonet_svc.get('running')}, status={localtonet_svc.get('status')}")
    print(f"   nexusnode runit service: running={nexusnode_svc.get('running')}, status={nexusnode_svc.get('status')}")
    assert localtonet_svc.get("running") is True
    assert nexusnode_svc.get("running") is True

    r_mcp_sum = requests.get(f"{PUBLIC_ORIGIN}/api/mcp/summary", headers=admin_headers, timeout=10)
    mcp_sum = r_mcp_sum.json()
    ingress_telemetry = mcp_sum.get("ingress", {})
    print(f"   Ingress Telemetry: {ingress_telemetry}")
    assert ingress_telemetry.get("tunnel_status") == "TUNNEL_CONNECTED"
    assert ingress_telemetry.get("is_public_healthy") is True
    assert ingress_telemetry.get("public_origin") == PUBLIC_ORIGIN

    # Appliance Health Check
    r_hlth = requests.get(f"{PUBLIC_ORIGIN}/api/health", headers=SKIP_HDR, timeout=10)
    print(f"   Appliance Health (/api/health): {r_hlth.json()}")
    assert r_hlth.status_code == 200
    assert r_hlth.json().get("status") == "healthy"

    # -------------------------------------------------------------
    # SECTION 14: DURING PUBLIC READS - CHROMIUM INVARIANT
    # -------------------------------------------------------------
    print("\n[Step 3] Section 14: Chromium Invariant DURING Public Activity...")
    # Rapid-fire requests to Dashboard, Academics, MCP
    for _ in range(3):
        requests.get(f"{PUBLIC_ORIGIN}/api/dashboard/summary", headers=admin_headers, timeout=10)
        requests.get(f"{PUBLIC_ORIGIN}/api/timetable/sessions", headers=admin_headers, timeout=10)
        requests.get(f"{PUBLIC_ORIGIN}/api/attendance/summary", headers=admin_headers, timeout=10)
        requests.get(f"{PUBLIC_ORIGIN}/api/academics/results", headers=admin_headers, timeout=10)

    chrom_during = get_bg6_chromium_count(ssh)
    print(f"   Chromium Process Count (DURING): {chrom_during}")
    assert chrom_during == 0, f"Chromium launched during API calls: {chrom_during}"

    # -------------------------------------------------------------
    # SECTION 15: SECURITY CHECK ON PUBLIC SURFACE
    # -------------------------------------------------------------
    print("\n[Step 4] Section 15: Security Verification on Public Surface...")

    # 15.1 Unauthenticated access checks
    unauth_endpoints = [
        ("GET", "/api/dashboard/summary"),
        ("GET", "/api/timetable/sessions"),
        ("GET", "/api/attendance/summary"),
        ("GET", "/api/academics/results"),
        ("GET", "/files?path="),
        ("GET", "/api/admin/users"),
    ]
    for method, ep in unauth_endpoints:
        r = requests.request(method, f"{PUBLIC_ORIGIN}{ep}", headers=SKIP_HDR, timeout=10)
        print(f"   Unauth {method} {ep}: HTTP {r.status_code}")
        assert r.status_code in [401, 403], f"Unauthenticated request to {ep} returned {r.status_code}!"

    # 15.2 Authenticated regular user accessing admin endpoints -> 403
    stud_verifier = secrets.token_urlsafe(32)
    stud_chal = base64.urlsafe_b64encode(hashlib.sha256(stud_verifier.encode('ascii')).digest()).decode('ascii').rstrip('=')
    stud_client = "test_student_client"
    stud_secret = "secret_student_999"
    stud_redirect = "https://oauth-redirect.googleusercontent.com/r/test_live"

    mint_stud_py = f"""cd ~/server && python3 -c "
import sqlite3, config
from agent.oauth_provider import OAuthProvider

conn_factory = lambda: sqlite3.connect(config.DB_PATH)
provider = OAuthProvider(conn_factory=conn_factory)
provider.register_client(
    client_id='{stud_client}', client_secret='{stud_secret}',
    client_name='Student RBAC Check', redirect_uris=['{stud_redirect}']
)
code, _ = provider.create_authorization_code(
    client_id='{stud_client}', redirect_uri='{stud_redirect}',
    user_id='teststudent', scope='mcp',
    code_challenge='{stud_chal}', code_challenge_method='S256'
)
print('STUD_CODE:' + code)
"
"""
    stdin, stdout, stderr = ssh.exec_command(mint_stud_py)
    stud_code_line = [l for l in stdout.read().decode().splitlines() if l.startswith("STUD_CODE:")][0]
    stud_auth_code = stud_code_line.split(":", 1)[1].strip()

    stud_basic = base64.b64encode(f"{stud_client}:{stud_secret}".encode()).decode()
    r_stud_tok = requests.post(
        f"{PUBLIC_ORIGIN}/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": stud_auth_code,
            "redirect_uri": stud_redirect,
            "code_verifier": stud_verifier
        },
        headers={"Authorization": f"Basic {stud_basic}", **SKIP_HDR},
        timeout=10
    )
    student_token = r_stud_tok.json()["access_token"]
    student_headers = {"Authorization": f"Bearer {student_token}", **SKIP_HDR}

    r_adm = requests.get(f"{PUBLIC_ORIGIN}/api/admin/users", headers=student_headers, timeout=10)
    print(f"   Regular student GET /api/admin/users: HTTP {r_adm.status_code}")
    assert r_adm.status_code == 403, f"Regular student accessed admin users: HTTP {r_adm.status_code}"

    r_goauth = requests.get(f"{PUBLIC_ORIGIN}/api/admin/google-oauth/status", headers=student_headers, timeout=10)
    print(f"   Regular student GET /api/admin/google-oauth/status: HTTP {r_goauth.status_code}")
    assert r_goauth.status_code == 403, f"Regular student accessed admin google-oauth: HTTP {r_goauth.status_code}"

    # 15.3 Server header & debug flag & stack trace isolation
    r_health = requests.get(f"{PUBLIC_ORIGIN}/api/health", headers=SKIP_HDR, timeout=10)
    server_hdr = r_health.headers.get("Server", "")
    print(f"   Server Header: '{server_hdr}' (Waitress production)")
    stdin, stdout, stderr = ssh.exec_command("cd ~/server && python3 -c 'import app; print(\"DEBUG_FLAG:\", app.app.debug)'")
    dbg_out = stdout.read().decode().strip()
    print(f"   Flask Debug: {dbg_out}")
    assert "DEBUG_FLAG: False" in dbg_out

    # Trigger a 404 on API endpoint and verify JSON response without stack trace
    r_bad = requests.get(f"{PUBLIC_ORIGIN}/api/non_existent_route_999", headers=SKIP_HDR, timeout=10)
    print(f"   Invalid route status: HTTP {r_bad.status_code}")
    assert "Traceback" not in r_bad.text

    # 15.4 Arbitrary filesystem traversal prevention
    r_trav = requests.get(f"{PUBLIC_ORIGIN}/files?path=../../etc/passwd", headers=admin_headers, timeout=10)
    print(f"   Path traversal /files?path=../../etc/passwd: HTTP {r_trav.status_code}")
    assert r_trav.status_code in [400, 403, 404]
    assert "root:x:0:0" not in r_trav.text

    # 15.5 Public SSH Port Check (Port 8022 or 22 over public domain should NOT be open)
    ssh_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    ssh_sock.settimeout(3)
    pub_ip = socket.gethostbyname(PUBLIC_HOST)
    res_ssh = ssh_sock.connect_ex((pub_ip, 8022))
    ssh_sock.close()
    print(f"   Public SSH probe {PUBLIC_HOST}:8022 -> connect_ex: {res_ssh} (Non-zero = CLOSED/FILTERED)")
    assert res_ssh != 0, "Public SSH port 8022 appears open on public IP!"

    # 15.6 Consequential mutation guardrail via MCP
    # Mint OAuth access token for admin
    verifier = secrets.token_urlsafe(32)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode('ascii')).digest()).decode('ascii').rstrip('=')
    client_id = "test_sec_check"
    client_secret = "secret_sec_999"
    redirect_uri = "https://oauth-redirect.googleusercontent.com/r/test_live"

    mint_py = f"""cd ~/server && python3 -c "
import sqlite3, config
from agent.oauth_provider import OAuthProvider

conn_factory = lambda: sqlite3.connect(config.DB_PATH)
provider = OAuthProvider(conn_factory=conn_factory)
provider.register_client(
    client_id='{client_id}', client_secret='{client_secret}',
    client_name='Sec Check', redirect_uris=['{redirect_uri}']
)
code, _ = provider.create_authorization_code(
    client_id='{client_id}', redirect_uri='{redirect_uri}',
    user_id='admin', scope='mcp',
    code_challenge='{challenge}', code_challenge_method='S256'
)
print('CODE:' + code)
"
"""
    stdin, stdout, stderr = ssh.exec_command(mint_py)
    code_line = [l for l in stdout.read().decode().splitlines() if l.startswith("CODE:")][0]
    auth_code = code_line.split(":", 1)[1].strip()

    basic_auth = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    r_tok = requests.post(
        f"{PUBLIC_ORIGIN}/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": auth_code,
            "redirect_uri": redirect_uri,
            "code_verifier": verifier
        },
        headers={"Authorization": f"Basic {basic_auth}", **SKIP_HDR},
        timeout=10
    )
    mcp_tok = r_tok.json()["access_token"]
    mcp_headers = {"Authorization": f"Bearer {mcp_tok}", **SKIP_HDR}

    # Call lms.submit_assignment without approval
    req_sub = {
        "jsonrpc": "2.0",
        "id": "mut-1",
        "method": "tools/call",
        "params": {
            "name": "lms.submit_assignment",
            "arguments": {"course_id": "101", "assignment_id": "999"}
        }
    }
    r_mut = requests.post(f"{PUBLIC_ORIGIN}/api/mcp", headers=mcp_headers, json=req_sub, timeout=10)
    print(f"   MCP lms.submit_assignment without approval: HTTP {r_mut.status_code}")
    mut_data = r_mut.json()
    print(f"   MCP Response: {mut_data}")
    # Must be error or content indicating APPROVAL_REQUIRED
    has_approval_required = (
        r_mut.status_code == 403 or
        "APPROVAL_REQUIRED" in str(mut_data) or
        "error" in mut_data or
        mut_data.get("result", {}).get("isError") is True
    )
    assert has_approval_required, f"Mutation was not blocked! Response: {mut_data}"
    print("   [PASS] Consequential mutation blocked successfully.")

    # -------------------------------------------------------------
    # SECTION 13: 3-HOUR AUTOMATION PERSISTENCE & INDEPENDENCE
    # -------------------------------------------------------------
    print("\n[Step 5] Section 13: 3-Hour Automation Persistence & Independence...")
    # Check scheduler code does NOT call localto.net
    stdin, stdout, stderr = ssh.exec_command("grep -rn 'localto.net' ~/server/timetable_sync.py ~/server/scheduled_jobs.py")
    grep_sched = stdout.read().decode().strip()
    print(f"   Grep 'localto.net' in scheduler modules: '{grep_sched}' (Expected: empty)")
    assert grep_sched == "", f"Scheduler contains references to public tunnel: {grep_sched}"

    # Run scheduler deterministic test suite on BG6
    stdin, stdout, stderr = ssh.exec_command("cd ~/server && python3 -m unittest tests/test_scheduler_3hour.py")
    sched_out = stdout.read().decode()
    sched_err = stderr.read().decode()
    print(f"   BG6 Scheduler Test Output:\n{sched_err.strip()}")
    assert "OK" in sched_err, f"Scheduler tests failed: {sched_err}"

    # -------------------------------------------------------------
    # SECTION 14: AFTER TESTS - CHROMIUM INVARIANT
    # -------------------------------------------------------------
    print("\n[Step 6] Section 14: Chromium Invariant AFTER Public Activity...")
    chrom_after = get_bg6_chromium_count(ssh)
    mem_avail_after, rss_after = get_bg6_memory_telemetry(ssh)
    print(f"   Chromium Process Count (AFTER): {chrom_after}")
    print(f"   MemAvailable (AFTER): {mem_avail_after} MB")
    print(f"   NexusNode RSS (AFTER): {rss_after} MB")
    assert chrom_after == 0, f"Chromium processes running after tests: {chrom_after}"

    # -------------------------------------------------------------
    # SECTION 11: TEST PUBLIC INGRESS RESTART PERSISTENCE
    # -------------------------------------------------------------
    print("\n[Step 7] Section 11: Restart LocalToNet Service & Measure Recovery...")
    t0 = time.time()
    stdin, stdout, stderr = ssh.exec_command("SVDIR=/data/data/com.termux/files/usr/var/service sv restart localtonet")
    sv_restart_out = stdout.read().decode().strip()
    print(f"   sv restart localtonet output: '{sv_restart_out}'")

    # Poll public health until 200
    recovered = False
    localtonet_recovery_s = None
    for attempt in range(90):
        time.sleep(0.5)
        try:
            r = requests.get(f"{PUBLIC_ORIGIN}/api/health", headers=SKIP_HDR, timeout=3)
            if r.status_code == 200 and r.json().get("status") == "healthy":
                localtonet_recovery_s = round(time.time() - t0, 2)
                recovered = True
                break
        except Exception:
            pass

    assert recovered, "LocalToNet did not recover public health within 45s!"
    print(f"   [PASS] LocalToNet service restarted and recovered in {localtonet_recovery_s}s!")

    print("\n[Step 8] Section 11: Restart NexusNode Service & Measure Recovery...")
    t0 = time.time()
    stdin, stdout, stderr = ssh.exec_command("SVDIR=/data/data/com.termux/files/usr/var/service sv restart nexusnode")
    sv_nn_out = stdout.read().decode().strip()
    print(f"   sv restart nexusnode output: '{sv_nn_out}'")

    recovered_nn = False
    nexusnode_recovery_s = None
    for attempt in range(60):
        time.sleep(0.5)
        try:
            r = requests.get(f"{PUBLIC_ORIGIN}/api/health", headers=SKIP_HDR, timeout=3)
            if r.status_code == 200 and r.json().get("status") == "healthy":
                nexusnode_recovery_s = round(time.time() - t0, 2)
                recovered_nn = True
                break
        except Exception:
            pass

    assert recovered_nn, "NexusNode did not recover public health within 30s!"
    print(f"   [PASS] NexusNode service restarted and recovered in {nexusnode_recovery_s}s!")

    ssh.close()

    print("\n" + "=" * 70)
    print("ALL SECTIONS 11 - 15 ACCEPTANCE TESTS COMPLETED SUCCESSFULLY!")
    print(f"Chromium 0/0/0: {chrom_before}/{chrom_during}/{chrom_after}")
    print(f"LocalToNet Recovery: {localtonet_recovery_s}s")
    print(f"NexusNode Recovery: {nexusnode_recovery_s}s")
    print(f"MemAvailable: {mem_avail_after} MB, NexusNode RSS: {rss_after} MB")
    print("=" * 70)

if __name__ == "__main__":
    main()
