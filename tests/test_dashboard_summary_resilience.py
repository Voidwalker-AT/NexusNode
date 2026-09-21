"""
NexusNode — Dashboard Summary Resilience & Regression Test Suite
================================================================
Guarantees /api/dashboard/summary NEVER returns HTTP 500 under:
1. Real TimetableSession dataclass objects in upcoming/today schedule.
2. Missing or empty results / attendance / timetable / LMS data.
3. Expired UPES session, disconnected Google, or null scheduler timestamps.
4. Subsystems raising exceptions (attendance, results, governor, timetable).
5. Full schema compliance with frontend static/js/dashboard.js.
"""

import time
import os
import unittest
from unittest.mock import patch, MagicMock
from decimal import Decimal

import app
import config
from timetable_sync import TimetableSession


class TestDashboardSummaryResilience(unittest.TestCase):

    def setUp(self):
        app.app.config["TESTING"] = True
        self.client = app.app.test_client()
        self.admin_token = "admin_dash_tok_" + os.urandom(8).hex()
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

    def test_01_unauthenticated_rejected(self):
        """Unauthenticated requests must return 401."""
        res = self.client.get("/api/dashboard/summary")
        self.assertEqual(res.status_code, 401)

    def test_02_dashboard_contract_healthy_user(self):
        """Dashboard summary must strictly return all fields required by dashboard.js."""
        res = self.client.get("/api/dashboard/summary", headers=self.headers)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.content_type, "application/json")
        data = res.get_json()

        # 1. Appliance section
        self.assertIn("appliance", data)
        app_sec = data["appliance"]
        self.assertIn("status", app_sec)
        self.assertIn("version", app_sec)
        self.assertIn("device", app_sec)
        self.assertIn("uptime", app_sec)
        self.assertIn("uptime_seconds", app_sec)
        self.assertIn("memory", app_sec)
        self.assertIn("total_mb", app_sec["memory"])
        self.assertIn("used_mb", app_sec["memory"])
        self.assertIn("available_mb", app_sec["memory"])
        self.assertIn("percent", app_sec["memory"])
        self.assertIn("pressure_level", app_sec)

        # 2. Account section
        self.assertIn("account", data)
        acc_sec = data["account"]
        self.assertEqual(acc_sec["user_id"], "admin")
        self.assertEqual(acc_sec["role"], "admin")
        self.assertIn("health_state", acc_sec)
        self.assertIn("google_connected", acc_sec)
        self.assertIn("upes_configured", acc_sec)
        self.assertIn("timetable_available", acc_sec)
        self.assertIn("timetable_source", acc_sec)
        self.assertIn("last_synced_at", acc_sec)

        # 3. Schedule section
        self.assertIn("schedule", data)
        sched_sec = data["schedule"]
        self.assertIn("today_classes_count", sched_sec)
        self.assertIn("next_class", sched_sec)
        self.assertIn("today_classes", sched_sec)
        self.assertIsInstance(sched_sec["today_classes"], list)

        # 4. Attendance section
        self.assertIn("attendance", data)
        att_sec = data["attendance"]
        self.assertIn("overall_percentage", att_sec)
        self.assertIn("total_subjects", att_sec)
        self.assertIn("at_risk_subjects", att_sec)
        self.assertIn("critical_count", att_sec)
        self.assertIn("safe_count", att_sec)
        self.assertIn("warning_count", att_sec)
        self.assertIn("subjects", att_sec)

        # 5. Results section
        self.assertIn("results", data)
        res_sec = data["results"]
        self.assertIn("available", res_sec)
        self.assertIn("cgpa", res_sec)
        self.assertIn("latest_sgpa", res_sec)
        self.assertIn("earned_credits", res_sec)
        self.assertIn("semesters_count", res_sec)
        self.assertIn("last_updated", res_sec)

        # 6. MCP section
        self.assertIn("mcp", data)
        mcp_sec = data["mcp"]
        self.assertEqual(mcp_sec["catalog"], "nexus-semantic-v1")
        self.assertEqual(mcp_sec["tools_count"], 11)

        # 7. Alerts section
        self.assertIn("alerts", data)
        self.assertIsInstance(data["alerts"], list)

    def test_03_timetable_session_dataclass_serialization(self):
        """Proves TimetableSession instances (upcoming/today) serialize without TypeError or NameError."""
        fake_sessions = [
            TimetableSession(
                course_name="Software Engineering",
                course_code="CSEG2001",
                date="2099-01-01",  # Future date
                start_time="09:00:00",
                end_time="10:00:00",
                room="Room 501",
                faculty="Dr. Turing",
                session_id="sess_mock_1"
            )
        ]
        with patch.object(app.timetable_service, "load_timetable_sessions", return_value=(fake_sessions, [])):
            res = self.client.get("/api/dashboard/summary", headers=self.headers)
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertIsNotNone(data["schedule"]["next_class"])
            self.assertEqual(data["schedule"]["next_class"]["course_name"], "Software Engineering")
            self.assertEqual(data["schedule"]["next_class"]["room"], "Room 501")

    def test_04_results_with_decimals_serializes_cleanly(self):
        """Proves AcademicRecord with Decimals converts cleanly to float without serialization crashes."""
        mock_sem = MagicMock()
        mock_sem.official_sgpa = Decimal("8.75")
        mock_sem.calculated_sgpa = Decimal("8.75")
        mock_sem.fetched_at = 1700000000.0

        mock_rec = MagicMock()
        mock_rec.semesters = [mock_sem]
        mock_rec.official_cgpa = Decimal("8.90")
        mock_rec.calculated_cgpa = Decimal("8.90")
        mock_rec.total_credits_earned = Decimal("64.0")
        mock_rec.last_synced_at = 1700000000.0

        with patch.object(app.results_service, "get_user_results", return_value=mock_rec):
            res = self.client.get("/api/dashboard/summary", headers=self.headers)
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertTrue(data["results"]["available"])
            self.assertEqual(data["results"]["cgpa"], 8.90)
            self.assertEqual(data["results"]["latest_sgpa"], 8.75)
            self.assertEqual(data["results"]["earned_credits"], 64.0)

    def test_05_tolerates_missing_optional_data(self):
        """Dashboard must return 200 when all optional integrations are empty or disconnected."""
        with patch.object(app.timetable_service, "load_timetable_sessions", return_value=([], [])), \
             patch.object(app.results_service, "get_user_results", return_value=None), \
             patch.object(app.attendance_service, "get_attendance_analytics", return_value={}):
            res = self.client.get("/api/dashboard/summary", headers=self.headers)
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertFalse(data["results"]["available"])
            self.assertIsNone(data["schedule"]["next_class"])
            self.assertIsNone(data["attendance"]["overall_percentage"])

    def test_06_tolerates_subsystem_exceptions(self):
        """Dashboard must return 200 degraded status even if internal subsystems throw exceptions."""
        with patch.object(app.timetable_service, "load_timetable_sessions", side_effect=RuntimeError("Timetable DB locked")), \
             patch.object(app.results_service, "get_user_results", side_effect=ValueError("Corrupt result row")), \
             patch.object(app.attendance_service, "get_attendance_analytics", side_effect=Exception("Attendance offline")):
            res = self.client.get("/api/dashboard/summary", headers=self.headers)
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertEqual(data["schedule"]["today_classes_count"], 0)
            self.assertFalse(data["results"]["available"])

    def test_07_tolerates_top_level_fatal_exception(self):
        """If a top-level unexpected error occurs, dashboard catches and returns 200 DEGRADED."""
        with patch.object(app.governor, "get_telemetry_snapshot", side_effect=Exception("Hardware sensor fault")):
            res = self.client.get("/api/dashboard/summary", headers=self.headers)
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertEqual(data["appliance"]["status"], "DEGRADED")
            self.assertEqual(data["account"]["health_state"], "DEGRADED")


if __name__ == "__main__":
    unittest.main()
