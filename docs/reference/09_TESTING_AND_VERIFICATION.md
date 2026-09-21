# Testing and Verification Reference

> **Status**: VERIFIED CURRENT  
> **Scope**: Test suites, test architecture, verification methodology, and empirical execution metrics  
> **Last verified**: 2026-09-20 (Phase 4.3A Production Verification Audit)  
> **Evidence basis**: Automated execution of 44 test files via `scripts/audit_test_suite.py` on Python 3.13; live execution on physical TECNO BG6 appliance via `scripts/deploy_phase43a_bg6.py`

---

## 1. Overview and Verification Architecture

NexusNode maintains an automated test suite comprising 44 test files across unit, integration, contract, and end-to-end boundaries. Verification enforces multi-tenant security, schema conformance, API-first fallback pipelines, Google Calendar synchronization, ephemeral browser execution invariants, academic results normalization, 3-hour scheduling, and MCP client compatibility.

### Test Execution Metrics (Phase 4.3A Production Audit)

The full test suite was audited and executed sequentially on 2026-09-20 following Phase 4.3A implementation. The official measured metrics are:

| Metric | Measured Value | Notes |
|---|---|---|
| **Total Test Files** | `44` | Located in `tests/` |
| **Total Tests Discovered** | `725` | Collected across all 44 test suites |
| **Tests Passed** | `724` | `99.86%` pass rate |
| **Tests Failed** | `0` | Zero failures across entire suite |
| **Tests Skipped** | `1` | `test_phase34_live_pinchtab.py` (requires live PinchTab bridge on host) |
| **Test Errors** | `0` | Zero syntax, import, or unhandled runner crashes |
| **Total Duration** | `195.87 seconds` | Full sequential regression audit |

---

## 2. Test Suite Classification

The 44 test files are categorized into distinct operational layers:

