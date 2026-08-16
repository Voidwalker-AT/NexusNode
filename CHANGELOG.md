# 📝 Changelog

All notable changes to the **NexusNode** project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [2.3.4] - 2026-08-16

### 🔧 Universal Remote CLI Live API Contract Repair

#### Fixed & Standardized
- **Centralized Normalization Layer (`nexus/normalize.py`)**:
  - Implemented authoritative response normalizers (`normalize_list`, `normalize_dict`, `normalize_models`, `normalize_task`, `normalize_tasks`, `normalize_system_status`, `normalize_services`, `normalize_rag`) to cleanly decouple remote REST payloads from UI formatting.
  - Transparently accepts both top-level JSON arrays (`[...]`) and wrapped dictionary responses (`{"models": [...]}`) across all CLI command modules.
  - Eliminated synthetic default zeros: missing or unavailable backend fields now render cleanly as `UNAVAILABLE` or `N/A` instead of fabricating false `0 MB / 1 MB` or `0 B free of 0 B` telemetry.
- **AI Models & State Endpoint Contract Repair (`nexus ai models`, `nexus models list`)**:
  - Resolved `[ERROR] Failed to fetch AI models (HTTP 200)` caused by rigid dictionary assumptions on the Ollama registry endpoint (`/api/ai/models`).
  - Correctly renders model names, parameters, family, and quantization levels from top-level list payloads.
- **System Telemetry & Resource Rendering (`nexus status`)**:
  - Synchronized schema parsing with `/api/system/status` (`memory.used_mb`, `disk.free_gb`, `battery.level`, `thermal.temp_c`, `services.*`).
  - Preserved real zero values while flagging unavailable metrics.
- **Task State & Lifecycle Separation (`nexus tasks list`, `nexus tasks status`)**:
  - Separated authoritative task `STATUS` and processing `STAGE` into distinct table columns.
  - Added visible warnings on contradictory task states (e.g., `STATUS=COMPLETED` with `STAGE=QUEUED`) rather than silently masking them.
  - Exposed live transfer speed (`MB/s`) and estimated completion (`ETA`) across background tasks.
- **Media Queue & Task ID Integration (`nexus media queue`, `nexus media download`)**:
  - Derived the media queue strictly from canonical task records (`type=media_download`), showing active speed, ETA, progress, and stage.
  - Made `media download` return and display server-assigned `task_id` (`task-...`) on submission.
- **Vault Directory & Metadata Normalization (`nexus vault list`)**:
  - Summed file sizes across non-directory items and displayed `FOLDER` for directory categories rather than `0 B`.
- **Administrative Endpoints & HTTP 201/204 Support**:
  - Standardized `logs recent`, `backups list/create`, `automation list`, `shares list`, `users list`, `services status`, and `diagnostics` to accept valid 200, 201, 202, and 204 HTTP status codes with robust list/dict normalization.
- **Comprehensive Regression Test Suite (157 Tests Passing)**:
  - 36 dedicated CLI tests in `tests/test_nexus_client.py` validating real schema parsing, array handling, HTTP 200/201/204 responses, task contradiction warnings, and folder metadata.

---

## [2.3.3] - 2026-08-16

### 💻 Universal Remote CLI Redesign & Polished Terminal Experience

#### Added & Improved
- **Dedicated Worldwide Connection UX (`nexus connect <url>`)**:
  - Primary connection flow connects to remote NexusNode servers across any network (Wi-Fi, mobile data, CGNAT, LocalToNet HTTPS tunnel) with zero SSH or Termux dependency.
  - Interactive connection sequence features a compact ASCII/Unicode header banner, step-by-step progress verification (`Endpoint`, `TLS`, `API`), and a real-time server metadata panel with roundtrip ping latency in milliseconds.
  - Smart login prompt: directly prompts for `Password:` when `--user` is provided, avoiding redundant username prompts.
- **HTTP 200 Bug Fix & Robust Response Handling**:
  - Eliminated the client-side `[!] Error: HTTP 200` bug by safely parsing session tokens and user identity from both root-level dictionaries and nested `resp["user"]` structures.
  - Implemented explicit HTML / WAF detection: if a public proxy or tunnel serves HTML instead of expected JSON, the CLI reports actionable diagnostic hints rather than generic status code errors.
  - Applied LocalToNet tunnel bypass headers (`localtonet-skip-warning: true`) only when connecting to verified LocalToNet domains.
