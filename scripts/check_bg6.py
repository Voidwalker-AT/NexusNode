import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.WarningPolicy())
ssh.connect('192.168.29.21', port=8022, username='u0_a208', key_filename=os.environ.get("BG6_SSH_KEY", os.path.expanduser("~/.ssh/nexusnode_bg6_ed25519")) if os.path.exists(os.path.expanduser("~/.ssh/nexusnode_bg6_ed25519")) else None, password=os.environ.get("BG6_SSH_PASSWORD"))

cmd = 'python -c "import pypdf; print(\'pypdf version:\', pypdf.__version__)"'
stdin, stdout, stderr = ssh.exec_command(cmd)
print("STDOUT:", stdout.read().decode().strip())
print("STDERR:", stderr.read().decode().strip())

ssh.close()
