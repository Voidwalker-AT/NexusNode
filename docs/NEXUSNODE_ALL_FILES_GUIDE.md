# NexusNode Comprehensive File Inventory & Repository Guide

> **Status**: VERIFIED CURRENT  
> **Scope**: Exhaustive inventory and architectural mapping of all 397 repository files across active, generated, test, and legacy tiers  
> **Last verified**: 2026-09-20 (Phase 4.2B Post-Rebase Audit)  
> **Evidence basis**: Automated crawler output `scripts/audit_inventory.json` (397 files verified, 94 Python source, 12 web, 41 tests, 41 docs, 6 configs, 12 deployment, 124 generated/runtime, 50 legacy/dead-code)

---

## 1. Repository File Hierarchy Overview

```
NexusNode/
├── agent/                       # Core MCP gateway, semantic facade, routing, and policy (19 files)
├── browser/                     # Ephemeral headless Chromium automation & CDP engine (10 files)
├── upes/                        # UPES academic portal authentication, scraping, and tracking (10 files)
├── lms/                         # Blackboard Learn LMS REST integration (6 files)
├── nexus/                       # Administrative CLI client & management utilities (27 files)
├── static/                      # Modern first-party web dashboard assets (HTML, CSS, JS) (12 files)
├── services/                    # Runit process supervisor configuration scripts (12 files)
├── storage_vault/               # Persistent SQLite database, artifacts, and user sandboxes (124+ files)
├── tests/                       # Complete automated verification suite (39 files, 682 tests)
├── docs/                        # Canonical documentation system (41 files)
└── scripts/                     # Forensic audit, drift detection, and benchmarking tools (11 files)
```

---

## 2. Directory Breakdown & Subsystem Mapping

