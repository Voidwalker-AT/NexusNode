import paramiko

s = paramiko.SSHClient()
s.set_missing_host_key_policy(paramiko.AutoAddPolicy())
s.connect('192.168.29.21', port=8022, username='u0_a208', password='anmol2005', timeout=10)

cmd = """python3 -c "
import sqlite3, config, app
conn = sqlite3.connect(config.DB_PATH)
cur = conn.cursor()
cur.execute('SELECT user_id, password_hash, salt FROM users')
rows = cur.fetchall()
conn.close()

candidates = ['Admin@1234', 'admin', 'anmol2005', 'nexusnode', 'Admin@123', 'admin123', 'password', 'password123', 'Papa@1234']
for u, h, salt in rows:
    print('USER:', u)
    matched = False
    for c in candidates:
        valid, _ = app.verify_password(c, h, salt)
        if valid:
            print(f'  -> MATCH for {u}: {c}')
            matched = True
            break
    if not matched:
        print(f'  -> No match in candidates for {u}')
"
"""

stdin, stdout, stderr = s.exec_command(f"export PATH=/data/data/com.termux/files/usr/bin:$PATH; cd ~/server && {cmd}")
print(stdout.read().decode().strip())
err = stderr.read().decode().strip()
if err:
    print("ERR:", err)
s.close()
