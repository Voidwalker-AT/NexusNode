# 🔌 NexusNode REST API Specification

Comprehensive documentation for all REST API endpoints, streaming protocols, and authentication contracts.

---

## 1. Authentication & Security

NexusNode uses **Bearer Token** session authentication for protected routes and query tokens for streaming/downloads.

### Headers:
```http
Authorization: Bearer <session_token>
```

### Rate Limiting:
- Brute-force protection locks client IP for 10 minutes upon 5 consecutive failed attempts.

---

## 2. API Endpoints

### 2.1. Authentication
- `POST /api/auth/login`: Authenticate with `user_id` and `password`. Returns session `token` and user privileges.
- `GET /api/auth/me`: Validate current session and retrieve active role/privileges.
- `POST /api/auth/logout`: Revoke active session token.

---

### 2.2. System Health & Telemetry
- `GET /api/health` or `/health`: Fast unauthenticated health check.
- `GET /api/services/status`: Probes OpenSSH (8022), LocalToNet, and Ollama statuses.
- `GET /api/system/status`: Comprehensive single-endpoint dashboard telemetry (RAM, Disk, CPU Thermals, Battery %, Services, Active Task, Incidents).
- `GET /api/device/telemetry`: Hardware sensor readings from `termux-battery-status` and thermal zones.

---

### 2.3. Media Center & Streaming
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

### 2.4. Temporary Secure Shares
- `GET /api/shares`: Lists active share tokens created by user.
- `POST /api/shares`: Creates scoped cryptographic share link.
  - **Body**: `{"filename": "Music/track.mp3", "expiry": "24h", "max_downloads": 5}`
- `DELETE /api/shares/<share_id>`: Instantly revokes a share token.
- `GET /share/<token>`: Public file stream/download for valid, non-expired tokens.

---

### 2.5. Storage Vault & Intelligence
- `GET /files`: Lists files in `storage_vault`.
- `POST /upload`: Multipart file upload with drag-and-drop support.
- `GET /download/<path:filename>`: Downloads file from vault.
- `GET /preview/<path:filename>`: In-browser preview for text, images, audio, video.
- `DELETE /files/<path:filename>`: Deletes file from vault.
- `POST /api/vault/rename`: Renames file within vault partition.
- `POST /api/vault/move`: Moves file between vault subfolders.
- `GET /api/vault/checksum/<path:filename>`: Calculates SHA-256 and MD5 hashes.
- `POST /api/vault/clean-temp`: Safely removes `.part`, `.ytdl`, and `.tmp` artifacts.
- `GET /api/storage/intelligence`: Categorized volume analysis and large file finder (>50 MB).

---

### 2.6. Atomic Backups
- `GET /api/backups`: Lists available backup snapshots.
- `POST /api/backups/create`: Creates atomic zip archive with SHA-256 checksum.
- `GET /api/backups/download/<id>`: Downloads backup zip file.
- `POST /api/backups/restore`: Restores configuration and RAG index with confirmation flag (`{"backup_id": "...", "confirm": true}`).
- `DELETE /api/backups/<id>`: Deletes backup archive.

---

### 2.7. Task Runner & Archive Extraction
- `GET /api/tasks`: Lists current, completed, and queued background tasks.
- `POST /api/tasks/<task_id>/cancel`: Cancels running task, terminates subprocesses, and cleans partial files.
- `POST /api/archive/extract`: Extracts zip, tar, tar.gz, tar.bz2, or 7z archives with path traversal verification.

---

### 2.8. AI Studio & Local RAG
- `POST /api/models/estimate`: Pre-checks model RAM requirement against available memory (`SAFE` vs `BLOCKED`).
- `GET /models`: Lists available local models (GGUF and Ollama).
- `POST /api/models/pull`: Enqueues Ollama model pull task.
- `DELETE /api/models/<model_name>`: Removes local model.
- `POST /start` / `POST /stop`: Starts/stops optional Ollama daemon under governor checks.
- `GET` & `POST /api/rag/sources`: Configures active document folders for RAG.
- `GET /api/rag/status`: Returns indexing status and document chunk counts.
- `POST /api/rag/index`: Triggers serialized asynchronous knowledge base rebuild.
- `POST /chat/stream`: Server-Sent Events (SSE) streaming chat endpoint with local document RAG citations.

---

### 2.9. Network & Scheduled Automation
- `GET /api/network/status`: Overview of IP routes, interfaces, and gateway.
- `POST /api/network/test`: Unprivileged round-trip latency checks (Internet 1.1.1.1, Localhost, NexusNode, LocalToNet, Ollama).
- `GET /api/automation/jobs`: Lists scheduled maintenance jobs.
- `POST /api/automation/jobs/<id>/toggle`: Enables or disables a scheduled job.
- `POST /api/automation/jobs/<id>/run`: Manually triggers a scheduled job.

---

### 2.10. Audit Events & Admin Hub
- `GET /api/events`: Categorized system log queries with level and search filters.
- `GET /api/incidents`: Correlated service degradation events.
- `GET /api/logs/stream`: Realtime Server-Sent Events (SSE) log terminal.
- `GET` & `POST /api/admin/users`: User management (Admin only).
- `POST /api/admin/users/update-privileges`: Updates granular RBAC permissions.
- `POST /api/admin/users/reset-password`: Resets user password.
- `DELETE /api/admin/users/<id>`: Deletes user.
- `GET /api/admin/stats`: Aggregate server performance metrics.
- `GET /api/admin/db/tables`: Lists SQLite database tables.
- `GET /api/admin/db/query`: Executes read queries for database inspection with password hash masking.
