# 3-Hour Automation & Google Calendar Reconciliation Architecture

## Overview
NexusNode Phase 4.3A establishes a persistent, reliable, and multi-subsystem isolated 3-hour automation pipeline. The scheduler coordinates synchronization across four independent subsystems—**Timetable & Google Calendar**, **Attendance**, **Results & SGPA/CGPA**, and **LMS**—while guaranteeing complete failure isolation between domains and tenants.

---

## 1. Cadence & Scheduler Loop Invariants

- **Interval**: Exactly 3 hours (`10,800` seconds / `interval_seconds = 10800` in SQLite `scheduled_jobs`).
- **Job ID**: `job_timetable_sync`
- **Execution Function**: `app.run_timetable_sync_job(task_obj)`
- **Restart Recovery**: The scheduler persists `next_run` timestamp in SQLite. On appliance reboot or daemon restart, jobs are evaluated against current time. If `next_run > now`, immediate duplicate runs are suppressed.
- **Resource Constraints on BG6**:
  - Memory delta per execution cycle $\le 10 \text{ MB}$.
  - Exactly **0 Chromium browser instances** launched during normal synchronization.

---

## 2. Multi-Subsystem Failure Containment Invariant

### Principle of Independent Subsystems
The scheduler loop dispatches each subsystem in independent `try...except` containment blocks:

```
[3-Hour Scheduler Tick]
         |
         +---> 1. Timetable & Google Calendar Reconciliation (Pillar B)
         |        - Success / Fail logged independently
         |
         +---> 2. Attendance Ledger Sync (Isolated)
         |        - Failure NEVER blocks timetable or calendar
         |
         +---> 3. Academic Results Sync (Pillar A)
         |        - Failure NEVER blocks timetable or calendar
         |
         +---> 4. LMS Metadata Telemetry (Pillar D)
                  - Failure NEVER blocks timetable or calendar
```

### Calendar Reconciliation Dependency Invariant
> [!IMPORTANT]
> **Calendar reconciliation depends ONLY on trustworthy timetable data.**
> Reconciliation MUST NOT depend on the success of Attendance, LMS, or Academic Results. If Results, LMS, or Attendance fail, their errors are recorded in audit logs and Calendar reconciliation continues uninterrupted.

---

## 3. Last Known Good (LKG) Destructive Protection

To prevent accidental event deletion from Google Calendar when upstream UPES portals return transient empty responses, network errors, or degraded states:

```
If Timetable Source is:
   - Fresh & Valid:
        reconcile_events(allow_deletions = True)
   - Empty, Malformed, Stale, or Degraded (LKG fallback):
        reconcile_events(allow_deletions = False)
```

1. **Empty Set Protection**: If the parser extracts 0 sessions while historical sessions exist, the payload is treated as suspicious, deletions are disabled (`allow_deletions = False`), and an alert incident is logged.
2. **LKG Degraded State**: When operating from cached timetable sessions, existing Google Calendar events are preserved and updated; no deletions are performed.

---

## 4. Calendar Reconciliation Idempotence

Reconciliation between the local `academic_sessions` database and the Google Calendar API strictly adheres to idempotent diffing:

$$\Delta = \text{Source Sessions} \setminus \text{Managed Remote Events}$$

On consecutive identical runs without upstream schedule modifications:
- `CREATE = 0`
- `UPDATE = 0`
- `DELETE = 0`
- `UNCHANGED > 0` (All existing events marked NOOP)

This guarantees zero Google Calendar API quota waste and prevents duplicate event clutter.

---

## 5. Multi-Tenant Failure Isolation

When processing multiple academic accounts in `sync_all_active_users()`:
1. Each tenant executes within an isolated exception handler.
2. A credential failure, expired token, or quota error in Tenant A (`student_a`) has zero side-effects on Tenant B (`student_b`).
3. Distributed SQLite leases (`DatabaseSyncLease` with 300s TTL) prevent concurrent execution collisions between scheduled background tasks and manual UI triggers.

---

## 6. Cloudflare & Ingress Tunnel Independence

The scheduler runs entirely within the local Python runtime on the physical BG6 appliance. It interacts with:
- Local SQLite database (`nexus_unified.db`)
- Direct upstream HTTPS endpoints (`upes.ac.in`, `googleapis.com`)

Tunnel health (Cloudflare / Localtonet) has zero impact on scheduler execution. Background timetable and calendar sync continues flawlessly even during ingress tunnel interruptions.
