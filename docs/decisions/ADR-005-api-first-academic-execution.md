# ADR-005: API-First Academic Execution

**Status:** ACCEPTED  
**Scope:** Academic Subsystem & Upstream Integration  
**Last verified:** 2026-09-20  
**Evidence basis:** Phase 4.1B implementation, `agent/execution_router.py`, `tests/test_api_first_router.py`  

---

## Context
Interacting with UPES student services (timetables, attendance, grades) historically swung between two extremes:
1. Pure direct HTTP calls that broke when upstream required WebSSO or dynamic JavaScript tokens.
2. Relying on headless browser automation for every query, which overloaded the BG6 (~320 MB per Chromium render, 2–3s cold start) and quickly triggered memory pressure.

## Decision
Enforce a strict **API-First Execution Architecture** managed by `ExecutionRouter`:
1. **Tier 1 (Direct API / Cache)**: Always attempt lightweight direct HTTP API calls using existing bearer/session tokens or cached Last-Known-Good (LKG) SQLite records.
2. **Tier 2 (Ephemeral Browser Fallback)**: Only when upstream explicitly requires interactive JavaScript evaluation or re-authentication does the system admit an ephemeral Chromium browser session.
3. **Strict Invariant**: Zero Chromium processes are permitted to launch for standard academic read queries (`academic.query`, timetable views, attendance checks) when valid tokens or LKG cache exist.

## Alternatives Considered
1. **Browser-First Architecture**: Rejected due to high RAM overhead, CPU exhaustion, and poor battery efficiency on the BG6 mobile hardware.
2. **Pure API Without Fallback**: Rejected because UPES WebSSO occasionally invalidates session tokens, requiring interactive or scripted DOM re-authentication that cannot be completed via simple HTTP calls.

## Consequences
- **Positive**: Academic queries execute in <30ms locally without memory spikes; preserves battery life and memory stability; graceful offline operation via LKG SQLite cache.
- **Negative**: Requires maintaining dual integration paths (direct API models + CDP DOM selectors) and synchronization logic.

## Evidence
- `tests/test_api_first_router.py` verifies Tier 1 execution without launching browser processes (9/9 passed).
- Live BG6 audit proves 0 Chromium processes during normal dashboard operation and academic queries.

## Related Components
- `agent/execution_router.py`
- `timetable_sync.py`
- `attendance_sync.py`
- `upes/router.py`
