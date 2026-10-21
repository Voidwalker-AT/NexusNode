# NexusNode — Phase 1B: Live UPES Authentication Recovery & Root Cause Audit

**Target Physical Device**: TECNO BG6 (`109973141A030946`), Android 13, ARM64  
**Date**: 2026-10-21  
**Authoritative Location**: `docs/operations/PHASE1B_AUTH_RECOVERY.md`  
**Git Checkpoint**: Phase 1B Verified  

---

## 1. Executive Summary

During Phase 1B, an exhaustive, evidence-backed recovery of the UPES authentication lifecycle was executed on the physical TECNO BG6 appliance.

### Primary Recoveries & Achievements
1. **Account Realignment to Authentic Identity**:
   - Investigation established that user `admin` on BG6 had mistakenly been configured with `Augustya.12410@stu.upes.ac.in`.
   - The user's authentic UPES credentials for `anmol.11794@stu.upes.ac.in` (SAP ID: `590011794`, Student UUID: `3a678d8e-8817-41e6-b1a8-5a3ec6ee4948`) were securely preserved under account `papa` on BG6 and `admin` on Windows.
   - A point-in-time SQLite snapshot backup was created at:
     `/data/data/com.termux/files/home/server_backup_phase1b_credentials_alignment/nexus_unified.db`
     *(SHA-256: `a2c685ae0ddbf7ddad8e627ddc351f6257c8be0c8ae7ebec73148eba26cacdd7`)*
   - `admin`'s stored credentials on BG6 were cleanly updated to `anmol.11794@stu.upes.ac.in` with the authentic AES-256-GCM encrypted password.

2. **Session Disappearance Root Cause**:
   - The last active UPES session on BG6 expired on **2026-08-28T16:13:24 UTC** (`1787919204`).
   - The upstream IdP SSO session cookie (`idp_session_info`) expired after 10 hours (`expires_at: 1787954832`), and the OAuth token expired after 7 days, exhausting headless renewal tiers (Tiers 2-4).
   - Calling direct-HTTP password login (`POST /sso/api/account/oauth2/token`) with dummy Captcha `-` returns HTTP 500 from UPES SSO because Google reCAPTCHA v2 is enforced on `https://myupes-beta.upes.ac.in/oneportal/app/auth/login`.

3. **Secure Interactive Handoff & Session Ingestion**:
   - The user completed the login challenge on the portal.
   - The fresh OAuth session context was securely ingested into NexusNode without exposing tokens, passwords, or cookies in chat or logs.
   - Identity validation against `https://myupes-beta.upes.ac.in/apigateway/connect-portal/api/studentloginbasicinfo` confirmed:
     - **Student Name**: ANMOL THAPLIYAL
     - **Student Email**: `ANMOL.11794@stu.upes.ac.in`
     - **Global/SAP ID**: `590011794`
     - **Student UUID**: `3a678d8e-8817-41e6-b1a8-5a3ec6ee4948`
     - **Course Family**: B.Tech CSE (Semester 5)
   - The session bundle was committed to SQLite table `upes_auth_sessions` using AES-256-GCM authenticated encryption (`UpesSessionCrypto`).

4. **Live Status**:
   - **State**: `AUTHENTICATED`
   - **Access Token TTL**: ~37,500s (~10.4 hours remaining)
   - **Has Refresh Token**: `True`
   - **Circuit Breaker**: `CLOSED` (0 consecutive failures)
   - **Is Live Ready**: `True`

---

## 2. On-Device Verification Evidence

```text
AUTH_SESSION ROW: ('admin', '3a678d8e-8817-41e6-b1a8-5a3ec6ee4948', 1792631460.66, 1, 'session_imported', 1792593816.55)
MGR STATUS: {
  'user_id': 'admin',
  'configured': True,
  'credentials_configured': True,
  'expected_identifier_format': 'FULL_EMAIL',
  'configured_identifier_format': 'UNKNOWN',
  'identifier_mismatch': False,
  'state': 'AUTHENTICATED',
  'session': {
    'user_id': 'admin',
    'configured': True,
    'state': 'AUTHENTICATED',
    'autonomy_level': 'LEVEL_2_IDP_REFRESH',
    'student_code_masked': '3a67***4948',
    'token_expiry': 1792631460.66,
    'token_ttl_seconds': 37587,
    'has_refresh_token': True,
    'is_live_ready': True
  },
  'circuit': {
    'state': 'closed',
    'last_error': None,
    'retry_after_seconds': 0
  }
}
```

---

## 3. The 6-Tier Authentication Pipeline Status

| Tier | Mechanism | Status | Evidence / Notes |
| :--- | :--- | :--- | :--- |
| **Tier 1** | Active In-Memory & Persisted OAuth Token | **ACTIVE** | Live token stored in `upes_auth_sessions` (TTL > 10h). |
| **Tier 2** | Headless OAuth Token Refresh (`/refresh-token`) | **ARMED** | Active `refresh_token` stored at rest; rotates automatically. |
| **Tier 3** | Silent IdP Session SSO Renewal (`/authorize`) | **ARMED** | Ready when IdP cookies are populated. |
| **Tier 4** | Silent Browser Context Renewal | **AVAILABLE** | Ephemeral Chromium available on device. |
| **Tier 5** | Direct Credential SSO Login | **FALLBACK** | Encrypted credentials stored for emergency fallback. |
| **Tier 6** | `AUTH_REQUIRED` / Interactive Handoff | **READY** | Handoff protocol verified; clean handoff if challenges appear. |
