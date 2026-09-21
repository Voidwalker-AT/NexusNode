# Authoritative UPES Attendance & Classroom Card-Punch Implementation Report

## Executive Summary

Phase 2 successfully replaces the synthetic attendance mechanism in NexusNode with the authoritative UPES attendance ledger discovered in Phase 1. The implementation ingests real-time academic hierarchy, course modules, official attendance summaries, and granular session ledgers (including RFID classroom card-punch timestamps) directly from the UPES API Gateway.

---

## 1. Architectural Changes & Data Layer

### 1.1 Direct SQLite Schema (`attendance_sync.py`)
All attendance data is normalized into direct SQLite tables without introducing SQLAlchemy or external ORM dependencies, fully compatible with `config.UNIFIED_DB_FILE`:

1. `academic_terms`:
   - Scoped by `(user_id, term_code_id, course_family_id)`.
   - Stores `term_code`, `term_name`, `start_date`, `end_date`, `is_current`, `last_synced_at`.
2. `academic_modules`:
   - Scoped by `(user_id, module_id)`.
   - Stores `term_code_id`, `module_name`, `module_code`, `course_family_id`, `last_synced_at`.
3. `official_attendance_summaries`:
   - Scoped by `(user_id, module_id)`.
   - Stores authoritative `total_sessions`, `total_attended`, `total_condoned`, `attendance_percentage`, `term_attendance_percentage`, `last_synced_at`.
4. `academic_sessions`:
   - Scoped by `(user_id, session_id)` (native UPES integer SessionId preventing any date/time collision).
   - Stores `module_id`, `course_name`, `session_date`, `start_time`, `end_time`, `faculty`, `room`, `virtual_room`, `mode`, `session_type`, `session_status`, `attendance_status` (`PRESENT`, `ABSENT`, `CONDONED`, `UNKNOWN`), `attendance_subtype` (`CRA`, `OA`, `MANUAL`), `punch_in_time`, and `reason_json`.
5. `attendance_sync_history`:
   - Tracks audit logs of synchronization runs, timestamps, counts, status (`ACTIVE`, `PARTIAL`, `AUTH_REQUIRED`, `ERROR`), and structured JSON error details.
6. `attendance_sync_locks`:
   - Distributed SQLite lease lock preventing concurrent duplicate sync runs per user.

---

## 2. Core Attendance Service (`attendance_sync.py`)

### 2.1 API Gateway Integration
Reuses `UpesSessionBroker` and `UpesBrowserSessionBridge` with existing encrypted credentials (`upes_auth_sessions`) and mandatory microservice headers:
- `x-applicationname: connectportal`
- `x-requestfrom: web`
- `x-appsecret: ku7GUMtyT8er51rTfTc7HC`
- `x-studentUniqueId: <StudentUUID>`
- `Authorization: Bearer <JWT>`

### 2.2 Classroom Card-Punch Semantics
- `AttendanceSubTypeCode: "CRA"` $\rightarrow$ Classroom Reader Attendance (RFID card punch).
- `StudentPunchInTime: "HH:MM"` $\rightarrow$ Exact timestamp when student punched in at the classroom door.
- `AttendanceSubTypeCode: "OA"` $\rightarrow$ Online / Alternative Attendance.
- `AttendanceSubTypeCode: "MANUAL"` $\rightarrow$ Legacy local punch entries.

### 2.3 Safe Bunk & Recovery Mathematics
Generic formulas implemented for any target threshold $T \in (0, 1)$ (default $T = 0.75$):
- **Safe Bunks Remaining ($B$)**:
  $$B = \begin{cases} \lfloor \frac{A - T \times C}{T} \rfloor & \text{if } A \ge T \times C \\ 0 & \text{otherwise} \end{cases}$$
- **Recovery Classes Required ($R$)**:
  $$R = \begin{cases} \lceil \frac{T \times C - A}{1 - T} \rceil & \text{if } A < T \times C \\ 0 & \text{otherwise} \end{cases}$$
- Zero conducted classes ($C=0$) handled gracefully without division-by-zero ($100.0\%$ default).

