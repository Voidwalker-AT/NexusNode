# NexusNode Phase 2 Deployment Report: TECNO BG6 Production Server

---

## 1. Deployment Source

- **Accepted Development Checkpoint**: `1b40f66 feat: add authoritative UPES attendance and resilient auth`
- **Target Branch**: `feature/diagnostics-model-runtime`
- **Follow-up Patch**: `252d714 fix(auth): remove duplicate classmethod decorator on journal recovery`
- **Source Remote**: `https://github.com/Voidwalker-AT/NexusNode.git`
- **Deployment Protocol**: SSH (`OpenSSH 10.5` over TCP Port `8022`) — **Zero ADB usage**.

---

## 2. SSH Connection

- **Remote Host**: `192.168.29.211`
- **Remote Port**: `8022`
- **OS User**: `u0_a208`
- **Remote Platform**: `Linux localhost 5.4.210-android12-9-667269-g856cdf2f247e-ab190 aarch64 Android`
- **Device Model**: `TECNO BG6`
- **Environment**: Termux (`PREFIX=/data/data/com.termux/files/usr`, `HOME=/data/data/com.termux/files/home`)
- **Connection Status**: **PASS**

---

## 3. Production Branch

- **Production Working Directory**: `/data/data/com.termux/files/home/server`
- **Active Branch**: `feature/diagnostics-model-runtime`
- **Production Commit (PRE)**: `d34ef0e` (`feat(academics): pink Google Calendar color for online classes, attendance punch tracking and 75% bunk planner data sheet`)
- **Production Commit (POST)**: `252d714` (`fix(auth): remove duplicate classmethod decorator on journal recovery`)
- **Git Merge Strategy**: Clean Fast-Forward (`git merge --ff-only origin/feature/diagnostics-model-runtime`)

---

## 4. Production PRE State

- **Unified SQLite Database**:
  - Path: `~/server/storage_vault/nexus_unified.db`
  - Size: 2,203,648 bytes
  - Integrity: `[{'integrity_check': 'ok'}]`
  - Table Count: 20 tables
  - Total System Logs: 5,059 rows
  - User Count: 2 (`admin`, `papa`)
  - User Auth Canonical Fingerprint Verified: **YES**
- **Persistent Vault & Secrets**:
  - Total Files: 23 files (17,444,062 bytes)
  - `.nexus_secret` Present: **YES**
  - `.env` Present: **YES**
  - RAG Database (`rag_vault.db`): 40,960 bytes, 6 documents, 6 chunks, integrity ok

---

## 5. Backup Verification

Prior to modifying production source or executing database migration, writes were quiesced via `SVDIR=$PREFIX/var/service sv down nexusnode` and verified backup artifacts were created in:
`~/nexusnode-deploy-backups/20260828_170511/`

- **Database Backups (SQLite API consistent copies)**:
  - `nexus_unified.db.bak`: 2,203,648 bytes | `integrity_check = ok`
  - `rag_vault.db.bak`: 40,960 bytes | `integrity_check = ok`
  - `nexus_vault.db.bak`: 471,040 bytes | `integrity_check = ok`
- **Persistent State Archive**:
  - `persistent_state_archive.tar.gz`: 14,233,090 bytes | Member count: 36 members verified via tar header verification.
- **Backup Verification Status**: **PASS**

---

## 6. Source Update

- Git fetch and fast-forward merge executed without conflict.
- Working tree restored cleanly.
- Pre-start bytecode compilation (`python -m py_compile app.py config.py timetable_sync.py attendance_sync.py`) succeeded with zero errors.
- Non-destructive module import test verified `config`, `timetable_sync`, `attendance_sync`, and `app`.

---

## 7. Database Migration

- Additive migration executed cleanly against the device's authoritative SQLite database.
- Table count increased from 20 to 26:
  - Added Tables: `academic_terms`, `academic_modules`, `academic_sessions`, `attendance_sync_locks`, `attendance_sync_history`, `official_attendance_summaries`.
  - Dropped Tables: **0**
- Database Integrity Post-Migration: `['ok']`

---

## 8. User / Auth Preservation

- **User Accounts**:
  - `admin` (Role: `admin`, Disabled: `0`, Privileges length: 349)
  - `papa` (Role: `user`, Disabled: `0`, Privileges length: 385)
- **User Canonical Auth Fingerprint**:
  - User identity/auth canonical state pre/post deployment identical: **YES**
- **Secret Encryption Key**:
  - `.nexus_secret` pre/post fingerprint identical: **YES**

---

## 9. Vault Preservation

- Vault directory structure and persistent files preserved intact.
- Storage categories (downloads, music, videos, backups) intact.
- Status: **PASS**

---

## 10. RAG Preservation

- RAG database (`rag_vault.db`) integrity: `['ok']`
- `rag_documents` count: 6 (100% preserved)
- `rag_chunks` count: 6 (100% preserved)
- Status: **PASS**

---

## 11. Google / Timetable Preservation

