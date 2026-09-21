import paramiko

s = paramiko.SSHClient()
s.set_missing_host_key_policy(paramiko.AutoAddPolicy())
s.connect('192.168.29.21', port=8022, username='u0_a208', password='anmol2005', timeout=10)

cmd = """python3 -c "
import sqlite3, config
conn = sqlite3.connect(config.DB_PATH)
cur = conn.cursor()
cur.execute('SELECT client_id, client_name, redirect_uris, created_at FROM oauth_clients')
print('CLIENTS:', cur.fetchall())
conn.close()
"
"""
stdin, stdout, stderr = s.exec_command(f"export PATH=/data/data/com.termux/files/usr/bin:$PATH; cd ~/server && {cmd}")
out = stdout.read().decode().strip()
err = stderr.read().decode().strip()
print('OUT:', out)
if err: print('ERR:', err)
s.close()
