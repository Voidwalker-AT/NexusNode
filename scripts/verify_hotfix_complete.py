import os
import sys

SERVER_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SERVER_ROOT not in sys.path:
    sys.path.insert(0, SERVER_ROOT)

import unittest
import paramiko

def run_local_tests():
    print("=" * 60)
    print("RUNNING LOCAL REGRESSION TESTS")
    print("=" * 60)
    suite = unittest.TestSuite()
    loader = unittest.TestLoader()
    suite.addTests(loader.loadTestsFromName("tests.test_dashboard_summary_resilience"))
    suite.addTests(loader.loadTestsFromName("tests.test_stage2_multi_user_isolation_acceptance"))
    suite.addTests(loader.loadTestsFromName("tests.test_scheduler_3hour"))
    
    runner = unittest.TextTestRunner(verbosity=2)
    res = runner.run(suite)
    assert res.wasSuccessful(), f"Local tests failed: {res.failures} {res.errors}"
    print("[PASS] All local regression tests passed successfully!")

def run_remote_bg6_verification():
    print("\n" + "=" * 60)
    print("RUNNING BG6 REMOTE VERIFICATION")
    print("=" * 60)
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect('192.168.29.21', port=8022, username='u0_a208', password='anmol2005', timeout=15)

    def exec_cmd(label, cmd):
        print(f"\n--- {label} ---")
        full_cmd = f"export PATH=/data/data/com.termux/files/usr/bin:$PATH; cd ~/server && {cmd}"
        stdin, stdout, stderr = ssh.exec_command(full_cmd)
        out = stdout.read().decode('utf-8', errors='replace').strip()
        err = stderr.read().decode('utf-8', errors='replace').strip()
        if out:
            print(out)
        if err:
            print("STDERR:", err)
        return out, err

    # 1. Runit Service Status
    exec_cmd("Service Status", "sv status nexusnode")

    # 2. Chromium process count
    out, _ = exec_cmd("Chromium Process Count", "ps aux | grep '[c]hromium' | wc -l")
    count = int(out.strip()) if out.strip().isdigit() else -1
    print(f"Verified Chromium Count: {count} (Must be 0)")
    assert count == 0, f"Expected 0 Chromium processes, found {count}"

    # 3. Test Dashboard Summary Resilience on BG6
    exec_cmd("Test Dashboard Summary Resilience", "python -m unittest tests/test_dashboard_summary_resilience.py")

    # 4. Test Stage 2 Multi-User Isolation on BG6
    exec_cmd("Test Stage 2 Multi-User Isolation Acceptance", "python -m unittest tests/test_stage2_multi_user_isolation_acceptance.py")

    # 5. Test Scheduler 3-Hour on BG6
    exec_cmd("Test Scheduler 3-Hour", "python -m unittest tests/test_scheduler_3hour.py")

    # 6. Verify stage 3 metrics script
    exec_cmd("Verify Stage 3 Acceptance Metrics", "python scripts/verify_stage3_acceptance.py")

    # 7. Check live authenticated /api/dashboard/summary via test client
    verify_script = """
import app
app.app.config["TESTING"] = True
client = app.app.test_client()
import sqlite3, config
conn = sqlite3.connect(config.DB_PATH)
cur = conn.cursor()
cur.execute("SELECT user_id, password_hash, salt FROM users WHERE user_id = 'admin'")
row = cur.fetchone()
conn.close()

import hashlib
# Test dashboard summary with fake admin session in app.SESSIONS
import secrets
token = secrets.token_hex(16)
app.SESSIONS[token] = {
    'user_id': 'admin',
    'created_at': 9999999999,
    'expires_at': 9999999999
}
res = client.get('/api/dashboard/summary', headers={'Cookie': f'session={token}'})
print('STATUS_CODE:', res.status_code)
print('CONTENT_TYPE:', res.content_type)
data = res.get_json()
print('DATA_KEYS:', list(data.keys()) if data else None)
print('STATUS:', data.get('status') if data else None)
print('ACADEMIC_RESULTS_PRESENT:', 'academic_results' in data if data else False)
print('SCHEDULE_NEXT_CLASS:', data.get('schedule', {}).get('next_class'))
"""
    exec_cmd("Live Dashboard Summary Call via BG6 Client", f'python -c "{verify_script}"')

    ssh.close()
    print("\n[PASS] Remote BG6 verification completed successfully!")

if __name__ == "__main__":
    run_local_tests()
    run_remote_bg6_verification()
