import paramiko
import json
import os
import sys

def audit_stage0():
    host = "192.168.29.21"
    port = 8022
    username = "u0_a208"
    password = os.environ.get("BG6_SSH_PASSWORD", "anmol2005")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, port=port, username=username, password=password, timeout=10)

    # 1. Runit status & process
    stdin, stdout, stderr = client.exec_command("sv status /data/data/com.termux/files/usr/var/service/nexusnode; ps -ef | grep waitress | grep -v grep")
    runit_status = stdout.read().decode().strip()
    runit_err = stderr.read().decode().strip()

    # 2. /api/health
    stdin, stdout, stderr = client.exec_command("curl -s http://127.0.0.1:5000/api/health")
    health = stdout.read().decode().strip()

    # 3. RAM / MemAvailable
    stdin, stdout, stderr = client.exec_command("cat /proc/meminfo | grep -E 'MemTotal|MemFree|MemAvailable'")
    meminfo = stdout.read().decode().strip()

    # 4. SQLite integrity
    py_cmd = (
        "python3 -c \""
        "import sqlite3; "
        "conn = sqlite3.connect('/data/data/com.termux/files/home/server/storage_vault/nexus_unified.db'); "
        "cur = conn.cursor(); "
        "cur.execute('PRAGMA integrity_check'); "
        "integ = cur.fetchone()[0]; "
        "cur.execute('SELECT name FROM sqlite_master WHERE type=\\'table\\' ORDER BY name'); "
        "tbls = [r[0] for r in cur.fetchall()]; "
        "cur.execute('PRAGMA table_info(users)'); "
        "u_cols = cur.fetchall(); "
        "cur.execute('PRAGMA table_info(background_tasks)'); "
        "bt_cols = cur.fetchall(); "
        "cur.execute('SELECT * FROM users'); "
        "users = cur.fetchall(); "
        "print('INTEGRITY:', integ); "
        "print('TABLE_COUNT:', len(tbls)); "
        "print('USERS_COLS:', u_cols); "
        "print('BG_TASKS_COLS:', bt_cols); "
        "print('USERS_COUNT:', len(users)); "
        "conn.close()\""
    )
    stdin, stdout, stderr = client.exec_command(py_cmd)
    db_status = stdout.read().decode().strip()
    db_err = stderr.read().decode().strip()

    # 5. LocalToNet / public ingress
    stdin, stdout, stderr = client.exec_command("pgrep -a -f localtonet")
    l2n = stdout.read().decode().strip()

    # 6. Chromium process count
    stdin, stdout, stderr = client.exec_command("pgrep -c -f '[c]hromium'")
    chromium_cnt = stdout.read().decode().strip()

    # 7. Scheduler state, last run, next run
    sched_py = """
import sqlite3, json, time
conn = sqlite3.connect('/data/data/com.termux/files/home/server/storage_vault/nexus_unified.db')
cur = conn.cursor()
cur.execute('SELECT id, name, job_type, interval_seconds, enabled, last_run, next_run, last_status FROM scheduled_jobs')
jobs = cur.fetchall()
print('SCHEDULED_JOBS:')
for j in jobs:
    lr = time.ctime(j[5]) if j[5] else 'Never'
    nr = time.ctime(j[6]) if j[6] else 'Never'
    print(f'  ID: {j[0]}, Name: {j[1]}, Type: {j[2]}, Interval: {j[3]}s, Enabled: {j[4]}, LastRun: {lr}, NextRun: {nr}, Status: {j[7]}')
cur.execute('SELECT id, type, status, error, updated_at, logs FROM background_tasks WHERE type=\\'timetable_sync\\' ORDER BY updated_at DESC LIMIT 3')
sync_tasks = cur.fetchall()
print('LAST_TIMETABLE_SYNC_TASKS:')
for st in sync_tasks:
    print(f'  ID: {st[0]}, Type: {st[1]}, Status: {st[2]}, Updated: {time.ctime(st[4])}, Logs: {st[5]}')
conn.close()
"""
    stdin, stdout, stderr = client.exec_command("python3")
    stdin.write(sched_py)
    stdin.channel.shutdown_write()
    sched_info = stdout.read().decode().strip()
    sched_err = stderr.read().decode().strip()

    # 8. Check process table for nexusnode/waitress/python
    stdin, stdout, stderr = client.exec_command("ps -ef | grep -E 'python|waitress|sv|runsv' | grep -v grep")
    procs = stdout.read().decode().strip()

    # 9. Check sv status with proper path or SVDIR
    stdin, stdout, stderr = client.exec_command("echo $SVDIR; ls -la $PREFIX/var/service")
    sv_dir = stdout.read().decode().strip()

    print("=== BG6 STAGE 0 TRUTH AUDIT ===")
    print("--- 1. Runit & Processes ---")
    print("RUNIT STDOUT:", runit_status)
    if runit_err:
        print("RUNIT STDERR:", runit_err)
    print("PROCS:\n", procs)
    print("\n--- 2. Health Endpoint ---")
    print(health)
    print("\n--- 3. Memory Telemetry ---")
    print(meminfo)
    print("\n--- 4. Database Integrity & Tables ---")
    print("STDOUT:", db_status)
    if db_err:
        print("STDERR:", db_err)
    print("\n--- 5. Ingress / LocalToNet ---")
    print(l2n)
    print("\n--- 6. Chromium Process Count ---")
    print("Chromium count:", chromium_cnt)
    print("\n--- 7. Scheduler Tasks & Settings ---")
    print("STDOUT:", sched_info)
    if sched_err:
        print("STDERR:", sched_err)
    print("\n--- 8. Service Directory ($PREFIX/var/service) ---")
    print(sv_dir)

    client.close()

if __name__ == "__main__":
    audit_stage0()
