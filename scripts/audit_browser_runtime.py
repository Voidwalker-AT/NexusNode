"""
Inspect proot, alpine, chromium, and browser benchmarks on BG6.
"""
import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("192.168.29.21", port=8022, username="u0_a208", password="anmol2005", timeout=10)

script = """
echo "=== PROOT-DISTRO ==="
proot-distro list 2>&1

echo "=== WHICH CHROMIUM ==="
which chromium 2>&1
which proot 2>&1

echo "=== BROWSER DIRECTORY ==="
ls -la /data/data/com.termux/files/home/server/browser 2>&1

echo "=== BENCHMARK FILES ==="
find /data/data/com.termux/files/home -name "*benchmark*" -o -name "*phase41*" 2>/dev/null

echo "=== CHROMIUM IN PROOT ==="
proot-distro run alpine -- chromium --version 2>&1 || true
"""

stdin, stdout, stderr = ssh.exec_command('bash -u')
stdin.write(script)
stdin.channel.shutdown_write()
print(stdout.read().decode())
ssh.close()
