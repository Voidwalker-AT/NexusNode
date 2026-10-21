# NexusNode Appliance Recovery & Deployment Runbook

> **Target Appliance**: TECNO BG6 (`192.168.29.21`)  
> **Development Host**: Windows 11 x64  
> **Date**: 2026-10-21 (Phase 0 Reconnaissance)

---

## 1. Quick Emergency Recovery (When Phone Reboots or Services Stop)

If the server becomes unreachable after an Android reboot or process kill:

### Step 1: Ensure USB Debugging is Connected
Connect the TECNO BG6 via USB to the development PC. Verify with:
```powershell
& "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe" devices -l
```

### Step 2: Relaunch Termux & Acquire WakeLock
Execute via ADB:
```powershell
$adb = "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe"
$serial = "109973141A030946"

# 1. Bring Termux to foreground
& $adb -s $serial shell "am start -n com.termux/.app.TermuxActivity"

# 2. Acquire Android WakeLock
& $adb -s $serial shell "run-as com.termux /data/data/com.termux/files/usr/bin/termux-wake-lock"

# 3. Start Runit Supervisor Daemon
$script = 'export PREFIX=/data/data/com.termux/files/usr; export PATH=$PREFIX/bin:$PATH; export SVDIR=$PREFIX/var/service; service-daemon start'
& $adb -s $serial shell "run-as com.termux /data/data/com.termux/files/usr/bin/bash -c '$script'"
```

### Step 3: Verify Services
```powershell
& $adb -s $serial shell "run-as com.termux /data/data/com.termux/files/usr/bin/sv status /data/data/com.termux/files/usr/var/service/*"
```
Ensure `nexusnode`, `sshd`, and `localtonet` report `run: (pid ...)`.

---

## 2. Safe Deployment Protocol (Windows to BG6)

To sync tested, uncommitted bug fixes from Windows to the physical BG6 server without risking database contamination or loss of working state:

### Step 1: Always Execute Precautionary Database Backup on BG6
```bash
ssh -p 8022 u0_a208@192.168.29.21 "TIMESTAMP=\$(date +%Y%m%d_%H%M%S) && mkdir -p ~/server_backup_\$TIMESTAMP/db_precautionary && cp ~/server/storage_vault/nexus_unified.db* ~/server_backup_\$TIMESTAMP/db_precautionary/ && echo 'BACKUP COMPLETED'"
```

### Step 2: Use `deploy_to_bg6_ssh.py`
The repository includes a dedicated SFTP synchronization script:
```powershell
python deploy_to_bg6_ssh.py 192.168.29.21 8022 u0_a208
```
This script:
1. Calculates file SHA256 checksums locally and remotely.
2. Excludes SQLite database files (`.db`, `.db-wal`), logs, and caches.
3. Automatically restarts the `nexusnode` runit service (`sv restart nexusnode`).

### Step 3: Verify Post-Deployment Health
```powershell
Invoke-RestMethod -Uri "http://192.168.29.21:5000/api/health"
```
