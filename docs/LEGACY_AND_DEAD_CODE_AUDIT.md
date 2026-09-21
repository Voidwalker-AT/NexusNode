# Legacy and Dead-Code Forensic Audit

> **Status**: RETIRED & RECONCILED (Phase 4.2C Executed)  
> **Scope**: Post-retirement status, evidence basis, reconciliation verification, and permanent architectural boundaries for retired legacy artifacts  
> **Last verified**: 2026-09-20 (Phase 4.2C Evidence-Gated Retirement)  
> **Evidence basis**: Automated file crawl (`scripts/audit_inventory.json`), test execution report (`scripts/test_execution_report.json`), and live BG6 physical appliance verification

---

## 1. Executive Summary & Verification Matrix

During Phase 4.2C, NexusNode successfully executed evidence-gated retirement of genuinely obsolete legacy backend code, mockups, and test artifacts without deleting active functionality, weakening security, or disrupting production student records.

| Category | Initial Count | Retired / Action Taken | Preserved / Retained | Final Status |
|---|---|---|---|---|
| **1. Deprecated Ollama Runit Services** | `2 files` | 2 files deleted (`services/ollama/run`, `services/ollama/log/run`) | 0 | **PURGED** |
| **2. Browser Bridge Provider** | `1 file` | 0 deleted; reclassified as `COMPATIBILITY` fallback provider | [`browser/pinchtab.py`](file:///e:/Workspace/Active/server/browser/pinchtab.py) | **RETAINED (COMPATIBILITY)** |
| **3. Prototype HTML Mockups** | `47 files` | 47 files deleted (`stitch_nexusnode_control_interface/`, ~8.07 MB) | 0 | **PURGED** |
| **4. CLI AI Subcommands** | `4 files` | 3 files deleted (`nexus/commands/ai.py`, `models.py`, `rag.py`) | [`nexus/commands/media.py`](file:///e:/Workspace/Active/server/nexus/commands/media.py) | **RETIRED / MEDIA PRESERVED** |
| **5. Pre-Rebase Legacy Tests** | `9 files` (22 issues) | 21 issues reconciled without weakening contracts; exact 11 semantic tools enforced | 1 deliberate skip (`test_phase34_live_pinchtab.py`) | **RECONCILED (681/682 PASS)** |
| **6. Obsolete SQLite Tables** | `3 candidate tables` | 2 zero-row tables dropped (`ai_inference_metrics`, `user_chats`) | `consequential_audit_log` (active security table) | **MIGRATION 002 APPLIED** |

---

## 2. Forensic Resolution by Category

### Category 1: Deprecated Ollama Runit Services
- **Deleted Paths**: `services/ollama/run`, `services/ollama/log/run` (directory removed).
- **Verification**: `services/ollama/` no longer exists. `runsvdir` on TECNO BG6 supervises only `nexusnode` and `localtonet`. Zero active scripts reference `services/ollama`.

### Category 2: Browser Bridge (`browser/pinchtab.py`)
- **Status**: **PRESERVED AS COMPATIBILITY RUNTIME**.
- **Forensic Truth**: Grep audit confirmed `browser/pinchtab.py` is actively imported in [`agent/browser_service.py`](file:///e:/Workspace/Active/server/agent/browser_service.py) as a runtime fallback provider when CDP is unavailable. 
- **Verification**: 9/9 tests pass in [`tests/test_bg6_browser_runtime.py`](file:///e:/Workspace/Active/server/tests/test_bg6_browser_runtime.py). Live execution test `tests/test_phase34_live_pinchtab.py` remains deliberately skipped in offline/CI environments.

### Category 3: Prototype HTML Mockups (`stitch_nexusnode_control_interface/`)
- **Deleted Paths**: Entire directory `stitch_nexusnode_control_interface/` (47 HTML/asset files, ~8.07 MB).
- **Verification**: Excluded from [`deploy_to_bg6_ssh.py`](file:///e:/Workspace/Active/server/deploy_to_bg6_ssh.py). Cleaned from disk. Zero Flask routes or build scripts referenced this directory.

### Category 4: CLI Subcommands
- **Deleted Paths**:
  - `nexus/commands/ai.py`
  - `nexus/commands/models.py`
  - `nexus/commands/rag.py`
- **Preserved Path**: [`nexus/commands/media.py`](file:///e:/Workspace/Active/server/nexus/commands/media.py) (actively required as `/api/media/*` helper surface).
- **Verification**: `nexus/__main__.py` and `nexus/shell.py` command dispatch tables cleaned. `python -m nexus --help` renders clean academic toolset. [`tests/test_package.py`](file:///e:/Workspace/Active/server/tests/test_package.py) passes 20/20.

### Category 5: Test Suite Reconciliation
All 21 failing test conditions across 9 suites were reconciled without weakening contracts:
1. [`tests/test_gemini_spark_compliance.py`](file:///e:/Workspace/Active/server/tests/test_gemini_spark_compliance.py): Fixed capability requirements for `lms.fetch` and `lms.prepare` to match `DEFAULT_SPARK_CAPABILITIES`. Asserted exact 11 semantic tools contract.
2. [`tests/test_docker_setup.py`](file:///e:/Workspace/Active/server/tests/test_docker_setup.py): Updated path resolution to match canonical `docs/phases/DOCKER.md`.
3. [`tests/test_nexus_client.py`](file:///e:/Workspace/Active/server/tests/test_nexus_client.py): Removed obsolete CLI subcommand tests; all 49 client tests passing.
4. [`tests/test_oauth_mcp_bridge.py`](file:///e:/Workspace/Active/server/tests/test_oauth_mcp_bridge.py): Updated assertion to verify exact 11 semantic tools set.
5. [`tests/test_oauth_provider.py`](file:///e:/Workspace/Active/server/tests/test_oauth_provider.py): Isolated granular consequential action testing within `MCP_CATALOG_MODE = "legacy"` context.
6. [`tests/test_mcp_gateway.py`](file:///e:/Workspace/Active/server/tests/test_mcp_gateway.py): Tested legacy granular mode explicitly under its own flag while enforcing default semantic contract (11 tools) on `/api/mcp`.
7. [`tests/test_tab_preloading_cache.py`](file:///e:/Workspace/Active/server/tests/test_tab_preloading_cache.py): Replaced obsolete `appData` assertions with modern Phase 4.2A router invariants, `VALID_TABS`, and view loaders.
8. [`tests/test_phase34_execution.py`](file:///e:/Workspace/Active/server/tests/test_phase34_execution.py): Added multi-tenant `**kwargs` support to mock provider; verified legacy tool schema under explicit legacy mode.
9. [`tests/test_attendance_frontend_contract.py`](file:///e:/Workspace/Active/server/tests/test_attendance_frontend_contract.py): Replaced legacy monolithic assertions with Phase 4.2A modular `academics.js` and `api.js` contracts.

### Category 6: Database Schema Migration 002
- **Applied Migration**: [`migrations/002_drop_legacy_ai_tables.sql`](file:///e:/Workspace/Active/server/migrations/002_drop_legacy_ai_tables.sql)
- **Tables Dropped**: `ai_inference_metrics` (0 rows), `user_chats` (0 rows).
- **Tables Preserved**: `consequential_audit_log` (active security/audit table for consequential actions).
- **Execution Verification**:
  - Local Database: Pre-integrity `ok`, post-integrity `ok`. Total tables reduced from 39 to 37 (36 user tables + 1 `sqlite_sequence`).
  - Remote TECNO BG6 Appliance: Executed via [`scripts/migrate_bg6_remote.py`](file:///e:/Workspace/Active/server/scripts/migrate_bg6_remote.py). Pre-integrity `ok`, post-integrity `ok`. Zero student records touched.

---

## 3. Final Verification Metrics
- **Total Test Files**: 39
- **Total Tests Discovered**: 682
- **Passed**: 681
- **Skipped**: 1 (`tests/test_phase34_live_pinchtab.py`, live hardware-dependent test)
- **Failed**: 0
- **Errors**: 0
- **Success Rate**: 99.85% (100% of executable tests)
