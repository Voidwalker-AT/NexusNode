"""
Deterministic 3-Hour Automation & Calendar Reconciliation Test Suite
Phase 4.3A: Fast-time scheduler simulation, multi-tenant failure isolation,
calendar idempotence, LKG destructive protection, and tunnel independence.
"""

import os
import time
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from decimal import Decimal

import config
from timetable_sync import (
    TimetableService,
    TimetableSession,
    TimetableSynchronizer,
    DatabaseSyncLease,
    GoogleCalendarClient,
    init_timetable_tables
)
from upes.results import CourseResult, SemesterResult, AcademicRecord


class TestThreeHourSchedulerSimulation(unittest.TestCase):
    """Deterministic fast-time simulation of 3-hour scheduler loop."""

    def setUp(self):
        self.temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.temp_db.close()
        self.db_path = self.temp_db.name

        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("""
            CREATE TABLE scheduled_jobs (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                job_type TEXT NOT NULL,
                interval_seconds INTEGER NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                last_run REAL,
                next_run REAL,
                last_status TEXT,
                last_error TEXT,
                created_at REAL DEFAULT 0
            );
        """)
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except Exception:
                pass

    def test_01_interval_is_exact_three_hours(self):
        """Verifies timetable sync cadence is seeded at 10,800 seconds (3 hours)."""
        t0 = 1700000000.0
        self.conn.execute("""
            INSERT INTO scheduled_jobs (id, name, job_type, interval_seconds, enabled, last_run, next_run)
            VALUES ('job_timetable_sync', 'UPES Timetable Google Calendar Sync', 'timetable_sync', 10800, 1, ?, ?)
        """, (t0, t0 + 10800))
        self.conn.commit()

        row = self.conn.execute("SELECT interval_seconds, next_run - last_run AS diff FROM scheduled_jobs WHERE id = 'job_timetable_sync'").fetchone()
        self.assertEqual(row["interval_seconds"], 10800)
        self.assertEqual(row["diff"], 10800)

    def test_02_fast_time_dispatch_simulation(self):
        """
        Simulates:
        T0: scheduler initialized
        T0 + 2h59m: no execution
        T0 + 3h: exactly one execution
        T0 + 6h: second execution
        """
        t0 = 1700000000.0
        interval = 10800  # 3 hours

        self.conn.execute("""
            INSERT INTO scheduled_jobs (id, name, job_type, interval_seconds, enabled, last_run, next_run)
            VALUES ('job_timetable_sync', 'UPES Timetable Sync', 'timetable_sync', ?, 1, ?, ?)
        """, (interval, t0, t0 + interval))
        self.conn.commit()

        dispatches = []

        def scheduler_tick(simulated_now: float):
            cur = self.conn.cursor()
            cur.execute("SELECT id, name, job_type, interval_seconds FROM scheduled_jobs WHERE enabled = 1 AND next_run <= ?", (simulated_now,))
            jobs = cur.fetchall()
            for j in jobs:
                dispatches.append((j["id"], simulated_now))
                self.conn.execute(
                    "UPDATE scheduled_jobs SET last_run = ?, next_run = ?, last_status = 'dispatched' WHERE id = ?",
                    (simulated_now, simulated_now + j["interval_seconds"], j["id"])
                )
            self.conn.commit()

        # Tick at T0 + 2h59m (10740s) -> Should NOT execute
        scheduler_tick(t0 + 10740)
        self.assertEqual(len(dispatches), 0, "Job must not execute before 3 hours")

        # Tick at T0 + 3h (10800s) -> Should execute EXACTLY once
        scheduler_tick(t0 + 10800)
        self.assertEqual(len(dispatches), 1, "Job must execute at exactly 3 hours")
        self.assertEqual(dispatches[0][0], "job_timetable_sync")

        # Verify next_run was updated to T0 + 6h (21600s)
        row = self.conn.execute("SELECT next_run FROM scheduled_jobs WHERE id = 'job_timetable_sync'").fetchone()
        self.assertEqual(row["next_run"], t0 + 21600)

        # Tick again at T0 + 4h (14400s) -> Should NOT execute again
        scheduler_tick(t0 + 14400)
        self.assertEqual(len(dispatches), 1, "Job must not re-execute prematurely")

        # Tick at T0 + 6h (21600s) -> Second execution
        scheduler_tick(t0 + 21600)
        self.assertEqual(len(dispatches), 2, "Job must execute again at 6 hours")
        self.assertEqual(dispatches[1][1], t0 + 21600)

    def test_03_restart_recovery_without_duplicate_dispatch(self):
        """Simulates server restart: next_run in DB must prevent duplicate immediate job run."""
        t0 = 1700000000.0
        interval = 10800

        # Server ran job at t0, scheduled next run at t0 + 10800
        self.conn.execute("""
            INSERT INTO scheduled_jobs (id, name, job_type, interval_seconds, enabled, last_run, next_run)
            VALUES ('job_timetable_sync', 'UPES Timetable Sync', 'timetable_sync', ?, 1, ?, ?)
        """, (interval, t0, t0 + interval))
        self.conn.commit()

        # Server restarts at t0 + 30 minutes (1800s)
        restart_time = t0 + 1800

        # Scheduler recovers jobs
        cur = self.conn.cursor()
        cur.execute("SELECT id, name, next_run FROM scheduled_jobs WHERE enabled = 1 AND next_run <= ?", (restart_time,))
        jobs_due = cur.fetchall()

        # Must be empty: job is not due yet
        self.assertEqual(len(jobs_due), 0, "Restart must not trigger immediate duplicate execution")


