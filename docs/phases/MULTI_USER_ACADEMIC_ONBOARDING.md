# NexusNode Multi-User Academic Onboarding Architecture

## 1. Architectural Overview

NexusNode provides a multi-tenant, self-service academic timetable and Google Calendar synchronization platform designed for the NexusNode administrator and invited friends.

```
+-------------------------------------------------------------------------------+
|                             NexusNode Appliance                                |
|                                                                               |
|  [Admin Hub]                                                                  |
|       |                                                                       |
|       +--> Creates Friend Account (Initial Password, Role: user)              |
|                                                                               |
|  [Friend Self-Service Flow]                                                   |
|       |                                                                       |
|       +--> Logs into NexusNode Appliance (/login)                             |
|       +--> Changes Initial Password (/api/auth/change-password)               |
|       +--> STEP 1: Connects Google Account (/api/auth/google/login)           |
|       +--> STEP 2: Configures UPES Credentials (/api/upes/auth/credentials)   |
|       +--> STEP 3: Selects Google Calendar (/api/auth/google/calendar)       |
|       +--> STEP 4: Triggers Initial Reconciliation (/api/timetable/sync)      |
|       +--> STEP 5: Verifies Setup & Enters Active Dashboard                   |
+-------------------------------------------------------------------------------+
```

---

## 2. Multi-Tenant Isolation & Security Boundary

Every service, repository, and endpoint enforces strict tenant isolation:

1. **Authenticated Context Binding**: All user-facing self-service endpoints resolve `user_id` strictly from the cryptographically verified session token (`request.user_id`). Client-supplied override parameters (e.g. `?user_id=target_user`) are strictly rejected.
2. **Google OAuth Tenant Binding**:
   - OAuth state parameters (`state_token`) are cryptographically generated and stored with an explicit `user_id` binding in `google_oauth_states`.
   - The OAuth callback handler verifies that the authenticated caller matches the user who initiated the OAuth flow.
   - Per-user OAuth tokens are encrypted at rest using tenant-specific AES-256-GCM.
3. **UPES Credential Storage**:
   - Stored in `upes_user_credentials` encrypted with tenant-specific HKDF keys derived from `MASTER_KEY` + `user_id`.
   - Plaintext passwords never exist in database tables, log files, or API telemetry.
4. **Timetable & Attendance Isolation**:
   - SQLite tables `user_timetables`, `attendance_punches`, `timetable_sync_history`, and `timetable_events_map` are keyed by `user_id`.
   - Multi-user background sync executes sequentially across tenants under per-user lease locks (`timetable_sync_locks`).
5. **Role-Based Access Control (RBAC)**:
   - Regular users access `/api/academics/*` and `/api/timetable/*` for their own tenant.
   - Admin-targeted routes (`/api/admin/*`) require `role: 'admin'`.

---

## 3. Authoritative Dual-Dimension State Model

The system computes a deterministic dual-dimension onboarding state through `compute_onboarding_status(user_id)`:

### A. Setup Progress State (`setup_state`)
- `INCOMPLETE`: User has not finished connecting Google, configuring credentials, selecting target calendar, or performing initial sync.
- `COMPLETE`: User has completed all initial onboarding configuration steps and possesses an initial cached schedule.

### B. Live Health State (`health_state`)
Determines the live operational health of the integration:

| Precedence | State | Description | Next User Action |
|---|---|---|---|
| 1 | `GOOGLE_REQUIRED` | Google Calendar is not connected | Click **Connect Google Calendar** |
| 2 | `GOOGLE_EXPIRED` | Google OAuth refresh token expired / revoked | Click **Reconnect Google** |
| 3 | `UPES_REQUIRED` | Encrypted UPES credentials not stored | Enter UPES institutional email and password |
| 4 | `UPES_INTERACTION_REQUIRED` | Portal captcha challenge / circuit breaker open | Interactive portal login required |
| 5 | `UPES_EXPIRED` | UPES session expired with no cached schedule | Click **Reauthenticate UPES** |
| 6 | `SYNCING` | Active synchronization lease lock held | Wait for background reconciliation |
| 7 | `READY_TO_SYNC` | Credentials configured, initial sync pending | Click **Sync Timetable Now** |
| 8 | `DEGRADED_LKG` / `LKG_ONLY` | Operating on cached Last Known Good schedule | View timetable (re-authenticate UPES to refresh attendance) |
| 9 | `SYNC_FAILED` | Last calendar sync run encountered an error | Click **Retry Timetable Sync** |
| 10 | `HEALTHY` / `READY` | Fully configured, live-authenticated, and operational | Normal operation / Dashboard active |

---

## 4. Zero-Secret Telemetry Contract

The following security constraints are enforced across all API routes and frontend code:

1. **No Plaintext Passwords**:
   - `GET /api/upes/auth/status`, `GET /api/academics/onboarding-status`, and all user queries return only masked username hints (e.g. `anm***@stu.upes.ac.in`).
   - Plaintext passwords are never returned in JSON payloads.
2. **No Raw Tokens**:
   - Google OAuth access/refresh tokens, session cookies, and AES authentication tags are stripped from all API outputs.
3. **Frontend Hygiene**:
   - Password fields use `type="password"` with optional eye-icon toggle.
   - Password inputs are cleared from DOM memory immediately upon form submission.
   - Stored in-memory only for the duration of the API call; never stored in `localStorage` or `sessionStorage`.

---

## 5. Background Reconciliation & Sync Policy

- **Cadence**: Full semester timetable is checked and reconciled automatically every 3 hours.
- **Scope**: Reconciles cancellations, faculty substitutions, room changes, and added lecture sessions.
- **Safety Policy**:
  - Safe deletion: Deletions are allowed only during live UPES syncs.
  - LKG Fallback: When UPES portal is temporarily unreachable, cached timetable is served with a visible warning banner. Existing Google Calendar events are preserved and not purged.
