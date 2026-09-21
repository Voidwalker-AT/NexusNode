import paramiko
import os

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("192.168.29.21", port=8022, username="u0_a208", password=os.environ.get("BG6_SSH_PASSWORD", "anmol2005"))

stdin, stdout, stderr = ssh.exec_command("pgrep -c -f '[c]hromium' || echo 0; pgrep -c -f '[c]hrome' || echo 0")
print("PGREP COUNT:")
print(stdout.read().decode())

ssh.close()
