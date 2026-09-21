import paramiko
import sys

sys.stdout.reconfigure(encoding='utf-8')

s = paramiko.SSHClient()
s.set_missing_host_key_policy(paramiko.AutoAddPolicy())
s.connect('192.168.29.21', port=8022, username='u0_a208', password='anmol2005', timeout=5)

def exec_cmd(cmd):
    print(f"\n=== {cmd} ===", flush=True)
    stdin, stdout, stderr = s.exec_command(f"export PATH=/data/data/com.termux/files/usr/bin:$PATH; {cmd}", timeout=10)
    out = stdout.read().decode('utf-8', errors='replace').strip()
    err = stderr.read().decode('utf-8', errors='replace').strip()
    if out:
        print(out, flush=True)
    if err:
        print("ERR:", err, flush=True)

exec_cmd("ls -la ~/.config/ngrok || true")
exec_cmd("cat ~/.config/ngrok/ngrok.yml || true")
exec_cmd("ls -la ~/.cloudflared || true")
exec_cmd("cat ~/.cloudflared/config.yml || true")
exec_cmd("ls -la /data/data/com.termux/files/usr/var/service")
s.close()
