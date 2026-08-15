# 📝 Changelog

All notable changes to the **NexusNode** project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [2.2.0] - 2026-08-15

### 🚀 Personal Mobile Server Appliance Evolution

#### Added
- **Thermal & Hardware Governance**: Telemetry probing via `termux-battery-status` and sysfs thermal zones. Implemented 4-tier thermal state machine (`NORMAL`, `WARM`, `THROTTLED`, `CRITICAL`) with automatic heavy task blocking at $\ge 55^\circ\text{C}$.
- **Advanced Media Center**: Support for yt-dlp extraction across 7 formats (MP3, M4A, OPUS, WAV, MP4, MKV, WebM), quality selection (1080p, 720p, 480p, audio only), subtitle embedding, and sequential multiline batch URL processing.
- **HTTP 206 Range Streaming**: Zero-memory binary chunked streaming for audio and video files, enabling seekable mobile playback without RAM buffering.
- **Temporary Secure Share Links**: Scoped `secrets.token_urlsafe(24)` share URLs with custom expiration (`1h`, `24h`, `7d`, custom), max download limits, and instant revocation.
- **Storage Intelligence & Safe Temp Cleaner**: Volume breakdown by media category and large-file detection (>50 MB). Safe temporary artifact sweep for `.part`, `.ytdl`, and `.tmp` files.
- **Atomic System Backups**: Live SQLite backup using `sqlite3.backup()` API, RAG index, and configuration archived into SHA-256 verified zips.
- **Unprivileged Network Center**: Latency and reachability diagnostics for Internet (1.1.1.1 DNS/HTTP), Localhost, NexusNode, LocalToNet tunnel, and Ollama engine.
- **Scheduled Automation Daemon**: 60-second background timer feeding `BoundedTaskRunner` for recurring backups, temp cleanups, and tunnel health audits.
- **All-in-One Appliance Launcher (`start_nexus.sh`)**: CLI manager providing `start`, `run`, `stop`, `restart`, `status`, and `logs` commands for SSHD, LocalToNet, and NexusNode.
- **Comprehensive Documentation Suite**: Added `ARCHITECTURE.md`, `DEPLOYMENT.md`, `API.md`, and `CHANGELOG.md`.
- **Automated Test Suite Expansion**: Upgraded to 34 comprehensive unit and integration tests (100% passing).

#### Changed
- Redesigned mobile web dashboard with pitch black OLED `#000000` design system, bottom navigation dock (`[Dash]`, `[Vault]`, `[Media]`, `[Tasks]`, `[AI]`, `[More]`), and action sheet drawer.
- Upgraded `scripts/install_services.sh` to prevent competing SSHD supervisors by respecting Termux's official `termux-services/sshd`.
- Hardened `services/localtonet/run` binary resolution with multi-path fallbacks and 5s backoff.

#### Fixed
- Fixed potential Android LMK crashes by strictly bounding all heavy work through `BoundedTaskRunner` ($N=1$).
- Fixed memory leakage during media playback via chunked HTTP 206 Partial Content generator.
- Fixed archive extraction security vulnerabilities with strict zip-slip canonical path validation.

---

## [2.0.0] - 2026-08-10

### 🛡️ 24/7 Mobile Hardening & Supervision

#### Added
- Centralized `config.py` configuration registry.
- `resource_governor.py` for RAM and disk pressure monitoring.
- `termux-services` (runit) process supervisor definitions.
- `Termux:Boot` auto-startup integration with Android CPU WakeLock.
- Serialized asynchronous local document RAG engine.
- SQLite WAL mode and transaction locking (`DB_LOCK`).
- SSE live audit log streaming.

---

## [1.0.0] - 2026-08-01

### Initial Release
- Basic Flask server prototype on Termux.
- User authentication and role-based access control.
- File upload and download vault.
- yt-dlp media downloader.
- Local Ollama AI chat integration.
