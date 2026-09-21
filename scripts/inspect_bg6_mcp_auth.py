import paramiko

s = paramiko.SSHClient()
s.set_missing_host_key_policy(paramiko.AutoAddPolicy())
s.connect('192.168.29.21', port=8022, username='u0_a208', password='anmol2005', timeout=5)

cmd = """python -c "
import sqlite3, config
c = sqlite3.connect(config.DB_PATH)
cur = c.cursor()
cur.execute('PRAGMA table_info(agent_tokens)')
print('Columns:', [col[1] for col in cur.fetchall()])
cur.execute('SELECT * FROM agent_tokens LIMIT 5')
print('Rows:', cur.fetchall())
"
"""
stdin, stdout, stderr = s.exec_command(f"export PATH=/data/data/com.termux/files/usr/bin:$PATH; cd ~/server && {cmd}")
print(stdout.read().decode())
err = stderr.read().decode()
if err:
    print("ERR:", err)
s.close()
