import paramiko

s = paramiko.SSHClient()
s.set_missing_host_key_policy(paramiko.AutoAddPolicy())
s.connect('192.168.29.21', port=8022, username='u0_a208', password='anmol2005', timeout=10)

cmd = "cat ~/.bash_history | tail -n 50"
stdin, stdout, stderr = s.exec_command(cmd)
print("BASH HISTORY:\n", stdout.read().decode().strip())
s.close()
