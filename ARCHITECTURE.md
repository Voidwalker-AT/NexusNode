# 🏛️ NexusNode System Architecture & Engineering Specification

```
                          NexusNode Mobile Server Appliance
           [ TECNO BG6 | Android 13 | Termux Environment | ~4 GB RAM | Unrooted ]
```

---

## 1. Design Philosophy & Engineering Constraints

NexusNode is engineered from the ground up to transform an unrooted Android mobile phone into a **resilient 24/7 personal server appliance**. Mobile Linux runtimes on Android 13 present distinct challenges compared to traditional cloud VPS or dedicated hardware:

1. **Android Low Memory Killer (LMK)**: The Android kernel aggressively terminates background processes that cross memory pressure boundaries.
2. **Aggressive Thermal Throttling**: Heavy CPU/GPU operations on mobile SoCs quickly spike thermal sensors, causing core frequency throttling and battery degradation.
3. **Android Doze & CPU Sleep**: When the screen is turned off, Android suspends unprivileged CPU threads unless explicit wake locks are maintained.
4. **Unprivileged User Namespace**: All operations execute within Termux user permissions without root access or kernel module manipulation.

To solve these constraints, NexusNode implements **deterministic resource governance, bounded sequential concurrency ($N=1$), zero-memory chunked streaming, SQLite FTS5 RAG indexing, authoritative Ollama runtime tracking, and external process supervision**.

---

## 2. Process Topology & Single Authoritative Supervision

NexusNode enforces a single authoritative supervision model via **`runit` / `termux-services`**:

```
Termux:Boot (Autostart on Phone Power-On)
    ↓
termux-wake-lock (Acquires Android CPU Lock)
    ↓
runit / termux-services (sv / runsvdir)
    ↓
├── sshd          (OpenSSH Daemon on :8022)
├── localtonet    (Encrypted Public Internet Tunnel)
├── nexusnode     (Waitress WSGI Personal Cloud Server on :5000)
└── ollama        (Optional Local AI Engine, supervised strictly via sv)
```

### Authoritative Process Roles:
- **SSHD (Port 8022)**: OpenSSH server managed via Termux's official `termux-services/sshd`.
- **LocalToNet Tunnel**: Exposes local port 5000 to an encrypted public URL with automatic keepalive.
- **NexusNode WSGI (`app.py` on :5000)**: Multi-threaded Waitress WSGI application executing the personal cloud control center.
- **Ollama Engine (:11434, Optional)**: AI inference engine, kept down by default to protect the 4 GB RAM budget, and started/stopped strictly via `sv up ollama` / `sv down ollama`.

---

## 3. Core Subsystems & Technical Mechanics

```
                                +---------------------------+
                                |      Client Browser       |
                                |  (Canonical Google Stitch)|
                                +---------------------------+
                                              |
                             HTTP / SSE (Waitress WSGI :5000)
                                              |
                                +---------------------------+
                                |   RBAC & Security Gate    |
                                +---------------------------+
                                              |
                   +--------------------------+--------------------------+
                   |                          |                          |
        +---------------------+    +--------------------+     +---------------------+
        |  Resource Governor  |    | BoundedTaskRunner  |     | Unified SQLite WAL  |
        | - RAM & PSS Monitor |    | - Concurrency = 1  |     | - DB_LOCK Protection|
        | - Thermal Zones     |    | - Ownership Guard  |     | - Index-Optimized   |
        | - Telemetry Cache   |    | - Subprocess Kill  |     | - conn.backup() API |
        +---------------------+    +--------------------+     +---------------------+
                   |                          |                          |
        +---------------------+    +--------------------+     +---------------------+
        |  Media & Streaming  |    | SQLite FTS5 RAG    |     | Root Diagnostics    |
        | - yt-dlp Multi-fmt  |    | - BM25 Full-Text   |     | - Problem Findings  |
        | - HTTP 206 Partial  |    | - Zero-Heap Bounds |     | - Process Tables    |
        +---------------------+    +--------------------+     +---------------------+
```

### 3.1. Resource Governor & Thermal State Engine
- **Telemetry Probes**: Reads unprivileged Android hardware sensors via `termux-battery-status` CLI with direct `/sys/class/power_supply/battery/` and `/sys/class/thermal/thermal_zone*/temp` fallbacks.
- **Thermal Thresholds**:
  - `NORMAL` (<42°C): Full system operations allowed.
  - `WARM` (42°C – 48°C): Normal background queueing.
  - `THROTTLED` (48°C – 55°C): Warning state logged; heavy task priority deprioritized.
  - `CRITICAL` ($\ge 55^\circ\text{C}$): **Strictly blocks** new heavy tasks (`yt-dlp`, transcoding, model pulls, RAG rebuilds, Ollama starts).
- **RAM Thresholds**:
  - `CRITICAL` (<600 MB free): Blocks heavy workloads; yields HTTP 429 JSON errors.

### 3.2. Bounded Task Worker (`BoundedTaskRunner`)
- **Strict Concurrency Limit = 1**: Heavy jobs are enqueued into an in-memory queue backed by SQLite `background_tasks`.
- **Object-Level Task Ownership**: Normal users can only view and cancel their own tasks; administrators can inspect and abort any task.
- **Automatic Crash Recovery**: On startup, any task marked `running` in SQLite is swept to `interrupted`, preventing zombie job deadlocks.
- **Graceful Subprocess Termination**: `cancel_task()` issues `SIGTERM`, waits 300ms, falls back to `SIGKILL`, and purges partial `.part`, `.ytdl`, and `.tmp` artifacts.

