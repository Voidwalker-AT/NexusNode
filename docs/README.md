# NexusNode Canonical Documentation Hub

> **Status**: VERIFIED CURRENT  
> **Scope**: Navigation hub, directory organization, documentation maintenance contract, and governance rules  
> **Last verified**: 2026-09-20 (Phase 4.2B Post-Rebase Audit)  
> **Evidence basis**: Canonical documentation suite established in Phase 4.2B

---

## 1. Documentation Structure & Map

The NexusNode documentation repository is organized into distinct functional domains, designed for clarity, modularity, and empirical truth:

```
docs/
├── README.md                          # This navigation hub and maintenance contract
├── NEXUSNODE_ALL_FILES_GUIDE.md       # Comprehensive inventory mapping all 397 repository files
├── LEGACY_AND_DEAD_CODE_AUDIT.md      # Detailed catalog of 50 legacy/dead-code files for Phase 4.2C
│
├── reference/                         # Canonical Reference Manuals
│   ├── 00_COMPLETE_REFERENCE.md       # Master consolidated technical reference
│   ├── 01_PROJECT_OVERVIEW.md         # Mission, capabilities, personas, and architecture
│   ├── 02_REQUIREMENTS.md             # Functional, non-functional, and SLA requirements
│   ├── 03_CURRENT_ARCHITECTURE.md     # Current architecture, execution tiers, and boundaries
│   ├── 04_IMPLEMENTATION_HISTORY.md   # Chronological development history (Phases 1 to 4.2B)
│   ├── 05_CONFIGURATION.md            # Environment variables, secrets, and path specifications
│   ├── 06_MCP_PROTOCOL_AND_SEMANTIC_FACADE.md # The 11 semantic MCP tools (nexus-semantic-v1)
│   ├── 07_SECURITY_AND_GUARDRAILS.md  # Multi-tenant security, AES-GCM, and Approval Grants
│   ├── 08_DEPLOYMENT_AND_OPERATIONS.md# BG6 appliance setup, Termux, runit, and networking
│   ├── 09_TESTING_AND_VERIFICATION.md # Test architecture, 687-test audit, and verification workflows
│   ├── 10_ROADMAP.md                  # Milestone progress, near-term schedule, and future horizons
│   ├── GLOSSARY.md                    # Authoritative terminology and concepts
│   └── PERFORMANCE_BASELINE.md        # Hardware specifications, memory baselines, and benchmarks
│
├── architecture/                      # Specialized Architectural Deep-Dives
│   ├── SYSTEM_ARCHITECTURE.md         # Component topology, request flows, and process layouts
│   ├── ACADEMIC_ARCHITECTURE.md       # UPES portal, attendance forecasting, and calendar sync
│   ├── BROWSER_ARCHITECTURE.md        # Ephemeral Chromium, CDP, accessibility sanitizer, and reapers
│   ├── MULTI_TENANT_ARCHITECTURE.md   # Row-level user isolation, scoped storage, and session guards
│   ├── DATABASE_ARCHITECTURE.md       # Unified SQLite schema (37 tables), WAL mode, and indexes
│   └── AUTH_ARCHITECTURE.md           # Authentication, AES-GCM crypto, OAuth rotation, and approvals
│
├── operations/                        # Operational Manuals & Runbooks
│   ├── RUNBOOK.md                     # Daily operations, service lifecycle, health checks, logs
│   ├── BACKUP_AND_RECOVERY.md         # SQLite hot backups, integrity validation, disaster recovery
│   └── TROUBLESHOOTING.md             # Diagnostic trees and resolution runbooks for failure modes
│
├── decisions/                         # Architecture Decision Records (ADRs)
│   ├── ADR-001-tecno-bg6-sole-appliance.md
│   ├── ADR-002-remote-ai-reasoning-over-local-ollama.md
│   ├── ADR-003-mcp-first-external-intelligence-interface.md
│   ├── ADR-004-semantic-facade-over-atomic-registry.md
│   ├── ADR-005-api-first-academic-execution.md
│   ├── ADR-006-ephemeral-chromium-instead-of-browser-daemon.md
│   ├── ADR-007-multi-tenant-user-id-isolation.md
│   ├── ADR-008-consequential-action-approval-grants.md
│   ├── ADR-009-shared-google-oauth-with-per-user-tokens.md
│   └── ADR-010-first-party-dashboard-uses-rest-not-mcp.md
│
└── phases/                            # Historical Phase Archives (Preserved Baseline)
    ├── PHASE_3_0_COMPLETION_REPORT.md
    ├── PHASE_3_1_COMPLETION_REPORT.md
    ├── PHASE_3_2_COMPLETION_REPORT.md
    ├── PHASE_3_3_COMPLETION_REPORT.md
    ├── PHASE_3_4_COMPLETION_REPORT.md
    ├── PHASE_3_5_COMPLETION_REPORT.md
    ├── PHASE_4_0A_AUDIT_REPORT.md
    ├── PHASE_4_0B_COMPLETION_REPORT.md
    ├── PHASE_4_1A_BENCHMARK_REPORT.md
    ├── PHASE_4_1B_COMPLETION_REPORT.md
    ├── PHASE_4_1C_COMPLETION_REPORT.md
    └── PHASE_4_2A_COMPLETION_REPORT.md
```

---

## 2. Documentation Governance & Maintenance Contract

To prevent documentation decay, all contributors and agents must adhere to the following documentation maintenance rules:

### A. Truth Hierarchy Rule
When documenting system behavior or resolving conflicts:
1. **Live Running Production Runtime** (on physical TECNO BG6 appliance) is the highest authority.
2. **Current Verified Source Code & Passing Tests** are second in authority.
3. **Previous Documentation or Phase Reports** rank lowest. If old documentation contradicts code or measured reality, update or archive the documentation immediately.

### B. Standard Document Header Contract
Every canonical document in `docs/` must start with a standardized metadata header:
```markdown
# Document Title

> **Status**: VERIFIED CURRENT | **Scope**: ... | **Last verified**: YYYY-MM-DD (Phase X.X) | **Evidence basis**: ...
```

### C. Status Taxonomy
Documents and architectural components must use only standard status descriptors:
- `VERIFIED CURRENT`: Actively deployed, code-verified, and live-tested.
- `IMPLEMENTED BUT NOT LIVE VERIFIED`: Code exists and passes unit tests, but not yet verified on hardware.
- `LEGACY`: Superseded by newer architecture; preserved temporarily.
- `DEAD-CODE CANDIDATE`: Identified for safe removal in Phase 4.2C.
- `PLANNED`: Speculative or scheduled for a future phase (e.g., Results/CGPA subsystem).
- `UNKNOWN`: Unverified or ambiguous; requires forensic audit.

### D. Zero-Secret Leaks & Real Metrics
- Never commit unredacted passwords, student portal credentials, Google OAuth secrets, or live session tokens to documentation.
- Never invent hypothetical or benchmark numbers. Always cite empirical test runs or physical device metrics recorded in `storage_vault/artifacts/` or `scripts/`.
