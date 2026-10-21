# NexusNode — Phase 1B: Live UPES Authentication Recovery & Root Cause Audit

**Target Physical Device**: TECNO BG6 (`109973141A030946`), Android 13, ARM64  
**Date**: 2026-10-21  
**Authoritative Location**: `docs/operations/PHASE1B_AUTH_RECOVERY.md`  
**Git Checkpoint**: `c812dd4`  

---

## 1. Executive Summary

During Phase 1B, an exhaustive, evidence-backed investigation was conducted into the UPES authentication lifecycle on the physical TECNO BG6 appliance.

### Primary Findings
1. **Admin Credentials Intact & Decryptable**:
   - User `admin` has encrypted credentials stored at rest in SQLite table `upes_user_credentials`.
   - Username hint: `Aug***@stu.upes.ac.in` (`Augustya.12410@stu.upes.ac.in`).
   - Format: `FULL_EMAIL` (Format mismatch: `False`).
   - AES-256-GCM domain envelope `nexusnode/upes/credentials/v1` decrypted successfully on BG6 using the host `SECRET_KEY`.
2. **Session Disappearance Root Cause**:
   - The historical backup (`phase32_1788076900/nexus_unified.db`) shows the last active UPES session was generated on **2026-08-28T16:13:24 UTC** (`1787919204`).
   - The upstream IdP SSO session cookie (`idp_session_info`) had a strict 10-hour lifespan (`expires_at: 1787954832`, ~22:07 UTC on Aug 28).
   - Once the IdP session cookie expired and the OAuth token expired (~7 days later), all unattended headless renewal tiers (Tier 2 and Tier 3) were exhausted.
   - During subsequent database hygiene / truth repairs, the expired, unrenewable record was pruned, leaving `upes_auth_sessions` empty (0 active sessions).
3. **Direct-HTTP Password Login Limitation**:
   - Calling `POST https://myupes-beta.upes.ac.in/sso/api/account/oauth2/token` with dummy Captcha (`-`) triggers an HTTP 500 error from UPES.
   - On-device CDP inspection using the ephemeral Chromium provider on BG6 confirmed that `https://myupes-beta.upes.ac.in/oneportal/app/auth/login` renders **Google reCAPTCHA v2** (`formcontrolname="recaptcha"`).
   - Form state remains `ng-invalid` and the `LOGIN` submit button remains strictly `disabled: true` until a human interaction solves the reCAPTCHA challenge.
   - In accordance with safety rules, zero CAPTCHA circumvention was attempted.

---

## 2. On-Device Authentication Verification Evidence

### A. Credential Verification on BG6
```text
admin has_credentials: True
admin credential identity: {
  'user_id': 'admin',
  'configured_format': 'IdentifierFormat.FULL_EMAIL',
  'username_hint': 'Aug***@stu.upes.ac.in',
  'mismatch': False
}
Decryption test: SUCCESS! Domain: nexusnode/upes/credentials/v1 Keys: ['username', 'password', 'updated_at', 'version', 'domain']
Username domain: stu.upes.ac.in
Circuit Breaker: CLOSED (consecutive_failures=0)
```

### B. Live DOM & CAPTCHA Inspection on BG6 (Ephemeral Chromium via CDP)
```json
{
  "url": "https://myupes-beta.upes.ac.in/oneportal/app/auth/login",
  "title": "Login | MyUPES",
  "uInputFound": true,
  "uInputSelector": "<input name=\"userName\" placeholder=\"Enter a valid user name\" ...>",
  "pInputFound": true,
  "btnFound": true,
  "btnText": "LOGIN",
  "btnDisabled": true,
  "hasCaptcha": true,
  "captchaEls": [
    {
      "tag": "RE-CAPTCHA",
      "id": "ngrecaptcha-0",
      "className": "ng-untouched ng-pristine ng-invalid",
      "outerHTML": "<re-captcha formcontrolname=\"recaptcha\" id=\"ngrecaptcha-0\" ...>"
    },
    {
      "tag": "TEXTAREA",
      "id": "g-recaptcha-response",
      "className": "g-recaptcha-response"
    }
  ]
}
```

### C. Automated Form Fill Test
When credentials were typed into `userName` and `password` via CDP DOM evaluation:
```json
{
  "uVal": "Augustya.12410@stu.upes.ac.in",
  "pValLen": 14,
  "btnDisabled": true,
  "formClass": "my-login-validation ng-untouched ng-invalid ng-dirty"
}
```
Result: The form remains `ng-invalid` because the Google reCAPTCHA v2 response textarea is empty. Clicking the button emits zero HTTP POST requests.

---

## 3. The 6-Tier Authentication Pipeline Status

| Tier | Mechanism | Status | Evidence / Notes |
| :--- | :--- | :--- | :--- |
| **Tier 1** | Active In-Memory & Persisted OAuth Token | **EXHAUSTED** | 0 active sessions in `upes_auth_sessions`. |
| **Tier 2** | Headless OAuth Token Refresh (`/refresh-token`) | **EXHAUSTED** | No active refresh token available in database. |
| **Tier 3** | Silent IdP Session SSO Renewal (`/authorize`) | **EXHAUSTED** | `idp_session_info` cookie expired in August 2026. |
| **Tier 4** | Silent Browser Context Renewal | **EXHAUSTED** | Ephemeral browser profiles start clean; no persistent SSO cookie saved. |
| **Tier 5** | Direct Credential SSO Login | **BLOCKED** | Upstream SSO returns HTTP 500 / requires Google reCAPTCHA v2. |
| **Tier 6** | `AUTH_REQUIRED` / Interactive Handoff | **ACTIVE** | Required interactive checkpoint reached. |

---

## 4. Minimum Interactive Handoff Protocol

To recover authentication without compromising credentials or bypassing security controls, the user performs a one-time interactive login:

### Step 1: Portal Login
Open `https://myupes-beta.upes.ac.in` in any standard web browser on laptop or smartphone, enter credentials for `Augustya.12410@stu.upes.ac.in`, and solve the reCAPTCHA challenge.

### Step 2: Extract Bearer Token
Open Developer Tools (`F12` or `Ctrl+Shift+I` -> Console tab) and execute:
```javascript
(() => {
  const d = JSON.parse(localStorage.getItem("qW0bzwe6hm4r") || "{}");
  const id = d.Identity || {};
  return {
    access_token: id.AccessToken,
    refresh_token: id.RefreshToken,
    expires_at: id.ExpiresIn ? (Date.now()/1000 + id.ExpiresIn) : undefined
  };
})()
```

### Step 3: Secure Session Import
Submit the token to NexusNode's production import endpoint:
```bash
curl -X POST "http://192.168.29.21:5000/api/upes/auth/import" \
  -H "Content-Type: application/json" \
  -d '{"access_token": "<EXTRACTED_ACCESS_TOKEN>", "refresh_token": "<EXTRACTED_REFRESH_TOKEN>"}'
```
Or execute on device via SSH:
```bash
python scripts/set_upes_session.py --token "<EXTRACTED_ACCESS_TOKEN>"
```

Once imported, `import_authenticated_context` validates student info with `studentloginbasicinfo`, encrypts the token at rest using `UpesSessionCrypto` (`nexusnode/upes/session/v1`), and unlocks live timetable and attendance synchronization.
