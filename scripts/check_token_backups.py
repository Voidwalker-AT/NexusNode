import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.WarningPolicy())
ssh.connect('192.168.29.21', port=8022, username='u0_a208', key_filename=os.environ.get("BG6_SSH_KEY", os.path.expanduser("~/.ssh/nexusnode_bg6_ed25519")) if os.path.exists(os.path.expanduser("~/.ssh/nexusnode_bg6_ed25519")) else None, password=os.environ.get("BG6_SSH_PASSWORD"), timeout=10)
cmd = """
import sqlite3, glob, os
for db in glob.glob('/data/data/com.termux/files/home/server/*.db*') + glob.glob('/data/data/com.termux/files/home/server/backups/*.db*'):
    try:
        c = sqlite3.connect(db)
        r = c.execute("SELECT user_id, calendar_id, connected_email, updated_at FROM google_oauth_tokens").fetchall()
        print(db, r)
        c.close()
    except Exception:
        pass
"""
stdin, stdout, stderr = ssh.exec_command("python3")
stdin.write(cmd)
stdin.channel.shutdown_write()
print(stdout.read().decode())
print(stderr.read().decode())
ssh.close()
