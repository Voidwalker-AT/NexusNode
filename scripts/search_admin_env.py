import paramiko

s = paramiko.SSHClient()
s.set_missing_host_key_policy(paramiko.AutoAddPolicy())
s.connect('192.168.29.21', port=8022, username='u0_a208', password='anmol2005', timeout=10)

cmd = """
grep -rn "NEXUS_ADMIN_PASSWORD" ~/ /data/data/com.termux/files/usr/etc/ 2>/dev/null || true
grep -rn "admin" ~/.config/ ~/.bashrc ~/.profile ~/.env ~/server/.env 2>/dev/null || true
"""

stdin, stdout, stderr = s.exec_command(f"export PATH=/data/data/com.termux/files/usr/bin:$PATH; {cmd}")
print("SEARCH ENV:", stdout.read().decode().strip())
s.close()
