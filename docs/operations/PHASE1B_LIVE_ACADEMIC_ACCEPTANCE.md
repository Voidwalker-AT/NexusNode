# NexusNode — Phase 1B: Academic Data & Synchronization Acceptance

**Target Appliance**: TECNO BG6 (`109973141A030946`), Android 13, ARM64  
**Date**: 2026-10-21  
**Authoritative Location**: `docs/operations/PHASE1B_LIVE_ACADEMIC_ACCEPTANCE.md`  

---

## 1. Academic Data Baseline & Invariant Analysis

### A. Authoritative Cached Schedule
The production SQLite database on TECNO BG6 (`nexus_unified.db`) holds the authoritative Semester 5 schedule for user `admin`:
- **Record Location**: `user_timetables` (805,646 bytes of normalized JSON).
- **Session Count**: 384 timetable slots across Semester 5.
- **Academic Range**: `2026-Aug-03` to `2026-Dec-02`.
- **Enrolled Context**:
  - Degree: `B.Tech CSE` (`CourseFamilyId: 593`, `CourseFamilyCode: BTECH_CS_CSE`)
  - Level: `Third Year (Y3)`
  - Term: `Semester 5` (`TermCodeId: 5`, `TermCode: SEM_5`)
  - Center: `UPES Bidholi Campus`
- **Modules Present**:
  - `CSEG3056_3`: Probability, Entropy, and MC Simulation (Faculty: Gourav Arora, Room: 11013)
  - `CSEG3055_3`: Formal Languages and Automata Theory (Faculty: Papia Mahato, Room: 11115)
  - Full semester schedule across all 9 modules.

### B. Decoupled Synchronization Invariant
- **Live Fetch Attempt**: When `sync_user_timetable("admin", live_fetch=True)` is called in the absence of an active UPES session, NexusNode deterministically:
  1. Identifies UPES session as expired/unconfigured (`upes_refresh_status: AUTH_REQUIRED`).
  2. Protects the 384 existing sessions in `user_timetables` and 66 records in `academic_sessions` (`timetable_status: PRESERVED_LKG`).
  3. Skips destructive Google Calendar deletions (`deleted: 0`).
  4. Returns `status: "failed"` (or `"partial"` if cached data is served).
  5. Never contaminates or resets attendance analytics.

---

## 2. API Contract & Acceptance Criteria for Live Data

Once the authenticated Bearer token is imported:

### Timetable Acceptance Gate
1. `GET https://myupes-beta.upes.ac.in/apigateway/api/timetable` with headers:
   - `Authorization: Bearer <TOKEN>`
   - `x-studentUniqueId: 3a678d8e-8817-41e6-b1a8-5a3ec6ee4948`
   - `x-appsecret: ku7GUMtyT8er51rTfTc7HC`
   - `x-applicationname: connectportal`
   - `x-requestfrom: web`
2. **Acceptance Rules**:
   - `len(sessions) >= 50`: Schedule must reflect enrolled semester subjects.
   - Date range must overlap current academic date (`2026-10-21`).
   - Sessions must parse into `TimetableSession` objects with valid start/end times and canonical slot keys.
   - Malformed/empty payloads are rejected and preserve LKG data.

### Attendance Acceptance Gate
1. `POST https://myupes-beta.upes.ac.in/apigateway/student-attendance/attendancedropdown`:
   - Returns active academic terms (`academic_terms`) and enrolled course modules (`academic_modules`).
2. `POST https://myupes-beta.upes.ac.in/apigateway/student-attendance/studentattendancesummary`:
   - Returns subject-wise attended and conducted counts.
3. **Analytics Rules**:
   - Total attended and conducted classes counted per subject.
   - Safe bunks formula applied: $\text{bunks} = \lfloor \frac{A - 0.75 \times C}{0.75} \rfloor$.
   - Recovery classes formula applied: $\text{recovery} = \lceil \frac{0.75 \times C - A}{0.25} \rceil$.
   - Overall attendance computed as $\frac{\sum A}{\sum C} \times 100$.

---

## 3. Production Readiness Matrix

| Component | State | Live Acceptance Status |
| :--- | :--- | :--- |
| **Timetable Model & Storage** | READY | Verified against 384 real UPES slots in SQLite. |
| **Attendance Math & Analytics** | READY | Verified mathematically (118/118 unit tests passed). |
| **Decoupled Sync Pipeline** | READY | Verified with Phase 1A patch (8/8 decoupling tests passed). |
| **Direct UPES Bearer Client** | READY | Microservice headers and URL routing verified. |
| **Authentication Credential** | **CHECKPOINT** | Stored password verified; waiting on user reCAPTCHA handoff. |