### A. Core Architecture and Server Verification
- [`test_server.py`](file:///e:/Workspace/Active/server/tests/test_server.py): 134 tests (134 passed). Validates core Flask/Waitress endpoints, database connection pooling, service initialization, and legacy route backward compatibility.
- [`test_startup_order.py`](file:///e:/Workspace/Active/server/tests/test_startup_order.py): 8 tests (8 passed). Confirms zero-dependency startup sequence, database migrations, and clean subsystem booting.
- [`test_production_hardening.py`](file:///e:/Workspace/Active/server/tests/test_production_hardening.py): 18 tests (18 passed). Verifies rate limiting, CORS restrictions, error masking, and graceful shutdown handlers.
- [`test_windows_install.py`](file:///e:/Workspace/Active/server/tests/test_windows_install.py): 12 tests (12 passed). Verifies cross-platform path handling and environment variable bootstrapping.
- [`test_package.py`](file:///e:/Workspace/Active/server/tests/test_package.py): 20 tests (20 passed). Verifies CLI package commands after Stage 3 cleanup.
- [`test_nexus_client.py`](file:///e:/Workspace/Active/server/tests/test_nexus_client.py): 49 tests (49 passed). Comprehensive tests covering remote CLI client authentication, session lifecycle, and argument consistency.

### B. Modern Post-Rebase and Semantic Facade (100% Passing)
- [`test_phase42a_endpoints.py`](file:///e:/Workspace/Active/server/tests/test_phase42a_endpoints.py): 6 tests (6 passed). Asserts the dedicated Phase 4.2A REST dashboard APIs (`/api/academic/dashboard`, `/api/system/status`, `/api/admin/users`, `/api/admin/approvals`).
- [`test_ui_rebase_contract.py`](file:///e:/Workspace/Active/server/tests/test_ui_rebase_contract.py): 7 tests (7 passed). Asserts clean 7-tab UI, 6 academic subtabs with active Results, and zero legacy residue.
- [`test_semantic_facade.py`](file:///e:/Workspace/Active/server/tests/test_semantic_facade.py): 12 tests (12 passed). Validates the 11 semantic MCP tools, argument parsing, and structured responses.
- [`test_gemini_spark_compliance.py`](file:///e:/Workspace/Active/server/tests/test_gemini_spark_compliance.py): 5 tests (5 passed). Validates RFC 9728, OAuth 2.0 PKCE, and exact 11 semantic tools catalog discovery.
- [`test_oauth_mcp_bridge.py`](file:///e:/Workspace/Active/server/tests/test_oauth_mcp_bridge.py): 7 tests (7 passed). Validates OAuth Bearer token to MCP bridge and exact 11 semantic tools contract.
- [`test_oauth_provider.py`](file:///e:/Workspace/Active/server/tests/test_oauth_provider.py): 12 tests (12 passed). Tests RFC 6749 authorization server, PKCE code exchange, token lifecycle, and consequential approval guards.
- [`test_mcp_gateway.py`](file:///e:/Workspace/Active/server/tests/test_mcp_gateway.py): 28 tests (28 passed). Tests MCP 2026-07-28 stateless protocol, granular atomic registry under legacy mode, and HTTP endpoints under semantic mode.
- [`test_multi_user_isolation.py`](file:///e:/Workspace/Active/server/tests/test_multi_user_isolation.py): 21 tests (21 passed). Proves strict row-level tenant isolation across all multi-tenant tables.
- [`test_api_first_router.py`](file:///e:/Workspace/Active/server/tests/test_api_first_router.py): 9 tests (9 passed). Exercises the tiered execution fallback (Local SQLite Cache -> Direct HTTP/API -> Ephemeral Headless Browser).
- [`test_bg6_browser_runtime.py`](file:///e:/Workspace/Active/server/tests/test_bg6_browser_runtime.py): 9 tests (9 passed). Validates browser lifecycle management, process trees, concurrency locks, watchdog timers, and memory thresholds.
- [`test_phase34_execution.py`](file:///e:/Workspace/Active/server/tests/test_phase34_execution.py): 12 tests (12 passed). Validates writable Vault, browser session lifecycle, document text extraction, and consequential action guards.

### C. Academic, LMS, and Timetable Synchronization (100% Passing)
- [`test_timetable_sync.py`](file:///e:/Workspace/Active/server/tests/test_timetable_sync.py): 101 tests (101 passed). Validates recurrence calculations, timezone transformations (Asia/Kolkata), Google Calendar patch sets, idempotency, and drift detection.
- [`test_upes_auth_manager.py`](file:///e:/Workspace/Active/server/tests/test_upes_auth_manager.py): 31 tests (31 passed). Tests encrypted credential storage, cookie jar encryption, refresh logic, and portal authentication flows.
- [`test_upes_zero_touch.py`](file:///e:/Workspace/Active/server/tests/test_upes_zero_touch.py): 20 tests (20 passed). Validates background cron sync for student attendance and timetable without user interaction.
- [`test_phase35_lms.py`](file:///e:/Workspace/Active/server/tests/test_phase35_lms.py): 9 tests (9 passed). Asserts LMS course, assignment, and resource parsing via Blackboard Learn APIs.
- [`test_phase35_upes_analytics.py`](file:///e:/Workspace/Active/server/tests/test_phase35_upes_analytics.py): 5 tests (5 passed). Validates ReportLab PDF analytics export.
- [`test_phase35_vault_docs.py`](file:///e:/Workspace/Active/server/tests/test_phase35_vault_docs.py): 4 tests (4 passed). Validates PDF extraction and document processing.
- [`test_secret_leak_regression.py`](file:///e:/Workspace/Active/server/tests/test_secret_leak_regression.py): 1 test (1 passed). Scans all committed code and logs for unredacted passwords, tokens, or private keys.
- [`test_attendance_frontend_contract.py`](file:///e:/Workspace/Active/server/tests/test_attendance_frontend_contract.py): 5 tests (5 passed). Verifies modular frontend contracts and Node.js syntax validity.
- [`test_tab_preloading_cache.py`](file:///e:/Workspace/Active/server/tests/test_tab_preloading_cache.py): 4 tests (4 passed). Validates tab router invariants and bounded polling helpers.

### D. Phase 4.3A Production Capabilities (100% Passing)
- [`test_upes_results.py`](file:///e:/Workspace/Active/server/tests/test_upes_results.py): 14 tests (14 passed). Validates UPES 10-point scale grade rules, `Decimal` rounding precision, dual normalization (ConnectPortal & Exam-Pro), LKG caching, and What-If simulator.
- [`test_results_api.py`](file:///e:/Workspace/Active/server/tests/test_results_api.py): 7 tests (7 passed). Asserts REST endpoints (`/api/academics/results`, `/api/academics/performance`, `/api/academics/what-if`).
- [`test_results_multi_user.py`](file:///e:/Workspace/Active/server/tests/test_results_multi_user.py): 4 tests (4 passed). Proves strict row-level multi-tenant isolation of academic results.
- [`test_scheduler_3hour.py`](file:///e:/Workspace/Active/server/tests/test_scheduler_3hour.py): 8 tests (8 passed). Fast-time simulation of 3-hour scheduling interval, multi-tenant failure isolation, calendar idempotency, and LKG destructive protection.
- [`test_mcp_client_compatibility.py`](file:///e:/Workspace/Active/server/tests/test_mcp_client_compatibility.py): 10 tests (10 passed). Enforces exact 11 semantic tools invariant, Gemini Spark and Mistral AI schema adaptation, direct HTTP LMS safety, and consequential mutation guardrails.
- [`test_attendance_sync.py`](file:///e:/Workspace/Active/server/tests/test_attendance_sync.py): 17 tests (17 passed). Exercises distributed sync lease locks and independent scheduler failure containment.
- [`test_onboarding_status.py`](file:///e:/Workspace/Active/server/tests/test_onboarding_status.py): 8 tests (8 passed). Validates 10-point student onboarding checklist and deterministic state machine.
- [`test_academic_onboarding_ui.py`](file:///e:/Workspace/Active/server/tests/test_academic_onboarding_ui.py): 12 tests (12 passed). Asserts accounts UI contract, admin 11-step wizard state, and student checklist presentation.

---

## 3. Test Reconciliation & Legacy Supersession (Phase 4.2C Resolved)

All 21 discrepancies identified in the pre-cleanup audit have been resolved without weakening assertions or artificially deleting active suites:

```
=========================== Short Resolution Breakdown ===========================
1. test_gemini_spark_compliance.py (Resolved -> 5/5 PASSED)
   - Fix: Aligned required_capability in agent/semantic_facade.py for lms.fetch (lms.resources.download)
     and lms.prepare (lms.submission.prepare) with DEFAULT_SPARK_CAPABILITIES.
   - Asserted exact 11 semantic tools contract.
2. test_oauth_mcp_bridge.py (Resolved -> 7/7 PASSED)
   - Fix: Updated tools/list assertion to expect exact 11 semantic tools contract instead of legacy count 43.
3. test_mcp_gateway.py (Resolved -> 28/28 PASSED)
   - Fix: Configured TestMcpGatewayModern to explicitly exercise legacy granular catalog mode,
     while TestMcpFlaskEndpointsModern asserts the exact 11 semantic tools via HTTP /api/mcp.
4. test_oauth_provider.py (Resolved -> 12/12 PASSED)
   - Fix: Wrapped consequential action test in config.MCP_CATALOG_MODE = "legacy" to test granular
     lms.submit_assignment approval enforcement while preserving semantic mode default.
5. test_docker_setup.py (Resolved -> 5/5 PASSED)
   - Fix: Updated doc path resolution to check docs/phases/DOCKER.md matching Phase 4.2B documentation layout.
6. test_nexus_client.py (Resolved -> 49/49 PASSED)
   - Fix: Removed imports and tests for retired CLI subcommands (ai, rag, models) deleted in Stage 3 CLI cleanup.
7. test_phase34_execution.py (Resolved -> 12/12 PASSED)
   - Fix: Added **kwargs to MockPinchTabProvider.create_session matching multi-tenant browser_service signature;
     wrapped test 12 in config.MCP_CATALOG_MODE = "legacy" for granular tool schema assertion.
8. test_tab_preloading_cache.py (Resolved -> 4/4 PASSED)
   - Fix: Replaced obsolete monolithic appData assertions with modern Phase 4.2A app.js router,
     VALID_TABS, view loaders, and bounded polling helpers.
9. test_attendance_frontend_contract.py (Resolved -> 5/5 PASSED)
   - Fix: Modernized to verify modular Phase 4.2A academics controller contracts, apiJson helpers,
     asset references in index.html, and zero Pythonisms with Node.js syntax verification.
10. test_phase35_upes_analytics.py & test_phase35_vault_docs.py (Resolved -> 5/5 & 4/4 PASSED)
    - Fix: Installed missing reportlab==5.0.1 and pypdf==6.19.0 in workstation environment.
```

---

## 4. Verification Procedures

### Running the Active Modern Test Suite
To run only the modern, actively maintained test suites:

```powershell
# Run modern core and post-rebase suites
pytest tests/test_server.py `
       tests/test_startup_order.py `
       tests/test_production_hardening.py `
       tests/test_phase42a_endpoints.py `
       tests/test_ui_rebase_contract.py `
       tests/test_semantic_facade.py `
       tests/test_multi_user_isolation.py `
       tests/test_api_first_router.py `
       tests/test_bg6_browser_runtime.py `
       tests/test_timetable_sync.py `
       tests/test_upes_auth_manager.py `
       tests/test_upes_zero_touch.py `
       tests/test_phase35_lms.py `
       tests/test_secret_leak_regression.py -v
```

### Running the Full Regression Suite
```powershell
python scripts/audit_test_suite.py
```
This executes all 39 test files, isolates stdout/stderr per file, generates `scripts/test_execution_report.json`, and reports aggregate metrics.

---

## 5. Continuous Invariance Checks

NexusNode enforces three continuous verification scripts:
1. **Database Fingerprinting** ([`scripts/audit_fingerprint.py`](file:///e:/Workspace/Active/server/scripts/audit_fingerprint.py)): Checks row counts across all 37 tables locally and remotely on the TECNO BG6 to guarantee zero data mutation.
2. **File Drift Detection** ([`scripts/audit_drift.py`](file:///e:/Workspace/Active/server/scripts/audit_drift.py)): Calculates SHA-256 hashes of 58 core deployed files across workstation and BG6 appliance, asserting 100% bit-for-bit parity.
3. **Secret Leak Detection** ([`tests/test_secret_leak_regression.py`](file:///e:/Workspace/Active/server/tests/test_secret_leak_regression.py)): Regex scanning over all Python, HTML, JS, JSON, and Markdown files to prevent credential commits.
