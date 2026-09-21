import paramiko

s = paramiko.SSHClient()
s.set_missing_host_key_policy(paramiko.AutoAddPolicy())
s.connect('192.168.29.21', port=8022, username='u0_a208', password='anmol2005', timeout=10)

cmd = """python3 -c "
import sqlite3, config
conn = sqlite3.connect(config.DB_PATH)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

cur.execute('SELECT DISTINCT user_id FROM user_timetables')
print('user_timetables:', [r[0] for r in cur.fetchall()])

cur.execute('SELECT DISTINCT user_id FROM official_attendance_summaries')
print('official_attendance_summaries:', [r[0] for r in cur.fetchall()])

cur.execute('SELECT DISTINCT user_id FROM academic_sessions')
print('academic_sessions:', [r[0] for r in cur.fetchall()])

cur.execute('SELECT DISTINCT user_id FROM academic_results')
print('academic_results:', [r[0] for r in cur.fetchall()])

conn.close()
"
"""

stdin, stdout, stderr = s.exec_command(f"export PATH=/data/data/com.termux/files/usr/bin:$PATH; cd ~/server && {cmd}")
print(stdout.read().decode().strip())
s.close()
