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

exec_cmd("ls -la /data/data/com.termux/files/home/localtonet/localtonet_Url_3jc4cffrzmr1haqrradcvp0prmbj3ay1")
exec_cmd("find /data/data/com.termux/files/home/localtonet/ -type f")
exec_cmd("cat /data/data/com.termux/files/home/localtonet/localtonet_Url_3jc4cffrzmr1haqrradcvp0prmbj3ay1/* || true")
exec_cmd("command -v cloudflared || true")
exec_cmd("command -v ngrok || true")
s.close()
