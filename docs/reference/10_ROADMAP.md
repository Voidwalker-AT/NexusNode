# Project Roadmap

> **Status**: VERIFIED CURRENT  
> **Scope**: Completed milestones, active baseline, near-term schedule, and future architectural horizons  
> **Last verified**: 2026-09-20 (Phase 4.2B Post-Rebase Audit)  
> **Evidence basis**: Architectural review, Phase 4.1C/4.2A acceptance criteria, and system status audit

---

## 1. Completed Milestones

### Phase 1.0 – 2.0: Initial Appliance & Automation Foundation
- Established 24/7 background operation on ARM64 Android (TECNO Spark Go 2024 / BG6) under Termux and `runit`.
- Implemented core Flask REST architecture, SQLite storage engine, and basic UPES student portal scraping.
- Integrated Google Calendar bi-directional synchronization for class timetable blocks.

### Phase 3.0 – 3.5: Multi-Tenant Architecture & Protocol Gateway
- Implemented multi-tenant user isolation (`user_id` scoping across all tables).
- Established Model Context Protocol (MCP) gateway over HTTP/SSE for external LLM reasoning clients.
- Built LMS Blackboard Learn integration, document vault storage, and audit logging.

### Phase 4.0A – 4.0B: Architectural Pivot & Local AI Deprecation
- Identified severe resource exhaustion (OOM crashes, CPU throttling) caused by running local LLMs (Ollama / Qwen) on the 3.7 GB RAM BG6 mobile appliance.
- Formulated Architecture Decision: Deprecate local AI execution on BG6; reposition NexusNode as a 24/7 personal appliance providing persistent state and tools to remote models (Gemini Spark, Mistral).

### Phase 4.1A – 4.1B: Ephemeral Browser Engine & API-First Execution
- Proved feasibility of running headless Chromium inside a `proot-distro` Alpine Linux container on BG6.
- Empirical benchmark: Mean cold start 1.97s, render RSS 320 MB, 100% clean shutdown (0 orphan PIDs across 10 sequential runs).
- Designed `ExecutionRouter` with 3-tier fallback: (1) SQLite cache, (2) Direct HTTP/API, (3) Ephemeral Headless Browser.

### Phase 4.1C: MCP-First Semantic Facade (`nexus-semantic-v1`)
- Implemented high-level semantic facade exposing 11 consolidated MCP tools (`nexus.*`, `academic.*`, `lms.*`, `vault.*`, `system.*`).
- Encapsulated 43+ internal atomic operations beneath semantic tools, reducing LLM context overhead by ~74%.
- Added consequential action guardrails (`ApprovalGrantManager`) requiring human token grants before destructive operations.

### Phase 4.2A: Product & Dashboard Rebase
- Completely rebased the web frontend (`index.html`, `app.js`, `index.css`) around NexusNode's true identity: an academic appliance, MCP server, and automation gateway.
- Removed legacy AI Studio, Ollama controls, local chat UI, and model manager.
- Introduced dedicated, lightweight REST endpoints for the first-party dashboard.

---

## 2. Current Baseline: Phase 4.2B

**Phase 4.2B — Canonical Documentation Rebase, Repository Truth Audit & Post-4.2A Baseline Freeze**
- Conducted full forensic repository audit (397 files cataloged, 687 tests executed, 37 database tables fingerprinted).
- Proved 100% bit-for-bit SHA-256 parity between workstation and remote TECNO BG6 appliance (zero drift).
- Established canonical documentation hierarchy (`docs/reference/`, `docs/architecture/`, `docs/operations/`, `docs/decisions/`, `docs/phases/`).
- Documented 10 authoritative Architecture Decision Records (ADRs).
- Formally cataloged 49 legacy backend and dead-code files for targeted removal.

---

## 3. Near-Term Schedule

