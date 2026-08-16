# 📱 NexusNode — Personal Mobile Server Appliance & Hardened AI Vault

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Platforms: Android 13 Termux](https://img.shields.io/badge/Platform-Android%2013%20%7C%20Termux-green.svg)](https://termux.dev)
[![Architecture: 4GB RAM Hardened](https://img.shields.io/badge/RAM-4GB%20Hardened-orange.svg)]()
[![Supervision: Runit / termux--services](https://img.shields.io/badge/Supervision-runit%20%2F%20termux--services-blueviolet.svg)]()
[![Tests: 232 Passed](https://img.shields.io/badge/Tests-232%20Passed%20(100%25)-brightgreen.svg)]()

**NexusNode** turns a low-resource, unrooted Android smartphone (e.g. TECNO BG6, ~4 GB RAM) into a reliable, self-supervising **24/7 personal mobile server appliance**. It provides personal cloud storage, bounded background media processing, encrypted sharing, SQLite FTS5 document RAG, local AI model serving, automated root-cause system diagnostics, and a polished **Universal Remote CLI**.

---

## ⚡ Key Capabilities

- 🎨 **Canonical Google Stitch UI Design System**: High-density pitch black OLED (`#000000`) and graphite surfaces (`#121212`), structural borders (`#2C2C2C`), primary cyan (`#00daf3`), and AI purple (`#dab9ff`). Responsive mobile viewport layouts (320px–412px), bottom dock (`[Dash]`, `[Vault]`, `[Media]`, `[Tasks]`, `[AI]`, `[More]`), slide-up utilities drawer, and touch targets $\ge 44\text{px}$.
- 💻 **Universal Remote CLI & Application Terminal**: Connect securely to NexusNode from anywhere worldwide (`nexus connect https://<domain>`) with zero SSH or Termux accounts required. Features live latency probes, role-aware tab autocompletion, grouped subcommands, and real-time task queue visualization.
- 🛡️ **Hardware & Thermal Resource Governor**: Unprivileged thermal and battery telemetry (`termux-battery-status` / sysfs fallback). Automatically blocks heavy tasks during Thermal `CRITICAL` ($\ge 55^\circ\text{C}$) or RAM `CRITICAL` (<600 MB free).
- ⚙️ **Bounded Task Runner (Concurrency = 1)**: Queues heavy workloads sequentially (yt-dlp downloads, transcoding, model pulls, archive extraction, backups) to prevent Android Low Memory Killer (LMK) kills. Includes strict task ownership isolation and clean subprocess cancellation.
- 📁 **Vault Storage, Destinations & Photo Lightbox**: Dynamic writable directory selector with RBAC protection, automatic photo categorization (`photos`), inline image previews with modal lightbox, directory zip streaming, and temporary download shares.
- 🎵 **Media Center & HTTP 206 Streaming**: Multi-format audio (MP3, M4A, OPUS, WAV) and video (MP4, MKV, WebM) downloader with quality presets, subtitle extraction, metadata embedding, exact MIME negotiation, and zero-memory chunked range streaming with query token authentication.
- 🤖 **AI Studio & Authoritative Model Serving**: Strict separation of *Selected Model*, *Installed Models* (`/api/tags`), and *Loaded Model* (`/api/ps`). Dedicated engine power controls (`/api/ai/start`, `/api/ai/stop`), real-time RAM/VRAM residency calculation, keep-alive control (`0`, `5m`, `15m`, `30m`), and streaming SSE chat.
- 🧠 **SQLite FTS5 Full-Text Search RAG**: Memory-bounded document search engine using SQLite FTS5 with BM25 ranking, source folder scoping (`docs`, `notes`, `code`), binary exclusion, and zero in-memory dictionary overhead.
- 🔍 **Automated Root-Cause Diagnostics**: Automated diagnostic analyzer returning structured findings (Problem, Severity, Evidence, Likely Cause, Recommendation), live process memory tables (PID, RSS, PSS, Threads, FDs), and on-demand profile snapshots.
- 🔒 **Hardened Security & RBAC**: Multi-tier RBAC matrix (Anonymous = 401, User = 403, Admin = 200), zero hardcoded passwords in code or initialization, brute-force IP rate limiting, and full session destruction on logout.
- 🔄 **Production Runit Supervision**: Single authoritative supervisor model via `termux-services` (runit) with `Termux:Boot` autostart, crash backoff, and Android CPU WakeLock integration.

---

## 🏗️ Architecture Overview

```
                  +----------------------------------------------+
                  |         Client (Mobile / Desktop Web)        |
                  |  - Google Stitch Design Tokens               |
                  |  - Responsive 12-Col / Bottom Dock Layout    |
                  +----------------------------------------------+
                                          |
                      HTTP / SSE (Waitress WSGI Server :5000)
                                          |
                  +----------------------------------------------+
                  |                 app.py                       |
                  |  +----------------------------------------+  |
                  |  | Granular RBAC & Brute-Force Gatekeeper |  |
                  |  +----------------------------------------+  |
                  +----------------------------------------------+
                     /             |               \            \
                    /              |                \            \
+---------------------+  +-------------------+  +-----------+  +-------------+
| Resource Governor   |  | BoundedTaskRunner |  | SQLite    |  | SQLite WAL  |
| - RAM & PSS Monitor |  | - Concurrency = 1 |  | FTS5 RAG  |  | Database    |
| - Thermal Zones     |  | - Ownership Guard |  | Engine    |  | (Vault,     |
| - Telemetry Cache   |  | - Subprocess Kill |  | (BM25)    |  |  Telemetry) |
+---------------------+  +-------------------+  +-----------+  +-------------+
```

---

## 📚 Documentation Matrix

| Document | Purpose |
| :--- | :--- |
| **[ARCHITECTURE.md](ARCHITECTURE.md)** | System architecture, thermal governance, memory model, and process topology. |
| **[DEPLOYMENT.md](DEPLOYMENT.md)** | Step-by-step phone setup, battery optimization, runit supervision, and troubleshooting. |
| **[API.md](API.md)** | Complete REST API specification for all 60+ endpoints and streaming protocols. |
| **[CHANGELOG.md](CHANGELOG.md)** | Detailed release history and evolution milestones. |

---

## 🚀 Production Deployment Flow (Single Authoritative Supervisor)

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
└── ollama        (Optional Local AI Engine, controlled via sv)
```

---

## ⚡ Quickstart (Android Termux)

### 1. Prerequisites (Inside Termux)
```bash
pkg update && pkg upgrade -y
pkg install -y python git termux-services termux-api openssh yt-dlp ffmpeg p7zip
```

### 2. Clone & Install
```bash
git clone https://github.com/Voidwalker-AT/NexusNode.git ~/server
cd ~/server
pip install -r requirements.txt
bash scripts/install_services.sh
```

### 3. Appliance Control (`start_nexus.sh` - runit CLI Wrapper)
`start_nexus.sh` is a convenience CLI that controls `runit` services without spawning competing processes:

```bash
chmod +x start_nexus.sh

# Start services via runit with WakeLock (sv up sshd, localtonet, nexusnode)
./start_nexus.sh start

# Query runit service status, local Wi-Fi IP, and SSH access
./start_nexus.sh status

# Follow authoritative svlogd logs
./start_nexus.sh logs

# Restart runit services
./start_nexus.sh restart

# Stop all services and release WakeLock
./start_nexus.sh stop
```

---

## 💻 Universal Remote CLI (Anywhere Worldwide)

The **NexusNode Universal Remote CLI** allows administrators and users to manage the appliance from any computer or terminal over HTTPS without SSH or phone filesystem access.

### Installation

#### 🪟 Windows (1-Line Automated Setup — Zero Manual PATH Configuration)
Run in PowerShell (installs client, creates shims, and configures User PATH automatically):
```powershell
irm https://raw.githubusercontent.com/Voidwalker-AT/NexusNode/main/install.ps1 | iex
```
*(Or run `install.bat` / `install.ps1` from the repository).*

#### 🐍 Python / Pip / Pipx (All Platforms: Linux, macOS, Windows, Termux)
```bash
# Recommended for CLI binaries with automatic PATH management:
pipx install nexusnode-cli

# Standard pip installation:
pip install nexusnode-cli
```

---

### Usage

Open any fresh terminal (PowerShell, Command Prompt, macOS/Linux Terminal) and run:

```powershell
# Connect interactively to a remote NexusNode appliance
nexus connect https://your-server.localto.net

# Direct command execution
nexus status
nexus vault list
nexus media queue
nexus tasks list
nexus ai models
nexus logout
```


## 🧪 Testing & Verification

Run the full automated test suite (155 unit, integration, CLI, and security tests):
```bash
python -m unittest discover -s tests -p "test_*.py"
```

---

## 🔒 Security Architecture

- **No Root Required**: All diagnostics and operations run strictly in unprivileged user space.
- **No Hardcoded Passwords**: Initial administrator accounts derive from environment (`NEXUS_ADMIN_PASSWORD`) or random tokens. Passwords stored with SHA-256 + 16-byte random salt.
- **Path Traversal Protection**: All file accesses use `sanitize_storage_path()` to prevent `../` attacks.
- **Object-Level Ownership**: Task supervision and cancellation enforce user ownership (users cancel own tasks; admin cancels all).
- **Secret Isolation**: Backups and public logs never bundle session tokens, plaintext passwords, or LocalToNet credentials.
- **Brute Force Protection**: IP rate-limiting with 10-minute lockout after 5 consecutive failed logins.

---

## 📄 License

MIT License. See [LICENSE](LICENSE) for details.
