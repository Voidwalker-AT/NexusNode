# NexusNode Phase 3.6A Deployment Report: TECNO BG6 Production Appliance

## 1. Deployment Overview
- **Deployment Target**: TECNO BG6 (Android 13 / Termux aarch64, ~4 GB RAM)
- **Deployment Host / User**: `192.168.29.211:8022` (`u0_a208`)
- **Deployment Method**: Direct SFTP Manifest Transfer & Controlled Service Restart
- **Appliance Status**: **HEALTHY** (Port 5000, Process PID 6694)
- **Deployment Timestamp**: 2026-08-31T01:23:45+05:30

---

## 2. Pre-Deployment Baseline & Backup
- **BG6 State Prior to Deployment**: STALE (missing `agent/consequential.py`, `agent/lms_service.py`, `lms/` directory, `agent/mcp_auth.py`, `agent/mcp_server.py`)
- **Pre-Deployment Backup Location**: `/data/data/com.termux/files/home/nexusnode-deploy-backups/20260831_011900/`
- **Backup Artifacts**:
  - `nexus_unified.db.bak` (2,572,288 bytes, `integrity_check = ok`)
  - `nexus_vault.db.bak` (471,040 bytes)
  - `rag_vault.db.bak` (40,960 bytes)
  - `.env.bak` (215 bytes)
  - `.nexus_secret.bak` (64 bytes)
  - `server_snapshot.tar.gz` (32,326,483 bytes)

---

## 3. Dependency Verification & Installation
- **Python Runtime**: Python 3.14.6 (Clang 21.0.0 aarch64)
- **Pre-existing Packages**: `flask`, `requests`, `cryptography`, `sqlite3`, `urllib3`
- **Installed Missing Dependencies**:
  - `pypdf` (6.16.2)
  - `reportlab` (5.0.1)

---

## 4. Deployment Manifest
- **Total Files Deployed / Updated**: 46 files
  - **Added Files (31)**: `agent/consequential.py`, `agent/lms_service.py`, `agent/mcp_auth.py`, `agent/mcp_client.py`, `agent/mcp_server.py`, `agent/rate_limiter.py`, `agent/sanitizer.py`, `agent/status_service.py`, `agent/vault_service.py`, `agent/browser_service.py`, `lms/base.py`, `lms/moodle.py`, `lms/models.py`, `lms/errors.py`, `lms/__init__.py`, `upes/crypto.py`, `upes/models.py`, `upes/tracker.py`, `docs/*` (13 documents).
  - **Modified Files (15)**: `app.py`, `config.py`, `timetable_sync.py`, `attendance_sync.py`, `resource_governor.py`, `agent/errors.py`, `agent/models.py`, `agent/policy.py`, `agent/__init__.py`, `upes/auth.py`, `upes/credentials.py`, `upes/router.py`, `upes/session.py`, `upes/__init__.py`, `browser/pinchtab.py`.
  - **Unchanged Files (19)**: Static assets, license, templates.

---

## 5. Non-Destructive Database Migration
- **Target Database**: `storage_vault/nexus_unified.db` (Preserved in place, zero data loss)
- **Pre-Migration Integrity**: `ok`
- **Post-Migration Integrity**: `ok`
- **Total Tables**: 35 tables
- **Consequential Schema Verified**:
  - `consequential_actions`: Present
  - `approval_requests`: Present
  - `approval_grants`: Present
  - `consequential_audit_log`: Present
  - `submission_plans`: Present
  - `agent_tokens`: Present
- **Existing User Accounts**: `admin`, `papa` (100% Preserved)
- **User Timetables**: 1 row (100% Preserved)
- **Google OAuth Tokens**: 1 row (100% Preserved)
- **Calendar Event Mappings**: 84 rows (`cslot_v1` mappings 100% Preserved)

---

## 6. Service Supervision & Restart Verification
- **Old PID**: 9547 (Stopped cleanly, port 5000 released)
- **New PID (First Start)**: 5919
- **Controlled Restart (Second Start)**: PID 6694
- **Running Instances**: Exactly 1 instance on port 5000
- **Timetable Scheduler**: Exactly 1 instance (`job_timetable_sync`, interval = `10800` seconds)
- **Calendar Policies**: Full-Semester Policy (`SYNC_FULL_SEMESTER = True`), LKG Deletion Guard (`LKG_RETENTION_ENABLED = True`)

---

## 7. MCP Gateway & Smoke Test Verification
- **MCP Protocol**: `2026-07-28`
- **Total Tools Count**: **43 Tools**
- **Phase 3.6A Tools**:
  - `lms.submit_assignment`: **PRESENT** (`RiskClass.CONSEQUENTIAL`)
  - `action.status`: **PRESENT** (`RiskClass.READ_ONLY`)
- **Spark Agent Token Verification**: Passed (verified via `Bearer` token auth against `/api/mcp`)
- **Remote Tool Executions**:
  - `nexus.status`: Passed (`HEALTHY`, Uptime active, TECNO BG6)
  - `upes.get_next_classes`: Passed (`SMDM3014_3`, `CSEG3056_3`, `CSAI3027P_5`)
  - `lms.list_courses`: Passed (transport: `direct_http`)
  - `action.status`: Passed (truthfully returns `ACTION_NOT_FOUND` on invalid ID)

---

## 8. System Resources
- **RAM Total**: 3,861,584 kB (~3.8 GB)
- **RAM Available**: 1,365,844 kB (~1.36 GB free)
- **Storage Free**: 28,371 MB (~28.3 GB free)
- **NexusNode RSS**: ~16.8 MB (Lightweight memory footprint)
