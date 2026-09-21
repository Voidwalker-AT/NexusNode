# ADR-006: Ephemeral Chromium Instead of Permanent Browser Daemon

**Status:** ACCEPTED  
**Scope:** Browser Architecture & Process Lifecycle  
**Last verified:** 2026-09-20  
**Evidence basis:** Phase 4.1A benchmarks, `browser/chromium_runtime.py`, `tests/test_bg6_browser_runtime.py`  

---

## Context
Running Chromium on low-power ARM64 hardware (Android/Termux via Alpine proot) presents severe memory retention challenges. If Chromium remains running as a permanent background daemon, memory leaks, zombie renderer processes, and high idle resident set size (~120–150 MB baseline) accumulate over time, ultimately triggering the Android LMK to kill the primary NexusNode process.

## Decision
Chromium must never run as a persistent daemon. Browser instances must be **strictly ephemeral**:
1. Launched on-demand via a single-flight file lock (`nexusnode_browser_flight.lock`).
2. Gated by a hardware memory admission check (`MemAvailable >= 500 MB`).
3. Bound to a strict watchdog timeout (default 30 seconds).
4. Unconditionally and aggressively terminated (`SIGTERM` followed by `SIGKILL` process tree sweep) immediately upon task completion or failure.

## Alternatives Considered
1. **Permanent Chromium Daemon with Warm Tabs**: Rejected because long-running Chromium processes on Termux/proot suffer from unrecoverable memory fragmentation and crash the host OS within hours.
2. **External Cloud Browser Service**: Rejected to maintain self-contained appliance independence, eliminate cloud costs, and protect student credentials.

## Consequences
- **Positive**: Zero background memory leakage; predictable memory reclamation; guarantees system stability for long uptimes (35+ days proven on BG6).
- **Negative**: Introduces a cold-start startup latency (~2.1–2.8 seconds) when a browser session is required.

## Evidence
- Phase 4.1A benchmark test 10 and live verification prove that 100% of Chromium process trees terminate completely with 0 orphaned PIDs remaining.
- BG6 idle audit confirms 0 running Chromium processes.

## Related Components
- `browser/chromium_runtime.py`
- `browser/bg6_cdp.py`
- `browser/cdp_client.py`
- `resource_governor.py`
