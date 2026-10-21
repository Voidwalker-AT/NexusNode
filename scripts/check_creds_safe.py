import paramiko
import json

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.WarningPolicy())
ssh.connect('192.168.29.21', port=8022, username='u0_a208', key_filename=os.environ.get("BG6_SSH_KEY", os.path.expanduser("~/.ssh/nexusnode_bg6_ed25519")) if os.path.exists(os.path.expanduser("~/.ssh/nexusnode_bg6_ed25519")) else None, password=os.environ.get("BG6_SSH_PASSWORD"), timeout=10)

cmd = """
export PATH=/data/data/com.termux/files/usr/bin:$PATH
cd ~/server
python3 -c "
import sqlite3
import config
from upes.credentials import UpesCredentialCrypto

conn = sqlite3.connect(config.UNIFIED_DB_FILE)
conn.row_factory = sqlite3.Row
rows = conn.execute('SELECT * FROM upes_user_credentials').fetchall()
for r in rows:
    dec = UpesCredentialCrypto.decrypt(r['encrypted_credentials'])
    uname = dec.get('username') if dec else None
    print('USER_ID:', r['user_id'], 'HINT:', r['username_hint'], 'DECRYPTED_USER:', uname)
"
"""

stdin, stdout, stderr = ssh.exec_command(cmd)
print(stdout.read().decode())
err = stderr.read().decode()
if err:
    print("STDERR:", err)
ssh.close()
