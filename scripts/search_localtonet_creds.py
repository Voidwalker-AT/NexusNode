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

exec_cmd("grep -ri 'localtonet' ~/.bash* ~/.profile /data/data/com.termux/files/home/server/.env* || true")
exec_cmd("grep -ri 'k09oezeyib' /data/data/com.termux/files/home/ || true")
exec_cmd("grep -ri 'localto.net' /data/data/com.termux/files/home/server/config.py || true")
s.close()
