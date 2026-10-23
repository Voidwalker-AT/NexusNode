"""
NexusNode — Phase 1C Stage 2: Academic Pipeline Recovery Test Suite
===================================================================
Independently verifies all Stage 2 repairs:
1. DEF-03: UpesAuthManager dependency injection into TimetableService & AttendanceService.
2. DEF-03: AttendanceService & TimetableSessionBroker session resolution and 401 retry with auth_manager.
3. DEF-06 & DEF-12: Timetable capacity (2000 sessions) and date-filtered pagination in _get_next_classes & _get_timetable.
4. Snapshot next_class truthfulness (no misleading sessions[-1] fallback).
5. DEF-09: Attendance field mapping in dashboard summary (overall_percentage, safe/warning/critical counts, truthful provenance).
6. DEF-09: /api/academics/refresh-all method invocation and sync_attendance alias.
7. DEF-05: GoogleCalendarClient conn_factory wiring for encrypted DB OAuth lookup.
8. DEF-05: TimetableSynchronizer immediate loop break on calendar auth failure.
9. Stage 5: Scheduler 3-hour job completion status recording in scheduled_jobs table.
"""

import time
import os
import sqlite3
import unittest
from unittest.mock import MagicMock, patch

import config
import timetable_sync
import attendance_sync
from timetable_sync import TimetableSession, GoogleCalendarError, TimetableSynchronizer, GoogleCalendarClient
import app


