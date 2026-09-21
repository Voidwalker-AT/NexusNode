# ADR-001: TECNO BG6 as Sole Production Compute Appliance

**Status:** ACCEPTED  
**Scope:** Appliance Hardware & Deployment Topology  
**Last verified:** 2026-09-20  
**Evidence basis:** Phase 4.0B forensic audit, Phase 4.1A benchmarks, live BG6 runtime  

---

## Context
NexusNode was originally conceived with hybrid execution options, including offloading tasks to a permanent workstation or secondary home server. However, real-world operational constraints revealed that the **TECNO BG6** (Android 13, Termux, aarch64, ~3.77 GB physical RAM) is the **only permanently available, always-on compute appliance** owned by the operator. There is no permanent workstation worker, no secondary home server, and no paid cloud infrastructure.

## Decision
NexusNode will execute exclusively on the physical TECNO BG6 appliance. All architectural patterns, memory ceilings, daemon lifecycles, and concurrency limits must be designed around and measured against this single hardware profile.

## Alternatives Considered
1. **Permanent Workstation Worker**: Rejected due to high power draw, lack of 24/7 availability, and operational requirement for continuous mobile operation.
2. **Paid Cloud VPS / Cloud Browser**: Rejected to maintain zero hosting cost, strict local privacy of student academic data, and appliance independence.

## Consequences
- **Positive**: True 24/7 zero-cost continuous operation; physical data sovereignty; battery-backed uptime during power outages.
- **Negative**: Strict physical RAM ceiling (~3.77 GB); CPU constraints on heavy parsing; requires aggressive process lifecycle management and zero-daemon browser policies.

## Evidence
- Live BG6 runtime confirms 35+ days uptime (`up 35 days, 21:04`) running Linux kernel 5.4.210 on `aarch64`.
- Measured available RAM under idle WSGI server: ~1.7 GB available.

## Related Components
- `resource_governor.py`
- `services/nexusnode/run`
- `browser/chromium_runtime.py`
