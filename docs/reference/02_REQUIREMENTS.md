# 02. System Requirements Specification

**Status:** VERIFIED CURRENT  
**Scope:** Functional & Non-Functional Contract Requirements  
**Last verified:** 2026-09-20  
**Evidence basis:** Verified product requirements, threat boundaries, mobile hardware constraints  

---

## 1. Functional Requirements

### 1.1 Academic Schedule & Synchronization
- **REQ-ACAD-001 (Continuous Ingestion)**: The system must automatically ingest student timetables on a configurable schedule, extracting session dates, times, rooms, courses, faculty, and attendance criteria.
- **REQ-ACAD-002 (Offline LKG Guarantee)**: If upstream services become unreachable or credentials expire, the system must continue serving the Last-Known-Good (LKG) cached schedule marked with an explicit stale provenance warning.
- **REQ-ACAD-003 (Manual Fallback)**: The system must allow students to manually import timetable schedules via structured JSON files when automated portal scrapers are unavailable.
- **REQ-ACAD-004 (Attendance Tracking)**: The system must track official attendance percentages per enrolled module and maintain fine-grained punch timestamps.
- **REQ-ACAD-005 (Safe Bunk Planning)**: The system must deterministically calculate:
  1. The exact number of future classes a student may safely miss while remaining at or above the mandatory 75% attendance threshold.
  2. The exact number of consecutive attended classes required to recover from a sub-75% attendance deficit.

### 1.2 Google Calendar Synchronization
- **REQ-GCAL-001 (Idempotent Event Reconciler)**: The system must synchronize academic sessions into a student's private Google Calendar without creating duplicate events across multiple sync passes.
- **REQ-GCAL-002 (In-Place Modifications)**: If a class room, faculty member, or schedule time changes upstream, the reconciler must patch the existing Google Calendar event rather than delete and recreate it.
- **REQ-GCAL-003 (Past Event Preservation)**: Schedule cancellations or timetable refreshes must never delete or overwrite past calendar events.

### 1.3 Learning Management System (LMS)
- **REQ-LMS-001 (Course Discovery)**: The system must retrieve active courses, assigned instructors, and course module structures.
- **REQ-LMS-002 (Assignment Tracking)**: The system must parse assignment deadlines, submission statuses, grading rubrics, and overdue alerts.
- **REQ-LMS-003 (Material Vaulting)**: The system must allow students or authorized agents to stream lecture presentations, syllabi, and assignment briefs directly into private Vault storage.

### 1.4 Private Tenant Vault
- **REQ-VAULT-001 (Filesystem Isolation)**: Each student must have a private file storage root. Files uploaded or created by one student must be completely inaccessible to other students.
- **REQ-VAULT-002 (File Operations)**: The system must support listing, searching, streaming upload, streaming download, directory creation, renaming, and deletion.
- **REQ-VAULT-003 (Storage Quotas)**: Individual file uploads must be subject to an enforceable size ceiling (default 500 MB).

### 1.5 Model Context Protocol (MCP) Surface
- **REQ-MCP-001 (Standard Protocol Compliance)**: The appliance must provide an RFC 9728 compliant OAuth 2.0 authorization server and an HTTP/SSE streamable MCP gateway.
- **REQ-MCP-002 (Compact Semantic Catalog)**: The external tool catalog presented to remote LLMs must not exceed 15 tools (target 8–12), with total `tools/list` schema payloads strictly under 12 KB.
- **REQ-MCP-003 (Truthful Provenance)**: All semantic tool responses must return structured metadata indicating execution tier (`api_direct`, `sqlite_cache`, `browser_fallback`), data timestamp, and freshness.

---

## 2. Non-Functional Requirements

### 2.1 Hardware & Performance Ceilings
- **REQ-PERF-001 (Physical Memory Headroom)**: The appliance must maintain at least 1,200 MB of available physical RAM during idle server operation.
- **REQ-PERF-002 (Read Latency)**: Local dashboard summary queries (`/api/dashboard/summary`) and cached academic reads must respond within 100 milliseconds.
- **REQ-PERF-003 (Browser Concurrency)**: On the TECNO BG6 appliance, simultaneous browser executions must be strictly capped at **1** (mutual exclusion). Duplicate concurrent browser requests must be rejected or queued.
- **REQ-PERF-004 (Browser Cold-Start Bounding)**: An on-demand headless browser cold-start must complete within 4.0 seconds.
- **REQ-PERF-005 (Watchdog Hard-Timeout)**: Any ephemeral browser process exceeding 30 seconds of execution must be terminated unconditionally.

### 2.2 Security & Safety Guardrails
- **REQ-SEC-001 (Data Encryption at Rest)**: All student portal passwords, Google OAuth refresh tokens, and sensitive integration credentials must be encrypted at rest using industry-standard authenticated encryption (PBKDF2-HMAC-SHA256 key derivation + AES-256-GCM).
- **REQ-SEC-002 (Zero Secret Exposure)**: Plaintext passwords, authentication tokens, cookies, or cryptographic keys must never be logged to disk, echoed in REST API error bodies, or returned in MCP tool output.
- **REQ-SEC-003 (Zero Agent Self-Approval)**: Autonomous AI clients must never be permitted to approve their own consequential action requests.
- **REQ-SEC-004 (Immutable Action Hashes)**: Consequential actions must be cryptographically bound to a SHA-256 digest of their exact input parameters. Any parameter deviation between approval and execution must cause an immediate abort.
- **REQ-SEC-005 (Network Boundary Defense)**: Headless browser sessions must enforce Server-Side Request Forgery (SSRF) protections, restricting navigation exclusively to whitelisted academic and identity domains.

### 2.3 Reliability & Self-Healing
- **REQ-REL-001 (Zero Browser Daemon Invariant)**: Headless Chromium must never run as a persistent background daemon. 100% of Chromium processes must be terminated following observation or action.
- **REQ-REL-002 (Continuous Uptime)**: The core appliance WSGI server and SSH maintenance daemons must be supervised by `termux-services` (runit), ensuring automatic restart within 2 seconds of unexpected failure.
- **REQ-REL-003 (Battery & Thermal Safety)**: When battery level falls below 15% or device temperature exceeds critical thresholds, background automation jobs must pause non-essential browser tasks.
