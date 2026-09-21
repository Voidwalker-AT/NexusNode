import os
import sys
import json
import sqlite3
import paramiko

def audit_remote_academics():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect('192.168.29.21', port=8022, username='u0_a208', password='anmol2005', timeout=15)

    remote_script = '''
import os, sys, time, json, sqlite3
import config

print("=" * 60)
print("ACADEMICS SAFE AUDIT ON BG6")
print("=" * 60)

conn = sqlite3.connect(config.DB_PATH)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# 1. Users table for admin
cur.execute("SELECT user_id, role, is_disabled, created_at FROM users WHERE user_id = 'admin'")
row = cur.fetchone()
print("ADMIN USER RECORD:", dict(row) if row else None)

def get_cols(table):
    cur.execute(f"PRAGMA table_info({table})")
    return [r[1] for r in cur.fetchall()]

# 2. UPES Credentials
print("UPES CREDENTIALS COLS:", get_cols("upes_user_credentials"))
cur.execute("SELECT * FROM upes_user_credentials WHERE user_id = 'admin'")
row = cur.fetchone()
if row:
    d = dict(row)
    # Mask secrets
    for k in ["password_encrypted", "auth_token_encrypted", "secret"]:
        if k in d: d[k] = "[ENCRYPTED]"
    print("UPES CREDENTIALS (SAFE):", d)
else:
    print("UPES CREDENTIALS: None")

# 3. UPES Token Cache / Session
try:
    print("UPES TOKEN CACHE COLS:", get_cols("upes_token_cache"))
    cur.execute("SELECT * FROM upes_token_cache WHERE user_id = 'admin'")
    row = cur.fetchone()
    if row:
        d = dict(row)
        for k in ["token", "access_token", "jwt", "refresh_token"]:
            if k in d: d[k] = "[TOKEN]"
        print("UPES TOKEN CACHE (SAFE):", d)
    else:
        print("UPES TOKEN CACHE: None")
except Exception as e:
    print("UPES TOKEN CACHE ERROR:", e)

# 4. UPES Portal Sessions
try:
    print("UPES PORTAL SESSIONS COLS:", get_cols("upes_portal_sessions"))
    cur.execute("SELECT * FROM upes_portal_sessions WHERE user_id = 'admin'")
    row = cur.fetchone()
    if row:
        d = dict(row)
        for k in ["session_token", "access_token", "token"]:
            if k in d: d[k] = "[TOKEN]"
        print("UPES PORTAL SESSIONS (SAFE):", d)
    else:
        print("UPES PORTAL SESSIONS: None")
except Exception as e:
    print("UPES PORTAL SESSIONS ERROR:", e)

# 5. Timetable files / records
print("\\n--- TIMETABLE AUDIT ---")
try:
    cur.execute("SELECT COUNT(*) FROM timetable_events_map WHERE user_id = 'admin'")
    count = cur.fetchone()[0]
    print("TIMETABLE EVENTS MAP COUNT:", count)
except Exception as e:
    print("TIMETABLE EVENTS MAP ERROR:", e)

# Check timetable files on disk
user_tt_dir = os.path.join(config.STORAGE_DIR, "users", "admin", "timetable")
if os.path.exists(user_tt_dir):
    print("TIMETABLE DIR FILES:", os.listdir(user_tt_dir))
else:
    print("TIMETABLE DIR DOES NOT EXIST:", user_tt_dir)

# Check load_timetable_sessions
import app
sessions, errors = app.timetable_service.load_timetable_sessions('admin')
print(f"LOADED TIMETABLE SESSIONS COUNT: {len(sessions)}, ERRORS: {errors}")
if sessions:
    s0 = sessions[0]
    print("SAMPLE SESSION 0 (dict):", s0.to_dict() if hasattr(s0, "to_dict") else vars(s0))

# 6. Attendance records
print("\\n--- ATTENDANCE AUDIT ---")
try:
    cur.execute("SELECT COUNT(*) FROM attendance_snapshots WHERE user_id = 'admin'")
    print("ATTENDANCE SNAPSHOTS COUNT:", cur.fetchone()[0])
except Exception as e:
    print("ATTENDANCE SNAPSHOTS ERROR:", e)

try:
    cur.execute("SELECT COUNT(*) FROM attendance_subjects WHERE user_id = 'admin'")
    print("ATTENDANCE SUBJECTS COUNT:", cur.fetchone()[0])
    cur.execute("SELECT subject_code, subject_name, conducted, attended, percentage, updated_at FROM attendance_subjects WHERE user_id = 'admin'")
    for r in cur.fetchall():
        print("  SUBJECT:", dict(r))
except Exception as e:
    print("ATTENDANCE SUBJECTS ERROR:", e)

# 7. Academic Results
print("\\n--- RESULTS AUDIT ---")
try:
    cur.execute("SELECT COUNT(*) FROM academic_results WHERE user_id = 'admin'")
    print("ACADEMIC RESULTS COUNT:", cur.fetchone()[0])
    cur.execute("SELECT term_id, official_sgpa, calculated_sgpa, official_cgpa, calculated_cgpa, last_synced_at FROM academic_results WHERE user_id = 'admin'")
    for r in cur.fetchall():
        print("  TERM:", dict(r))
except Exception as e:
    print("ACADEMIC RESULTS ERROR:", e)

try:
    cur.execute("SELECT COUNT(*) FROM academic_result_courses WHERE user_id = 'admin'")
    print("ACADEMIC RESULT COURSES COUNT:", cur.fetchone()[0])
except Exception as e:
    print("ACADEMIC RESULT COURSES ERROR:", e)

# 8. LMS Cache
print("\\n--- LMS AUDIT ---")
try:
    cur.execute("SELECT COUNT(*) FROM lms_courses WHERE user_id = 'admin'")
    print("LMS COURSES COUNT:", cur.fetchone()[0])
except Exception as e:
    print("LMS COURSES ERROR:", e)

try:
    cur.execute("SELECT COUNT(*) FROM lms_assignments WHERE user_id = 'admin'")
    print("LMS ASSIGNMENTS COUNT:", cur.fetchone()[0])
except Exception as e:
    print("LMS ASSIGNMENTS ERROR:", e)

# 9. Google OAuth
print("\\n--- GOOGLE OAUTH AUDIT ---")
try:
    cur.execute("SELECT user_id, user_email, calendar_id, updated_at FROM google_oauth_tokens WHERE user_id = 'admin'")
    row = cur.fetchone()
    if row:
        print("GOOGLE OAUTH:", {"user_id": row[0], "user_email": row[1], "calendar_id": row[2], "updated_at": row[3]})
    else:
        print("GOOGLE OAUTH: None")
except Exception as e:
    print("GOOGLE OAUTH ERROR:", e)

conn.close()

# 10. Test client query against all Academics endpoints
print("\\n--- ACADEMICS ENDPOINTS DIRECT TEST CLIENT ---")
import app
app.app.config["TESTING"] = True
client = app.app.test_client()

import secrets
tok = "audit_tok_" + secrets.token_hex(8)
with app.SESSIONS_LOCK:
    app.SESSIONS[tok] = {
        "user_id": "admin",
        "role": "admin",
        "privileges": dict(config.ADMIN_DEFAULT_PRIVILEGES),
        "created_at": time.time(),
        "expires_at": time.time() + 3600
    }
headers = {"Authorization": f"Bearer {tok}"}

endpoints = [
    "/api/academics/onboarding-status",
    "/api/timetable/sessions",
    "/api/attendance/summary",
    "/api/academics/results",
    "/api/academics/performance",
    "/api/lms/courses",
    "/api/lms/assignments",
    "/api/auth/google/status",
    "/api/mcp/summary"
]

for ep in endpoints:
    r = client.get(ep, headers=headers)
    ct = r.headers.get("Content-Type", "")
    print(f"EP: {ep} -> Status: {r.status_code}")
    if r.status_code == 200 and "application/json" in ct:
        data = r.get_json()
        if isinstance(data, dict):
            keys = list(data.keys())
            summary = {k: (len(data[k]) if isinstance(data[k], (list, dict)) else data[k]) for k in keys[:6]}
            print(f"    Keys: {keys} | Preview: {summary}")
        elif isinstance(data, list):
            print(f"    List items count: {len(data)}")
    else:
        print(f"    Raw content: {r.data[:200]}")
'''

    sftp = ssh.open_sftp()
    with sftp.file('/data/data/com.termux/files/home/server/audit_academics_runner.py', 'w') as f:
        f.write(remote_script)
    sftp.close()

    stdin, stdout, stderr = ssh.exec_command('export PATH=/data/data/com.termux/files/usr/bin:$PATH; cd ~/server && python audit_academics_runner.py && rm audit_academics_runner.py')
    print(stdout.read().decode('utf-8', errors='replace'))
    err = stderr.read().decode('utf-8', errors='replace')
    if err:
        print("STDERR:", err)

    ssh.close()

if __name__ == '__main__':
    audit_remote_academics()
