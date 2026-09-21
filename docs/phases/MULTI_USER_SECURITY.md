# NexusNode Multi-User Security & Tenant Isolation Architecture

**Status**: Phase 3.7B Production Foundation  
**Classification**: Internal Technical & Security Architecture Document  
**Scope**: Multi-tenant Academic, Timetable, Google Calendar, and UPES Microservice Integration

---

## 1. Tenant Boundary & Data Partitioning Model

NexusNode enforces strict multi-tenant isolation across all persistent storage layers, runtime memory spaces, cryptographic secrets, and background scheduler jobs.

```
+-----------------------------------------------------------------------------------+
|                               NexusNode Security Perimeter                         |
+-----------------------------------------------------------------------------------+
                                         |
                       [ Authenticated Session Header / Cookie ]
                                         |
                                         v
                         +-------------------------------+
                         |      get_self_service_user     |
                         |  (Derives g.user['user_id'])  |
                         +-------------------------------+
                                         |
               +-------------------------+-------------------------+
               |                                                   |
      [ Tenant: User A ]                                  [ Tenant: User B ]
+-------------------------------+                   +-------------------------------+
| UPES Creds (AES-GCM Domain A) |                   | UPES Creds (AES-GCM Domain B) |
| Timetable Map: user_a:slot:dt |                   | Timetable Map: user_b:slot:dt |
| Sync Lock: user_a             |                   | Sync Lock: user_b             |
| Attendance Ledger: user_a     |                   | Attendance Ledger: user_b     |
| Google OAuth: user_a          |                   | Google OAuth: user_b          |
+-------------------------------+                   +-------------------------------+
```

### 1.1 Multi-Tenant Database Partitioning
Every academic and credential SQLite database table is strictly partitioned by `user_id`:
- `upes_user_credentials`: `user_id PRIMARY KEY`, encrypted payload, masked hint.
- `upes_auth_sessions`: `user_id PRIMARY KEY`, encrypted JWT access token, encrypted refresh token, encrypted IDP cookies.
- `user_timetables`: `user_id PRIMARY KEY`, raw ingested timetable JSON.
- `timetable_events_map`: `(user_id, source_session_id, source_date) PRIMARY KEY`, mapping UPES slots to Google Calendar event IDs.
- `timetable_sync_locks`: `user_id PRIMARY KEY`, distributed per-tenant database lease.
- `timetable_sync_history`: `user_id NOT NULL`, per-tenant audit log and delta metrics.
- `google_oauth_tokens`: `user_id PRIMARY KEY`, AES-GCM encrypted tokens, custom selected `calendar_id`.
- `google_oauth_states`: `state_token PRIMARY KEY`, bound to `user_id` with 10-minute TTL.
- `attendance_punches`: `user_id NOT NULL`, granular classroom punch timestamps.
- `official_attendance_summaries`: `user_id NOT NULL`, official UPES LMS attendance percentages.
- `academic_sessions`: `user_id NOT NULL`, per-student attendance ledger sessions.
- `attendance_sync_locks`: `user_id PRIMARY KEY`, distributed lease lock for attendance fetch.

### 1.2 Compound Mapping Keys
In `timetable_events_map`, the composite identity key:
$$\text{CompoundKey} = \text{user\_id} : \text{source\_session\_id} : \text{source\_date}$$
guarantees that even if User A and User B share the exact same course slot ID on the same date, their Google Calendar event mappings cannot collide or overwrite each other.

---

## 2. Authentication, Authorization & Self-Service Binding

### 2.1 NexusNode Session & Password Security
- **Password Storage**: Passwords are hashed using standard PBKDF2-HMAC-SHA256 with 100,000 iterations and 16-byte random hex salts.
- **Session Tokens**: 32-byte cryptographic random hex strings (256 bits of entropy) stored in memory with TTL expiration.
- **Session Cookies**: Set with `HttpOnly=True` and `SameSite=Lax` to mitigate XSS extraction and cross-site request forgery.
- **Lockout Mechanism**: Exponential backoff and IP/user lockout triggered upon consecutive failed authentication attempts.

