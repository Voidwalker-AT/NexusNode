import paramiko
import sys
import json
import requests

def inspect_bg6():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect('192.168.29.21', port=8022, username='u0_a208', password='anmol2005')

    def run(cmd):
        print(f"\n=== CMD: {cmd} ===")
        stdin, stdout, stderr = ssh.exec_command(f'export PATH=/data/data/com.termux/files/usr/bin:$PATH; cd ~/server && {cmd}')
        out = stdout.read().decode('utf-8', errors='replace').strip()
        err = stderr.read().decode('utf-8', errors='replace').strip()
        if out: print(out)
        if err: print('ERR:', err)
        return out, err

    # 1. Process check for tunnel/localtonet
    run("ps aux | grep -E 'localto|tunnel|cloudfla' | grep -v grep")
    
    # 2. Check runit services
    run("ls -la /data/data/com.termux/files/usr/var/service")
    
    # 3. Check for any localtonet config files or logs
    run("find /data/data/com.termux/files -name '*localtonet*' 2>/dev/null")
    run("find /data/data/com.termux/files -name '*localtotunnel*' 2>/dev/null")
    
    # 4. Check config.py and .env on BG6
    run("grep -i 'tunnel' config.py || true")
    run("grep -i 'localto' config.py || true")
    run("grep -i 'PUBLIC_ORIGIN' config.py || true")
    run("cat .env 2>/dev/null || echo 'no .env'")

    ssh.close()

if __name__ == '__main__':
    inspect_bg6()
