"""
NexusNode Phase 4.2B - Read-Only BG6 Runtime Forensic Audit
Collects exact environment, process, ingress, and hardware metrics from TECNO BG6.
"""
import paramiko
import json

HOST = "192.168.29.21"
PORT = 8022
USER = "u0_a208"
PASS = "anmol2005"

def run_cmd(ssh, cmd):
    stdin, stdout, stderr = ssh.exec_command(cmd)
    return stdout.read().decode().strip(), stderr.read().decode().strip()

def main():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, port=PORT, username=USER, password=PASS, timeout=10)
    
    print("=== BG6 HARDWARE & OS ===")
    out, _ = run_cmd(ssh, "uname -a; getprop ro.build.version.release; getprop ro.product.model; getprop ro.product.brand; uptime")
    print(out)
    
    print("\n=== TERMUX & PYTHON ===")
    out, _ = run_cmd(ssh, "python --version; which python; echo PREFIX=$PREFIX")
    print(out)
    
    print("\n=== RUNIT SERVICES STATUS ===")
    out, _ = run_cmd(ssh, "sv status /data/data/com.termux/files/usr/var/service/*")
    print(out)
    
    print("\n=== ACTIVE PROCESSES (PYTHON / BROWSER / TUNNELS) ===")
    out, _ = run_cmd(ssh, "ps aux | grep -E 'python|chromium|cloudflared|localtonet' | grep -v grep")
    print(out)
    
    print("\n=== NETWORK LISTENERS (PORTS) ===")
    out, _ = run_cmd(ssh, "netstat -tuln 2>/dev/null || ss -tuln 2>/dev/null || lsof -i -P -n | grep LISTEN")
    print(out)
    
    print("\n=== MEMORY & STORAGE TELEMETRY ===")
    out, _ = run_cmd(ssh, "free -m; df -h /data/data/com.termux/files/home")
    print(out)
    
    print("\n=== CLOUDFLARED INGRESS LOGS ===")
    out, _ = run_cmd(ssh, "tail -n 25 /data/data/com.termux/files/home/cloudflared.log 2>/dev/null || tail -n 25 /data/data/com.termux/files/home/nexus_logs/cloudflared/current 2>/dev/null")
    print(out)
    
    print("\n=== LOCALTONET INGRESS LOGS ===")
    out, _ = run_cmd(ssh, "tail -n 25 /data/data/com.termux/files/home/localtonet.log 2>/dev/null || tail -n 25 /data/data/com.termux/files/home/nexus_logs/localtonet/current 2>/dev/null")
    print(out)
    
    print("\n=== PROOT ALPINE & CHROMIUM RUNTIME ===")
    out, _ = run_cmd(ssh, "proot -r /data/data/com.termux/files/home/browser/alpine-rootfs -b /dev -b /proc -b /sys /usr/bin/chromium --version 2>/dev/null || proot-distro list 2>/dev/null || ls -la /data/data/com.termux/files/home/browser")
    print(out)

    print("\n=== STORED BROWSER BENCHMARK ARTIFACTS ===")
    out, _ = run_cmd(ssh, "ls -lh /data/data/com.termux/files/home/server/scratch_phase41b_results.json /data/data/com.termux/files/home/server/storage_vault/artifacts/benchmarks/* 2>/dev/null || true")
    print(out)

    ssh.close()

if __name__ == "__main__":
    main()
