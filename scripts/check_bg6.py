import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('192.168.29.21', port=8022, username='u0_a208', password='anmol2005')

cmd = 'python -c "import pypdf; print(\'pypdf version:\', pypdf.__version__)"'
stdin, stdout, stderr = ssh.exec_command(cmd)
print("STDOUT:", stdout.read().decode().strip())
print("STDERR:", stderr.read().decode().strip())

ssh.close()
