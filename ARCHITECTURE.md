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

To solve these constraints, NexusNode implements **deterministic resource governance, bounded sequential concurrency ($N=1$), zero-memory chunked streaming, serialized asynchronous RAG, and external process supervision**.

---

## 2. Process Topology & Process Supervision

NexusNode separates lifecycle management into three distinct operational modes:

```
[ Mode A: termux-services (runit) ]     [ Mode B: All-in-One CLI Launcher ]     [ Mode C: Termux:Boot ]
           |                                             |                                 |
+---------------------+                       +---------------------+           +---------------------+
| runsvdir supervisor |                       |   start_nexus.sh    |           | start-nexusnode.sh  |
+---------------------+                       +---------------------+           +---------------------+
     |        |      \                             |        |      \                       |
     v        v       v                            v        v       v                      v
 [nexusnode] [sshd] [localtonet]              [nexusnode] [sshd] [localtonet]     [Acquires Wakelock &
                                                                                  invokes supervisor]
```

### Authoritative Process Roles:
- **SSHD (Port 8022)**: OpenSSH server managed either via Termux's official `termux-services/sshd` or standalone `sshd -p 8022`.
- **LocalToNet Tunnel**: Exposes local port 5000 to an encrypted public URL with automatic keepalive.
- **NexusNode WSGI (`app.py` on :5000)**: Multi-threaded Waitress WSGI application executing the personal cloud control center.
- **Ollama Engine (:11434, Optional)**: AI inference engine, kept down by default to protect the 4 GB RAM budget.

---

## 3. Core Subsystems & Technical Mechanics

```
                                +---------------------------+
                                |      Client Browser       |
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
        | - RAM State Machine |    | - Concurrency = 1  |     | - DB_LOCK Protection|
        | - Thermal Zones     |    | - Sequential Queue |     | - Index-Optimized   |
        | - Battery Telemetry |    | - Auto Recovery    |     | - conn.backup() API |
        +---------------------+    +--------------------+     +---------------------+
                   |                          |                          |
        +---------------------+    +--------------------+     +---------------------+
        |  Media & Streaming  |    | Serialized RAG     |     | Scheduled Automator |
        | - yt-dlp Multi-fmt  |    | - Non-blocking     |     | - 60s Queue Daemon  |
        | - HTTP 206 Partial  |    | - Pending Rebuild  |     | - Zero Direct Exec  |
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
- **Automatic Crash Recovery**: On startup, any task marked `running` in SQLite is swept to `interrupted`, preventing zombie job deadlocks.
- **Graceful Subprocess Termination**: `cancel_task()` issues `SIGTERM`, waits 300ms, falls back to `SIGKILL`, and purges partial `.part`, `.ytdl`, and `.tmp` artifacts.

### 3.3. Zero-Memory HTTP 206 Range Streaming
- **Memory Pressure Prevention**: Mobile browsers streaming 500 MB+ audio or video files could trigger Android LMK if buffered into memory.
- **Range Implementation**: `stream_file_range()` parses `Range: bytes=start-end`, returns `HTTP 206 Partial Content`, and yields 64 KB binary chunks directly from disk with seekable scrubbing support.

### 3.4. Unified SQLite WAL & Non-Blocking Backups
- **Concurrency & Integrity**: SQLite operates in `journal_mode=WAL` with `synchronous=NORMAL`.
- **Atomic Backups**: `create_system_backup_sync()` uses SQLite's official `conn.backup()` C-API to copy active databases safely without locking read operations, packaged into versioned zip archives with SHA-256 checksums.

### 3.5. Serialized Asynchronous Local Document RAG
- **Zero Startup Lag**: RAG index is loaded from `rag_index.json` on boot without blocking the main server thread.
- **Pending Rebuild Coalescing**: When reindexing is requested while an existing rebuild is running, `_pending_rebuild = True` coalesces subsequent requests into a single follow-up execution.

### 3.6. Cryptographic Temporary Share Links
- **Scoped Tokens**: Generates `secrets.token_urlsafe(24)` URLs.
- **Access Boundary**: Public `/share/<token>` endpoint verifies expiration timestamps, revocation flags, and maximum download quotas without exposing internal filesystem paths.

---

## 4. Security Model & Defense in Depth

| Vector | Defense Mechanism |
| :--- | :--- |
| **Path Traversal** | `sanitize_storage_path()` canonicalizes targets via `os.path.commonpath` against `STORAGE_DIR`. |
| **Archive Slip** | Zip, Tar, and 7z extractors validate destination path before writing each member file. |
| **Brute Force** | IP lockout table locks client IP for 10 minutes after 5 consecutive failed login attempts. |
| **Secret Leakage** | Database viewer and backup archives mask PBKDF2 password hashes and exclude session tokens. |
| **Command Injection** | Zero `shell=True` execution on user inputs. All subprocesses use explicit list argument arrays. |

---

## 5. Directory Layout

```
server/
├── app.py                      # Core Waitress WSGI application & API routes
├── config.py                   # Centralized configuration & RBAC definitions
├── resource_governor.py        # RAM, Disk, Thermal, and Battery telemetry engine
├── index.html                  # OLED Mobile Control Center frontend
├── start_nexus.sh              # All-in-one CLI launcher & process manager
├── requirements.txt            # Python dependencies (flask, waitress, requests)
├── scripts/
│   ├── install_services.sh     # runit service supervisor installer
│   └── boot/
│       └── termux_boot.sh      # Termux:Boot autostart script
├── services/                   # runit service definitions
│   ├── nexusnode/              # NexusNode WSGI service
│   ├── sshd/                   # OpenSSH service
│   ├── localtonet/             # LocalToNet tunnel service
│   └── ollama/                 # Ollama engine service (down by default)
├── static/
│   ├── css/index.css           # Pure OLED black responsive mobile design system
│   └── js/app.js               # Reactive client-side application controller
├── storage_vault/              # Personal cloud storage partition
│   ├── Music/                  # Audio downloads destination
│   ├── Videos/                 # Video downloads destination
│   ├── Podcasts/               # Podcast downloads destination
│   ├── Downloads/              # General downloads destination
│   └── backups/                # SHA-256 verified system backups
└── tests/
    └── test_server.py          # 34-test automated unit & integration test suite
```