class TestAcademicPipelineRecovery(unittest.TestCase):

    def setUp(self):
        app.app.config["TESTING"] = True
        self.client = app.app.test_client()
        self.admin_token = "admin_recovery_tok_" + os.urandom(8).hex()
        with app.SESSIONS_LOCK:
            app.SESSIONS[self.admin_token] = {
                "user_id": "admin",
                "role": "admin",
                "privileges": dict(config.ADMIN_DEFAULT_PRIVILEGES),
                "created_at": time.time(),
                "expires_at": time.time() + 3600
            }
        self.headers = {"Authorization": f"Bearer {self.admin_token}"}

    def tearDown(self):
        with app.SESSIONS_LOCK:
            if self.admin_token in app.SESSIONS:
                del app.SESSIONS[self.admin_token]

    # --------------------------------------------------------------------------
    # 1. DEF-03: Auth Manager Dependency Injection
    # --------------------------------------------------------------------------
    def test_01_auth_manager_wiring_and_init(self):
        """Verifies UpesAuthManager is injected into both TimetableService and AttendanceService."""
        self.assertIsNotNone(app.timetable_service.auth_manager)
        self.assertIsNotNone(app.attendance_service.auth_manager)
        self.assertIs(app.timetable_service.auth_manager, app.upes_auth_manager)
        self.assertIs(app.attendance_service.auth_manager, app.upes_auth_manager)

        # Test __init__ parameter acceptance
        mock_auth = MagicMock()
        tt_svc = timetable_sync.TimetableService(app.get_db_connection, auth_manager=mock_auth)
        self.assertIs(tt_svc.auth_manager, mock_auth)

        att_svc = attendance_sync.AttendanceService(app.get_db_connection, auth_manager=mock_auth)
        self.assertIs(att_svc.auth_manager, mock_auth)

    def test_02_attendance_service_auth_manager_resolution_and_retry(self):
        """Verifies AttendanceService uses auth_manager without broker overwrite, and retries on 401."""
        mock_auth = MagicMock()
        mock_auth.ensure_authenticated.return_value = ("tok_valid_123", "student_999", "https://api.upes.ac.in", time.time() + 3600)

        mock_broker = MagicMock()
        # If broker resolution fails, it must NOT overwrite the valid session from auth_manager
        mock_broker.resolve_session.return_value = (None, "broker_failed")

        att_svc = attendance_sync.AttendanceService(
            conn_factory=app.get_db_connection,
            session_broker=mock_broker,
            auth_manager=mock_auth
        )

        with patch("attendance_sync.AttendanceSyncLease") as mock_lease, \
             patch("attendance_sync.execute_upes_attendance_request") as mock_req:
            mock_lease.return_value.acquire.return_value = True

            # First request returns auth_required to test retry
            mock_req.side_effect = [
                (None, "auth_required: token expired"),
                ({"term_list": []}, None)
            ]

            att_svc.sync_user_attendance("test_user")

            # Check that ensure_authenticated was called initially
            mock_auth.ensure_authenticated.assert_any_call("test_user")
            # Check that 401 retry invoked ensure_authenticated with force_login=True
            mock_auth.ensure_authenticated.assert_any_call("test_user", force_login=True)

    def test_03_timetable_broker_retry_with_auth_manager(self):
        """Verifies UpesSessionBroker invokes auth_manager force_login on 401."""
        mock_service = MagicMock()
        mock_auth = MagicMock()
        mock_service.auth_manager = mock_auth
        mock_service.get_full_upes_session.return_value = None

        broker = timetable_sync.UpesSessionBroker(mock_service)
        mock_auth.ensure_authenticated.return_value = ("tok_1", "stu_1", "https://api", time.time() + 3600)

        # Call execute_with_retry where API fails once with auth_required then succeeds
        calls = []
        def mock_api(tok, code):
            calls.append((tok, code))
            if len(calls) == 1:
                return None, "auth_required: 401 unauthorized"
            return {"status": "ok"}, None

        data, err = broker.execute_with_retry("test_user", mock_api)
        self.assertEqual(data, {"status": "ok"})
        mock_auth.ensure_authenticated.assert_any_call("test_user", force_login=True)

    # --------------------------------------------------------------------------
    # 2. DEF-06 & DEF-12: Timetable Correctness & Capacity
    # --------------------------------------------------------------------------
    def test_04_timetable_capacity_and_date_filtering(self):
        """Verifies TIMETABLE_MAX_SESSIONS is 2000 and router filters before slicing."""
        self.assertGreaterEqual(config.TIMETABLE_MAX_SESSIONS, 2000)

        # Verify _get_next_classes passes start_date to _get_timetable
        router = app.upes_router
        with patch.object(router, "_get_timetable") as mock_get_tt:
            mock_get_tt.return_value = MagicMock(ok=True, data={"events": []}, source="lkg", provider="cache")
            router._get_next_classes("admin", {"limit": 5}, time.time())

            mock_get_tt.assert_called_once()
            args, _ = mock_get_tt.call_args
            params_passed = args[1]
            self.assertIn("start_date", params_passed)
            self.assertEqual(params_passed["limit"], 100)

    def test_05_academics_snapshot_next_class_truthful(self):
        """Verifies get_academics_snapshot does NOT fall back to past sessions[-1] when upcoming is empty."""
        with patch.object(app.timetable_service, "load_timetable_sessions") as mock_load, \
             patch.object(app.timetable_service, "get_user_status") as mock_status:

            # Past session only
            past_session = MagicMock()
            past_session.date = "2020-01-01"
            past_session.start_time = "09:00"
            mock_load.return_value = ([past_session], [])
            mock_status.return_value = {"source": "lkg"}

            res = self.client.get("/api/academics/snapshot", headers=self.headers)
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertIsNone(data["timetable"]["next_class"])

    # --------------------------------------------------------------------------
    # 3. DEF-09: Attendance & Dashboard Field Mapping
    # --------------------------------------------------------------------------
    def test_06_dashboard_attendance_mapping_and_provenance(self):
        """Verifies get_dashboard_summary accurately extracts attendance analytics and provenance."""
        mock_analytics = {
            "overall": {
                "attendance_percentage": 88.5,
                "total_subjects": 4,
                "critical_subjects": 1,
                "conducted_classes": 40,
                "attended_classes": 35
            },
            "subjects": [
                {"module_name": "Math", "status_badge": "safe"},
                {"module_name": "Physics", "status_badge": "warning"},
                {"module_name": "Chemistry", "status_badge": "critical"},
                {"module_name": "English", "status_badge": "safe"}
            ]
        }
        mock_status = {
            "sync_status": "ACTIVE",
            "last_sync": {"timestamp": time.time() - 600}
        }

        with patch.object(app.attendance_service, "get_attendance_analytics", return_value=mock_analytics), \
             patch.object(app.attendance_service, "get_attendance_status", return_value=mock_status):

            res = self.client.get("/api/dashboard/summary", headers=self.headers)
            self.assertEqual(res.status_code, 200)
            att = res.get_json()["attendance"]

            self.assertEqual(att["overall_percentage"], 88.5)
            self.assertEqual(att["total_subjects"], 4)
            self.assertEqual(att["critical_count"], 1)
            self.assertEqual(att["warning_count"], 1)
            self.assertEqual(att["safe_count"], 2)
            self.assertEqual(att["at_risk_subjects"], 2)
            self.assertEqual(att["provenance"], "LIVE")
            self.assertEqual(len(att["subjects"]), 4)

    def test_07_refresh_all_route_and_alias(self):
        """Verifies /api/academics/refresh-all calls sync_user_attendance and sync_attendance alias exists."""
        self.assertTrue(hasattr(app.attendance_service, "sync_attendance"))
        self.assertEqual(app.attendance_service.sync_attendance, app.attendance_service.sync_user_attendance)

        with patch.object(app.timetable_service, "fetch_and_store_upes_timetable", return_value=(True, "ok", 10)), \
             patch.object(app.attendance_service, "sync_user_attendance", return_value={"status": "ACTIVE", "modules_synced": 5}), \
             patch.object(app.results_service, "sync_user_results", return_value={"status": "success"}), \
             patch.object(app.lms_service, "list_courses") as mock_lms:

            mock_lms.return_value.ok = True
            mock_lms.return_value.to_dict.return_value = {"courses": []}

            res = self.client.post("/api/academics/refresh-all", headers=self.headers)
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertEqual(data["status"], "success")
            self.assertTrue(data["summary"]["attendance"]["ok"])

    # --------------------------------------------------------------------------
    # 4. DEF-05: Google Calendar Client & Auth Short-Circuit
    # --------------------------------------------------------------------------
    def test_08_google_calendar_client_conn_factory_and_auth_break(self):
        """Verifies conn_factory wiring on GoogleCalendarClient and mutation loop short-circuit on auth failure."""
        token_data = {"access_token": "valid_dummy_tok", "expires_at": time.time() + 3600}
        client = GoogleCalendarClient(token_data, "admin", conn_factory=app.get_db_connection)
        self.assertIsNotNone(client.conn_factory)

        # Test synchronizer halts loop on GoogleCalendarError 401
        synchronizer = TimetableSynchronizer(app.get_db_connection, "admin", client, "primary")
        client.list_managed_events = MagicMock(return_value=[])

        # Create dummy sessions to trigger plan_creates
        s1 = TimetableSession(
            session_id="s1", course_name="Algorithms", course_code="CS101",
            date="2026-10-25", start_time="09:00", end_time="10:00",
            room="101", faculty="Dr. Smith"
        )
        s2 = TimetableSession(
            session_id="s2", course_name="Database", course_code="CS102",
            date="2026-10-25", start_time="10:00", end_time="11:00",
            room="102", faculty="Dr. Jones"
        )

        create_calls = []
        def mock_create(cal_id, sess, uid):
            create_calls.append(sess.course_name)
            raise GoogleCalendarError("invalid_grant: Token has been revoked.", status_code=401)

        client.create_event = mock_create

        res = synchronizer.synchronize([s1, s2], dry_run=False)
        # Should halt after the first session failure, NOT call s2
        self.assertEqual(len(create_calls), 1)
        self.assertEqual(create_calls[0], "Algorithms")
        self.assertIn("invalid_grant", res["errors"][0])

    # --------------------------------------------------------------------------
    # 5. Stage 5: Scheduler Status Recording
    # --------------------------------------------------------------------------
    def test_09_scheduler_status_recording(self):
        """Verifies run_timetable_sync_job updates scheduled_jobs.last_status."""
        with patch.object(app.timetable_service, "sync_all_active_users", return_value={"admin": {"created": 0, "errors": []}}), \
             patch.object(app.attendance_service, "sync_all_active_users", return_value={"admin": {"modules_synced": 0}}), \
             patch.object(app.results_service, "sync_all_active_users", return_value={"admin": {"status": "success"}}):

            app.run_timetable_sync_job()

            conn = app.get_db_connection()
            try:
                row = conn.execute("SELECT last_status FROM scheduled_jobs WHERE job_type = 'timetable_sync'").fetchone()
                self.assertIsNotNone(row)
                self.assertIn(row["last_status"], ["success", "partial"])
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
