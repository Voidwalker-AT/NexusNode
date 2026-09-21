import paramiko

s = paramiko.SSHClient()
s.set_missing_host_key_policy(paramiko.AutoAddPolicy())
s.connect('192.168.29.21', port=8022, username='u0_a208', password='anmol2005', timeout=10)

cmd = "grep -i 'signed in' ~/nexus_logs/nexusnode/current || grep -i 'login' ~/nexus_logs/nexusnode/current | tail -n 20"
stdin, stdout, stderr = s.exec_command(cmd)
print("LOGS:", stdout.read().decode().strip())
s.close()
