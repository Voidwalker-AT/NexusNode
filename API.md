# 🔌 NexusNode REST API Specification

Comprehensive documentation for all REST API endpoints, streaming protocols, and authentication contracts.

---

## 1. Authentication & Security

NexusNode uses **Bearer Token** session authentication for protected routes and query tokens for streaming/downloads.

### Headers:
```http
Authorization: Bearer <session_token>
```

### Authorization Model:
- **Anonymous**: `401 Unauthorized` on protected routes.
- **Unauthorized User**: `403 Forbidden` on admin-only routes or routes lacking explicit privilege.
- **Authorized / Admin**: `200 OK` (or `201 Created`).

### Rate Limiting:
- Brute-force protection locks client IP for 10 minutes upon 5 consecutive failed attempts.

---

## 2. API Endpoints

### 2.1. Authentication & Session Management
- `POST /api/auth/login`: Authenticate with `username`/`user_id` and `password`. Returns session `token` and user privileges.
- `GET /api/auth/me`: Validate current session and retrieve active role/privileges.
- `POST /api/auth/logout`: Revoke active session token server-side and purge session state.

---

### 2.2. System Health & Telemetry
- `GET /api/health` or `/health`: Fast unauthenticated health check.
- `GET /api/services/status`: Probes OpenSSH (8022), LocalToNet, and Ollama statuses.
- `GET /api/system/status`: Comprehensive dashboard telemetry (RAM PSS + Ollama, Swap, Disk, CPU Thermals, Battery %, Services, Active Task).
- `GET /api/device/telemetry`: Hardware sensor readings from `termux-battery-status` and thermal zones.

---

### 2.3. Automated Root-Cause Diagnostics (Admin Only)
- `GET /api/admin/diagnostics/full-report`: Returns automated root-cause findings (Problem, Severity, Evidence, Likely Cause, Recommendation) and deep process memory tables (`PID`, `RSS`, `PSS`, `VMS`, `FDs`, `Threads`).
- `GET /api/admin/diagnostics/system`: Deep low-level system diagnostic report.
- `POST /api/admin/diagnostics/profile-snapshot`: Captures instantaneous system performance profile.

---

### 2.4. Media Center & Streaming
- `POST /api/media/download`: Enqueues media download/extraction.
  - **Body**:
    ```json
    {
      "url": "https://youtube.com/watch?v=...",
      "format": "mp3",
      "quality": "best",
      "destination": "Music",
      "custom_filename": "MySong",
      "metadata": { "embed_metadata": true, "embed_thumbnail": true },
      "subtitles": { "mode": "embed" }
    }
    ```
- `GET /api/media/library`: Returns categorized media library (`music`, `videos`, `podcasts`, `downloads`).
- `GET /stream/<path:filepath>`: **HTTP 206 Partial Content** range streaming generator with byte seeking support.

---

### 2.5. Storage Vault & Intelligence
- `GET /files?path=<subpath>`: Lists files and folders in vault, automatically filtering `.gitkeep`.
- `POST /upload`: Multipart file upload with directory path parameter.
- `GET /download/<path:filename>`: Downloads file, or zips directory on the fly if target is a folder.
- `GET /preview/<path:filename>`: In-browser preview for text, images, audio, video.
- `DELETE /files/<path:filename>`: Deletes file from vault.
- `POST /api/vault/clean-temp`: Safely removes `.part`, `.ytdl`, and `.tmp` artifacts.
- `GET /api/storage/intelligence`: Categorized volume analysis and large file finder (>50 MB).

---

### 2.6. Temporary Secure Shares
- `GET /api/shares`: Lists active share tokens created by user.
- `POST /api/shares`: Creates scoped cryptographic share link (`{"filename": "...", "expiry": "24h", "max_downloads": 5}`).
- `DELETE /api/shares/<share_id>`: Instantly revokes a share token.
- `GET /share/<token>`: Public file stream/download for valid, non-expired tokens.

---

### 2.7. Task Runner Supervision
- `GET /api/tasks`: Lists current, completed, and queued background tasks.
- `POST /api/tasks/<task_id>/cancel`: Cancels running task, terminates subprocesses, and cleans partial files. Enforces ownership: users cancel own tasks; admin cancels all.

---

### 2.8. Authoritative AI Model Serving & SQLite FTS5 RAG
- `GET /api/ai/models`: Queries Ollama `/api/tags` for authoritative installed models list.
- `GET /api/ai/state`: Queries Ollama `/api/ps` for live model memory residency, processor assignment, and supervisor state.
- `POST /api/ai/models/select`: Selects active target model.
- `POST /api/models/estimate`: Pre-checks model RAM requirement against available memory (`SAFE` vs `BLOCKED`).
- `POST /api/models/pull`: Enqueues Ollama model pull task.
- `POST /start` / `POST /stop`: Starts/stops Ollama daemon via runit supervisor (`sv up/down ollama`).
- `GET /api/rag/status`: Returns SQLite FTS5 document and chunk counts.
- `GET /api/rag/diagnostics`: Returns SQLite FTS5 inverted index metrics, database file size, and chunk distribution.
- `POST /api/rag/index`: Triggers serialized SQLite FTS5 knowledge base rebuild.
- `POST /api/rag/compact`: Compacts SQLite FTS5 database and migrates legacy JSON indices.
- `POST /chat/stream`: Server-Sent Events (SSE) streaming chat endpoint with SQLite FTS5 BM25 context retrieval.

---

### 2.9. Atomic Backups
- `GET /api/backups`: Lists available backup snapshots.
- `POST /api/backups/create`: Creates atomic zip archive with SHA-256 checksum via `sqlite3.backup()` API.
- `GET /api/backups/download/<id>`: Downloads backup zip file.
- `POST /api/backups/restore`: Restores configuration and database with confirmation flag.
- `DELETE /api/backups/<id>`: Deletes backup archive.

---

### 2.10. Admin Hub & User Management (Admin Only)
- `GET` & `POST /api/admin/users`: User management and provisioning.
- `POST /api/admin/users/update-privileges`: Updates granular RBAC permissions.
- `POST /api/admin/users/reset-password`: Resets user password.
- `DELETE /api/admin/users/<user_id>`: Deletes user.
- `GET /api/admin/stats`: Aggregate server performance metrics.
- `GET /api/admin/db/tables`: Lists SQLite database tables.
- `GET /api/admin/db/query?table=<table_name>`: Inspects table records with password hash masking.
- `GET /api/logs/stream`: Realtime Server-Sent Events (SSE) log terminal.
