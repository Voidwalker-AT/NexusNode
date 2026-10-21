# NexusNode — Independent Auditor Handoff Document (Gemini Argon)

**Target Repository**: `https://github.com/Voidwalker-AT/NexusNode`  
**Authoritative Branch**: `feature/diagnostics-model-runtime`  
**Target Commit SHA**: `a074669`  
**Production Hardware**: TECNO BG6 (`109973141A030946`), Android 13, ARM64  
**Operating Environment**: Termux + runit supervisor (Python / Waitress / Flask)  
**Date of Audit Handoff**: 2026-10-21  
**Status**: `PUBLISHED_WITH_KNOWN_LIMITATIONS`  

---

## 1. Executive Mission & Audit Scope

This document provides independent verification agents (specifically Gemini Argon) with an authoritative, evidence-backed overview of the NexusNode codebase, architecture, production appliance deployment, and operational boundaries.

NexusNode is an academic automation appliance designed to operate continuously on an inexpensive Android smartphone (TECNO BG6, 4 GB physical RAM). Remote AI reasoning is provided by external Model Context Protocol (MCP) clients (e.g. Gemini Spark, Mistral). The phone is the sole production compute appliance; local LLM inference (e.g. Ollama) is not required.

### Phases Addressed
- **Phase 0**: Physical appliance reconnaissance, repository alignment, production truth auditing.
- **Phase 1A**: Google Calendar decoupling from UPES live academic ingestion.
- **Phase 1B**: Authentic UPES identity realignment, session recovery, live timetable & attendance ingestion, 3-hour scheduler path verification.

---

## 2. System Architecture & Component Mapping

```
                                +---------------------------+
                                |  External AI Clients      |
                                |  (Gemini Spark / Mistral) |
                                +-------------+-------------+
                                              | MCP (JSON-RPC)
                                              v
+-----------------------------------------------------------------------------------------+
|  TECNO BG6 Appliance (Android 13 / Termux)                                              |
|                                                                                         |
|  +--------------------+        +-------------------------+       +-------------------+  |
|  |  Public Ingress    | -----> |  Waitress / Flask Core  | <---> | SQLite Unified    |  |
|  |  (LocalToNet HTTPS)|        |  (app.py - port 5000)   |       | (nexus_unified.db)|  |
|  +--------------------+        +------------+------------+       +-------------------+  |
|                                             |                                           |
|         +-------------------+---------------+--------------------+                      |
|         |                   |                                    |                      |
|         v                   v                                    v                      |
|  +-------------+    +---------------+                     +--------------+              |
|  | UPES Auth   |    | Timetable &   |                     | Attendance & |              |
|  | Manager     |    | Calendar Sync |                     | Analytics    |              |
|  | (auth.py)   |    | (timetable_   |                     | (attendance_ |              |
|  +------+------+    |  sync.py)     |                     |  sync.py)    |              |
|         |           +-------+-------+                     +-------+------+              |
|         |                   |                                     |                     |
|         +-------------------+-------------------------------------+                     |
|                             |                                                           |
|                             v                                                           |
|             +-------------------------------+                                           |
|             | Upstream UPES API Gateway     |                                           |
|             | (myupes-beta.upes.ac.in)      |                                           |
|             +-------------------------------+                                           |
+-----------------------------------------------------------------------------------------+
```

