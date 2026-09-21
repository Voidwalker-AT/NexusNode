import paramiko

s = paramiko.SSHClient()
s.set_missing_host_key_policy(paramiko.AutoAddPolicy())
s.connect('192.168.29.21', port=8022, username='u0_a208', password='anmol2005', timeout=10)

cmd = """python3 -c "
import glob, sqlite3

for db in glob.glob('/data/data/com.termux/files/home/**/*.db', recursive=True):
    try:
        conn = sqlite3.connect(db)
        cur = conn.cursor()
        cur.execute('SELECT user_id, password_hash, salt FROM users WHERE user_id = \\'admin\\'')
        row = cur.fetchone()
        if row:
            print(f'{db} -> {row[0]}: {row[1][:30]}... salt={row[2]}')
        conn.close()
    except Exception:
        pass
"
"""

stdin, stdout, stderr = s.exec_command(f"export PATH=/data/data/com.termux/files/usr/bin:$PATH; {cmd}")
print(stdout.read().decode().strip())
s.close()
