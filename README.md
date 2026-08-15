# 📱 NexusNode — Personal Mobile Server Appliance & Hardened AI Vault

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Platform: Android 13 Termux](https://img.shields.io/badge/Platform-Android%2013%20%7C%20Termux-green.svg)](https://termux.dev)
[![Architecture: 4GB RAM Hardened](https://img.shields.io/badge/RAM-4GB%20Hardened-orange.svg)]()
[![Supervision: Runit / termux--services](https://img.shields.io/badge/Supervision-runit%20%2F%20termux--services-blueviolet.svg)]()
[![Tests: 34 Passed](https://img.shields.io/badge/Tests-34%20Passed%20(100%25)-brightgreen.svg)]()

**NexusNode** turns a low-resource, unrooted Android smartphone (e.g. TECNO BG6, ~4 GB RAM) into a reliable, self-supervising **24/7 personal mobile server appliance**. It provides personal cloud storage, bounded background media processing, encrypted sharing, local document RAG, optional local AI, and system health governance.

---

## ⚡ Key Capabilities

- 🛡️ **Hardware & Thermal Resource Governor**: Unprivileged thermal and battery telemetry (`termux-battery-status` / sysfs fallback). Automatically blocks heavy tasks during Thermal `CRITICAL` ($\ge 55^\circ\text{C}$) or RAM `CRITICAL` (<600 MB free).
- ⚙️ **Bounded Task Runner (Concurrency = 1)**: Queues heavy workloads sequentially (yt-dlp downloads, transcoding, model pulls, archive extraction, backups) to prevent Android Low Memory Killer (LMK) kills.
- 🎵 **Media Center & HTTP 206 Streaming**: Multi-format audio (MP3, M4A, OPUS, WAV) and video (MP4, MKV, WebM) downloader with quality presets, subtitle extraction, metadata embedding, and zero-memory chunked range streaming.
- 🔗 **Temporary Secure Shares**: Scoped cryptographically random tokens with custom expiration (`1h`, `24h`, `7d`, custom), max download limits, and instant revocation.
- 💾 **Storage Intelligence**: Visual volume breakdown by category (Videos, Music, Models, Vault, Backups, Temp) and large file inspection (>50 MB).
- 📦 **Atomic Backup & Safe Restore**: Full SQLite database backup using `sqlite3.backup()` API, RAG index, and configuration in SHA-256 verified archives.
- 🌐 **Network Center & Safe Diagnostics**: Unprivileged latency probes for Internet (1.1.1.1 DNS/HTTP), Localhost, NexusNode, LocalToNet, and Ollama.
- 🧠 **Serialized Asynchronous RAG**: Zero-blocking local semantic document indexing with lock serialization and pending queueing.
- 🤖 **AI Studio & Model Management**: Integrated chat with streaming SSE responses, model pre-load RAM estimation (`SAFE` vs `BLOCKED`), and optional Ollama engine integration.
- 🔁 **Scheduled Automation**: Lightweight 60-second background daemon that enqueues maintenance tasks without heavy direct execution.
- 📱 **OLED Mobile-First Control Console**: High-density Pitch Black (`#000000`) responsive UI with bottom dock (`[Dash]`, `[Vault]`, `[Media]`, `[Tasks]`, `[AI]`, `[More]`), quick actions, and SSE audit terminal.
- 🔄 **Production Supervision**: Supervised by `termux-services` (runit) with `Termux:Boot` autostart, crash backoff, and wakelock integration.

---

## 🏗️ Architecture Overview

```
                  +----------------------------------------------+
                  |         Client (Mobile / Desktop Web)        |
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
| Resource Governor   |  | BoundedTaskRunner |  | Document  |  | SQLite WAL  |
| - RAM Monitoring    |  | - Concurrency = 1 |  | RAG Engine|  | Database    |
| - Thermal Zones     |  | - Sequential Queue|  | (Pending  |  | (Indexes,   |
| - Battery Telemetry |  | - Process Kill/Clr|  |  Rebuilds)|  |  Backups)   |
+---------------------+  +-------------------+  +-----------+  +-------------+
```

## 📚 Documentation Matrix

| Document | Purpose |
| :--- | :--- |
| **[ARCHITECTURE.md](ARCHITECTURE.md)** | System architecture, thermal governance, memory model, and process topology. |
| **[DEPLOYMENT.md](DEPLOYMENT.md)** | Step-by-step phone setup, battery optimization, runit supervision, and troubleshooting. |
| **[API.md](API.md)** | Complete REST API specification for all 50+ endpoints and streaming protocols. |
| **[CHANGELOG.md](CHANGELOG.md)** | Detailed release history and evolution milestones. |

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
└── ollama        (Optional Local AI Engine, down by default)
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

## 🧪 Testing & Verification

Run the automated test suite (34 unit, integration, and security tests):
```bash
python -m unittest tests/test_server.py
```

---

## 🔒 Security Architecture

- **No Root Required**: All diagnostics and operations run in unprivileged user space.
- **Path Traversal Protection**: All file accesses use `sanitize_storage_path()` to prevent `../` attacks.
- **Archive Traversal Defense**: Zip, tar, and 7z extractions validate extracted member destinations.
- **Secret Isolation**: Backups and public logs never bundle session tokens, plaintext passwords, or LocalToNet credentials.
- **Brute Force Protection**: IP rate-limiting with 10-minute lockout after 5 consecutive failed logins.

---

## 📄 License

MIT License. See [LICENSE](LICENSE) for details.
