import hashlib

# Let's check both legacy hashes
h1 = "0d119e4419ecf4d09bf344a08d17e6" # truncated in output
# Let's get full hashes from BG6
import paramiko
s = paramiko.SSHClient()
s.set_missing_host_key_policy(paramiko.AutoAddPolicy())
s.connect('192.168.29.21', port=8022, username='u0_a208', password='anmol2005', timeout=10)

cmd = """python3 -c "
import sqlite3, hashlib
db = '/data/data/com.termux/files/home/server/storage_vault/nexus_vault.db'
conn = sqlite3.connect(db)
cur = conn.cursor()
cur.execute('SELECT user_id, password_hash, salt FROM users WHERE user_id = \\'admin\\'')
row = cur.fetchone()
print('ROW:', row)
conn.close()
"
"""
stdin, stdout, stderr = s.exec_command(f"export PATH=/data/data/com.termux/files/usr/bin:$PATH; {cmd}")
print(stdout.read().decode().strip())
s.close()