### 2.2 Strict Self-Service Target Derivation
All regular-user endpoints use `get_self_service_user(privilege="can_sync_timetable")` to determine the target tenant:
1. **Authoritative Session Source**: The target `user_id` is derived **exclusively** from the authenticated session context (`g.user["user_id"]`).
2. **Explicit Cross-Tenant Rejection**: If a client attempts to specify a conflicting `user_id` or `target_user` in the query string (`?user_id=...`) or JSON body (`{"user_id": ...}`), the request is **explicitly rejected with HTTP 403 Forbidden** and a security audit warning is logged.
3. **Admin Segregation**: Administrative inspection routes are explicitly namespaced under `/api/admin/users/<target_user_id>/...` and guarded with `@require_admin()`.

---

## 3. Cryptographic Storage & Domain Separation

```
[ Root Config Secret: config.SECRET_KEY ]
                   |
                   v
         [ HKDF-SHA256 Derivation ]
         ├── Salt: b"nexusnode_root_kdf_salt_v1"
         └── Info: b"nexusnode/upes/credentials/v1"
                   |
                   v
   [ Dedicated 256-bit AES Key (AESGCM) ]
                   |
        +----------+----------+
        |                     |
   [ User A Blob ]       [ User B Blob ]
   - Nonce (12 B)        - Nonce (12 B)
   - Ciphertext          - Ciphertext
   - Auth Tag (16 B)     - Auth Tag (16 B)
```

### 3.1 UPES Credential Cryptography (`UpesCredentialCrypto`)
- **Key Derivation**: 256-bit AES key derived from `config.SECRET_KEY` using HKDF-SHA256 with domain salt `b"nexusnode_root_kdf_salt_v1"` and info `b"nexusnode/upes/credentials/v1"`.
- **Payload Validation**: Plaintext payload includes domain tag `nexusnode/upes/credentials/v1` and payload version.
- **Ciphertext Format**: Base64 URL-safe encoding of 12-byte random nonce + AES-GCM ciphertext + 16-byte authentication tag.
- **Sanitized Introspection**: `get_credential_status()` never decrypts or returns credentials; it returns only masked hints (e.g. `ali***@stu.upes.ac.in`) and identifier format metadata.

### 3.2 Google OAuth Cryptography (`OAuthTokenCrypto`)
- **Key Derivation**: 256-bit AES key derived from `config.SECRET_KEY` using HKDF-SHA256 with salt `b"nexusnode_google_oauth_aesgcm_salt_v1"` and info `b"nexusnode_google_oauth_tokens_v1"`.
- **Tokens Encrypted**: `access_token`, `refresh_token`, and token expiry metadata encrypted at rest.

---

## 4. Google OAuth Flow & CSRF Defense-in-Depth

```
User A (Session A)                     NexusNode Backend                   Google OAuth
     |                                         |                                |
     | --- GET /api/auth/google/authorize ---> |                                |
     |                                         | -- Generate 32-byte State ---> |
     |                                         |    (Store state -> user_a)     |
     | <--- Redirect to Google Auth URL ------ |                                |
     |                                                                          |
     | ---------------- User Authenticates & Grants Scopes --------------------> |
     |                                                                          |
     | <--- Redirect to /api/auth/google/callback?code=...&state=... ---------- |
     |                                                                          |
     | --- Callback with State & Code -------> |                                |
     |                                         | -- Consume & Delete State ---> |
     |                                         | -- Verify session == user_a -- |
     |                                         | -- Exchange code for token --> |
     |                                         | -- Save AES tokens (user_a) -> |
     | <--- Redirect: Auth Success ----------- |                                |
```

