import paramiko

s = paramiko.SSHClient()
s.set_missing_host_key_policy(paramiko.AutoAddPolicy())
s.connect('192.168.29.21', port=8022, username='u0_a208', password='anmol2005', timeout=10)

cmd = """python3 -c "
import sqlite3, config
conn = sqlite3.connect(config.DB_PATH)
conn.row_factory = sqlite3.Row
cur = conn.cursor()
for tbl in ['upes_auth_sessions', 'upes_timetable_sessions', 'upes_attendance_summary', 'academic_results']:
    try:
        cur.execute(f'SELECT DISTINCT user_id FROM {tbl}')
        users = [r[0] for r in cur.fetchall()]
        print(f'{tbl}: {users}')
    except Exception as e:
        print(f'{tbl}: error {e}')
conn.close()
"
"""

stdin, stdout, stderr = s.exec_command(f"export PATH=/data/data/com.termux/files/usr/bin:$PATH; cd ~/server && {cmd}")
print(stdout.read().decode().strip())
s.close()
