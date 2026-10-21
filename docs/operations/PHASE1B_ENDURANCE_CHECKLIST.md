# NexusNode — Phase 1B: Endurance & Operational Verification Checklist

**Target Physical Device**: TECNO BG6 (`109973141A030946`), Android 13, ARM64  
**Date**: 2026-10-21  
**Authoritative Location**: `docs/operations/PHASE1B_ENDURANCE_CHECKLIST.md`  

---

## 1. Phase 1B Operational Gate Checklist

- [x] **Production Appliance Online**: TECNO BG6 accessible via SSH (`192.168.29.21:8022`) and ADB (`109973141A030946`).
- [x] **Production SQLite Backup**: Snapshot created at `/data/data/com.termux/files/home/server_backup_phase1b_credentials_alignment/nexus_unified.db` (SHA-256: `a2c685ae0ddbf7ddad8e627ddc351f6257c8be0c8ae7ebec73148eba26cacdd7`).
- [x] **Identity Realignment**: `admin` credentials updated to `anmol.11794@stu.upes.ac.in` (SAP ID: `590011794`, UUID: `3a678d8e-8817-41e6-b1a8-5a3ec6ee4948`).
- [x] **Root Cause Verified**: Session expired August 2026; direct-HTTP password login returns HTTP 500 due to Google reCAPTCHA v2.
- [x] **Interactive Handoff Completed**: Authenticated session imported without token/password leakage.
- [x] **Session Persistence**: AES-256-GCM encrypted in `upes_auth_sessions` (`state: AUTHENTICATED`, TTL ~10.4h, generation: 1).
- [x] **Live Timetable Retrieved**: 335 sessions persisted to `user_timetables` (`704,267` bytes, range `2026-Aug-03` to `2026-Sep-30`).
- [x] **Live Attendance Retrieved**: 9 modules, 189 session punches, and official summaries synced (Overall: 87.83%, 166/189 attended, 30 safe bunks).
- [x] **Live Results Retrieved**: Synchronized via ConnectPortal API Gateway.
- [x] **Autonomous 3-Hour Scheduler Verified**: `job_timetable_sync` interval 10,800s; live dispatch completed 0 errors.
- [x] **Google Calendar Invariant Preserved**: `CALENDAR_AUTH_REQUIRED` recorded; 0 Google mutations; zero calendar deletions.
- [x] **Multi-User Isolation**: Tenant isolation verified across `admin`, `papa`, `testadmin`, `teststudent`.
- [x] **Resource Telemetry Clean**: Available RAM: 2,292 MB; 0 orphan Chromium PIDs; 1 supervised Waitress/Flask process.
- [x] **Unit & Regression Tests**: 51/51 targeted tests passed on Windows (40 scheduler/auth tests + 11 results tests).
- [x] **Public HTTPS Endpoint Verified**: `https://k09oezeyib.localto.net/api/health` returns HTTP 200 OK.
