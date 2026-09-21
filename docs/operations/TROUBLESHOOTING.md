# Operational Troubleshooting Guide

> **Status**: VERIFIED CURRENT  
> **Scope**: Diagnostic trees, failure scenarios, root cause analysis, and resolution procedures  
> **Last verified**: 2026-09-20 (Phase 4.2B Post-Rebase Audit)  
> **Evidence basis**: Historical failure signatures, runtime guardrails, and production runbooks on TECNO BG6

---

## 1. Quick Diagnostic Decision Tree

```
Issue Observed
│
├── Ingress / Tunnel Unreachable (502 / Connection Refused)
│   └── See Section 2: Ingress & Network Troubleshooting
│
├── Ephemeral Browser Fails or Rejects Launch
│   ├── Error: "ADMISSION_DENIED: MemAvailable < 500 MB" -> See Section 3.1
│   ├── Error: "RESOURCE_BUSY: Concurrency lock held" -> See Section 3.2
│   └── Browser hangs or crashes -> See Section 3.3
│
├── Database Errors ("database is locked" or Slow Queries)
│   └── See Section 4: Database Contention & Lockout
│
├── Academic Sync Failures (Attendance / LMS not updating)
│   └── See Section 5: Portal Authentication & Scraping
│
└── Google Calendar Reconciliation Errors (Duplicates / Sync Drift)
    └── See Section 6: Calendar Synchronization Drift
```

---

## 2. Ingress & Network Troubleshooting

### Symptom: `https://k09oezeyib.localto.net/` returns `502 Bad Gateway` or timeouts
- **Root Cause**: Either Waitress (:5000) is down or the `localtonet` tunnel client daemon lost connection.
- **Diagnostic Steps**:
  ```bash
  # Check if Waitress is running locally
  curl -s http://127.0.0.1:5000/health

  # Check runit service status
  sv status nexusnode
  sv status localtonet
  ```
- **Resolution**:
  1. If Waitress is down: `sv restart nexusnode`
  2. If Waitress is healthy but tunnel is failing: `sv restart localtonet`
  3. Inspect tunnel logs: `cat ~/services/localtonet/log/current`
  4. Verify Wi-Fi internet connectivity on the mobile device.

---

## 3. Ephemeral Browser Subsystem Failures

### 3.1 Error: `ADMISSION_DENIED: MemAvailable < 500 MB`
- **Root Cause**: The physical mobile appliance is experiencing transient memory pressure; the memory admission gate aborted the browser launch to prevent kernel out-of-memory thrashing.
- **Diagnostic Steps**:
  ```bash
  cat /proc/meminfo | grep MemAvailable
  ps -o pid,user,rss,args -C python
  ```
- **Resolution**:
  1. Clear OS buffer caches: Run `sync; echo 3 > /proc/sys/vm/drop_caches` (if rooted) or restart background Termux applications.
  2. Check if a runaway background task is leaking memory.
  3. If normal system state has recovered, re-trigger the browser query.

### 3.2 Error: `RESOURCE_BUSY: Concurrency lock held`
- **Root Cause**: Another browser operation is currently active. The appliance permits strictly **1 active browser session**.
- **Resolution**:
  - The caller should wait 3–5 seconds and retry with exponential backoff.
  - If no browser is running, the lock might be orphaned from an unhandled server crash:
    ```bash
    python -c "from browser.chromium_runtime import clear_browser_lock; clear_browser_lock()"
    ```

### 3.3 Browser Hangs or Orphaned PIDs Detected
- **Root Cause**: Complex JavaScript infinite loop on target portal, or CDP WebSocket disconnected unexpectedly.
- **Diagnostic Steps**:
  ```bash
  # Check for running Chromium processes
  ps aux | grep -i chromium
  ```
- **Resolution**:
  1. Trigger the process tree reaper manually:
     ```bash
     pkill -9 -f "chromium"
     ```
  2. The automated watchdog timer should clean up automatically within 30 seconds; if it failed, inspect `browser/chromium_runtime.py` log traces.

---

## 4. Database Contention & Lockout

### Symptom: `sqlite3.OperationalError: database is locked`
- **Root Cause**: Multiple concurrent threads attempting write transactions exceeding the 10,000 ms busy timeout.
- **Diagnostic Steps**:
  ```bash
  # Check active WAL file sizes
  ls -la storage_vault/nexus_unified.db*
  ```
- **Resolution**:
  1. Ensure WAL mode is active:
     ```bash
     sqlite3 storage_vault/nexus_unified.db "PRAGMA journal_mode;"
     # Should output: wal
     ```
  2. Force a WAL checkpoint to truncate journal files:
     ```bash
     sqlite3 storage_vault/nexus_unified.db "PRAGMA wal_checkpoint(TRUNCATE);"
     ```
  3. Clear any orphaned background task sync locks:
     ```bash
     sqlite3 storage_vault/nexus_unified.db "DELETE FROM timetable_sync_locks; DELETE FROM attendance_sync_locks;"
     ```

---

## 5. Portal Authentication & Scraping Failures

### Symptom: Attendance sync fails with `AUTH_EXPIRED` or `SCRAPE_FAILED`
- **Root Cause**: The student portal forced a session logout, updated anti-bot challenge headers, or is undergoing campus maintenance.
- **Diagnostic Steps**:
  ```bash
  # Test direct portal login via Python
  python -c "from upes.auth import test_portal_login; print(test_portal_login(user_id='usr_01'))"
  ```
- **Resolution**:
  1. Verify student portal credentials in the database:
     - Navigate to `https://k09oezeyib.localto.net/` -> Academic Settings.
     - Re-enter the SAP ID and portal password to refresh the encrypted store.
  2. If the portal has introduced new dynamic JavaScript logins, ensure the ExecutionRouter falls back to Tier 3 (Ephemeral Browser).

---

## 6. Calendar Synchronization Drift

### Symptom: Timetable events are missing or duplicated in Google Calendar
- **Root Cause**: Network timeouts during Google Calendar batch patches, or out-of-band manual edits made to Google Calendar directly by the student.
- **Resolution**:
  1. Perform a full state reset and forced resync:
     ```bash
     # Clear calendar sync mapping state for the user
     sqlite3 storage_vault/nexus_unified.db "DELETE FROM timetable_events_map WHERE user_id = 'usr_01';"

     # Trigger full fresh reconciliation
     python timetable_sync.py --force-sync --user-id usr_01
     ```
  2. Verify that `google_oauth_tokens` has not expired or been revoked by Google.
