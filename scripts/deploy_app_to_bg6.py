import paramiko
import time

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('192.168.29.21', port=8022, username='u0_a208', password='anmol2005', timeout=15)

# 1. SFTP app.py
sftp = ssh.open_sftp()
print("Uploading app.py to BG6...")
sftp.put(r"E:\Workspace\Active\server\app.py", "/data/data/com.termux/files/home/server/app.py")
sftp.close()
print("Uploaded app.py successfully.")

# 2. Syntax check on BG6
stdin, stdout, stderr = ssh.exec_command("export PATH=/data/data/com.termux/files/usr/bin:$PATH; cd ~/server && python3 -c 'import app; print(\"BG6 App Import OK\")'")
out = stdout.read().decode().strip()
err = stderr.read().decode().strip()
print("Syntax Check:", out)
if err:
    print("Syntax Check Err:", err)
assert "BG6 App Import OK" in out, "BG6 syntax check failed!"

# 3. Restart nexusnode service
print("Restarting nexusnode service...")
stdin, stdout, stderr = ssh.exec_command("export PATH=/data/data/com.termux/files/usr/bin:$PATH; SVDIR=/data/data/com.termux/files/usr/var/service sv restart nexusnode")
print("Restart output:", stdout.read().decode().strip())

# 4. Wait 4s and check status
time.sleep(4)
stdin, stdout, stderr = ssh.exec_command("export PATH=/data/data/com.termux/files/usr/bin:$PATH; SVDIR=/data/data/com.termux/files/usr/var/service sv status nexusnode")
stat = stdout.read().decode().strip()
print("Service status:", stat)
assert "run: nexusnode:" in stat, f"nexusnode service not running: {stat}"

ssh.close()
print("Deployment and verification complete!")