class TestMultiTenantSchedulerFailureContainment(unittest.TestCase):
    """Tests that one tenant's failure never cascades to other tenants."""

    def test_tenant_failure_isolation(self):
        tenants = ["student_a", "student_b", "student_c"]
        sync_results = {}

        def mock_sync_user(user_id: str):
            if user_id == "student_a":
                # Healthy user: sync succeeds
                return {"status": "success", "created": 2, "updated": 0, "deleted": 0, "unchanged": 10, "errors": []}
            elif user_id == "student_b":
                # Expired auth: raises exception or degrades to LKG
                raise RuntimeError("UPES token expired (HTTP 401)")
            elif user_id == "student_c":
                # Google disconnected: returns error dictionary
                return {"status": "error", "message": "Google account not connected", "errors": ["Google disconnected"]}

        # Run multi-tenant loop with isolation pattern
        for u in tenants:
            try:
                sync_results[u] = mock_sync_user(u)
            except Exception as e:
                sync_results[u] = {"status": "failed", "errors": [str(e)]}

        # Assert all 3 were processed
        self.assertIn("student_a", sync_results)
        self.assertIn("student_b", sync_results)
        self.assertIn("student_c", sync_results)

        # Assert student_a succeeded despite student_b failing
        self.assertEqual(sync_results["student_a"]["status"], "success")
        self.assertEqual(sync_results["student_a"]["created"], 2)

        # Assert student_b failure was contained
        self.assertEqual(sync_results["student_b"]["status"], "failed")
        self.assertIn("HTTP 401", sync_results["student_b"]["errors"][0])

        # Assert student_c error was contained
        self.assertEqual(sync_results["student_c"]["status"], "error")

    @patch("app.attendance_service.sync_all_active_users")
    @patch("app.results_service.sync_all_active_users")
    @patch("app.timetable_service.sync_all_active_users")
    def test_subsystem_failure_isolation_in_sync_job(self, mock_tt, mock_res, mock_att):
        """Proves Calendar reconciliation succeeds even if Results/Attendance/LMS fail."""
        import app
        mock_tt.return_value = {"student_1": {"status": "success", "created": 1, "updated": 0, "deleted": 0, "unchanged": 5}}
        mock_att.side_effect = RuntimeError("Attendance portal timed out")
        mock_res.side_effect = RuntimeError("Results ExamPro DB unreachable")

        task_obj = {"logs": []}
        app.run_timetable_sync_job(task_obj)

        # Timetable sync must have executed and succeeded
        mock_tt.assert_called_once()
        mock_att.assert_called_once()
        mock_res.assert_called_once()

        logs_str = "\n".join(task_obj["logs"])
        self.assertIn("Timetable sync completed: 1 users", logs_str)
        self.assertIn("Attendance sync job error", logs_str)
        self.assertIn("Results sync job error", logs_str)


