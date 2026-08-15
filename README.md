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

---

## 🚀 Quickstart & Installation (Android Termux)

### 1. Prerequisites (Inside Termux)
```bash
pkg update && pkg upgrade -y
pkg install -y python git termux-services termux-api openssh yt-dlp ffmpeg p7zip
```

### 2. Clone & Install Dependencies
```bash
git clone https://github.com/Voidwalker-AT/NexusNode.git ~/server
cd ~/server
pip install -r requirements.txt
```

### 3. Install 24/7 Services & Termux:Boot Integration
```bash
bash scripts/install_services.sh
```

### 4. Service Management
```bash
# Start NexusNode server
sv up nexusnode

# Check status
sv status nexusnode

# Start optional LocalToNet tunnel
sv up localtonet

# Start optional Ollama AI engine
sv up ollama
```

### 5. Running Standalone (Development Mode)
```bash
python app.py
```
Default root login: `admin` (Initial password generated on first run or specified via `NEXUS_ADMIN_PASSWORD` environment variable).

---

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
