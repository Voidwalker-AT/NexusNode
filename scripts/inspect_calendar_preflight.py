import time
import json
import paramiko

def main():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect('192.168.29.21', port=8022, username='u0_a208', password='anmol2005', timeout=10)

    py_code = """
import sqlite3, time, json
import config
from timetable_sync import TimetableService, OAuthTokenCrypto

conn_factory = lambda: sqlite3.connect(config.DB_PATH)
svc = TimetableService(conn_factory)

# 1. Google OAuth tokens for admin
oauth_info = svc.get_oauth_tokens('admin')
google_connected = oauth_info is not None

cur_u = conn_factory().cursor()
cur_u.execute("SELECT user_id, upes_email, google_email FROM users WHERE user_id = 'admin'")
user_row = cur_u.fetchone()
google_email_from_users = user_row[2] if user_row else None
cur_u.execute("SELECT calendar_id, connected_email, created_at, updated_at FROM google_oauth_tokens WHERE user_id = 'admin'")
token_row = cur_u.fetchone()
cur_u.close()

email = None
cal_id = None
access_valid = 'N/A'
refresh_present = 'ABSENT'
refresh_capability = 'NO'

if oauth_info:
    token_data, cal_id, email = oauth_info
    expires_at = token_data.get('expires_at', 0)
    now = time.time()
    access_valid = 'VALID' if now < expires_at else 'EXPIRED'
    has_rt = bool(token_data.get('refresh_token'))
    refresh_present = 'PRESENT' if has_rt else 'ABSENT'
    refresh_capability = 'YES' if has_rt else 'NO'

# 2. Timetable sessions count & status
sessions, errs = svc.load_timetable_sessions('admin')
session_count = len(sessions) if sessions else 0
status_info = svc.get_user_status('admin')
source = status_info.get('timetable_source') or 'CACHED'
if not status_info.get('timetable_loaded'):
    source = 'EMPTY'

# 3. Existing timetable_events_map rows
conn = conn_factory()
cur = conn.cursor()
cur.execute("SELECT COUNT(*) FROM timetable_events_map WHERE user_id = 'admin'")
mapped_total = cur.fetchone()[0]
cur.execute("SELECT COUNT(*) FROM timetable_events_map WHERE user_id = 'admin' AND status = 'synced'")
mapped_synced = cur.fetchone()[0]

# 4. Last calendar sync
cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND (name LIKE '%sync%' OR name LIKE '%history%' OR name LIKE '%log%')")
tables = [r[0] for r in cur.fetchall()]

last_sync = "None recorded"
if "calendar_sync_history" in tables:
    cur.execute("SELECT timestamp, status, created_count, updated_count FROM calendar_sync_history WHERE user_id = 'admin' ORDER BY id DESC LIMIT 1")
    r = cur.fetchone()
    if r:
        last_sync = f"{r[0]} (status={r[1]}, created={r[2]}, updated={r[3]})"
elif "attendance_sync_history" in tables:
    pass

# Check scheduled_jobs
cur.execute("PRAGMA table_info(scheduled_jobs)")
cols = [r[1] for r in cur.fetchall()]
cur.execute("SELECT * FROM scheduled_jobs")
sched_rows = cur.fetchall()
sched_info = f"cols={cols}, rows={sched_rows}"

conn.close()

out = {
    'google_connected': google_connected,
    'email': email,
    'calendar_id': cal_id,
    'access_valid': access_valid,
    'refresh_present': refresh_present,
    'refresh_capability': refresh_capability,
    'session_count': session_count,
    'source': source,
    'mapped_total': mapped_total,
    'mapped_synced': mapped_synced,
    'google_email_from_users': google_email_from_users,
    'token_row': list(token_row) if token_row else None,
    'last_sync': last_sync,
    'sched_info': sched_info
}
print(json.dumps(out))
"""

    stdin, stdout, stderr = ssh.exec_command("cd ~/server && python3")
    stdin.write(py_code)
    stdin.channel.shutdown_write()
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    ssh.close()

    if err:
        print("STDERR:", err)
    print("OUTPUT:", out)

if __name__ == "__main__":
    main()