- `google_oauth_tokens` (1 record) decrypted successfully with master key.
- `upes_auth_sessions` (1 record) decrypted successfully.
- UPES session identity preserved: **YES**
- `timetable_events_map` (82 mapping records) preserved 100%.
- `user_timetables` (1 record) preserved 100%.
- Status: **PASS**

---

## 12. Service Restart

- NexusNode WSGI Server restarted cleanly under Termux runit supervision (`SVDIR=$PREFIX/var/service sv restart nexusnode`).
- Active Service PID: `26735` (running, zero restart loops).
- Status: **PASS**

---

## 13. Login Acceptance

- Normal User `papa` Authentication: **PASS** (`POST /api/auth/login` returns valid JWT token and user profile).
- Admin Identity & Password Hash: **PRESERVED** (Verified identical canonical cryptographic auth hash).
- Admin Direct Password Verification: **PASS** (Zero account lockouts, zero privilege loss).

---

## 14. Attendance Acceptance

On the live TECNO production server, the following Phase 2 endpoints were queried with authenticated session token:
- `GET /api/attendance/status` $\rightarrow$ `200 OK` (Auth status: `NOT_CONFIGURED` for user `papa`)
- `GET /api/attendance/summary` $\rightarrow$ `200 OK` (Attendance stats and 75% bunk calculations initialized)
- `GET /api/attendance/modules` $\rightarrow$ `200 OK`
- `GET /api/attendance/sessions` $\rightarrow$ `200 OK`
- Normalized SQLite tables present and queryable: `academic_terms`, `academic_modules`, `academic_sessions`, `attendance_sync_history`, `official_attendance_summaries`.
- Status: **PASS**

---

## 15. Service Health & Network Access

- **Local Service Health**: `http://127.0.0.1:5000/api/health` $\rightarrow$ `200 OK` (`{"status": "healthy", "version": "2.3.8"}`)
- **LAN Health**: `http://192.168.29.211:5000/api/health` $\rightarrow$ `200 OK` (`{"status": "healthy", "version": "2.3.8"}`)
- **LocalToNet Process Status**: **UP** (PID `23052`, supervised by runit)
- **Actual LocalToNet Public Endpoint Health**: `https://k09oezeyib.localto.net/api/health` $\rightarrow$ `200 OK` (`{"status": "healthy", "version": "2.3.8"}`)
- **SSH Daemon**: **UP** (PID `23703`, port `8022`)
- Status: **PASS**

---

## 16. PRE vs POST Comparison Table

| Metric / Table | PRE Deployment | POST Deployment | Status |
| :--- | :--- | :--- | :--- |
| **Git Commit** | `d34ef0e` | `252d714` | Updated (Clean Fast-Forward) |
| **Unified DB Tables** | 20 tables | 26 tables | Additive Migration (+6 tables) |
| **DB Integrity Check** | `ok` | `ok` | Intact |
| **User Count** | 2 (`admin`, `papa`) | 2 (`admin`, `papa`) | 100% Preserved |
| **User Auth Fingerprint** | Identical | Identical | 100% Preserved |
| **`.nexus_secret` Key** | Identical | Identical | 100% Preserved |
| **`background_tasks`** | 393 rows | 393 rows | 100% Preserved |
| **`backups`** | 16 rows | 16 rows | 100% Preserved |
| **`google_oauth_tokens`** | 1 row | 1 row | 100% Preserved (Decrypted OK) |
| **`scheduled_jobs`** | 5 rows | 5 rows | 100% Preserved |
| **`shares`** | 6 rows | 6 rows | 100% Preserved |
| **`timetable_events_map`** | 82 rows | 82 rows | 100% Preserved |
| **`timetable_sync_history`**| 83 rows | 83 rows | 100% Preserved |
| **`upes_auth_sessions`** | 1 row | 1 row | 100% Preserved (Decrypted OK) |
| **`user_timetables`** | 1 row | 1 row | 100% Preserved |
| **`rag_documents`** | 6 rows | 6 rows | 100% Preserved |
| **`rag_chunks`** | 6 rows | 6 rows | 100% Preserved |
| **NexusNode Service** | UP (PID 17354) | UP (PID 26735) | Healthy |
| **LocalToNet Service** | UP (PID 23052) | UP (PID 23052) | Healthy |

---

## 17. Rollback Readiness

Verified snapshot backups and persistent state archives remain preserved in `~/nexusnode-deploy-backups/20260828_170511/`. Rollback was **NOT required** because all audit gates passed with zero data loss and zero regressions.

---

## 18. Known Limitations

1. **UPES SSO Session Lifetime**: As established during Phase 2 discovery, headless token refresh relies on browser session cookies (`idp_session_info`) which expire naturally after ~10 hours. When expired, the system transitions gracefully to `AUTH_REQUIRED`.
2. **LocalToNet WAF Interstitial**: External web browsers accessing the LocalToNet public tunnel will encounter the standard LocalToNet tunnel confirmation header requirement (`localtonet-skip-warning: true` or interactive clickthrough), while API clients supply the skip header automatically.

---

## 19. Final Production Decision

```
==================================================
DEPLOYMENT ACCEPTED — PRODUCTION PASS
==================================================
```