1. **State Token Generation**: 32-byte URL-safe cryptographic token (256-bit entropy) generated and stored in `google_oauth_states` with a 10-minute expiration.
2. **Single-Use Consumption**: `validate_and_consume_state()` retrieves the bound `user_id` and immediately deletes the state token from SQLite, preventing replay attacks.
3. **Session Binding Defense-in-Depth**: If an active NexusNode session is present when the OAuth callback is processed, the backend verifies that `g.user["user_id"] == state_user_id`. If a mismatched session is detected (e.g. User B logged in while consuming User A's OAuth state), the request is rejected with **HTTP 403 Forbidden**.

---

## 5. UPES Format Contract & Identifier Validation

### 5.1 Format Contract Distinction
| Entity | Accepted Format | Example | Behavior |
| :--- | :--- | :--- | :--- |
| **NexusNode Contract** | `FULL_EMAIL` | `user.sapid@stu.upes.ac.in` | **Required**. Enforced on `POST /api/upes/auth/credentials`. |
| **Numeric SAP ID** | `NUMERIC_SAP_ID` | `590011794` | **Rejected with HTTP 400** (`invalid_identifier_format`). |
| **Live Upstream Verification** | Live Tested | Real-world SSO response | Verified dynamically during runtime authentication. |

### 5.2 Centralized Validation
When submitting credentials:
```python
detected_format = IdentifierFormat.detect(username)
if detected_format != IdentifierFormat.FULL_EMAIL:
    return jsonify({
        "error": "invalid_identifier_format",
        "message": "UPES identifier must be your full institutional student email (e.g. user.sapid@stu.upes.ac.in). Numeric SAP ID is not accepted.",
        "expected_format": "FULL_EMAIL"
    }), 400
```

---

## 6. Deterministic Onboarding State Machine

`GET /api/timetable/onboarding-status` and `GET /api/academics/onboarding-status` evaluate the tenant's integration status using strict, deterministic precedence:

```
                                [ Start ]
                                    |
                          Google Connected?
                             /             \
                           No               Yes
                          /                   \
               [ GOOGLE_REQUIRED ]      Google Expired?
                                          /          \
                                        Yes           No
                                        /               \
                             [ GOOGLE_EXPIRED ]   UPES Creds Configured?
                                                    /                \
                                                  No                  Yes
                                                 /                      \
                                        [ UPES_REQUIRED ]         Circuit Open / Challenge?
                                                                    /                   \
                                                                  Yes                    No
                                                                  /                        \
                                                  [ UPES_INTERACTION_REQUIRED ]     UPES Expired / Failed?
                                                                                      /                 \
                                                                                    Yes                  No
                                                                                    /                     \
                                                                          [ UPES_EXPIRED ]           Syncing?
                                                                                                       /    \
                                                                                                     Yes     No
                                                                                                     /        \
                                                                                             [ SYNCING ]  TT Available?
                                                                                                           /         \
                                                                                                         No           Yes
                                                                                                         /              \
                                                                                               [ READY_TO_SYNC ]    LKG / Stale?
                                                                                                                      /      \
                                                                                                                    Yes       No
                                                                                                                    /           \
                                                                                                            [ LKG_ONLY ]   Sync Failed?
                                                                                                                             /      \
                                                                                                                           Yes       No
                                                                                                                           /           \
                                                                                                                  [ SYNC_FAILED ]   [ READY ]
```

### Precedence Matrix
1. `GOOGLE_REQUIRED`: Google Calendar OAuth token not present.
2. `GOOGLE_EXPIRED`: Google token present but refresh token revoked or expired.
3. `UPES_REQUIRED`: Encrypted UPES credentials not stored.
4. `UPES_INTERACTION_REQUIRED`: UPES circuit breaker tripped or security CAPTCHA challenge detected.
5. `UPES_EXPIRED`: UPES portal session expired or authentication exhausted.
6. `SYNCING`: Distributed database sync lease lock actively held.
7. `READY_TO_SYNC`: All accounts connected, awaiting initial synchronization.
8. `LKG_ONLY`: Synchronization operating on cached Last Known Good timetable.
9. `SYNC_FAILED`: Most recent synchronization run encountered an error.
10. `READY`: Fully authenticated, timetable active, calendar synchronized.

---

## 7. Multi-Tenant Background Scheduler Resilience

The background daemon iterates all active users sequentially via `sync_all_active_users()`:
```python
for uid in sorted(users_to_sync):
    try:
        summaries[uid] = self.sync_user_timetable(uid)
    except Exception as e:
        summaries[uid] = {"status": "failed", "errors": [str(e)]}
```

### Resilience Guarantees
- **Failure Containment**: A network timeout, upstream API exception, or invalid token for User A is trapped in an isolated `try/except` block and recorded in `timetable_sync_history`. It never prevents User B from synchronizing.
- **Independent Locks**: Each tenant acquires `DatabaseSyncLease(conn_factory, user_id)`. Simultaneous jobs for different tenants never block each other.
- **Deletion Safety**: When syncing under LKG fallback or network failure, calendar event deletion is strictly suppressed to preserve the student's existing schedule.
