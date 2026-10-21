import paramiko
import json

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.WarningPolicy())
ssh.connect('192.168.29.21', port=8022, username='u0_a208', key_filename=os.environ.get("BG6_SSH_KEY", os.path.expanduser("~/.ssh/nexusnode_bg6_ed25519")) if os.path.exists(os.path.expanduser("~/.ssh/nexusnode_bg6_ed25519")) else None, password=os.environ.get("BG6_SSH_PASSWORD"), timeout=10)

cmd = """
export PATH=/data/data/com.termux/files/usr/bin:$PATH
cd ~/server
python3 -c "
import sqlite3
import json
import time
import os
import config
from upes.crypto import UpesSessionCrypto

conn = sqlite3.connect(config.UNIFIED_DB_FILE)
conn.row_factory = sqlite3.Row
now = time.time()

# 1. user_timetables
utt = conn.execute('SELECT user_id, updated_at, length(raw_json) as len_raw FROM user_timetables').fetchall()
print('USER_TIMETABLES:', [dict(r) for r in utt])

# 2. academic_sessions
as_count = conn.execute('SELECT COUNT(*) as c, MIN(start_time) as min_t, MAX(start_time) as max_t FROM academic_sessions WHERE user_id=\\'admin\\'').fetchone()
print('ACADEMIC_SESSIONS:', dict(as_count))

# 3. Sample timetable sessions from user_timetables
utt_row = conn.execute('SELECT raw_json FROM user_timetables WHERE user_id=\\'admin\\'').fetchone()
if utt_row:
    raw_data = json.loads(utt_row['raw_json'])
    events = raw_data if isinstance(raw_data, list) else raw_data.get('events', raw_data.get('data', []))
    print(f'Parsed timetable events count: {len(events)}')
    if events:
        print('Sample first event:', json.dumps(events[0], indent=2))
        print('Sample last event:', json.dumps(events[-1], indent=2))

# 4. attendance summaries & modules
att_rows = conn.execute('SELECT m.module_name, s.* FROM official_attendance_summaries s LEFT JOIN academic_modules m ON s.module_id = m.id WHERE s.user_id=\\'admin\\'').fetchall()
print('ATTENDANCE ROWS:', [dict(r) for r in att_rows])

# 5. credentials
creds = conn.execute('SELECT user_id, username_hint, updated_at FROM upes_user_credentials').fetchall()
print('UPES_USER_CREDENTIALS:', [dict(r) for r in creds])

# 6. upes_auth_sessions
sessions = conn.execute('SELECT user_id, student_code, api_url, expires_at, cookie_expires_at, credential_generation, last_refresh_at, last_refresh_status FROM upes_auth_sessions').fetchall()
print('UPES_AUTH_SESSIONS:', [dict(r) for r in sessions])

# 7. recent timetable sync history
tt_hist = conn.execute('SELECT * FROM timetable_sync_history WHERE user_id=\\'admin\\' ORDER BY timestamp DESC LIMIT 5').fetchall()
print('RECENT TIMETABLE SYNC HIST:', [dict(r) for r in tt_hist])

# 8. recent attendance sync history
att_hist = conn.execute('SELECT * FROM attendance_sync_history WHERE user_id=\\'admin\\' ORDER BY timestamp DESC LIMIT 5').fetchall()
print('RECENT ATTENDANCE SYNC HIST:', [dict(r) for r in att_hist])
"
"""

stdin, stdout, stderr = ssh.exec_command(cmd)
print(stdout.read().decode())
err = stderr.read().decode()
if err:
    print("STDERR:", err)
ssh.close()