- **Polished Application REPL (`nexus>` Shell)**:
  - Role-aware command categorization in `help` (SYSTEM, STORAGE, MEDIA, TASKS, AI, RAG, ACCOUNT, and ADMIN for administrators).
  - Dynamic tab autocompletion (`complete_*`) scoped by user permissions.
  - Clear rejection of arbitrary OS shell commands (`bash`, `rm`, `ls`) with helpful command guidance.
- **Task & Media Queue Integration**:
  - Integrated authoritative SQLite task state machine displaying real-time stages (`QUEUED`, `STARTING`, `RUNNING`, `POST_PROCESSING`, `VERIFYING`, `COMPLETED`, `CANCELLED`).
  - Active download status displays formatted speed (`MB/s`) and estimated completion time (`ETA`).
- **Cross-Platform Convenience Launchers**:
  - Added `nexus.bat` for Windows and `nexus_launcher` / `bin/nexus` POSIX scripts for Linux, macOS, and Termux.
- **Expanded Test Suite (155 Tests Passing)**:
  - Added 34 dedicated unit tests in `tests/test_nexus_client.py` covering token extraction, URL normalization, WAF detection, 401/403/429/500 error responses, tab completion, and task lifecycle rendering.

---

## [2.3.2] - 2026-08-16

### 🛡️ Deep Task Queue & Vault Internal Files Security Repair

#### Fixed & Hardened
- **Authoritative SQLite Task State Machine**:
  - Promoted SQLite `background_tasks` to the authoritative persistent state store across all task transitions, decoupling execution state from volatile memory caches.
  - Added explicit lifecycle stages: `QUEUED` -> `STARTING` -> `RUNNING` / `DOWNLOADING` -> `POST_PROCESSING` -> `VERIFYING` -> `COMPLETED`, with failure and cancellation states (`CANCELLING` -> `CANCELLED`, `FAILED`).
  - Implemented output verification gate: tasks only reach `COMPLETED` when the destination media file is physically verified on disk with non-zero byte size and zero partial residue (`.part` / `.ytdl`).
  - Added robust process-tree termination (`terminate_process_tree`) supporting POSIX session process groups and Windows `/T /F` process-tree termination, guaranteeing zero orphaned `yt-dlp` or `ffmpeg` child processes on task cancellation.
  - Normalized task schema with canonical ISO-8601 UTC timestamp strings (`created_at`, `started_at`, `updated_at`, `completed_at`), download speed (`speed_bps`), and ETA (`eta_seconds`).
- **Protected Internal Files & Vault Boundary Enforcement**:
  - Implemented authoritative `is_protected_internal_path` helper resolving real paths and preventing directory traversal and symlink escapes.
  - Enforced system-wide isolation across `/files`, `/download/<path>`, `/stream/<path>`, `/files/<path>` (DELETE), `/upload`, `/api/shares`, `/s/<token>`, and `/api/vault/checksum/<path>`.
  - Guaranteed internal databases (`nexus_vault.db*`, `rag_vault.db*`), RAG indexes (`rag_index.json`), configuration (`server_config.json`, `.env*`), and sensitive system folders (`__pycache__`, `.git`, `.ssh`, `.tmp`, `backups`, `.localtonet`) are never exposed as user-manageable Vault objects.
  - Updated folder zip generator in `/download/<folder>` to recursively exclude all protected internal files.
- **Frontend & CLI Synchronization**:
  - Added defensive `formatTimestamp()` utility in `static/js/app.js` supporting both numeric epoch and string timestamps, eliminating `t.created_at.substring is not a function` errors.
  - Updated Media Center queue counter to reflect `${activeCount} ACTIVE • ${queuedCount} QUEUED` and automatically reload the media library upon download completion.
  - Properly escaped and string-quoted task IDs in `cancelTask('...')` calls.
  - Hardened Universal Remote CLI `nexus tasks` and `nexus media` commands to seamlessly accept both list and dictionary server responses.
- **Test Suite Expansion**:
  - Added regression test suites `test_51_protected_internal_paths_policy_and_vault_isolation`, `test_52_folder_zip_excludes_protected_files`, and `test_53_task_queue_sqlite_persistence_and_lifecycle_stages`.
  - All **138 unit, client, and security tests** passing with 100% OK.

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