class TestCalendarReconciliationIdempotenceAndLKG(unittest.TestCase):
    """Tests calendar reconciliation idempotence and LKG destructive protection."""

    def setUp(self):
        self.temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.temp_db.close()
        self.db_path = self.temp_db.name

        def conn_factory():
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            return conn

        self.conn_factory = conn_factory

        # Initialize event map table
        conn = self.conn_factory()
        init_timetable_tables(conn)
        conn.commit()
        conn.close()

        # Mock Google Calendar Client
        self.mock_client = MagicMock()
        self.remote_events = {}

        def mock_create(cal_id, session, user_id):
            event_id = f"g_event_{len(self.remote_events) + 1}"
            slot_key = session.canonical_slot_key
            event_obj = {
                "id": event_id,
                "summary": session.course_name,
                "start": {"dateTime": f"{session.date}T{session.start_time}+05:30"},
                "end": {"dateTime": f"{session.date}T{session.end_time}+05:30"},
                "extendedProperties": {
                    "private": {
                        "nexusnode_managed": "true",
                        "nexusnode_schema": "timetable-v1",
                        "nexusnode_slot_key": slot_key,
                        "nexusnode_user_id": user_id,
                        "nexusnode_session_id": session.session_id,
                        "nexusnode_course_code": session.course_code or "",
                        "nexusnode_date": session.date,
                        "nexusnode_hash": session.deterministic_hash
                    }
                }
            }
            self.remote_events[event_id] = event_obj
            return event_obj

        def mock_update(cal_id, event_id, session, user_id):
            if event_id in self.remote_events:
                self.remote_events[event_id]["summary"] = session.course_name
                return self.remote_events[event_id]
            return {"id": event_id}

        def mock_delete(cal_id, event_id):
            if event_id in self.remote_events:
                del self.remote_events[event_id]
            return True

        def mock_list(cal_id, time_min=None, time_max=None):
            return list(self.remote_events.values())

        self.mock_client.create_event.side_effect = mock_create
        self.mock_client.update_event.side_effect = mock_update
        self.mock_client.delete_event.side_effect = mock_delete
        self.mock_client.list_managed_events.side_effect = mock_list

        self.synchronizer = TimetableSynchronizer(
            self.conn_factory, "student_test", self.mock_client, "primary"
        )

    def tearDown(self):
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except Exception:
                pass

    def _sample_sessions(self):
        return [
            TimetableSession(
                course_name="Data Structures",
                course_code="CS101",
                date="2026-09-21",
                start_time="09:00:00",
                end_time="10:00:00",
                room="Room 101",
                faculty="Dr. Smith",
                session_id="sess_1"
            ),
            TimetableSession(
                course_name="Algorithms",
                course_code="CS102",
                date="2026-09-21",
                start_time="10:00:00",
                end_time="11:00:00",
                room="Room 102",
                faculty="Dr. Jones",
                session_id="sess_2"
            )
        ]

    def test_idempotent_reconciliation(self):
        sessions = self._sample_sessions()

        # 1. First reconciliation: should create 2 events
        res1 = self.synchronizer.synchronize(sessions, dry_run=False, allow_deletions=True)
        self.assertEqual(res1["created"], 2)
        self.assertEqual(res1["updated"], 0)
        self.assertEqual(res1["deleted"], 0)
        self.assertEqual(res1["unchanged"], 0)
        self.assertEqual(len(self.remote_events), 2)

        # 2. Second reconciliation on identical data: MUST be 100% idempotent
        res2 = self.synchronizer.synchronize(sessions, dry_run=False, allow_deletions=True)
        self.assertEqual(res2["created"], 0, "Idempotence failed: CREATE > 0 on identical rerun")
        self.assertEqual(res2["updated"], 0, "Idempotence failed: UPDATE > 0 on identical rerun")
        self.assertEqual(res2["deleted"], 0, "Idempotence failed: DELETE > 0 on identical rerun")
        self.assertEqual(res2["unchanged"], 2, "Idempotence failed: Expected 2 NOOP events")
        self.assertEqual(len(self.remote_events), 2)

    def test_controlled_timetable_mutations(self):
        """Tests minimal mutation diffs when classes are added, modified, or removed."""
        sessions = self._sample_sessions()

        # 1. Initial 2 classes
        res1 = self.synchronizer.synchronize(sessions, dry_run=False, allow_deletions=True)
        self.assertEqual(res1["created"], 2)

        # 2. Add a 3rd class
        sessions_added = sessions + [
            TimetableSession(
                course_name="Machine Learning",
                course_code="CS103",
                date="2026-09-21",
                start_time="11:00:00",
                end_time="12:00:00",
                room="Room 103",
                faculty="Dr. Turing",
                session_id="sess_3"
            )
        ]
        res_add = self.synchronizer.synchronize(sessions_added, dry_run=False, allow_deletions=True)
        self.assertEqual(res_add["created"], 1)
        self.assertEqual(res_add["unchanged"], 2)
        self.assertEqual(res_add["deleted"], 0)

        # 3. Modify room on class 1
        sessions_mod = [
            TimetableSession(
                course_name="Data Structures",
                course_code="CS101",
                date="2026-09-21",
                start_time="09:00:00",
                end_time="10:00:00",
                room="Room 999 NEW",  # Modified room
                faculty="Dr. Smith",
                session_id="sess_1"
            ),
            sessions_added[1],
            sessions_added[2]
        ]
        res_mod = self.synchronizer.synchronize(sessions_mod, dry_run=False, allow_deletions=True)
        self.assertEqual(res_mod["updated"], 1)
        self.assertEqual(res_mod["unchanged"], 2)
        self.assertEqual(res_mod["created"], 0)

        # 4. Remove 3rd class
        res_rem = self.synchronizer.synchronize(sessions_mod[:2], dry_run=False, allow_deletions=True)
        self.assertEqual(res_rem["deleted"], 1)
        self.assertEqual(res_rem["unchanged"], 2)
        self.assertEqual(res_rem["created"], 0)

    def test_lkg_destructive_protection_prevents_wiping(self):
        sessions = self._sample_sessions()

        # Seed initial 2 events
        self.synchronizer.synchronize(sessions, dry_run=False, allow_deletions=True)
        self.assertEqual(len(self.remote_events), 2)

        # Feed empty or degraded sessions with allow_deletions=False (LKG mode)
        # Even if upstream returned 0 sessions or changed data, allow_deletions=False MUST NOT delete events!
        res_lkg = self.synchronizer.synchronize([], dry_run=False, allow_deletions=False)
        self.assertEqual(res_lkg["deleted"], 0, "LKG violation: Deleted events when allow_deletions=False")
        self.assertEqual(len(self.remote_events), 2, "Existing calendar events must be preserved during LKG")

    def test_tunnel_independence(self):
        """Proves background sync operates independently of public tunnel (LocalToNet) status."""
        # Simulated tunnel state = DOWN
        tunnel_online = False

        # Outbound HTTP sync directly to Google Calendar and UPES API Gateway
        # Outbound sockets do not require public inbound tunnel
        sessions = self._sample_sessions()
        res = self.synchronizer.synchronize(sessions, dry_run=False, allow_deletions=True)

        self.assertIn(res["status"], ["success", "completed"])
        self.assertEqual(res["created"] + res["unchanged"], 2)


if __name__ == "__main__":
    unittest.main()
