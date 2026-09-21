"""
NexusNode — Remote BG6 Database Migration 002
Safely uploads and executes migration 002 on the physical TECNO BG6 appliance.
"""

import sys
import os
import paramiko

def run_remote_migration():
    host = "192.168.29.21"
    port = 8022
    username = "u0_a208"
    password = os.environ.get("BG6_SSH_PASSWORD", "anmol2005")

    print(f"Connecting to BG6 appliance at {host}:{port}...")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, port=port, username=username, password=password, timeout=10)

    sftp = client.open_sftp()
    remote_base = "/data/data/com.termux/files/home/server"

    try:
        # 1. Ensure directories exist
        for d in ["migrations", "scripts"]:
            try:
                sftp.mkdir(f"{remote_base}/{d}")
            except Exception:
                pass

        # 2. Upload migration SQL and script
        print("Uploading migration files to BG6...")
        sftp.put("migrations/002_drop_legacy_ai_tables.sql", f"{remote_base}/migrations/002_drop_legacy_ai_tables.sql")
        sftp.put("scripts/migrate_database_002.py", f"{remote_base}/scripts/migrate_database_002.py")

        # 3. Execute migration on BG6
        print("Executing migration 002 on BG6 appliance...")
        cmd = f"cd {remote_base} && python scripts/migrate_database_002.py storage_vault/nexus_unified.db migrations/002_drop_legacy_ai_tables.sql"
        stdin, stdout, stderr = client.exec_command(cmd)

        out = stdout.read().decode("utf-8")
        err = stderr.read().decode("utf-8")
        exit_status = stdout.channel.recv_exit_status()

        print(f"Remote command exited with status: {exit_status}")
        print("STDOUT:\n" + out)
        if err:
            print("STDERR:\n" + err)

        if exit_status != 0:
            raise RuntimeError(f"Remote migration failed with exit status {exit_status}")

        print("=== Remote BG6 Migration 002 Successfully Applied! ===")
    finally:
        sftp.close()
        client.close()

if __name__ == "__main__":
    run_remote_migration()
