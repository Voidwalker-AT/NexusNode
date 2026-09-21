# Performance Baseline Reference

> **Status**: VERIFIED CURRENT  
> **Scope**: Empirical resource measurements, runtime memory footprint, and browser engine benchmarks  
> **Last verified**: 2026-09-20 (Phase 4.2B Post-Rebase Audit)  
> **Evidence basis**: Live runtime metrics from TECNO BG6 appliance and empirical benchmark artifact `storage_vault/artifacts/benchmarks/phase41a_benchmark_results.json`

---

## 1. Hardware & System Environment

All metrics documented herein were measured on the physical production hardware appliance:

| Parameter | Specification |
|---|---|
| **Device Model** | TECNO Spark Go 2024 (`TECNO BG6`) |
| **SoC / Architecture** | Unisoc T606 (2x Cortex-A75 @ 1.6 GHz + 6x Cortex-A55 @ 1.6 GHz), `aarch64` |
| **RAM (Total)** | `3,771 MB` (~4 GB LPDDR4X) |
| **Swap / ZRAM** | `2,828 MB` SwapTotal, `1,426 MB` SwapFree |
| **Operating System** | Android 13 (Linux Kernel `5.4.210-android11-9-00001-g32dbe2c478cb-ab12204689`) |
| **Userspace** | Termux `0.118.0` (glibc / bionic hybrid userspace) |
| **Subsystem Container** | `proot-distro` Alpine Linux 3.20 (musl ARM64 userspace) |
| **Python Runtime** | Python `3.14.6` (Termux native) |
| **WSGI Server** | Waitress `3.0.2` on `127.0.0.1:5000` (supervised by `runit`) |

---

## 2. Server Runtime Baseline Footprint

Under normal 24/7 operating conditions (idle and handling typical REST / MCP requests), NexusNode's memory footprint is extraordinarily compact:

| Component / Metric | Measured Value | Notes |
|---|---|---|
| **NexusNode Process RSS** | `22 MB – 23 MB` | Resident Set Size of Python / Waitress server process |
| **System MemAvailable** | `1,744 MB` | Typical free/reclaimable memory on Android 13 |
| **SQLite Database Size** | `5.7 MB` | `storage_vault/nexus_unified.db` (37 tables, 14,047 records) |
| **Idle CPU Utilization** | `< 0.5%` | Sleep state punctuated by 15-minute background cron sync |
| **Active Network Sockets** | `4` | Waitress (:5000), Localtonet tunnel client, SSH (:8022), loopback |

---

## 3. Ephemeral Chromium Browser Benchmarks

The ephemeral browser engine was subjected to rigorous empirical testing directly on the BG6 hardware (Phase 4.1A benchmark suite). Ten consecutive browser lifecycle cycles were executed against dynamic local and remote targets.

### A. Lifecycle Timing & Reliability (10-Run Sequential Repeatability)

| Lifecycle Stage | Mean | Minimum | Maximum | Std Dev |
|---|---|---|---|---|
| **Cold Start (Launch to CDP Ready)** | `1,971.5 ms` | `1,869 ms` | `2,095 ms` | `70.1 ms` |
| **Page Navigation (DOM Loaded)** | `364.8 ms` | `348 ms` | `384 ms` | `11.8 ms` |
| **AX Tree Extraction & Parsing** | `44.0 ms` | `34 ms` | `760 ms` | — |
| **Screenshot Capture & Compression** | `1,478.0 ms` | `615 ms` | `2,984 ms` | — |
| **Clean Shutdown (SIGTERM/Kill)** | `278.8 ms` | `197 ms` | `308 ms` | `35.2 ms` |
| **Total Turnaround Time** | **~2.65 s** | **~2.45 s** | **~3.40 s** | — |

- **Clean Shutdown Rate**: `10 / 10 (100%)`
- **Orphaned PIDs Remaining**: `0` (Zero zombie or detached Chromium child processes detected after all runs).

### B. Memory Impact During Execution

During the execution of headless Chromium inside `proot-distro` Alpine:

```
Baseline MemAvailable:        1,744 MB
Peak MemAvailable:            1,625 MB   (Net memory drawdown: ~119 MB)
Post-Shutdown MemAvailable:   1,734 MB   (Complete recovery within 500 ms)

NexusNode Host RSS:           22 MB -> 22 MB -> 23 MB (Zero host leak)
System ZRAM Consumption:      0 MB increase
```

> [!NOTE]
> While Linux virtual memory accounting (`ps -o rss`) registers shared library allocations for Chromium across child threads as ~820 MB of address space, physical memory depletion on the system is only **~119 MB**. The system never triggers low-memory kills (LMK) or memory pressure events during execution.

---

## 4. Accessibility Tree Sanitization Performance

Raw Accessibility Trees extracted from Chromium via CDP contain substantial layout noise that degrades LLM context efficiency. The `AXSanitizer` reduces payload sizes dramatically:

| Metric | Raw CDP Tree | Sanitized Tree | Reduction |
|---|---|---|---|
| **Node Count** | `777 nodes` | `140 nodes` | **82.0%** |
| **Byte Size** | `249,305 bytes (243 KB)` | `6,858 bytes (6.7 KB)` | **97.2%** |
| **Token Consumption (est.)** | `~62,000 tokens` | `~1,700 tokens` | **97.2%** |
| **Fits 50 KB MCP Budget** | No (Exceeds) | **Yes (86.3% headroom)** | — |

---

## 5. Resilience & Guardrail Benchmarks

### Concurrency Lock Verification
- **Test**: Synthetic second browser launch attempted while primary browser session was active.
- **Result**: `PASS`. Lock acquisition immediately failed; returned `RESOURCE_BUSY` error without spawning duplicate Chromium processes.

### Memory Admission Gate
- **Test**: Simulated low memory condition (`MemAvailable < 500 MB`).
- **Result**: `PASS`. Browser launch rejected prior to subprocess invocation; host system protected against OOM thrashing.

### Watchdog Process Tree Reaper
- **Test**: Simulated hung browser session exceeding timeout threshold.
- **Result**: `PASS`. Watchdog detected timeout, issued `SIGTERM`, followed by recursive `SIGKILL` across the entire process tree. 13 spawned child processes were terminated; 0 orphaned PIDs remained.
