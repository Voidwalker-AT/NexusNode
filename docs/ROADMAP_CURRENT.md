# NexusNode — Master Operational Roadmap

> **Status**: ACTIVE & CURRENT  
> **Target Appliance**: TECNO BG6 (Android 13 / Termux)  
> **Current Phase**: Phase 0 (Device Reconnaissance & Production Truth)  
> **Last Revised**: 2026-10-21

---

## 1. Phase 0: Reconnaissance & Production Truth (COMPLETED)

- [x] Locate authoritative repository (`E:\Workspace\Active\NexusNode\server`).
- [x] Establish ADB hardware connection to physical TECNO BG6 (`109973141A030946`).
- [x] Restore Termux process supervision (`service-daemon`, `termux-wake-lock`).
- [x] Audit physical compute metrics (2.24 GB free RAM, 30.7 GB storage, 30.6°C cool thermal state).
- [x] Verify production SQLite database integrity (`nexus_unified.db` OK).
- [x] Catalog registered MCP tools (43 tools operational).
- [x] Discover root causes of academic and calendar synchronization stall.

---

## 2. Phase 1: High-Priority Appliance Stabilization (NEXT)

### 1.1 Source Code Alignment & Decoupling Deployment
- Deploy commit `02a70c0` to BG6 so that Google Calendar authorization failure does NOT block UPES timetable fetching.
- Ensure `timetable_sync.py` and `attendance_sync.py` run the latest hardened resilience logic on the phone.

### 1.2 UPES Session Recovery & Live Academic Ingestion
- Execute fresh student session import (`idp_session_info` + OAuth tokens) into `/api/upes/auth/import` via dashboard or authenticated browser extraction.
- Trigger immediate live timetable sync to refresh the 54-day stale cache with current October/November 2026 classes.
- Trigger immediate live attendance sync to ingest current semester lecture punches.

### 1.3 Google Calendar Reauthorization
- Initiate user consent flow on the dashboard (`/api/auth/google/calendar`) to replace the revoked/expired token (`invalid_grant`) with a fresh Google OAuth refresh token.
- Verify end-to-end event reconciliation for current timetable slots without duplicate events.

---

## 3. Phase 2: Unattended Endurance & Boot Hardening

### 2.1 Termux:Boot Installation
- Install official `com.termux.boot` package on the TECNO BG6.
- Verify that `~/.termux/boot/start-nexusnode.sh` reliably acquires `termux-wake-lock` and starts `service-daemon` automatically across physical phone reboots.

### 2.2 Ingress Optimization
- Address LocalToNet free-tier interstitial page or configure alternate egress (Cloudflare Tunnel / DDNS) to guarantee friction-free external MCP client connections (Gemini Spark / Mistral).

### 2.3 Production Data Hygiene
- Clean leaked synthetic records (`student_a`, `student_b`) from `academic_result_sync_history` and `academic_results` in the production database.
