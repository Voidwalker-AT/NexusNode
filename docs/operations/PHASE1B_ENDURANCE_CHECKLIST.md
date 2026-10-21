# NexusNode — Phase 1B: Zero-Touch Endurance & Scheduler Checklist

**Target Appliance**: TECNO BG6 (`109973141A030946`), Android 13, ARM64  
**Date**: 2026-10-21  
**Authoritative Location**: `docs/operations/PHASE1B_ENDURANCE_CHECKLIST.md`  

---

## 1. 3-Hour Academic Scheduler Invariants

The background academic synchronization job (`job_timetable_sync`) is registered in SQLite table `scheduled_jobs`:
- **Job ID**: `job_timetable_sync`
- **Job Type**: `timetable_sync`
- **Interval**: `10800` seconds (3 hours)
- **Enabled**: `1` (True)
- **Status**: `dispatched`

### Execution Invariants
1. **Decoupled Execution**: The job must attempt UPES timetable and attendance synchronization regardless of Google Calendar OAuth state (`invalid_grant`).
2. **Proactive Renewal**: When an active token is within 12 hours of expiration, the job must attempt headless token refresh via `/sso/user/oauth2/refresh-token`.
3. **Stage Telemetry**: The scheduler records independent stage outcomes in `timetable_sync_history`:
   - `stages.upes_refresh.status`: `SUCCESS`, `AUTH_REQUIRED`, or `NETWORK_ERROR`
   - `stages.timetable.status`: `UPDATED`, `PRESERVED_LKG`, or `UNCHANGED`
   - `stages.calendar.status`: `RECONCILED`, `CALENDAR_AUTH_REQUIRED`, `ERROR`, or `PRESERVED`
4. **Crash-Safe Persistence**: Token rotations use write-ahead journal (`.upes_session_journal.enc`) to survive sudden power cuts or Termux OOM kills.
5. **No False Positives**: If UPES authentication fails, overall status must report `failed` (or `partial` if LKG data is served). Never report `success`.

---

## 2. Resource & Process Governance (TECNO BG6)

| Parameter | Safety Baseline | Production Value Observed | Health Verdict |
| :--- | :--- | :--- | :--- |
| **Available RAM** | $\ge 800$ MB | `2,295 MB` | **PASS** (Abundant headroom) |
| **ZRAM Usage** | $< 1,024$ MB | `0 MB` | **PASS** (Zero swapping) |
| **Max Concurrent Browsers** | $\le 1$ | `0 active` (Flight lock enforced) | **PASS** |
| **Process Tree Cleanup** | 0 orphan pids | Clean (`find_system_chromium_pids() == []`) | **PASS** |
| **Workflow Timeout** | $\le 60$ s | 60.0s watchdog active | **PASS** |

---

## 3. Rollback & Emergency Recovery Protocol

In the event of an operational anomaly during or after authentication recovery:

### Source Rollback
```bash
ssh -p 8022 u0_a208@192.168.29.21 \
  "cp ~/server_backup_phase1a_20261021_190627/source_backup/timetable_sync.py ~/server/ && \
   export SVDIR=/data/data/com.termux/files/usr/var/service && \
   sv restart nexusnode"
```

### Database Point-in-Time Restore (If Corruption Occurs)
```bash
ssh -p 8022 u0_a208@192.168.29.21 \
  "cp ~/server_backup_phase1a_20261021_190627/db_backup/nexus_unified.db ~/server/storage_vault/nexus_unified.db && \
   export SVDIR=/data/data/com.termux/files/usr/var/service && \
   sv restart nexusnode"
```
*Note: Point-in-time database SHA-256 is `3317c875befeb2815d7a208e5e3d9552b4747b0d991f2d946799f1afae664626`.*
