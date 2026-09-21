import paramiko

s = paramiko.SSHClient()
s.set_missing_host_key_policy(paramiko.AutoAddPolicy())
s.connect('192.168.29.21', port=8022, username='u0_a208', password='anmol2005', timeout=10)

cmd = """python3 -c "
import sqlite3
db = '/data/data/com.termux/files/home/storage_vault/nexus_vault.db'
conn = sqlite3.connect(db)
cur = conn.cursor()
cur.execute('SELECT user_id, password_hash, salt FROM users WHERE user_id = \\'admin\\'')
print('ROW:', cur.fetchone())
conn.close()
"
"""
stdin, stdout, stderr = s.exec_command(f"export PATH=/data/data/com.termux/files/usr/bin:$PATH; {cmd}")
print(stdout.read().decode().strip())
s.close()