### A. Root Application & Entrypoints (10 Files)
- [`app.py`](file:///e:/Workspace/Active/server/app.py): Primary WSGI application entrypoint; boots Waitress server on `127.0.0.1:5000`.
- [`config.py`](file:///e:/Workspace/Active/server/config.py): Global configuration, environment variable loader, and directory path constants.
- [`attendance_sync.py`](file:///e:/Workspace/Active/server/attendance_sync.py): Background zero-touch cron worker for student attendance synchronization.
- [`timetable_sync.py`](file:///e:/Workspace/Active/server/timetable_sync.py): Google Calendar bi-directional timetable reconciliation worker.
- [`resource_governor.py`](file:///e:/Workspace/Active/server/resource_governor.py): Host system CPU, memory, and zram governor.
- [`nexus_admin.py`](file:///e:/Workspace/Active/server/nexus_admin.py): Administrative terminal management tool.
- [`nexus_shell.py`](file:///e:/Workspace/Active/server/nexus_shell.py): Interactive diagnostic console.
- [`deploy_to_bg6_ssh.py`](file:///e:/Workspace/Active/server/deploy_to_bg6_ssh.py): Automated deployment script pushing changes to BG6 over SSH.
- [`deploy_phase42a.py`](file:///e:/Workspace/Active/server/deploy_phase42a.py): Phase 4.2A release deployment automation.
- [`verify_bg6_live.py`](file:///e:/Workspace/Active/server/verify_bg6_live.py): Live HTTP/SSE health verification against deployed appliance.

### B. Agent & Semantic MCP Gateway (`agent/`, 19 Files)
- [`agent/semantic_facade.py`](file:///e:/Workspace/Active/server/agent/semantic_facade.py): Canonical definition of the 11 semantic tools (`nexus-semantic-v1`).
- [`agent/execution_router.py`](file:///e:/Workspace/Active/server/agent/execution_router.py): 3-tier dispatch engine (SQLite Cache -> Direct HTTP -> Ephemeral Browser).
- [`agent/mcp_server.py`](file:///e:/Workspace/Active/server/agent/mcp_server.py): MCP protocol transport server supporting SSE and JSON-RPC.
- [`agent/mcp_auth.py`](file:///e:/Workspace/Active/server/agent/mcp_auth.py): Bearer token validation and multi-tenant user context injection.
- [`agent/mcp_client.py`](file:///e:/Workspace/Active/server/agent/mcp_client.py): MCP client connector for external agent communications.
- [`agent/consequential.py`](file:///e:/Workspace/Active/server/agent/consequential.py): Human approval grant challenge and validation engine.
- [`agent/policy.py`](file:///e:/Workspace/Active/server/agent/policy.py): Role-based access control (RBAC) and tool permission policies.
- [`agent/rate_limiter.py`](file:///e:/Workspace/Active/server/agent/rate_limiter.py): In-memory and sliding-window rate limiters.
- [`agent/registry.py`](file:///e:/Workspace/Active/server/agent/registry.py): Registry of 43+ internal atomic operations.
- [`agent/sanitizer.py`](file:///e:/Workspace/Active/server/agent/sanitizer.py): Accessibility tree and HTML string sanitizer.
- [`agent/status_service.py`](file:///e:/Workspace/Active/server/agent/status_service.py): System health and metrics collection service.
- [`agent/lms_service.py`](file:///e:/Workspace/Active/server/agent/lms_service.py): Higher-level LMS business logic wrapper.
- [`agent/vault_service.py`](file:///e:/Workspace/Active/server/agent/vault_service.py): Vault storage service and document indexer.
- [`agent/browser_service.py`](file:///e:/Workspace/Active/server/agent/browser_service.py): Agent interface for ephemeral browser actions.
- [`agent/oauth_provider.py`](file:///e:/Workspace/Active/server/agent/oauth_provider.py): Third-party OAuth 2.0 provider endpoints.
- [`agent/models.py`](file:///e:/Workspace/Active/server/agent/models.py): Data models and Pydantic/dataclass schemas.
- [`agent/errors.py`](file:///e:/Workspace/Active/server/agent/errors.py): Standardized JSON-RPC and MCP error taxonomy.

### C. Ephemeral Browser Engine (`browser/`, 10 Files)
- [`browser/chromium_runtime.py`](file:///e:/Workspace/Active/server/browser/chromium_runtime.py): Proot-distro Chromium process management, concurrency lock, and watchdog reaper.
- [`browser/bg6_cdp.py`](file:///e:/Workspace/Active/server/browser/bg6_cdp.py): Direct WebSocket client for Chrome DevTools Protocol.
- [`browser/cdp_client.py`](file:///e:/Workspace/Active/server/browser/cdp_client.py): High-level CDP session abstraction.
- [`browser/observation.py`](file:///e:/Workspace/Active/server/browser/observation.py): Accessibility tree extractor and visual locator.
- [`browser/camofox.py`](file:///e:/Workspace/Active/server/browser/camofox.py): Anti-fingerprinting and stealth profile configuration.
- [`browser/profile_manager.py`](file:///e:/Workspace/Active/server/browser/profile_manager.py): Ephemeral browser profile directory sandboxing.
- [`browser/base.py`](file:///e:/Workspace/Active/server/browser/base.py): Abstract browser interface definitions.
- [`browser/pinchtab.py`](file:///e:/Workspace/Active/server/browser/pinchtab.py): *[LEGACY]* Superseded Phase 3.4 PinchTab bridge code.

### D. UPES Academic Portal Engine (`upes/`, 10 Files)
- [`upes/auth.py`](file:///e:/Workspace/Active/server/upes/auth.py): Portal authentication and session cookie jar manager.
- [`upes/tracker.py`](file:///e:/Workspace/Active/server/upes/tracker.py): Attendance scraper, parser, and percentage calculator.
- [`upes/router.py`](file:///e:/Workspace/Active/server/upes/router.py): HTTP request router with retry logic for university portals.
- [`upes/credentials.py`](file:///e:/Workspace/Active/server/upes/credentials.py): Encrypted credential storage and retrieval API.
- [`upes/crypto.py`](file:///e:/Workspace/Active/server/upes/crypto.py): AES-256-GCM cipher and key derivation implementation.
- [`upes/session.py`](file:///e:/Workspace/Active/server/upes/session.py): Session state representation and serialization.
- [`upes/validators.py`](file:///e:/Workspace/Active/server/upes/validators.py): Input validation for student IDs, passwords, and date ranges.
- [`upes/models.py`](file:///e:/Workspace/Active/server/upes/models.py): Data models for attendance records and class sessions.

### E. Blackboard Learn LMS Engine (`lms/`, 6 Files)
- [`lms/base.py`](file:///e:/Workspace/Active/server/lms/base.py): Base LMS client and REST communication primitives.
- [`lms/moodle.py`](file:///e:/Workspace/Active/server/lms/moodle.py): Moodle / Blackboard REST endpoint parser.
- [`lms/models.py`](file:///e:/Workspace/Active/server/lms/models.py): Data models for courses, assignments, and grades.
- [`lms/errors.py`](file:///e:/Workspace/Active/server/lms/errors.py): LMS-specific error handling and exceptions.

### F. Frontend Web Dashboard (`static/` & `index.html`, 12 Files)
- [`index.html`](file:///e:/Workspace/Active/server/index.html): Clean, rebased single-page application entrypoint.
- [`static/css/index.css`](file:///e:/Workspace/Active/server/static/css/index.css): Responsive dashboard stylesheet.
- [`static/js/app.js`](file:///e:/Workspace/Active/server/static/js/app.js): Modern vanilla JavaScript root controller.
- [`static/js/academics.js`](file:///e:/Workspace/Active/server/static/js/academics.js): Academic tab UI controller and attendance cards.
- [`static/js/accounts.js`](file:///e:/Workspace/Active/server/static/js/accounts.js): User profile and academic credentials manager.
- [`static/js/api.js`](file:///e:/Workspace/Active/server/static/js/api.js): REST client communication layer.
- [`static/js/dashboard.js`](file:///e:/Workspace/Active/server/static/js/dashboard.js): Main dashboard metrics and timetable views.
- [`static/js/diagnostics.js`](file:///e:/Workspace/Active/server/static/js/diagnostics.js): System status, memory, and log viewer.
- [`static/js/mcp.js`](file:///e:/Workspace/Active/server/static/js/mcp.js): MCP semantic catalog and token status.
- [`static/js/settings.js`](file:///e:/Workspace/Active/server/static/js/settings.js): System settings and preferences.
- [`static/js/ui.js`](file:///e:/Workspace/Active/server/static/js/ui.js): Common modal, toast, and tab navigation utilities.
- [`static/js/vault.js`](file:///e:/Workspace/Active/server/static/js/vault.js): Vault storage and file management controller.

### G. Supervised Services (`services/`, 10 Files)
- `services/nexusnode/run`: Main Waitress application runner script.
- `services/nexusnode/log/run`: Application logger script.
- `services/localtonet/run`: Ingress tunnel daemon runner script.
- `services/localtonet/log/run`: Tunnel logger script.
- `services/cloudflared/run`: Secondary tunnel runner script (marked down).
- `services/cloudflared/log/run`: Secondary tunnel logger script.
- `services/ollama/*`: *[RETIRED]* Obsolete runit scripts deleted in Phase 4.2C Stage 2.

### H. Test Suites (`tests/`, 39 Files)
- 39 automated test execution suites covering 682 tests (681 passing, 0 failing, 1 skipped, 0 errors).
- Detailed breakdown in [`09_TESTING_AND_VERIFICATION.md`](file:///e:/Workspace/Active/server/docs/reference/09_TESTING_AND_VERIFICATION.md).

### I. Persistent Storage (`storage_vault/`, 124+ Files)
- [`storage_vault/nexus_unified.db`](file:///e:/Workspace/Active/server/storage_vault/nexus_unified.db): Unified multi-tenant SQLite database (5.6 MB, 37 tables, WAL mode).
- `storage_vault/artifacts/`: Empirical benchmark outputs, logs, and generated public summaries.
- `storage_vault/backups/`: Automated snapshot database backups.
- `storage_vault/users/`: Partitioned user document vaults.

### J. Retired UI Mockups (`stitch_nexusnode_control_interface/`, 47 Files)
- *[RETIRED in Phase 4.2C]* 47 static prototype mockup files (~8.07 MB) excised in Stage 1. Production UI is served exclusively from `index.html` and `static/`.
