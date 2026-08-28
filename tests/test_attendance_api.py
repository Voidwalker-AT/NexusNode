"""
tests/test_attendance_api.py — REST API Integration Tests for Attendance Endpoints.
"""

import os
import sys
import json
import time
import unittest
from unittest.mock import MagicMock, patch

# Ensure server root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import app as flask_app
import config
import attendance_sync


def fake_require_auth_admin():
    flask_app.g.user = {"user_id": "admin", "role": "admin", "privileges": ["*"]}
    return None


class TestAttendanceAPI(unittest.TestCase):
    """Tests all Flask endpoints under /api/attendance/*."""

    @classmethod
    def setUpClass(cls):
        flask_app.app.config["TESTING"] = True
        cls.client = flask_app.app.test_client()

    @patch("app.attendance_service.get_attendance_status")
    def test_get_attendance_status_unauthorized(self, mock_status):
        # Without auth (require_auth executes normally and blocks)
        res = self.client.get("/api/attendance/status")
        self.assertIn(res.status_code, (401, 302))

    @patch("app.require_auth", side_effect=fake_require_auth_admin)
    @patch("app.attendance_service.get_attendance_status")
    def test_get_attendance_status_authorized(self, mock_status, mock_auth):
        mock_status.return_value = {
            "user_id": "admin",
            "sync_status": "ACTIVE",
            "modules_count": 9,
            "sessions_count": 78,
            "punches_count": 70,
            "current_term": {"term_code": "Semester 5"},
            "last_sync": {"status": "ACTIVE", "modules_synced": 9}
        }
        res = self.client.get("/api/attendance/status")
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertEqual(data["sync_status"], "ACTIVE")
        self.assertEqual(data["modules_count"], 9)

    @patch("app.require_auth", side_effect=fake_require_auth_admin)
    @patch("app.attendance_service.get_attendance_analytics")
    def test_get_attendance_summary_custom_threshold(self, mock_analytics, mock_auth):
        mock_analytics.return_value = {
            "user_id": "admin",
            "threshold": 0.80,
            "overall": {
                "conducted_classes": 78,
                "attended_classes": 70,
                "attendance_percentage": 89.74,
                "total_safe_bunks": 9
            },
            "subjects": []
        }
        res = self.client.get("/api/attendance/summary?threshold=0.80")
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertEqual(data["overall"]["attendance_percentage"], 89.74)
        mock_analytics.assert_called_with("admin", threshold=0.80)

    @patch("app.require_auth", side_effect=fake_require_auth_admin)
    @patch("app.attendance_service.get_attendance_analytics")
    def test_get_attendance_modules(self, mock_analytics, mock_auth):
        mock_analytics.return_value = {
            "subjects": [
                {
                    "module_id": 87945,
                    "course_name": "Cryptography and Network Security",
                    "attendance_percentage": 90.0,
                    "conducted_classes": 10,
                    "attended_classes": 9
                }
            ]
        }
        res = self.client.get("/api/attendance/modules")
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertEqual(len(data["modules"]), 1)
        self.assertEqual(data["modules"][0]["module_id"], 87945)

    @patch("app.require_auth", side_effect=fake_require_auth_admin)
    @patch("app.attendance_service.get_sessions")
    def test_list_attendance_sessions_with_filters(self, mock_sessions, mock_auth):
        mock_sessions.return_value = [
            {
                "session_id": 12345,
                "module_id": 87945,
                "course_name": "Cryptography and Network Security",
                "attendance_status": "PRESENT",
                "attendance_subtype": "CRA",
                "punch_in_time": "10:01"
            }
        ]
        res = self.client.get("/api/attendance/sessions?module_id=87945&limit=50")
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["sessions"][0]["attendance_subtype"], "CRA")
        mock_sessions.assert_called_with("admin", module_id=87945, date_from=None, date_to=None, limit=50)

    @patch("app.require_auth", side_effect=fake_require_auth_admin)
    @patch("app.attendance_service.get_attendance_analytics")
    def test_get_today_attendance(self, mock_analytics, mock_auth):
        mock_analytics.return_value = {
            "as_of_date": "2026-08-28",
            "today_classes": [
                {
                    "session_id": 9991,
                    "course_name": "Network Security",
                    "attendance_status": "PRESENT",
                    "punch_in_time": "09:02"
                }
            ]
        }
        res = self.client.get("/api/attendance/today")
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertEqual(data["as_of_date"], "2026-08-28")
        self.assertEqual(len(data["today_classes"]), 1)

    @patch("app.require_auth", side_effect=fake_require_auth_admin)
    @patch("app.attendance_service.sync_user_attendance")
    def test_post_attendance_sync_trigger(self, mock_sync, mock_auth):
        mock_sync.return_value = {
            "status": "ACTIVE",
            "message": "Successfully synchronized 9/9 modules (78 sessions).",
            "modules_synced": 9,
            "sessions_synced": 78
        }
        res = self.client.post("/api/attendance/sync")
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertEqual(data["status"], "ACTIVE")
        self.assertEqual(data["modules_synced"], 9)


if __name__ == "__main__":
    unittest.main()
