import paramiko

s = paramiko.SSHClient()
s.set_missing_host_key_policy(paramiko.WarningPolicy())
s.connect('192.168.29.21', port=8022, username='u0_a208', key_filename=os.environ.get("BG6_SSH_KEY", os.path.expanduser("~/.ssh/nexusnode_bg6_ed25519")) if os.path.exists(os.path.expanduser("~/.ssh/nexusnode_bg6_ed25519")) else None, password=os.environ.get("BG6_SSH_PASSWORD"), timeout=5)

cmd = """python -c "
import sqlite3
c = sqlite3.connect('/data/data/com.termux/files/home/server/users.db')
cur = c.cursor()
cur.execute('SELECT user_id, role, password_hash, salt FROM users WHERE user_id = \\'admin\\'')
print(cur.fetchone())
"
"""
stdin, stdout, stderr = s.exec_command(f"export PATH=/data/data/com.termux/files/usr/bin:$PATH; {cmd}")
print("Admin User Row:", stdout.read().decode().strip())
s.close()
