# NexusNode — UPES Timetable to Google Calendar Synchronization Manual

## 1. Overview & Architecture

NexusNode provides an automated, resilient synchronization bridge between **UPES Timetable JSON data** and **Google Calendar**.

```
+--------------------------+
|   UPES Timetable JSON    | (Web UI Upload / API / storage_vault/upes_timetable.json)
+--------------------------+
             |
             v
+--------------------------+
|  Tolerant Parser Engine  | (Extracts course, code, date, times, room, faculty)
+--------------------------+
             |
             v
+--------------------------+
|   Normalized Sessions    | (Timezone-aware Asia/Kolkata ISO datetimes)
+--------------------------+
             |
             v
+-------------------------------------------------------------+
|               Timetable Synchronizer & Engine               |
|  - Distributed SQLite Database Lease Lock                   |
|  - Idempotent Mapping Reconciliation (timetable_events_map) |
|  - AES-GCM Authenticated Token Vault                        |
+-------------------------------------------------------------+
             |
     +-------+-------+
     |               |
     v               v
[CREATE]         [UPDATE]        [DELETE]        [NO-OP]
(New Class)    (Room/Time)     (Cancelled)     (Unchanged)
     |               |               |
     +---------------+---------------+
                     |
                     v
       +----------------------------+
       |   Google Calendar API v3   | (Extended properties marker)
       +----------------------------+
```

---

## 2. Google Cloud Setup & OAuth Configuration

To enable Google Calendar synchronization:

