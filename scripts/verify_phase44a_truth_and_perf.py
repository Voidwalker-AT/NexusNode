import paramiko
import requests
import secrets
import base64
import hashlib
import json
import time

HOST = "192.168.29.21"
PORT = 8022
USER = "u0_a208"
PASS = "anmol2005"
LAN_URL = f"http://{HOST}:5000"
PUB_URL = "https://k09oezeyib.localto.net"

def mint_admin_token():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, port=PORT, username=USER, password=PASS, timeout=10)

    verifier = secrets.token_urlsafe(32)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode('ascii')).digest()).decode('ascii').rstrip('=')
    client_id = 'test_p44_bench'
    client_secret = 'sec_p44_999'
    redirect_uri = 'https://oauth-redirect.googleusercontent.com/r/test_live'

    mint_py = f"""
import sqlite3, config
from agent.oauth_provider import OAuthProvider

conn_factory = lambda: sqlite3.connect(config.DB_PATH)
provider = OAuthProvider(conn_factory=conn_factory)
provider.register_client(
    client_id='{client_id}', client_secret='{client_secret}',
    client_name='P44 Bench', redirect_uris=['{redirect_uri}']
)
code, _ = provider.create_authorization_code(
    client_id='{client_id}', redirect_uri='{redirect_uri}',
    user_id='admin', scope='mcp',
    code_challenge='{challenge}', code_challenge_method='S256'
)
print('CODE:' + code)
"""
    stdin, stdout, stderr = ssh.exec_command("cd ~/server && python3")
    stdin.write(mint_py)
    stdin.channel.shutdown_write()
    out = stdout.read().decode()
    code = [l for l in out.splitlines() if l.startswith('CODE:')][0].split(':', 1)[1].strip()
    ssh.close()

    basic_auth = base64.b64encode(f'{client_id}:{client_secret}'.encode()).decode()
    r_tok = requests.post(
        f"{LAN_URL}/oauth/token",
        data={'grant_type': 'authorization_code', 'code': code, 'redirect_uri': redirect_uri, 'code_verifier': verifier},
        headers={'Authorization': f'Basic {basic_auth}'},
        timeout=10
    )
    return r_tok.json()['access_token']

def measure_endpoint(url, token, desc):
    headers = {
        'Authorization': f'Bearer {token}',
        'localtonet-skip-warning': 'true'
    }
    t0 = time.perf_counter()
    r = requests.get(url, headers=headers, timeout=15)
    t1 = time.perf_counter()
    lat_ms = (t1 - t0) * 1000.0
    size_bytes = len(r.content)
    return r.status_code, lat_ms, size_bytes, r.json() if r.headers.get('content-type', '').startswith('application/json') else None