### 3.3. SQLite FTS5 Full-Text Search RAG Engine
- **Zero Massive In-Memory Dictionaries**: Eliminates heap explosion on 4 GB RAM mobile hardware by persisting document chunks directly in `rag_vault.db` using SQLite FTS5.
- **BM25 Search Ranking**: Evaluates search queries using SQLite's native BM25 relevance scoring algorithm.
- **Strict Scope Boundaries**: Restricts indexing exclusively to text source folders (`docs`, `notes`, `code`), strictly ignoring media, binary files, and backups.

### 3.4. Authoritative Ollama Model Serving Architecture
- **Concept Separation**:
  - `selected_model`: The model user has targeted for inference.
  - `installed_models`: Authoritative list from `GET /api/tags`.
  - `loaded_model`: Authoritative resident model from `GET /api/ps`.
- **Live Memory Residency**: Live residency telemetry calculated from `/api/ps` metrics (`runtime_size_mb`, `runtime_vram_mb`, `processor`).
- **Supervision Rule**: Server never executes raw `ollama serve` or `pkill -f ollama`. All lifecycle triggers execute via `sv up ollama` / `sv down ollama`.

### 3.5. Automated Root-Cause Diagnostics Engine
- **Automated Root-Cause Findings**: Diagnoses system state and produces structured cards with `Problem`, `Severity`, `Evidence`, `Likely Cause`, and `Recommendation`.
- **Deep Process Table**: Details PID, RSS, PSS, VMS, open file descriptors, and thread counts from `/proc`.
- **Snapshot Profiling**: Captures instant performance profiles via `POST /api/admin/diagnostics/profile-snapshot`.

### 3.6. Zero-Memory HTTP 206 Range Streaming
- **Memory Pressure Prevention**: Mobile browsers streaming 500 MB+ audio or video files could trigger Android LMK if buffered into memory.
- **Range Implementation**: `stream_file_range()` parses `Range: bytes=start-end`, returns `HTTP 206 Partial Content`, and yields 64 KB binary chunks directly from disk with seekable scrubbing support.

---

## 4. Security Model & Defense in Depth

| Vector | Defense Mechanism |
| :--- | :--- |
| **No Hardcoded Passwords** | Admin user is seeded from `NEXUS_ADMIN_PASSWORD` env var or randomly generated token; passwords hashed with SHA-256 + 16-byte random salt. |
| **Path Traversal** | `sanitize_storage_path()` canonicalizes targets via `os.path.commonpath` against `STORAGE_DIR`. |
| **Archive Slip** | Zip, Tar, and 7z extractors validate destination path before writing each member file. |
| **RBAC Matrix** | Multi-tier validation: Anonymous = 401, Unauthorized User = 403, Admin = 200. |
| **Brute Force** | IP lockout table locks client IP for 10 minutes after 5 consecutive failed login attempts. |
| **Secret Isolation** | Database viewer and backup archives mask password hashes and exclude session tokens. |
| **Command Injection** | Zero `shell=True` execution on user inputs. All subprocesses use explicit list argument arrays. |

---

## 5. UI Architecture (Google Stitch Integration)

- **Tokens & Surfaces**: Pitch Black (`#000000`), Graphite (`#121212`, `#1c1b1b`), 1px structural borders (`#2C2C2C`), Primary Cyan (`#00daf3`), Neural Purple (`#dab9ff`).
- **Responsive Layout**: 12-column desktop grid with sticky top status strip; mobile viewport reflow (375x667, 390x844, 412x915) with fixed bottom dock (`[Dash]`, `[Vault]`, `[Media]`, `[Tasks]`, `[AI]`, `[More]`), slide-up utilities sheet, and $\ge 44\text{px}$ touch targets.
- **Telemetry Precision**: Strict labeling for `MEASURED` (e.g. RSS/PSS, storage), `ESTIMATED` (model memory), and `UNAVAILABLE` (unrooted thermal sensors).

---

## 6. Dual-Frontend Architecture (Web GUI & Universal Remote CLI)

NexusNode exposes two first-class user frontends communicating over encrypted HTTPS:

```
Internet (LocalToNet Encrypted HTTPS / LAN HTTPS :5000)
                              │
               ┌──────────────┴──────────────┐
               ▼                             ▼
       Frontend 1: Web GUI           Frontend 2: Universal CLI
    (Desktop & Android Browser)    (Windows / Linux / macOS / Termux)
               │                             │
               └──────────────┬──────────────┘
                              ▼
                NexusNode Authoritative API (:5000)
       ┌──────────────────────────────────────────────┐
       │ • Shared Auth & Session Tokens (/api/auth)  │
       │ • Authoritative RBAC & Object Ownership      │
       │ • Resource Governor & Task Engine (N=1)      │
       │ • Vault / Media / AI / RAG / Diagnostics     │
       └──────────────────────────────────────────────┘
```

### 6.1. Separation of Concerns
- **Application Users**: Access NexusNode solely via HTTPS using application credentials. No SSH keys, Linux OS accounts, or Termux shell access required.
- **Operator Maintenance Path**: Host Termux administration remains preserved strictly via private OpenSSH (`ssh -p 8022 u0_a208@PHONE_IP`).
- **Zero Client Dependencies**: The `nexus` CLI package utilizes exclusively Python standard library modules (`urllib.request`, `json`, `ssl`, `cmd`, `getpass`), running out of the box on Windows, Linux, macOS, and Termux.
- **Full Parity**: Interactive application shell (`nexus> `), direct scriptable command mode (`nexus <command> --json`), token streaming, media downloads, RAG search, and admin diagnostics all interface with the same authoritative backend REST endpoints.

