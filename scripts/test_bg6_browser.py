import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.WarningPolicy())
ssh.connect('192.168.29.21', port=8022, username='u0_a208', key_filename=os.environ.get("BG6_SSH_KEY", os.path.expanduser("~/.ssh/nexusnode_bg6_ed25519")) if os.path.exists(os.path.expanduser("~/.ssh/nexusnode_bg6_ed25519")) else None, password=os.environ.get("BG6_SSH_PASSWORD"), timeout=10)

script = """
export PATH=/data/data/com.termux/files/usr/bin:$PATH
cd ~/server
python3 -c "
import sys
try:
    from browser.bg6_cdp import BG6EphemeralCDPProvider
    p = BG6EphemeralCDPProvider()
    print('HEALTH:', p.get_health())
except Exception as e:
    print('BG6EphemeralCDPProvider ERROR:', e)

import subprocess
res = subprocess.run(['proot-distro', 'run', 'alpine', '--', 'chromium', '--version'], capture_output=True, text=True)
print('PROOT CHROMIUM:', res.returncode, res.stdout, res.stderr)
"
"""

stdin, stdout, stderr = ssh.exec_command('bash -u')
stdin.write(script)
stdin.channel.shutdown_write()
print(stdout.read().decode())
print('STDERR:', stderr.read().decode())
ssh.close()