### Phase 4.2C: Safe Dead-Code and Legacy Backend Retirement [COMPLETED]
- **Status**: COMPLETE (2026-09-20)
- Excised static prototype UI directory (`stitch_nexusnode_control_interface/`, 47 files, ~8.07 MB).
- Excised obsolete Ollama runit services (`services/ollama/run`, `services/ollama/log/run`).
- Excised obsolete CLI commands (`nexus/commands/ai.py`, `models.py`, `rag.py`) while retaining `media.py` compatibility utility.
- Classified `browser/pinchtab.py` as COMPATIBILITY provider for runtime fallback in `agent/browser_service.py`.
- Reconciled all 21 test failures/errors across 39 test files; achieved 681 passed, 0 failed, 1 skipped, 0 errors.
- Safely dropped genuinely obsolete 0-row tables (`ai_inference_metrics`, `user_chats`) via versioned migration 002 locally and on physical BG6 appliance; verified `consequential_audit_log` is preserved.
- Verified bit-for-bit deployment on BG6 with zero production data drift.

### Phase 4.3A: Academic Results, 3-Hour Calendar Automation, Multi-Account Onboarding & Real MCP [COMPLETED]
- **Status**: COMPLETE (2026-09-20)
- **Pillar A (Results / SGPA / CGPA)**: Authoritative UPES 10-point scale engine (`decimal.Decimal`), dual normalization (ConnectPortal & Exam-Pro), automated discrepancy detection, LKG caching, What-If GPA modeling, REST and semantic MCP endpoints.
- **Pillar B (3-Hour Automation & Google Calendar)**: Persistent 3-hour sync cadence (`10800s`), independent subsystem failure isolation (Calendar reconciliation depends exclusively on trustworthy timetable data), LKG destructive protection (`allow_deletions = False` on empty/stale timetable), calendar idempotence (`CREATE=0` on identical rerun), and 0 Chromium launches.
- **Pillar C (Guided Multi-User Onboarding)**: Authoritative 11-step Admin "+ Add Academic Account" wizard, contextual student self-service 10-point checklist with dynamic `NEXT REQUIRED ACTION`, shared Google OAuth Web App configuration, and Google Cloud Console Testing-mode guidance.
- **Pillar D (Real MCP & LMS Integration)**: Frontier model tool-calling adaptation (Gemini Spark strict typing, Mistral OpenAI function format), exact 11 semantic tools catalog invariant, safe direct HTTP read-only LMS with Vault material download, consequential mutation blocking (`APPROVAL_REQUIRED`), and isolated browser fallback.
- **Verification**: 44 test suites (724 passed, 0 failed, 1 skipped, 0 errors), 10/10 deployment and deep capabilities verified on physical TECNO BG6 appliance.

### Phase 4.3B: Extended Academic Analytics & Real-Time Alerts [NEXT]
- **Objective**: Expand analytics and push alerting on top of the Phase 4.3A foundation.
- **Targets**:
  - Longitudinal performance trends (semester-over-semester SGPA trajectories).
  - WebPush / NTFY alerts on attendance threshold drops and timetable room changes.
  - Automated quota enforcement (Vault storage limits, browser session rate limits).

---

## 4. Long-Term Horizons (Phase 5.0+)

### Phase 5.0: Mobile PWA & Push Notifications
- Progressive Web App (PWA) manifest and service worker for mobile home-screen installation.
- Real-time event notifications via WebPush and UnifiedPush/NTFY (attendance threshold alerts, timetable room changes, assignment deadlines).
- Quick-action widgets for attendance logging and schedule queries.

### Phase 5.1: Automated Assignment Workflows (Human-in-the-Loop)
- Automated LMS assignment brief retrieval and document extraction into Vault.
- AI-assisted draft synthesis via remote MCP reasoning models.
- Strict human approval gating before any submission action is executed.

---

## 5. Experimental / Exploratory Tracks

- **Accessibility-Tree Visual Locator**: Augmenting CDP accessibility tree parsing with bounding-box coordinate mapping for complex dynamic canvas/canvas-rendered student portals.
- **Local Whisper Transcription**: Investigating quantized 4-bit Whisper models for voice queries on BG6 without exceeding the 500 MB appliance memory budget.
- **Federated Calendar Reconciliation**: Multi-calendar bi-directional sync supporting Outlook 365 alongside Google Calendar.
