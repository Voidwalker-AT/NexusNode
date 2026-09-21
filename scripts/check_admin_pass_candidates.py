import paramiko

s = paramiko.SSHClient()
s.set_missing_host_key_policy(paramiko.AutoAddPolicy())
s.connect('192.168.29.21', port=8022, username='u0_a208', password='anmol2005', timeout=10)

cmd = """python3 -c "
import sqlite3, config, app
conn = sqlite3.connect(config.DB_PATH)
cur = conn.cursor()
cur.execute('SELECT user_id, password_hash, salt FROM users WHERE user_id = \\'admin\\'')
row = cur.fetchone()
conn.close()

u, h, salt = row
candidates = [
    'Anmol@2005', 'anmol2005', 'Anmol2005', 'Nexus@1234', 'NexusNode@2026', 'NexusNode@2025',
    'Admin@2025', 'Admin@2026', 'Admin@12345', 'upes1234', 'UPES@1234', 'Admin@anmol',
    'anmol@2005', 'Anmol@1234', 'Anmol@123', 'admin@123', 'admin@1234', 'admin2025', 'admin2026',
    'NexusNode', 'nexusnode', 'nexusnode2026', 'Nexus@2026', 'Nexus@2025', 'Anmol@2024',
    'Admin#1234', 'Admin!1234', '12345678', 'password', 'adminpassword', 'root', 'toor',
    '500122941', 'UPES500122941', 'Sap@1234', 'Sap@123', 'Student@123', 'Student@1234'
]
matched = False
for c in candidates:
    valid, _ = app.verify_password(c, h, salt)
    if valid:
        print(f'MATCH for admin: {c}')
        matched = True
        break
if not matched:
    print('No match for admin among candidates')
"
"""

stdin, stdout, stderr = s.exec_command(f"export PATH=/data/data/com.termux/files/usr/bin:$PATH; cd ~/server && {cmd}")
print(stdout.read().decode().strip())
err = stderr.read().decode().strip()
if err:
    print("ERR:", err)
s.close()