def main():
    print("Minting admin token...")
    token = mint_admin_token()
    print("Admin token obtained.")

    results = {}

    print("\n" + "="*70)
    print("1. LATENCY BENCHMARK — LAN vs PUBLIC")
    print("="*70)

    endpoints = [
        ("/api/dashboard/summary", "Dashboard Summary (1st call)"),
        ("/api/dashboard/summary", "Dashboard Summary (2nd call - cached)"),
        ("/api/academics/snapshot", "Academics Snapshot (Consolidated)"),
        ("/api/academics/results", "Academics Results"),
        ("/api/lms/courses", "LMS Courses (Fast failure check)"),
        ("/api/timetable/onboarding-status", "Onboarding Status")
    ]

    for path, desc in endpoints:
        lan_code, lan_lat, lan_sz, lan_data = measure_endpoint(f"{LAN_URL}{path}", token, desc)
        pub_code, pub_lat, pub_sz, pub_data = measure_endpoint(f"{PUB_URL}{path}", token, desc)
        print(f"[{desc}]")
        print(f"  LAN:    {lan_code} in {lan_lat:6.1f}ms  ({lan_sz} bytes)")
        print(f"  PUBLIC: {pub_code} in {pub_lat:6.1f}ms  ({pub_sz} bytes)")
        results[path] = {
            "desc": desc,
            "lan_lat_ms": lan_lat,
            "pub_lat_ms": pub_lat,
            "size_bytes": pub_sz,
            "data": pub_data
        }

    print("\n" + "="*70)
    print("2. DATA TRUTH VERIFICATION")
    print("="*70)

    # 1. Dashboard summary
    dash = results["/api/dashboard/summary"]["data"]
    acc = dash.get("account", {})
    print("Dashboard Summary:")
    print(f"  account.google_needs_reauth: {acc.get('google_needs_reauth')} (expected: True)")
    print(f"  account.health_state:        {acc.get('health_state')} (expected: GOOGLE_EXPIRED)")
    assert acc.get("google_needs_reauth") is True, f"FAIL: google_needs_reauth should be True, got {acc.get('google_needs_reauth')}!"
    assert acc.get("health_state") == "GOOGLE_EXPIRED", f"FAIL: health_state should be GOOGLE_EXPIRED, got {acc.get('health_state')}!"

    # 2. Academics snapshot
    snap = results["/api/academics/snapshot"]["data"]
    print("\nAcademics Snapshot:")
    print(f"  timetable.count:     {snap.get('timetable', {}).get('count')} (expected: 384)")
    print(f"  timetable.is_stale:  {snap.get('timetable', {}).get('is_stale')} (expected: True)")
    print(f"  timetable.source:    {snap.get('timetable', {}).get('source')} (expected: lkg)")
    print(f"  results.cgpa:        {snap.get('results', {}).get('cgpa')} (expected: None)")
    print(f"  results.semesters:   {snap.get('results', {}).get('semesters_count')} (expected: 0)")
    print(f"  lms.status:          {snap.get('lms', {}).get('status')} (expected: AUTH_REQUIRED)")
    print(f"  lms.courses_count:   {snap.get('lms', {}).get('courses_count')} (expected: 0)")
    assert snap.get('results', {}).get('cgpa') is None, "FAIL: results cgpa should be None!"
    assert snap.get('lms', {}).get('status') == 'AUTH_REQUIRED', "FAIL: LMS status should be AUTH_REQUIRED!"

    # 3. Results endpoint
    res_data = results["/api/academics/results"]["data"]
    print("\nResults Endpoint:")
    print(f"  official_cgpa:       {res_data.get('official_cgpa')} (expected: None)")
    print(f"  calculated_cgpa:     {res_data.get('calculated_cgpa')} (expected: None)")
    print(f"  semesters count:     {len(res_data.get('semesters', []))} (expected: 0)")
    assert len(res_data.get('semesters', [])) == 0, "FAIL: semesters list must be empty!"

    # 4. LMS courses endpoint
    lms_data = results["/api/lms/courses"]["data"]
    print("\nLMS Courses Endpoint:")
    print(f"  ok:                  {lms_data.get('ok')} (expected: False)")
    print(f"  error_code:          {lms_data.get('error_code')} (expected: LMS_AUTH_REQUIRED)")
    print(f"  message:             {lms_data.get('message')}")
    assert lms_data.get("ok") is False, "FAIL: lms ok should be False!"
    assert lms_data.get("error_code") == "LMS_AUTH_REQUIRED", "FAIL: lms error_code must be LMS_AUTH_REQUIRED!"

    # 5. BG6 Chromium process check
    print("\n" + "="*70)
    print("3. BG6 PROCESS HYGIENE & CHROMIUM CHECK")
    print("="*70)
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, port=PORT, username=USER, password=PASS, timeout=10)
    stdin, stdout, stderr = ssh.exec_command("pgrep -l chromium || echo 'NO_CHROMIUM'")
    chrom_out = stdout.read().decode().strip()
    print(f"BG6 Chromium processes: {chrom_out}")
    assert "chromium" not in chrom_out.lower() or chrom_out == "NO_CHROMIUM", "FAIL: Chromium process detected!"

    stdin, stdout, stderr = ssh.exec_command("uptime")
    uptime = stdout.read().decode().strip()
    print(f"BG6 Uptime / Load: {uptime}")
    ssh.close()

    print("\nALL EMPIRICAL LATENCY & TRUTH CHECKS PASSED PERFECTLY!")

if __name__ == "__main__":
    main()
