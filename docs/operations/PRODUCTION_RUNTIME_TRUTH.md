# NexusNode Production Runtime Truth & Verification Audit

> **Status**: OBSERVED & VERIFIED ON PRODUCTION APPLIANCE  
> **Appliance Target**: TECNO BG6 (`192.168.29.21`)  
> **Date**: 2026-10-21  
> **Audit Type**: Evidence-Backed Systems Reconnaissance (Gravitas Core)

---

## 1. Executive Summary & Verification Matrix

| Subsystem | Stated Intent | Observed Runtime Reality | Verdict | Evidence |
|---|---|---|---|---|
| **Repository Root** | `E:\Workspace\Active\NexusNode` | `E:\Workspace\Active\NexusNode\server` is the single `.git` repo | **LOCATED** | `git remote -v`, `git log` |
| **Physical Appliance** | TECNO BG6 on Android 13 | Serial `109973141A030946`, Android 13, 2.24 GB free RAM | **VERIFIED ON DEVICE** | `adb shell getprop`, `cat /proc/meminfo` |
| **Termux Access** | SSH on port 8022 | Restored via `run-as com.termux` & `service-daemon start` | **OPERATIONAL** | TCP 8022 pass, SSH authenticated |
| **NexusNode WSGI** | Waitress on port 5000 | PID 5024, RSS ~70 MB, `/api/health` 200 OK | **OPERATIONAL** | HTTP 200 `{"status": "healthy"}` |
| **Public Ingress** | `k09oezeyib.localto.net` | Tunnel active; requires `localtonet-skip-warning: true` header | **OPERATIONAL** | HTTP 200 with skip-warning |
| **MCP Catalog** | 11 semantic tools | **43 MCP Tools**, 52 Agent Registry Operations | **VERIFIED IN CODE & RUNTIME** | `mcp_adapter.tool_defs`, `/api/mcp/health` |
| **Database Integrity** | `nexus_unified.db` | Path: `storage_vault/nexus_unified.db` (5.6 MB), Integrity OK | **VERIFIED ON DEVICE** | `PRAGMA integrity_check` -> `ok` |
| **UPES Auth Session** | Active session in SQLite | **0 rows in `upes_auth_sessions`**, state `AUTH_REQUIRED` | **EXPIRED / ABSENT** | SQLite count = 0 |
| **UPES Credentials** | Stored encrypted credentials | Encrypted creds exist for `admin` (`Aug***@stu.upes.ac.in`) | **PRESERVED** | `upes_user_credentials` (2 rows) |
| **Direct SSO Login** | Direct HTTP authentication | Returns `HTTP 500: Internal Server Error` (CAPTCHA/Challenge) | **BLOCKED BY UPSTREAM** | Live HTTP probe against SSO endpoint |
| **Timetable Data** | Live university schedule | **66 sessions recorded; all from August 2026 (54 days stale)** | **STALE CACHE** | `MIN: 2026-08-03, MAX: 2026-08-27` |
| **Attendance Analytics** | Live attendance counts | 66 conducted, 59 attended (89.39%), 1 critical subject (50%) | **LKG CACHED (Aug 28)** | `attendance_service.get_attendance_analytics` |
| **Google Calendar** | 3-hour automatic sync | Refresh token expired (`invalid_grant: Bad Request`) | **AUTH_REQUIRED** | Decrypted token `reauth_required: True` |
| **3-Hour Scheduler** | Autonomous background sync | Configured and dispatched, but fails due to `auth_required` | **DISPATCHED BUT FAILING** | `scheduled_jobs` last_run `1792588724` |
| **Code Drift** | Windows matches BG6 | **BG6 is at older commit `50a2f34`**, missing `78f4de0` & `02a70c0` | **SOURCE DRIFT CONFIRMED** | Hash mismatch on `app.py`, `config.py` |

---

## 2. Production Database Inventory

- **Location**: `/data/data/com.termux/files/home/server/storage_vault/nexus_unified.db`
- **File Size**: `5,873,664 bytes` (~5.6 MB)
- **Integrity**: `PRAGMA integrity_check` -> `ok`
- **Journal Mode**: WAL mode enabled

### Verified Table Counts

| Category | Table Name | Row Count | Commentary |
|---|---|---|---|
| **Users** | `users` | 4 | `admin`, `papa`, `testadmin`, `teststudent` |
| **UPES Auth** | `upes_user_credentials` | 2 | AES-GCM encrypted credentials for `admin` and `papa` |
| **UPES Sessions** | `upes_auth_sessions` | **0** | **Session bundle is empty; requires reacquisition/import** |
| **Academic Ledger** | `academic_sessions` | 66 | Stored lectures and lab slots (August 2026) |
| **Academic Ledger** | `academic_modules` | 9 | Enrolled subjects |
| **Academic Ledger** | `official_attendance_summaries` | 9 | Subject-wise attendance percentages |
| **Calendar Mapping** | `timetable_events_map` | 84 | Maps local sessions to Google Calendar event IDs |
| **Sync Histories** | `timetable_sync_history` | 609 | Shows repeated `auth_required` errors |
| **Sync Histories** | `attendance_sync_history` | 21 | Shows repeated `AUTH_REQUIRED` errors |
| **Sync Histories** | `academic_result_sync_history` | 382 | **Contains leaked synthetic records (`student_a`, `student_b`)** |
| **Google OAuth** | `google_oauth_tokens` | 1 | User `admin`, expired with `invalid_grant` |
| **Scheduled Jobs** | `scheduled_jobs` | 5 | Timetable sync, daily backup, temp clean, retention, tunnel check |
| **Logs** | `system_logs` | 10,009 | Retained audit logs |

---

## 3. Discovered Architectural Reality

### 3.1 The 43-Tool MCP Semantic Catalog
The historical documentation referenced 11 semantic tools. Inspection of `mcp_adapter.tool_defs` and `agent_registry` reveals that the production server has advanced to **43 MCP Tools** spanning:
- `nexus.status`, `action.status`
- `upes.*` (8 tools: attendance, timetable, courses, punches, performance)
- `lms.*` (8 tools: course discovery, assignment ledger, submission plan)
- `vault.*` (11 tools: file manager, archives, isolation)
- `browser.*` (12 tools: remote observation, navigation, interaction)
- `document.*` (2 tools: creation and extraction)

### 3.2 The Google Calendar Coupling Trap
In earlier revisions deployed to BG6, `timetable_sync.py` blocked all timetable processing if Google Calendar synchronization failed.
On Windows development, commit `02a70c0` (`feat(academics): decouple Google Calendar gate from UPES timetable sync`) successfully decoupled these two systems, but this fix **was never deployed to the physical phone**.

### 3.3 Upstream SSO Challenge Reality
Direct HTTP login to `https://myupes-beta.upes.ac.in/sso/api/account/oauth2/token` is currently returning `HTTP 500: Internal Server Error` due to anti-automation checks. The verified method to establish an active session is to capture or import an authenticated browser session bundle (`idp_session_info` cookie + token bundle) into `/api/upes/auth/import` or via the ephemeral Chromium bridge.
