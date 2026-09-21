import paramiko
import os
import json

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("192.168.29.21", port=8022, username="u0_a208", password=os.environ.get("BG6_SSH_PASSWORD", "anmol2005"))

sftp = ssh.open_sftp()
sftp.put("scripts/bg6_check_upes.py", "/data/data/com.termux/files/home/server/scripts/bg6_check_upes.py")
sftp.close()

stdin, stdout, stderr = ssh.exec_command("python /data/data/com.termux/files/home/server/scripts/bg6_check_upes.py")
print(stdout.read().decode())
err = stderr.read().decode()
if err:
    print("ERR:", err)

ssh.close()
