import paramiko

s = paramiko.SSHClient()
s.set_missing_host_key_policy(paramiko.WarningPolicy())
s.connect('192.168.29.21', port=8022, username='u0_a208', key_filename=os.environ.get("BG6_SSH_KEY", os.path.expanduser("~/.ssh/nexusnode_bg6_ed25519")) if os.path.exists(os.path.expanduser("~/.ssh/nexusnode_bg6_ed25519")) else None, password=os.environ.get("BG6_SSH_PASSWORD"), timeout=10)

cmd = "grep -i 'signed in' ~/nexus_logs/nexusnode/current || grep -i 'login' ~/nexus_logs/nexusnode/current | tail -n 20"
stdin, stdout, stderr = s.exec_command(cmd)
print("LOGS:", stdout.read().decode().strip())
s.close()
