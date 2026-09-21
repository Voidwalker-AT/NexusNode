import paramiko
import time
import os

HOST = '192.168.29.21'
PORT = 8022
USER = 'u0_a208'
PASS = 'anmol2005'
REMOTE_BASE = '/data/data/com.termux/files/home/server'
LOCAL_BASE = r'E:\Workspace\Active\server'

FILES_TO_UPLOAD = [
    ("agent/semantic_facade.py", "agent/semantic_facade.py"),
    ("upes/router.py", "upes/router.py"),
    ("upes/results.py", "upes/results.py"),
    ("app.py", "app.py")
]

def main():
    print(f"Connecting to BG6 at {HOST}:{PORT}...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, port=PORT, username=USER, password=PASS, timeout=15)

    sftp = ssh.open_sftp()
    for rel_local, rel_remote in FILES_TO_UPLOAD:
        loc_path = os.path.join(LOCAL_BASE, rel_local.replace('/', os.sep))
        rem_path = f"{REMOTE_BASE}/{rel_remote}"
        print(f"Uploading {rel_local} -> {rem_path}...")
        sftp.put(loc_path, rem_path)
    sftp.close()
    print("Files uploaded successfully.")

    # Syntax and import check on BG6
    print("Running syntax and import verification on BG6...")
    cmd_check = "export PATH=/data/data/com.termux/files/usr/bin:$PATH; cd ~/server && python3 -c 'import app; from agent.semantic_facade import SemanticMcpFacade; from upes.router import UpesExecutionRouter; print(\"BG6_IMPORTS_OK\")'"
    stdin, stdout, stderr = ssh.exec_command(cmd_check)
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    print("Output:", out)
    if err:
        print("Stderr:", err)
    assert "BG6_IMPORTS_OK" in out, f"BG6 syntax check failed: {err}"

    # Restart nexusnode service
    print("Restarting nexusnode runit service...")
    cmd_restart = "export PATH=/data/data/com.termux/files/usr/bin:$PATH; SVDIR=/data/data/com.termux/files/usr/var/service sv restart nexusnode"
    stdin, stdout, stderr = ssh.exec_command(cmd_restart)
    print("Restart:", stdout.read().decode().strip())

    time.sleep(3)

    # Status check
    cmd_status = "export PATH=/data/data/com.termux/files/usr/bin:$PATH; SVDIR=/data/data/com.termux/files/usr/var/service sv status nexusnode"
    stdin, stdout, stderr = ssh.exec_command(cmd_status)
    print("Service Status:", stdout.read().decode().strip())
    ssh.close()
    print("BG6 deployment complete.")

if __name__ == "__main__":
    main()