### 2.4 Future Timetable Projections
Correlates upcoming class slots from `user_timetables` for next-lecture attendance impact projections without creating synthetic attendance records:
- Projected % if attended: $\frac{A + 1}{C + 1} \times 100$
- Projected % if skipped: $\frac{A}{C + 1} \times 100$

---

## 3. REST API Surface (`app.py`)

| Endpoint | Method | Role / Auth | Description |
|---|---|---|---|
| `/api/attendance/status` | `GET` | Authenticated | Health status, active term, total counts, and last sync state |
| `/api/attendance/summary` | `GET` | Authenticated | Overall statistics, per-subject safe bunks, recovery needs, and next-class projections |
| `/api/attendance/modules` | `GET` | Authenticated | Enrolled academic modules and official attendance percentages |
| `/api/attendance/sessions` | `GET` | Authenticated | Granular session ledger with `module_id`, date range, and pagination filters |
| `/api/attendance/today` | `GET` | Authenticated | Today's scheduled sessions and live punch status |
| `/api/attendance/sync` | `POST` | Authenticated | Triggers live on-demand synchronization with UPES Gateway |
| `/api/attendance/punch` | `POST` | Authenticated | Legacy manual punch logging (backward compatibility) |
| `/api/attendance/punches` | `GET` | Authenticated | Legacy manual punches query (backward compatibility) |

---

## 4. Frontend Attendance Interface (`static/js/app.js` & `index.html`)

- **Top Metric Cards**:
  - Authoritative Overall Attendance % with color-coded pills ($\ge 80\%$ Safe, $75-80\%$ Warning, $< 75\%$ Critical).
  - Total Safe Bunks Available across the semester.
  - Total Classes Conducted vs Attended.
  - Today's Live Sessions punched.
- **Action Toolbar**:
  - Dedicated `Sync with UPES` button with live loading spinner and toast notifications.
  - Refresh button for cached analytics.
- **Subject-wise 75% Safe Bunk Data Sheet**:
  - Course Name & Module ID.
  - Conducted, Attended, and Absent figures.
  - Official Attendance % with visual progress bars.
  - Safe Bunks Left / Recovery Classes Needed.
  - Next Lecture Projection (e.g., *Tomorrow 13:00 $\rightarrow$ 81.82% if attended / 72.73% if skipped*).
- **Authoritative Granular Session Ledger**:
  - Date & Slot Time.
  - Punch In Time (e.g. `13:02`, `10:01`, or `—`).
  - Course Name & Session ID.
  - Venue & Faculty.
  - Official Status (`PRESENT`, `ABSENT`, `CONDONED`).
  - Subtype & Mode (`CRA` RFID Reader, `OA` Online, `MANUAL`).

---

## 5. Verification & Test Coverage

### 5.1 Automated Unit & Integration Tests
111 total tests passed cleanly across the test suite:
- `tests/test_attendance_sync.py`: 15 unit tests covering mathematical boundary conditions, custom thresholds (80%, 85%, 90%), zero-division handling, SQLite table creation, multi-user scoping isolation, `CRA` RFID punch mapping, `SessionId` uniqueness, lease locking concurrency, and partial failure LKG resilience.
- `tests/test_attendance_api.py`: 7 integration tests covering all `/api/attendance/*` endpoints, RBAC, query parameters, and backward-compatible legacy routes.
- Existing suites (`test_timetable_sync.py`, `test_tab_preloading_cache.py`, `test_production_hardening.py`, `test_startup_order.py`): 89 tests passed with zero regressions.

### 5.2 Controlled Live Verification Results
Live synchronization performed against active student portal session:
- **Status**: `ACTIVE`
- **Modules Synced**: 9 / 9
- **Total Conducted Sessions**: 66
- **Total Attended Sessions**: 59 (7 absent)
- **Overall Attendance**: **89.39%**
- **Total Semester Safe Bunks**: **11**
- **CRA RFID Card Punches**: 58 session punches captured with exact room and door punch timestamps (e.g., `13:02`, `12:02`, `10:01`).
