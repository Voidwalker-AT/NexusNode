# Guided Academic Account Onboarding & Multi-Tenant Operations

## Overview
Phase 4.3A introduces the dual-persona onboarding system for NexusNode:
1. **Admin Governance Wizard** (`+ Add Academic Account`): An authoritative 11-step wizard for administrators to provision, validate, and verify academic accounts.
2. **Student Self-Service View** (`My Academic Account`): A contextual, state-driven checklist displaying real-time synchronization readiness, verification points, and the dynamic `NEXT REQUIRED ACTION`.

---

## 1. Admin 11-Step Onboarding Wizard

The administrator accesses the wizard via the **Accounts** tab by clicking `+ Add Academic Account`:

| Step | Stage Name | Verification Action |
| :--- | :--- | :--- |
| **1** | **Identity Configuration** | Provision unique `user_id`, username, and assign role (`STUDENT`). |
| **2** | **UPES Credentials** | Input student SAP ID / enrollment number and portal password. |
| **3** | **Hardware Encryption** | Encrypt credentials using appliance AES-256-GCM hardware key. |
| **4** | **Upstream Authentication Test** | Execute safe read-only login probe to verify password validity. |
| **5** | **Google OAuth Client Setup** | Validate presence of shared Google OAuth Web App configuration. |
| **6** | **Google Authorization URL** | Generate scoped authorization link with state nonce. |
| **7** | **Google Consent Verification** | Verify token exchange (`access_token`, `refresh_token`, calendar scopes). |
| **8** | **Initial Timetable Sync** | Ingest academic schedule from UPES ConnectPortal. |
| **9** | **Initial Attendance Sync** | Fetch attendance records, safe bunks baseline, and punch logs. |
| **10** | **Initial Results Ingestion** | Ingest published semester results, SGPA, and cumulative CGPA. |
| **11** | **Activation & Scheduler Enrollment**| Mark user operational; register into 3-hour automated sync rotation. |

---

## 2. Student Self-Service Checklist & State Machine

When an authenticated student logs into NexusNode, the Accounts view dynamically presents the **10-Point Readiness Checklist**:

```
[Student Account State Engine]
              |
              +---> 1. Account Identity Provisioned
              +---> 2. Encrypted UPES Credentials Present
              +---> 3. UPES Portal Login Validated
              +---> 4. Google OAuth Connected
              +---> 5. Google Calendar Scopes Granted
              +---> 6. Timetable Ingested & Active
              +---> 7. Google Calendar Reconciled
              +---> 8. Attendance Ledger Synchronized
              +---> 9. Academic Results & CGPA Available
              +---> 10. Automated 3-Hour Sync Active
```

### Deterministic Precedence & `NEXT REQUIRED ACTION`
The state engine computes the immediate single action required from the user:
1. `GOOGLE_REQUIRED`: "Connect your Google Calendar account to begin schedule sync."
2. `GOOGLE_EXPIRED`: "Re-authenticate your Google Account (refresh token revoked)."
3. `UPES_REQUIRED`: "Enter your UPES credentials to enable timetable and attendance sync."
4. `UPES_EXPIRED`: "Re-enter your UPES password (upstream authentication expired)."
5. `UPES_INTERACTION_REQUIRED`: "UPES portal requires manual verification / captcha solve."
6. `READY_TO_SYNC`: "All credentials connected. Click 'Trigger Sync' to run first-time ingestion."
7. `READY`: "All academic systems operational and synchronized."

---

## 3. Shared Google OAuth Web App Architecture

NexusNode implements a shared multi-tenant OAuth Web App model:
- **Client Configuration**: A single Google Cloud Console OAuth 2.0 Web Application client ID and secret is stored in `google_oauth_app_config`.
- **Per-Tenant Isolation**: Each student authorizes their own Google account. Tokens (`access_token`, `refresh_token`, expiry) are stored in `google_oauth_tokens` partitioned strictly by `user_id`.
- **Testing-Mode Guidance**:
  - Because the Google OAuth consent screen is in *Testing* mode, students must be added as **Test Users** under Google Cloud Console $\rightarrow$ APIs & Services $\rightarrow$ OAuth consent screen.
  - Authorized Redirect URI must include both local and ingress domain paths:
    - `http://192.168.29.21:5000/oauth2callback`
    - `https://<public-tunnel-domain>/oauth2callback`
