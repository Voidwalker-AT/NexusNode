import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('192.168.29.21', port=8022, username='u0_a208', password='anmol2005', timeout=15)

def run(cmd):
    print(f"\n=== {cmd} ===")
    stdin, stdout, stderr = ssh.exec_command(f"export PATH=/data/data/com.termux/files/usr/bin:$PATH; {cmd}")
    out = stdout.read().decode('utf-8', errors='replace').strip()
    err = stderr.read().decode('utf-8', errors='replace').strip()
    if out:
        print(out)
    if err:
        print("STDERR:", err)
    return out

run("ls -la /data/data/com.termux/files/home/nexus_logs/localtonet")
run("tail -n 60 /data/data/com.termux/files/home/nexus_logs/localtonet/current")
run("which localtonet")
run("cat $(which localtonet)")
run("ls -la ~/.localtonet")
run("find /data/data/com.termux/files/home -name '*localtonet*' -maxdepth 3 2>/dev/null")
run("find /data/data/com.termux/files/usr -name '*localtonet*' -maxdepth 4 2>/dev/null")
ssh.close()