### Key Source Manifest
| Component | Primary File | Responsibilities |
| :--- | :--- | :--- |
| **UPES Authentication** | [`upes/auth.py`](file:///E:/Workspace/Active/NexusNode/server/upes/auth.py) | 6-tier auth pipeline, token encryption, circuit breaker, identity binding. |
| **UPES Credentials** | [`upes/credentials.py`](file:///E:/Workspace/Active/NexusNode/server/upes/credentials.py) | AES-256-GCM encrypted credential vault (`nexusnode/upes/credentials/v1`). |
| **Timetable Sync** | [`timetable_sync.py`](file:///E:/Workspace/Active/NexusNode/server/timetable_sync.py) | Timetable ingestion, Google Calendar decoupling, `UpesSessionBroker`. |
| **Attendance Service** | [`attendance_sync.py`](file:///E:/Workspace/Active/NexusNode/server/attendance_sync.py) | Enrolled modules, 189 session punch ledger, safe bunk & recovery analytics. |
| **Results Service** | [`upes/results.py`](file:///E:/Workspace/Active/NexusNode/server/upes/results.py) | Semester CGPA/SGPA, course family grading via ConnectPortal API. |
| **MCP Server** | [`agent/mcp_server.py`](file:///E:/Workspace/Active/NexusNode/server/agent/mcp_server.py) | 43 discrete tools + 11 semantic tools (`academic.query`, `academic.sync`). |
| **Browser Runtime** | [`browser/bg6_cdp.py`](file:///E:/Workspace/Active/NexusNode/server/browser/bg6_cdp.py) | Ephemeral Chromium automation under Alpine proot on BG6. |

---

## 3. Verified Production Acceptance Evidence

### A. Authentic Identity Realignment
- **Student Name**: ANMOL THAPLIYAL
- **UPES Username**: `anmol.11794@stu.upes.ac.in`
- **Global / SAP ID**: `590011794`
- **Student UUID**: `3a678d8e-8817-41e6-b1a8-5a3ec6ee4948`
- **Degree & Level**: B.Tech CSE (Semester 5)
- **Data Protection**: Prior to credential migration on BG6, an online SQLite snapshot backup was created at:
  `/data/data/com.termux/files/home/server_backup_phase1b_credentials_alignment/nexus_unified.db`  
  *(SHA-256: `a2c685ae0ddbf7ddad8e627ddc351f6257c8be0c8ae7ebec73148eba26cacdd7`)*

### B. Live Timetable Ingestion
- **Sessions Ingested**: **335 timetable slots**
- **Payload Size**: `704,267 bytes` in `user_timetables.raw_json`
- **Date Range**: `2026-Aug-03` to `2026-Sep-30`
- **Unique Venues**: 17 venues (`11011`, `11012`, `11013`, `11014`, `11015`, etc.)
- **Decoupled Google State**: `status: partial` (`upes_refresh: SUCCESS`, `calendar: CALENDAR_AUTH_REQUIRED`, 0 Google mutations, zero deletions).

### C. Live Attendance Ingestion
- **Modules Synced**: **9 / 9 enrolled modules**
- **Individual Session Punches**: **189 session records** in `academic_sessions`
- **Overall Attendance**: **166 / 189 sessions (87.83%)**
- **Safe Bunks Remaining**: **30 bunks** across enrolled subjects
- **Critical Subjects (<75%)**: 1 subject (*Object Oriented Analysis and Design* at 72.73%, requiring 2 recovery sessions)

### D. Autonomous Three-Hour Scheduler
- Configured interval: `10,800 seconds` (3 hours) via `job_timetable_sync`.
- Controlled dispatch of `run_timetable_sync_job()` completed with 0 errors across timetable, attendance, results, and LMS telemetry passes.

---

## 4. Test Suite & Verification Commands

All unit and integration tests use isolated in-memory (`:memory:`) or temporary file databases and never modify the production database:

```bash
# Set PYTHONPATH to repository root
export PYTHONPATH=$(pwd)  # On Linux/macOS
$env:PYTHONPATH = "E:\Workspace\Active\NexusNode\server"  # On Windows PowerShell

# Target Core Academic & Auth Test Suite (59 tests)
python -m pytest \
  tests/test_phase1a_decoupling.py \
  tests/test_scheduler_3hour.py \
  tests/test_upes_auth_manager.py \
  tests/test_results_api.py \
  tests/test_results_multi_user.py

# Full Regression & Secret Leak Test Suite (119 tests)
python -m pytest \
  tests/test_secret_leak_regression.py \
  tests/test_timetable_sync.py \
  tests/test_attendance_sync.py
```
**Test Result**: **178 passed, 0 failed, 0 skipped** (100% pass rate).

---

## 5. Critical Distinctions & Known Limitations

Auditors must review the following explicit operational boundaries:

### 1. Timetable Freshness Discrepancy (CRITICAL)
- The live timetable payload retrieved directly from UPES contains 335 sessions with dates spanning **`2026-Aug-03` to `2026-Sep-30`**.
- The current operating date is **`2026-10-21`**.
- **Explanation**: UPES ConnectPortal API Gateway returns batch schedule allocations per term block. The retrieved payload represents the authoritative records returned by upstream UPES at request time.
- **Auditor Invariant**: **This MUST NOT be presented or reported as proof of a current October 2026 timetable.** Future timetable synchronization will automatically ingest October/November records when UPES publishes them upstream.

### 2. Google Calendar Authorization Status
- Google OAuth is currently expired (`CALENDAR_AUTH_REQUIRED`).
- In accordance with Phase 1A decoupling rules, Google Calendar mutations are strictly halted (`created: 0, updated: 0, deleted: 0`).
- Academic timetable and attendance ingestion succeed completely independently of Google Calendar.
- Resuming Google Calendar sync requires user reauthorization via `/api/auth/google/authorize`.

### 3. Separation of Operational Outcomes
Auditors must strictly distinguish between these four distinct outcomes:
1. **Scheduler Dispatch**: The scheduler job (`job_timetable_sync`) fires every 10,800s and records job status.
2. **Live UPES Fetch**: Direct API calls retrieve and persist authentic university data.
3. **Google Calendar Reconciliation**: Decoupled subsystem that synchronizes local sessions to Google Calendar when OAuth is valid.
4. **Autonomous Token Renewal**: Tier 1 (token) and Tier 2 (refresh token) are active (~10.4 hours remaining). However, multi-day endurance across full OAuth expiration cycles requires long-term tracking.

### 4. Interactive Handoff Limitation
- Upstream UPES SSO protects the login endpoint with **Google reCAPTCHA v2**.
- Unattended direct-HTTP password login without CAPTCHA is blocked by university security controls.
- When all token renewal tiers expire, NexusNode truthfully reports `AUTH_REQUIRED` and provides an interactive handoff checkpoint.

---

## 6. Secret & Security Audit Certification

Prior to publication, an automated regex and entropy scan was conducted across all 57 commits in branch history and all 455 tracked files:
- **JWTs / Bearer Tokens**: 0 found
- **UPES Passwords**: 0 found
- **Google OAuth Secrets**: 0 found
- **Private Keys**: 0 found (test fixture assertions use string labels only)
- **Production SQLite Databases**: 0 tracked
- **Environment Files**: 0 tracked (`.env.example` contains safe placeholders only)
- **LocalToNet Tokens**: 0 tracked

---

## 7. Operational Contact & Reference Endpoints

- **Public Endpoint**: `https://k09oezeyib.localto.net/api/health`
- **Public MCP Gateway**: `https://k09oezeyib.localto.net/api/mcp`
- **Local LAN Host**: `192.168.29.21:5000`
- **Appliance SSH**: `u0_a208@192.168.29.21:8022`
