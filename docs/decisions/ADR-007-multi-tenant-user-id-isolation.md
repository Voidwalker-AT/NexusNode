# ADR-007: Multi-Tenant User ID Isolation

**Status:** ACCEPTED  
**Scope:** Security & Data Multi-Tenancy  
**Last verified:** 2026-09-20  
**Evidence basis:** Phase 3.2 implementation, `tests/test_multi_user_isolation.py`, database schemas  

---

## Context
NexusNode was originally designed as a single-user personal server where all database queries implicitly assumed a single global student profile. To support multiple family members or academic peers on the same appliance, strong isolation is necessary to prevent data leakage between different student accounts.

## Decision
Enforce strict multi-tenancy based on `user_id` across all layers:
1. **Database Queries**: All academic tables (`user_timetables`, `official_attendance_summaries`, `academic_sessions`, `timetable_events_map`, `upes_user_credentials`, `google_oauth_tokens`) enforce `user_id` in their primary keys and require `WHERE user_id = ?` on every query.
2. **Vault Filesystem**: Each user has an isolated root directory (`storage_vault/users/{user_id}/`). Directory traversal outside the tenant root is strictly prevented.
3. **Browser Profiles**: Each user has an isolated browser profile directory (`browser/profiles/{user_id}/`) to ensure cookies, WebSSO sessions, and localStorage are completely segregated.
4. **Principal Derivation**: In MCP and REST requests, `user_id` is derived strictly from the authenticated token/session, rejecting any client attempts to override the target user.

## Alternatives Considered
1. **Separate Database Per User (Database-per-tenant)**: Rejected due to file descriptor limits, connection pooling overhead, and complex maintenance on Android Termux.
2. **Global Single User with Profiles in UI**: Rejected due to zero security isolation and vulnerability to credential cross-contamination.

## Consequences
- **Positive**: Clean multi-user isolation on a single SQLite database; robust role-based access control (`admin` vs `user`); secure multi-tenant hosting on a single appliance.
- **Negative**: Requires rigorous unit testing of every route and database query to prevent missing `user_id` filters.

## Evidence
- `tests/test_multi_user_isolation.py` comprehensively verifies that user B cannot read or overwrite user A's timetable, attendance, credentials, or files (21/21 passed).

## Related Components
- `app.py`
- `agent/policy.py`
- `timetable_sync.py`
- `attendance_sync.py`
- `upes/credentials.py`
