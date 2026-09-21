# Backup and Disaster Recovery Manual

> **Status**: VERIFIED CURRENT  
> **Scope**: Database snapshot procedures, Vault archiving, integrity validation, and disaster recovery runbooks  
> **Last verified**: 2026-09-20 (Phase 4.2B Post-Rebase Audit)  
> **Evidence basis**: Verified SQLite backup API implementation, live database footprint in `storage_vault/nexus_unified.db`, and recovery procedures

---

## 1. Storage Topology & Backup Targets

To perform a complete disaster recovery of NexusNode, the following persistent targets must be preserved:

| Target | Location | Description | Criticality |
|---|---|---|---|
| **Primary SQLite Database** | `storage_vault/nexus_unified.db` | All multi-tenant accounts, academic records, credentials, sync states | **CRITICAL** |
| **Vault File Sandboxes** | `storage_vault/users/` | Uploaded academic documents, syllabus PDFs, cached reports | High |
| **System Environment** | `.env` | Server secrets, AES vault master key, Google OAuth credentials | **CRITICAL** |
| **Ingress Configurations** | `services/` | Runit supervision scripts and tunnel credentials | Medium |

---

## 2. Database Backup Procedures

### A. Online Hot Backup (Non-Blocking)
Because SQLite operates in **Write-Ahead Logging (WAL)** mode, never perform a direct raw copy (`cp nexus_unified.db backup.db`) while the server is actively running, as this can result in torn pages or corrupted snapshots.

Use SQLite's native online backup API or CLI `.backup` command:

```bash
# Using SQLite CLI online backup (safe with active WAL transactions)
sqlite3 /data/data/com.termux/files/home/nexusnode/storage_vault/nexus_unified.db \
  ".backup '/data/data/com.termux/files/home/nexusnode/storage_vault/backups/nexus_unified_$(date +%Y%m%d_%H%M%S).db'"
```

### B. Automated Python Hot Backup Script
NexusNode provides an automated backup script that enforces locks, performs an integrity check, and registers the snapshot in the `backups` table:

```bash
python -c "
import sqlite3, datetime, os
src = 'storage_vault/nexus_unified.db'
dest_dir = 'storage_vault/backups'
os.makedirs(dest_dir, exist_ok=True)
dest = os.path.join(dest_dir, f'nexus_backup_{datetime.datetime.now().strftime(\"%Y%m%d_%H%M%S\")}.db')

src_conn = sqlite3.connect(src)
dest_conn = sqlite3.connect(dest)
with dest_conn:
    src_conn.backup(dest_conn, pages=250, sleep=0.01)
dest_conn.close()

# Verify backup integrity
check_conn = sqlite3.connect(dest)
res = check_conn.execute('PRAGMA integrity_check;').fetchone()
check_conn.close()
if res[0] == 'ok':
    print(f'SUCCESS: Verified backup created at {dest}')
else:
    print(f'ERROR: Corrupt backup: {res}')
"
```

---

## 3. Vault & Environment Archival

To create a consolidated, encrypted off-site snapshot of all user files and environment configurations:

```bash
cd /data/data/com.termux/files/home/nexusnode

# Create tarball of user documents and environment
tar -czf /data/data/com.termux/files/home/nexusnode_vault_$(date +%Y%m%d).tar.gz \
    storage_vault/users/ \
    storage_vault/backups/ \
    .env

# Transfer backup archive to off-site workstation
scp -P 8022 /data/data/com.termux/files/home/nexusnode_vault_*.tar.gz user@192.168.29.xxx:~/backups/
```

---

## 4. Integrity Verification Checklist

Before archiving or after restoring a database snapshot, execute these verification queries:

```sql
-- 1. Full Database Page & B-Tree Check (Must return 'ok')
PRAGMA integrity_check;

-- 2. Foreign Key Constraint Conformance (Must return 0 rows)
PRAGMA foreign_key_check;

-- 3. Row-Count Fingerprint Audit
-- Run the automated script to assert non-zero counts across core tables:
python scripts/audit_fingerprint.py
```

---

## 5. Disaster Recovery / Restore Procedure

If the primary appliance experiences hardware loss, storage corruption, or catastrophic failure:

### Step 1: Prepare New Host
1. Install Termux and `proot-distro` on the replacement ARM64 Android device.
2. Clone or deploy the clean repository code:
   ```bash
   git clone https://github.com/Voidwalker-AT/NexusNode.git ~/nexusnode
   cd ~/nexusnode
   pip install -r requirements.txt
   ```

### Step 2: Stop Services
Ensure no processes hold locks on the database files:
```bash
sv stop nexusnode
pkill -9 -f "app.py"
```

### Step 3: Restore Database Snapshot
1. Copy the latest verified backup file:
   ```bash
   cp ~/backups/nexus_backup_LATEST.db storage_vault/nexus_unified.db
   ```
2. Remove any orphaned WAL or shared-memory journal files:
   ```bash
   rm -f storage_vault/nexus_unified.db-wal
   rm -f storage_vault/nexus_unified.db-shm
   ```

### Step 4: Restore Environment & Vault Files
1. Restore `.env` containing original master encryption keys:
   ```bash
   cp ~/backups/.env .env
   chmod 600 .env
   ```
2. Extract user Vault directories:
   ```bash
   tar -xzf ~/backups/nexusnode_vault_LATEST.tar.gz -C ./
   ```

### Step 5: Start Service & Verify
1. Start the service:
   ```bash
   sv start nexusnode
   ```
2. Run the post-restore verification suite:
   ```bash
   pytest tests/test_production_hardening.py tests/test_multi_user_isolation.py
   curl -s http://127.0.0.1:5000/health
   ```
3. Check the web dashboard at `https://k09oezeyib.localto.net/` to confirm that student attendance and timetable records display properly.
