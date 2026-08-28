# NexusNode Phase 2.7 — Production UPES Session Bundle & Headless Refresh Implementation Report

**Date**: 2026-08-28  
**Repository**: `NexusNode`  
**Module Scope**: `timetable_sync.py`, `attendance_sync.py`, `app.py`, `tests/test_timetable_sync.py`, `tests/test_attendance_sync.py`  
**Status**: **IMPLEMENTED & VERIFIED**  
**Test Baseline**: **372 / 372 Tests Passing (100%)**  

---

## 1. Executive Summary & Verification State

Phase 2.7 establishes a crash-consistent, unattended authentication lifecycle for UPES Portal integration across both the Timetable and Attendance systems in NexusNode. 

Rather than treating authentication as an ephemeral access token or assuming infinite unattended validity, NexusNode models the verified truth of the UPES authentication architecture:
1. **SSO Session Cookie Lifetime**: The authoritative upstream identity cookie (`idp_session_info` on `myupes-beta.upes.ac.in`) has a fixed ~10-hour lifetime that is **not** extended during token refresh.
2. **Rotating Refresh Token**: The OAuth 2.0 refresh endpoint (`/sso/user/oauth2/refresh-token`) rotates single-use refresh tokens across network boundaries.
3. **Headless Execution**: Unattended background jobs execute headless refresh in pure Python requests without launching or interacting with Chrome as long as the SSO session cookie remains valid.
4. **Crash-Consistency Protection**: An encrypted write-ahead recovery journal (`storage_vault/.upes_session_journal.enc`) protects credentials across the non-atomic network boundary between UPES token rotation and local SQLite persistence.
5. **Honest Degraded States**: When the SSO session cookie expires, the broker transitions deterministically to `AUTH_REQUIRED` (or triggers browser reacquisition via CDP if the user's browser is active).

---

## 2. Production Schema Evolution (`upes_auth_sessions`)

The `upes_auth_sessions` SQLite schema has been expanded from a single access token storage table into a full encrypted session bundle ledger:

```sql
CREATE TABLE IF NOT EXISTS upes_auth_sessions (
    user_id TEXT PRIMARY KEY,
    encrypted_access_token TEXT NOT NULL,
    student_code TEXT NOT NULL,
    api_url TEXT,
    expires_at REAL,
    encrypted_refresh_token TEXT,
    encrypted_cookies TEXT,
    cookie_expires_at REAL,
    credential_generation INTEGER DEFAULT 1,
    last_refresh_at REAL,
    last_refresh_status TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
```

### Schema Migration & Backward Compatibility
- Automatic idempotent `ALTER TABLE` statements check existing columns and migrate legacy schemas on server startup.
- Existing single-token records continue to resolve seamlessly with `credential_generation = 1`.
- Legacy `get_upes_session(user_id)` returns the standard 4-tuple `(access_token, student_code, api_url, expires_at)`.
- Modern callers use `get_full_upes_session(user_id)` for the complete session bundle.

---

## 3. Cryptographic Storage Architecture

All credentials, refresh tokens, and cookies are encrypted at rest using AES-256-GCM via `OAuthTokenCrypto`:
- **Key Derivation**: 256-bit symmetric key stored in `.nexus_secret` (or configured via environment).
- **Authenticated Encryption**: 96-bit random nonce per operation, producing authenticated ciphertext + tag (`base64` encoded).
- **Separation of Sensitive Fields**: `encrypted_access_token`, `encrypted_refresh_token`, and `encrypted_cookies` are individually encrypted so that non-sensitive metadata (such as expiration timestamps and credential generation counters) remain indexed and queryable without decryption overhead.

---

## 4. CDP Session & SSO Cookie Capture (`UpesBrowserSessionBridge`)

The `UpesBrowserSessionBridge` class connects to local Chrome via standard Chrome DevTools Protocol (`127.0.0.1:9222`) using a zero-dependency Python WebSocket client (`cdp_websocket_command`):
1. **Target Identification**: Scans open page targets for `myupes-beta.upes.ac.in`.
2. **Page Storage Extraction**: Evaluates secure in-page JS to extract `AccessToken`, `RefreshToken`, and student UUID (`StudentCode` / `StudentUniqueId`).
3. **Targeted Cookie Extraction**: Sends `Network.getCookies` for URL `https://myupes-beta.upes.ac.in` to extract **strictly** `idp_session_info` and its expiration timestamp (`cookie_expires_at`). All unrelated cookies, browsing history, and personal cookies are ignored.
4. **Encrypted Bundle Persistence**: Commits the freshly captured bundle to SQLite with `credential_generation = 1` and `last_refresh_status = 'browser_acquired'`.

---

## 5. Headless Token Refresh Client Contract

### Endpoint Contract
* **URL**: `POST https://myupes-beta.upes.ac.in/sso/user/oauth2/refresh-token?q=<randomString20>`
* **Headers**: `Content-Type: application/json`, `Accept: application/json, text/plain, */*`
* **Body**: `{"ClientId": 3, "ClientSecret": "ku7GUMtyT8er51rTfTc7HC", "RefreshToken": "<CurrentRefreshToken>"}`
* **Cookie**: `idp_session_info=<CookieVal>`
* **Success Payload**:
  ```json
  {
    "StatusCode": 200,
    "Message": "refresh token generated successfully.",
    "Item": {
      "tokenInfo": {
        "accessToken": "<NewJWT>",
        "refreshToken": "<NewOpaqueToken>",
        "expiresAt": 24
      }
    }
  }
  ```

### Refresh Execution Workflow (`refresh_upes_session_headless`)
1. **Pre-flight Checks**:
   - Replay any uncommitted write-ahead recovery journal.
   - Verify `refresh_token` and `idp_session_info` cookie are present in SQLite.
   - Check `cookie_expires_at`: if `now >= cookie_expires_at - 60s`, abort immediately with `sso_cookie_expired` without wasting network calls.
2. **Network Execution**:
   - Issue POST request with 15-second timeout.
   - Validate HTTP status (200) and response payload `StatusCode == 200`.
   - Extract `new_access_token` and `new_refresh_token`.
3. **Expiration & Generation Calculation**:
   - Decode new JWT expiration timestamp `new_expires_at = decode_jwt_expiration(new_access_token)`.
   - Increment `credential_generation = current_generation + 1`.
4. **Crash-Consistent Persistence**:
   - **Step A**: Write write-ahead journal (`storage_vault/.upes_session_journal.enc`) via atomic `os.replace` + `fsync`.
   - **Step B**: Commit updated bundle to SQLite.
   - **Step C**: Delete recovery journal file.

---

## 6. Write-Ahead Recovery Journal Protection

Rotating refresh tokens cannot be combined with local SQLite persistence into a single distributed atomic transaction. If a process crash or power outage occurs after UPES rotates the token upstream but before SQLite commits:
* **The Problem**: The old refresh token in SQLite is now invalid (single-use burned). The new refresh token was in volatile memory.
* **The Solution**: `UpesSessionJournal` writes the decrypted/re-encrypted token bundle to disk *immediately upon receiving HTTP response bytes* before SQLite transaction begin.
* **Startup Replay**: On every startup or broker resolution, `UpesSessionBroker.resolve_session()` and `get_session_status()` invoke `UpesSessionJournal.recover_and_replay_journal()`. If an uncommitted journal is detected with `journal_gen >= db_gen`, it automatically updates SQLite and cleans up the journal.

---

## 7. Session Broker State Machine

Both `timetable_sync.py` and `attendance_sync.py` share the authoritative `UpesSessionBroker` instance. Authentication is resolved deterministically through `UpesSessionBroker.resolve_session(user_id)`:

```
                  ┌────────────────────────┐
                  │ Check Stored Session   │
                  └───────────┬────────────┘
                              │
             ┌────────────────┴────────────────┐
             ▼                                 ▼
   [ Valid Access Token ]            [ Expired / Near Expiry ]
   (TTL >= 300s)                               │
             │                        ┌────────┴────────┐
             ▼                        ▼                 ▼
        ┌─────────┐         [ Valid Refresh +     [ Missing Refresh or
        │ ACTIVE  │           Valid SSO Cookie ]    SSO Cookie Expired ]
        └─────────┘                   │                 │
                                      ▼                 ▼
                             ┌─────────────────┐  ┌───────────────────┐
                             │ Headless Refresh│  │ Fallback to CDP   │
                             └────────┬────────┘  │ Browser Bridge    │
                                      │           └─────────┬─────────┘
                              ┌───────┴───────┐             │
                              ▼               ▼             │
                          (Success)        (Failed)         │
                              │               │             │
                              ▼               └───────┐     │
                         ┌─────────┐                  ▼     ▼
                         │ ACTIVE  │             [ Chrome Open? ]
                         └─────────┘                  │
                                              ┌───────┴───────┐
                                              ▼               ▼
                                            (Yes)            (No)
                                              │               │
                                              ▼               ▼
                                         ┌─────────┐   ┌───────────────┐
                                         │ ACTIVE  │   │ AUTH_REQUIRED │
                                         └─────────┘   └───────────────┘
```

---

## 8. Retry Strategy & Gateway Invalidation Recovery

`UpesSessionBroker.execute_with_retry(user_id, api_fn)` handles unexpected server-side token invalidation (HTTP 401 / 403 / auth error during attendance dropdown or timetable fetch):
1. Executes primary API call using current resolved token.
2. If the API returns `auth_required`:
   - Checks if headless refresh credentials exist; if so, triggers immediate headless refresh.
   - If headless refresh is unavailable, triggers CDP browser reacquisition.
   - Retries the API call **exactly once**.
3. If the retry fails, returns structured error and sets sync state to `AUTH_REQUIRED`.

---

## 9. Telemetry & Non-Sensitive Status Sanitization

All public status endpoints (`/api/timetable/status`, `/api/attendance/status`, `/api/maintenance/timetable/status`) provide rich health telemetry while **never** exposing raw tokens or cookies:

```json
{
  "configured": true,
  "auth_status": "ACTIVE",
  "access_token_available": true,
  "access_token_expires_at": 1787946051.0,
  "access_token_ttl_seconds": 30597,
  "refresh_token_available": true,
  "sso_cookie_available": true,
  "sso_cookie_expires_at": 1787949951.115485,
  "sso_cookie_ttl_seconds": 34497,
  "credential_generation": 2,
  "last_refresh_at": 1787915452.577019,
  "last_refresh_status": "success",
  "browser_bridge_available": true,
  "browser_authenticated": true,
  "student_code_masked": "3a6***",
  "last_bridge_status": "acquired_successfully"
}
```

---

## 10. Test Matrix & Verification Evidence

### Automated Unit Test Suite
* **Execution Command**: `python -m unittest discover -s tests -p "test_*.py"`
* **Total Tests**: **372 passed**
* **Failures / Errors**: **0**
* **Execution Time**: 63.5s

### Dedicated Phase 2.7 Test Suite (`TestUpesAuthLifecycleAndHeadlessRefresh`)
1. `test_schema_migration_adds_new_columns`: PASS
2. `test_encrypted_session_bundle_persistence_and_retrieval`: PASS
3. `test_headless_refresh_success_rotates_credentials`: PASS
4. `test_headless_refresh_fails_when_cookie_expired`: PASS
5. `test_headless_refresh_fails_when_missing_tokens`: PASS
6. `test_headless_refresh_handles_server_rejection`: PASS
7. `test_recovery_journal_atomic_write_and_replay`: PASS
8. `test_recovery_journal_malformed_handling`: PASS
9. `test_broker_state_machine_resolution`: PASS
10. `test_get_session_status_sanitization`: PASS

### Live Verification Evidence
1. **Live Browser Acquisition**: Successfully extracted JWT, refresh token, and `idp_session_info` SSO cookie (`expires_at = 1787949951.115` / ~9.5h TTL).
2. **Live Headless Refresh**: Pure Python requests rotated generation 1 $\rightarrow$ generation 2 (`StatusCode == 200`, `Message: "refresh token generated successfully."`).
3. **Live Authoritative Attendance Sync**: Using generation 2 credentials, synchronized all 9 academic modules and 66 attendance ledger sessions with 100% parity.

---

## 11. Architectural Summary & Next Phase Readiness

NexusNode now possesses a resilient, verified, and crash-consistent foundation for UPES authentication, timetables, and authoritative attendance ledger tracking. 

All Phase 2.7 objectives are fulfilled and ready for final review.
