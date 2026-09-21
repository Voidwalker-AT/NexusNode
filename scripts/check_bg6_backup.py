import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('192.168.29.21', port=8022, username='u0_a208', password='anmol2005')

cmd = 'python -c "import sqlite3, hashlib; p = \'/data/data/com.termux/files/home/server/storage_vault/backups/nexus_unified_pre42c_remote.db\'; c = sqlite3.connect(p); print(\'INTEGRITY:\', c.execute(\'PRAGMA integrity_check;\').fetchone()[0]); c.close(); print(\'SHA256:\', hashlib.sha256(open(p, \'rb\').read()).hexdigest())"'
stdin, stdout, stderr = ssh.exec_command(cmd)
print(stdout.read().decode().strip())
print(stderr.read().decode().strip())
ssh.close()
