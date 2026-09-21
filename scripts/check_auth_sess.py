import paramiko
import json

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('192.168.29.21', port=8022, username='u0_a208', password='anmol2005')

remote_script = '''
import app, config, sqlite3, json
conn = sqlite3.connect(config.DB_PATH)
conn.row_factory = sqlite3.Row
cur = conn.cursor()
cur.execute("SELECT user_id, student_code, expires_at, cookie_expires_at, credential_generation, last_refresh_at, last_refresh_status, updated_at FROM upes_auth_sessions WHERE user_id = 'admin'")
row = cur.fetchone()
print("UPES_AUTH_SESSIONS (SAFE):", dict(row) if row else None)
conn.close()
'''

sftp = ssh.open_sftp()
with sftp.file('/data/data/com.termux/files/home/server/test_auth_sess.py', 'w') as f:
    f.write(remote_script)
sftp.close()

stdin, stdout, stderr = ssh.exec_command('export PATH=/data/data/com.termux/files/usr/bin:$PATH; cd ~/server && python test_auth_sess.py && rm test_auth_sess.py')
print(stdout.read().decode('utf-8', errors='replace'))
err = stderr.read().decode('utf-8', errors='replace')
if err: print('STDERR:', err)
ssh.close()
