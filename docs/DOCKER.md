# 🐳 NexusNode Docker Deployment Guide

NexusNode provides an isolated, production-grade containerized deployment architecture that separates application logic from persistent data and external AI backends.

---

## 🏗️ Architecture Overview

```
+-------------------------------------------------------------------------+
|                              Docker Host                                |
|                                                                         |
|   +--------------------------+          +---------------------------+   |
|   |   nexusnode container    |          |     ollama container      |   |
|   |  (Python 3.11-slim)      |          |  (ollama/ollama:latest)   |   |
|   |                          |          |                           |   |
|   |  - Waitress / WSGI       |          |  - Model Registry         |   |
|   |  - SQLite Inverted Index |  HTTP    |  - Local Inference Engine |   |
|   |  - yt-dlp & FFmpeg       | -------> |  - Port :11434            |   |
|   |  - Non-root user: nexus  |          |                           |   |
|   |  - Port :5000            |          +---------------------------+   |
|   +--------------------------+                        |                 |
|                |                                      |                 |
|   +--------------------------+          +---------------------------+   |
|   | Persistent Named Volumes |          |    ollama_models Volume   |   |
|   | - nexus_vault (DB/Files) |          |    (/root/.ollama)        |   |
|   | - nexus_logs  (Logs)     |          +---------------------------+   |
|   +--------------------------+                                          |
+-------------------------------------------------------------------------+
```

---

## 🚀 Quickstart

### 1. Configure Environment
```bash
cp .env.example .env
# Edit .env and set your SECRET_KEY and bootstrap password
```

### 2. Build & Launch Containers
```bash
docker compose up -d --build
```

### 3. Verify Deployment & Health
```bash
docker compose ps
curl -sS http://127.0.0.1:5000/api/health
```

Expected output:
```json
{"status":"healthy","uptime_seconds":15,"version":"2.3.8"}
```

---

## 💾 Persistent Storage Management

All stateful data is isolated in Docker named volumes:

| Volume Name | Container Mount Point | Contents |
| :--- | :--- | :--- |
| `nexus_vault` | `/app/storage_vault` | SQLite database (`nexus_unified.db`), uploaded files, categories, backups |
| `nexus_logs` | `/app/logs` | Emergency fallback logs and audit records |
| `ollama_models` | `/root/.ollama` | Downloaded local AI models (Qwen, Llama, etc.) |

### Restart & Rebuild Safe
Containers can be freely stopped, removed, or upgraded without losing user accounts or vault objects:
```bash
# Tear down containers
docker compose down

# Rebuild and start
docker compose up -d --build
```

---

## 🔒 Security Model

1. **Non-Root Execution**: The NexusNode application runs strictly as unprivileged user `nexus` (UID 1000).
2. **First-Time Password Seeding Only**: `NEXUS_ADMIN_PASSWORD` is evaluated only during initial database creation and will **never** overwrite an existing admin password on subsequent restarts.
3. **Secret Isolation**: Development tests, local DBs, and private keys are barred from the image build via `.dockerignore`.
4. **Health Monitoring**: Docker continuously queries `GET /api/health` to detect and recover from unresponsive states.
