import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('192.168.29.21', port=8022, username='u0_a208', password='anmol2005', timeout=10)
cmd = "cd ~/server && python3 -c \"import sqlite3, config; c=sqlite3.connect(config.DB_PATH); print(c.execute('SELECT user_id, role, is_disabled FROM users').fetchall())\""
stdin, stdout, stderr = ssh.exec_command(cmd)
out = stdout.read().decode().strip()
err = stderr.read().decode().strip()
print("Out:", out)
print("Err:", err)
ssh.close()
