# 📝 Changelog

All notable changes to the **NexusNode** project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [2.3.1] - 2026-08-16

### 🚀 Live Functionality & Performance Audit & Repair

#### Fixed & Optimized
- **API Endpoint Performance & Latency Overhaul**:
  - Reduced `/api/system/status` polling latency from ~3.9s to ~1.5s (>60% reduction) by short-circuiting dead daemon probes.
  - Reduced `/api/ai/state` probe latency from ~3.5s to ~1.0s (>70% reduction) with immediate exit when Ollama engine is offline, eliminating sequential HTTP socket timeouts.
  - Reduced `/api/admin/diagnostics/full-report` latency from ~3.6s to ~1.0s (>70% reduction).
- **Service Badge & Status Normalization**:
  - Fixed NexusNode reporting `STOPPED` while actively serving requests by checking `status === 'online'`, `running`, and active `pid`.
  - Aligned OpenSSH, LocalToNet, and Ollama service telemetry parsing across all backend states.
- **AI Studio Model Loading & Residency**:
  - Fixed model selector hanging indefinitely on *"Loading installed models..."* by supporting both raw JSON arrays and wrapped object payloads.
  - Concurrently queried `/api/ai/models` and `/api/ai/state` via `Promise.allSettled()`.
- **SQLite Database Schema Auto-Migration**:
  - Resolved HTTP 500 error on `/api/backups` caused by column naming mismatch (`filepath` vs `file_path`) with automatic `PRAGMA table_info` schema migration.
- **Resilient UI Data Loaders & Non-Destructive Error States**:
  - Implemented graceful loading indicators and visible `UNAVAILABLE` / `ERROR` messages for Vault, Media Library, Task Supervision, Backups, Events, Storage Intelligence, and Admin Users.
  - Registered `/api/system/storage-intel` route alias to `/api/storage/intelligence`.
  - Added `case 'network': loadNetworkInterfaces(); break;` in client-side `switchTab()` router.
- **Frontend Concurrency & Timeout Hardening**:
  - Integrated 8-second `AbortController` timeout inside `apiFetch()` to eliminate stalled promises.
  - Added an in-flight polling guard (`isPollingSystemStatus`) to prevent duplicate overlapping poll requests.
- **Expanded Test Suite**:
  - Verified 100% pass rate across all 135 unit, client, and integration tests (`python -m unittest tests/test_server.py tests/test_nexus_client.py`).

---

## [2.3.0] - 2026-08-16

### 🎨 Canonical Google Stitch UI & Hardened Diagnostics Runtime

#### Added
- **Canonical Google Stitch Design System**:
  - Implemented exact design tokens from `stitch_nexusnode_control_interface/nexusnode/DESIGN.md`: OLED Pitch Black (`#000000`), Graphite (`#121212`, `#1c1b1b`, `#201f1f`), 1px structural borders (`#2C2C2C`), Primary Cyan (`#00daf3`), AI Purple (`#dab9ff`/`#602b9d`), and Inter + JetBrains Mono typography.
  - Responsive desktop 12-column grid and mobile viewport reflow (375x667, 390x844, 412x915) with sticky device identity strip, thumb-friendly quick directives, slide-up utilities sheet (`.drawer-content`), and bottom navigation bar (`>=44px` touch targets).
- **Authoritative Ollama Model Serving & Memory Architecture**:
  - Strict separation of concepts: `selected_model` (user target), `installed_models` (`/api/tags`), and `loaded_model` (`/api/ps`).
  - Real-time RAM/VRAM residency calculations from live `/api/ps` metrics.
  - Single authoritative runit supervision (`sv up/down/restart ollama`), zero unmanaged subprocesses.
  - Keep-alive management (`0`, `5m`, `15m`, `30m`).