### 2.1 Create Google Cloud Project
1. Navigate to the [Google Cloud Console](https://console.cloud.google.com/).
2. Create a new project named `NexusNode Appliance` (or select an existing project).

### 2.2 Enable Google Calendar API
1. In the Google Cloud Console, go to **APIs & Services** > **Library**.
2. Search for **Google Calendar API** and click **Enable**.

### 2.3 Configure OAuth Consent Screen
1. Go to **APIs & Services** > **OAuth consent screen**.
2. Select **External** (or Internal for Google Workspace).
3. Fill in required App name, user support email, and developer contact email.
4. Under **Scopes**, add `https://www.googleapis.com/auth/calendar.events` and `https://www.googleapis.com/auth/calendar.readonly`.
5. Add your Google account as a **Test User** if the app status is in Testing mode.

### 2.4 Create OAuth 2.0 Credentials
1. Go to **APIs & Services** > **Credentials** > **Create Credentials** > **OAuth client ID**.
2. Select **Web application** as the application type.
3. Under **Authorized redirect URIs**, add:
   - For local development: `http://localhost:5000/api/auth/google/callback`
   - For remote server: `http://<YOUR_SERVER_IP>:5000/api/auth/google/callback` or `https://<YOUR_DOMAIN>/api/auth/google/callback`
4. Copy the generated **Client ID** and **Client Secret**.

---

## 3. Environment Variables

Configure the following variables in your `.env` or system environment:

| Variable | Default | Description |
| :--- | :--- | :--- |
| `GOOGLE_CLIENT_ID` | `""` | Google OAuth 2.0 Web Client ID. |
| `GOOGLE_CLIENT_SECRET` | `""` | Google OAuth 2.0 Client Secret. |
| `GOOGLE_REDIRECT_URI` | `http://localhost:5000/api/auth/google/callback` | Authorized OAuth redirect callback URL. |
| `TIMETABLE_TIMEZONE` | `Asia/Kolkata` | Timezone for class schedules (IST). |
| `TIMETABLE_SYNC_INTERVAL_SECONDS` | `10800` (3 hours) | Scheduled automation run interval in seconds. |
| `UPES_TIMETABLE_JSON_PATH` | `storage_vault/upes_timetable.json` | Fallback timetable file path on disk. |
| `NEXUS_TIMETABLE_MAX_UPLOAD` | `2097152` (2 MB) | Maximum upload payload size in bytes. |

---

## 4. Timetable Data Ingestion

Authenticated UPES timetable data can enter NexusNode through any of the following methods without CAPTCHA bypass:

### Option A: Web UI Upload
1. Open the NexusNode web console.
2. Navigate to the **Automation** tab.
3. Under **UPES Timetable & Google Calendar Synchronization**, click **Upload Timetable JSON**.
4. Select your exported UPES timetable `.json` file.

### Option B: REST API
```bash
curl -X POST http://localhost:5000/api/maintenance/timetable/upload \
  -H "Authorization: Bearer <YOUR_SESSION_TOKEN>" \
  -H "Content-Type: application/json" \
  -d @upes_timetable.json
```

### Option C: File Placement in Storage Vault
Save your timetable JSON directly to `storage_vault/upes_timetable.json`.

---

## 5. Supported Timetable JSON Schema

The parser is schema-tolerant and automatically extracts sessions from list or dictionary payloads:

```json
[
  {
    "course_name": "Cloud Computing",
    "course_code": "CS301",
    "date": "2026-08-20",
    "start_time": "09:00:00",
    "end_time": "10:00:00",
    "room": "Room 501",
    "faculty": "Dr. Sharma",
    "session_id": "sess_101"
  },
  {
    "subject": "Distributed Operating Systems",
    "subjectCode": "CS302",
    "slotDate": "20/08/2026",
    "time": "10:00 AM - 12:00 PM",
    "venue": "Lab 3",
    "instructor": "Prof. Verma"
  }
]
```

---

## 6. Automation & 3-Hour Scheduler

NexusNode includes a native 3-hour background job registered in the `scheduled_jobs` table:
- **Job ID**: `job_timetable_sync`
- **Name**: `UPES Timetable Google Calendar Sync`
- **Interval**: `10800` seconds (3 hours)
- **Supervision**: Runs via `task_runner` with automatic logging and non-overlapping execution locks.

### Manual Synchronization Trigger:
```bash
curl -X POST http://localhost:5000/api/maintenance/timetable/sync \
  -H "Authorization: Bearer <YOUR_SESSION_TOKEN>"
```

### Telemetry / Diagnostics Endpoint:
```bash
curl http://localhost:5000/api/maintenance/timetable/status \
  -H "Authorization: Bearer <YOUR_SESSION_TOKEN>"
```

---

## 7. Zero-Duplicate Idempotency Guarantee

- **Mapping Table (`timetable_events_map`)**: Stores `(user_id, source_session_id, source_date, google_calendar_id, google_event_id, source_hash)`.
- **Reconciliation Engine**:
  - Unchanged sessions perform zero API mutations (`unchanged_count += 1`).
  - Modified room or time slots update the existing Google Calendar event via `PUT`.
  - Sessions removed from the active timetable window delete only their corresponding managed Google Calendar event via `DELETE`.
- **Event Ownership**: Every created event includes private extended properties:
  ```json
  "extendedProperties": {
    "private": {
      "nexusnode_managed": "true",
      "nexusnode_user_id": "user_id",
      "nexusnode_session_id": "session_id",
      "nexusnode_date": "date"
    }
  }
  ```
  NexusNode **never** modifies or deletes unmanaged user calendar events.

---

## 8. Security & Cryptography

1. **AES-GCM Authenticated Encryption**: Google OAuth tokens (`refresh_token`, `access_token`) are encrypted at rest with a 256-bit key derived from `NEXUS_SECRET_KEY` using PBKDF2-HMAC-SHA256.
2. **CSRF Protection**: OAuth authorization URLs include a cryptographically random, 10-minute TTL one-time token validated and consumed on callback.
3. **Zero Secrets in Logs**: OAuth tokens, credentials, and raw keys are never logged or returned over API endpoints.
4. **Multi-User Isolation**: All token stores, event mappings, and sync states are strictly scoped to `user_id`.
