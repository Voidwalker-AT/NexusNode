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
      "destination": "music",
      "custom_filename": "MySong",
      "metadata": { "embed_metadata": true, "embed_thumbnail": true },
      "subtitles": { "mode": "embed" }
    }
    ```
- `GET /api/media/library`: Returns categorized media library (`music`, `videos`, `podcasts`, `downloads`).
- `POST /api/media/playback-token`: Generates a short-lived (60–120s) cryptographic token bound to the requesting `user_id` and normalized media path.
- `GET /stream/<path:filepath>?playback_token=<token>`: **HTTP 206 Partial Content** range streaming generator with byte seeking support, exact MIME type detection, and short-lived playback token authentication.

---

### 2.5. Storage Vault & Intelligence
- `GET /files?path=<subpath>`: Lists files and folders in vault, categorizing images as `photos` and filtering protected internal system paths.
- `GET /api/vault/destinations`: Dynamically returns accessible, writable Vault destination directories based on user role and permissions.
- `POST /upload`: Multipart file upload with directory path destination parameter (`path`).
- `GET /download/<path:filename>?auth=<token>&inline=true`: Downloads file as attachment or renders inline with appropriate MIME type (images, pdfs).
- `GET /preview/<path:filename>`: In-browser preview for text, images, audio, video.
- `DELETE /files/<path:filename>`: Deletes file from vault.
- `POST /delete`: Alternative deletion endpoint (`{"filename": "..."}`).
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
- `GET /api/ai/state`: Unified endpoint returning engine supervisor state (`running`, `stopped`, `unavailable`), resident model memory, and selected model.
- `POST /api/ai/start` & `POST /api/ai/stop`: Canonical endpoints to start/stop the Ollama daemon via the runit service supervisor.
- `POST /api/ai/models/select`: Selects active target model.
- `POST /api/models/estimate`: Pre-checks model RAM requirement against available memory (`SAFE` vs `BLOCKED`).
- `POST /api/models/pull`: Enqueues Ollama model pull task.
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

### 2.10. Admin Hub & User Governance (Admin Only)
- `GET /api/admin/privileges`: Exposes complete privilege metadata registry, descriptions, categories, and role defaults.
- `GET /api/admin/users`: Lists registered user accounts with role, status (`ACTIVE`/`DISABLED`), and privilege counts.
- `POST /api/admin/users`: Creates a user with custom granular privileges and status.
- `GET /api/admin/users/<user_id>`: Fetches user details, role, status, and permissions.
- `PATCH /api/admin/users/<user_id>`: Updates user role, disabled status, or privileges.
- `DELETE /api/admin/users/<user_id>`: Deletes user account and revokes sessions (protects primary `admin`).
- `POST /api/admin/users/<user_id>/password`: Admin password reset with automatic session revocation.
- `POST /api/admin/users/<user_id>/sessions/revoke`: Revokes all active sessions for target user.
- `GET /api/admin/stats`: Aggregate server performance metrics.
- `GET /api/admin/db/tables`: Lists SQLite database tables.
- `GET /api/admin/db/query?table=<table_name>`: Inspects table records with password hash masking.
- `GET /api/logs/stream`: Realtime Server-Sent Events (SSE) log terminal.

---

### 2.11. Self-Service Account Security
- `POST /api/account/password`: Changes caller's password (verifying current password) and revokes other active sessions.
- `POST /api/account/sessions/revoke`: Revokes all other active sessions for current user.
