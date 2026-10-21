# NexusNode — Phase 1B: Academic Data & Synchronization Acceptance

**Target Appliance**: TECNO BG6 (`109973141A030946`), Android 13, ARM64  
**Date**: 2026-10-21  
**Authoritative Location**: `docs/operations/PHASE1B_LIVE_ACADEMIC_ACCEPTANCE.md`  
**Git Checkpoint**: Phase 1B Verified  

---

## 1. Executive Summary

Phase 1B live academic acceptance has achieved full verification on the production TECNO BG6 appliance:
- Authoritative UPES live timetable retrieved and persisted.
- Authoritative live attendance records ingested across all 9 modules.
- Three-hour autonomous scheduler execution path verified live.
- Google Calendar decoupling verified (zero Google mutations, academic fetch preserved).

---

## 2. Live Timetable Acceptance Evidence

### Ingestion Results
- **API Endpoint**: `https://myupes-beta.upes.ac.in/apigateway/api/timetable`
- **Student Code**: `3a678d8e-8817-41e6-b1a8-5a3ec6ee4948`
- **Sessions Ingested**: **335 live sessions**
- **Persistence Target**: `user_timetables` SQLite table (`704,267` bytes)
- **Date Range**: `2026-Aug-03` to `2026-Sep-30`
- **Unique Venues**: 17 venues (`11011`, `11012`, `11013`, `11014`, `11015`, etc.)
- **Decoupled Google Status**:
  ```text
  status: partial
  message: Timetable successfully updated from UPES, but Google Calendar authorization is required (CALENDAR_AUTH_REQUIRED).
  source: live
  upes_refresh_status: SUCCESS
  timetable_status: UPDATED
  calendar_status: CALENDAR_AUTH_REQUIRED
  sessions_seen: 335
  created: 0, updated: 0, deleted: 0, unchanged: 0
  stale: False
  ```

---

## 3. Live Attendance Acceptance Evidence

### Ingestion Results
- **Enrolled Modules**: **9 modules** synchronized to `academic_modules`.
- **Individual Session Punches**: **189 session records** ingested to `academic_sessions`.
- **Official Summaries**: **9 module summaries** updated in `official_attendance_summaries`.
- **Authoritative Student Metrics**:
  - **Overall Attendance**: **166 / 189 sessions (87.83%)**
  - **Total Safe Bunks Available**: **30 bunks** across subjects
  - **Critical Subjects (<75%)**: **1 subject** (*Object Oriented Analysis and Design* at 72.73%, requiring 2 recovery sessions)

### Subject-Wise Attendance Breakdown
| Module ID | Course Name | Conducted | Attended | Pct (%) | Status | Safe Bunks | Recovery Needed |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **88877** | Deep Learning | 43 | 42 | **97.67%** | `safe` | 13 | 0 |
| **87948** | Probability, Entropy, and MC Simulation | 26 | 25 | **96.15%** | `safe` | 7 | 0 |
| **87945** | Cryptography and Network Security | 30 | 26 | **86.67%** | `safe` | 4 | 0 |
| **87949** | Research Methodology in CS | 22 | 19 | **86.36%** | `safe` | 3 | 0 |
| **87946** | Formal Languages and Automata Theory | 28 | 23 | **82.14%** | `safe` | 2 | 0 |
| **89088** | AI and Multimedia | 16 | 13 | **81.25%** | `safe` | 1 | 0 |
| **88742** | Leadership and Team Building | 2 | 2 | **100.0%** | `safe` | 0 | 0 |
| **87947** | Object Oriented Analysis and Design | 22 | 16 | **72.73%** | `critical` | 0 | 2 |
| **80955** | EDGE - Advance Communication | 0 | 0 | **0.00%** | `not_started` | 0 | 0 |

---

## 4. Autonomous Three-Hour Scheduler Verification

- **Configured Interval**: `10,800` seconds (3 hours)
- **Job ID**: `job_timetable_sync`
- **Execution Path**: `run_timetable_sync_job()`
- **Live Dispatch Evidence**:
  ```text
  Executing scheduled 3-hour academic synchronization loop...
  Timetable sync completed: 1 users (C:0 U:0 D:0 NOOP:0 ERR:1)
  Attendance sync completed: 1 users (9 modules updated).
  Results sync: 3 users (3 records updated/LKG).
  LMS sync telemetry pass completed in 0.0ms.
  LATEST TIMETABLE HISTORY: status=partial | sessions=335
  LATEST ATTENDANCE HISTORY: status=ACTIVE | modules=9 | sessions=189
  ```
- **Scheduler Decoupling Invariant**: Upstream Google Calendar authentication failures (`CALENDAR_AUTH_REQUIRED`) did NOT degrade, block, or corrupt academic timetable, attendance, or results synchronizations.

---

## 5. Multi-User Isolation Verification

Database inspections confirmed strict multi-user tenant separation:
- `users`: `admin` (`anmol.11794@stu.upes.ac.in`), `papa`, `testadmin`, `teststudent`
- `upes_auth_sessions`: 1 record strictly scoped to `admin`
- `user_timetables`: 1 record strictly scoped to `admin`
- `academic_modules`: 9 records strictly scoped to `admin`
- `official_attendance_summaries`: 9 records strictly scoped to `admin`
- `academic_sessions`: 189 records strictly scoped to `admin`
- `academic_results`: isolated across students.
