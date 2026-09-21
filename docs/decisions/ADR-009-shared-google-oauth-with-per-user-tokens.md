# ADR-009: Shared Google OAuth Application with Per-User Tokens

**Status:** ACCEPTED  
**Scope:** External Integrations & Google Calendar  
**Last verified:** 2026-09-20  
**Evidence basis:** Phase 3.2 implementation, `timetable_sync.py`, `tests/test_timetable_sync.py`  

---

## Context
Google Calendar integration requires a Google Cloud Platform (GCP) OAuth 2.0 Client ID and Secret configured with appropriate scopes (`https://www.googleapis.com/auth/calendar.events`). Requiring every student user on the appliance to create their own GCP project and configure OAuth credentials is an impossible barrier for non-technical users. Conversely, using a single shared Google account for all users would destroy multi-tenant privacy.

## Decision
Adopt a hybrid multi-tenant OAuth model:
1. **Appliance-Level OAuth App**: The administrator configures a single GCP OAuth 2.0 Client application (stored encrypted in `google_oauth_app_config`).
2. **Per-User Scoped Tokens**: Each student user authenticates individually against their own personal Google account via an OAuth 2.0 authorization code flow.
3. **Encrypted Token Storage**: The resulting access and refresh tokens are stored encrypted at rest with PBKDF2/AES-GCM in `google_oauth_tokens` scoped strictly to `user_id`.
4. **Isolated Reconciler**: Background Google Calendar synchronization reconciles timetables into each user's separate calendar using only their own decrypted tokens.

## Alternatives Considered
1. **Per-User GCP Projects**: Rejected due to extreme setup friction and technical complexity for student users.
2. **Service Account with Domain-Wide Delegation**: Rejected because students use personal `@gmail.com` or university-managed Google Workspace accounts where domain delegation cannot be granted.

## Consequences
- **Positive**: One-time administrative setup on the appliance; simple one-click "Connect Google Calendar" flow for individual students; strong cryptographic segregation of Google access tokens.
- **Negative**: The administrator's GCP project must register student emails as "Test Users" in Google Cloud Console while in OAuth Testing status.

## Evidence
- `tests/test_timetable_sync.py` and `tests/test_multi_user_isolation.py` verify that Google OAuth tokens are isolated by `user_id` and never accessible across tenant boundaries.

## Related Components
- `timetable_sync.py`
- `app.py`
- `static/js/accounts.js`