- **Automated Root-Cause Diagnostics**:
  - Automated diagnostic analyzer (`GET /api/admin/diagnostics/full-report`) returning structured problem findings (Problem, Severity, Evidence, Likely Cause, Recommendation).
  - Process memory table with measured PID, RSS, PSS, VMS, open file descriptors, and thread counts.
  - On-demand performance profile snapshots (`POST /api/admin/diagnostics/profile-snapshot`).
  - Data-driven telemetry labels (`MEASURED`, `ESTIMATED`, `UNAVAILABLE`).
- **SQLite FTS5 Full-Text Search RAG Engine**:
  - High-efficiency SQLite FTS5 inverted index with BM25 ranking and chunking.
  - Source folder scoping (`docs`, `notes`, `code`), binary/media format exclusion, and index compaction.
- **Vault File Manager Enhancements**:
  - Folder navigation and subfolder browsing with parent links (`..`).
  - Automatic `.gitkeep` placeholder filtration.
  - On-the-fly zip compression and download for folders (`GET /download/<path>` or folder zip action).
- **Security & RBAC Matrix Hardening**:
  - Complete elimination of hardcoded default passwords in source code and initialization logic (`NEXUS_ADMIN_PASSWORD` env or cryptographically secure token generator).
  - Object-level task ownership isolation.
  - Multi-tier RBAC authorization (Anonymous = 401, User = 403, Admin = 200).
- **Expanded Test Suite (53 Tests Passing)**:
  - 53 unit, integration, and security tests verifying all subsystems.

#### Fixed
- Fixed task cancellation ownership bug to ensure database-backed background tasks can be aborted cleanly.
- Fixed vault `.gitkeep` clutter and directory download handling.

---

## [2.2.1] - 2026-08-15

### 🛡️ UX, Navigation & Session Isolation Security Pass

#### Added
- **Single Source of Truth Auth State**: Centralized reactive frontend `authState` store ensuring clean session management, token storage, and instantaneous privilege reactivity.
- **Granular Least-Privilege RBAC Matrix**: Distinguishes Core Users from Administrators with granular privileges.
- **Streamlined Navigation & Collapsible More Menu**: Redesigned Desktop Header and Mobile bottom dock with touch targets $\ge 44\text{px}$.
- **Toast Notification Engine**: Non-blocking user notifications for HTTP 403 access denials and action confirmations.

#### Fixed
- **Admin Hub Leak Isolation**: Fixed issue where Admin Hub or admin DOM state could linger after an admin logged out.
- **Differentiated 401 vs 403 API Handling**: Forbidden actions (403) notify without session destruction; invalid tokens (401) clean up session.

---

## [2.2.0] - 2026-08-15

### 🚀 Personal Mobile Server Appliance Evolution

#### Added
- **Thermal & Hardware Governance**: Telemetry probing via `termux-battery-status` and sysfs thermal zones. Implemented 4-tier thermal state machine (`NORMAL`, `WARM`, `THROTTLED`, `CRITICAL`).
- **Advanced Media Center**: Support for yt-dlp extraction across 7 formats with HTTP 206 Range streaming.
- **Temporary Secure Share Links**: Scoped share URLs with custom expiration and instant revocation.
- **Storage Intelligence & Safe Temp Cleaner**: Volume breakdown by media category and large-file detection.
- **Atomic System Backups**: Live SQLite backup using `sqlite3.backup()` API and SHA-256 verified zips.
- **All-in-One Appliance Launcher (`start_nexus.sh`)**: CLI manager over runit.

---

## [2.0.0] - 2026-08-10

### 🛡️ 24/7 Mobile Hardening & Supervision
- Centralized `config.py` configuration registry.
- `resource_governor.py` for RAM and disk pressure monitoring.
- `termux-services` (runit) process supervisor definitions.
- `Termux:Boot` auto-startup integration with Android CPU WakeLock.
- SQLite WAL mode and transaction locking (`DB_LOCK`).
- SSE live audit log streaming.

---

## [1.0.0] - 2026-08-01

### Initial Release
- Basic Flask server prototype on Termux.
- User authentication and role-based access control.
- File upload and download vault.
- yt-dlp media downloader.
- Local Ollama AI chat integration.
