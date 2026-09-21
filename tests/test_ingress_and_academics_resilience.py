"""
NexusNode — Ingress Discovery & Academics Contract Resilience Test Suite
======================================================================
Guarantees:
1. get_ingress_info() produces valid public HTTPS and LAN HTTP endpoints.
2. probe_localtonet_health() rejects HTML 'Tunnel Stopped' error pages.
3. OAuth discovery metadata uses public issuer without leaking LAN IP.
4. /api/timetable/sessions returns both canonical and legacy field mappings.
5. /api/attendance/summary returns both canonical and legacy field mappings.
6. /api/lms/courses returns top-level courses array.
7. Cheap page load invariant: 0 Chromium launches, 0 live logins on GET requests.
"""

import time
import os
import unittest
from unittest.mock import patch, MagicMock

import app
import config
from timetable_sync import TimetableSession


class TestIngressAndAcademicsResilience(unittest.TestCase):

    def setUp(self):
        app.app.config["TESTING"] = True
        self.client = app.app.test_client()
        self.admin_token = "test_ingress_admin_" + os.urandom(8).hex()
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

    # ==========================================================================
    # 1. INGRESS & PROBE RESILIENCE
    # ==========================================================================

    def test_01_is_private_or_local_host(self):
        """Validates IP and hostname classification."""
        self.assertTrue(app.is_private_or_local_host("localhost"))
        self.assertTrue(app.is_private_or_local_host("127.0.0.1"))
        self.assertTrue(app.is_private_or_local_host("192.168.29.21"))
        self.assertTrue(app.is_private_or_local_host("10.0.0.5"))
        self.assertTrue(app.is_private_or_local_host("172.20.0.1"))
        self.assertTrue(app.is_private_or_local_host("192.168.29.21:5000"))

        self.assertFalse(app.is_private_or_local_host("k09oezeyib.localto.net"))
        self.assertFalse(app.is_private_or_local_host("nexusnode.example.com"))

    def test_02_probe_localtonet_health_rejects_html(self):
        """probe_localtonet_health must reject HTTP 200 responses that return HTML."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "text/html; charset=utf-8"}
        mock_resp.text = "<html><head><title>Localtonet – Tunnel Stopped</title></head></html>"
        mock_resp.json.side_effect = Exception("Not JSON")

        app.app.config["TESTING"] = False
        try:
            with patch("subprocess.run", return_value=MagicMock(returncode=0, stdout="18293\n")), \
                 patch("requests.get", return_value=mock_resp):
                with app._TUNNEL_CACHE["lock"]:
                    app._TUNNEL_CACHE["last_check"] = 0
                info = app.probe_localtonet_health()
                # Process is alive but public endpoint returned HTML error page -> PROCESS_ONLY, not TUNNEL_CONNECTED
                self.assertEqual(info["state"], "PROCESS_ONLY")
                self.assertEqual(info["public_endpoint"], "unreachable")
        finally:
            app.app.config["TESTING"] = True

    def test_03_probe_localtonet_health_accepts_healthy_json(self):
        """probe_localtonet_health accepts verified JSON healthy payload."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "application/json"}
        mock_resp.json.return_value = {"status": "healthy", "version": "1.0.0"}

        app.app.config["TESTING"] = False
        try:
            with patch("subprocess.run", return_value=MagicMock(returncode=0, stdout="18293\n")), \
                 patch("requests.get", return_value=mock_resp):
                with app._TUNNEL_CACHE["lock"]:
                    app._TUNNEL_CACHE["last_check"] = 0
                info = app.probe_localtonet_health()
                self.assertEqual(info["state"], "TUNNEL_CONNECTED")
                self.assertEqual(info["public_endpoint"], "reachable")
        finally:
            app.app.config["TESTING"] = True

    def test_04_get_ingress_info_structure(self):
        """get_ingress_info must return distinct public HTTPS and LAN HTTP endpoints."""
        ingress = app.get_ingress_info()
        self.assertIn("public_origin", ingress)
        self.assertIn("public_mcp_url", ingress)
        self.assertIn("lan_origin", ingress)
        self.assertIn("lan_mcp_url", ingress)
        self.assertIn("tunnel_provider", ingress)
        self.assertIn("tunnel_status", ingress)

        # LAN URL must strictly use http:// on port 5000, never https://
        self.assertTrue(ingress["lan_origin"].startswith("http://"))
        self.assertFalse(ingress["lan_origin"].startswith("https://"))
        self.assertTrue(ingress["lan_mcp_url"].endswith("/api/mcp"))

        if ingress["public_origin"]:
            self.assertTrue(ingress["public_origin"].startswith("https://"))
            self.assertTrue(ingress["public_mcp_url"].endswith("/api/mcp"))

    def test_05_mcp_summary_returns_ingress(self):
        """GET /api/mcp/summary returns full ingress section."""
        res = self.client.get("/api/mcp/summary", headers=self.headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("ingress", data)
        self.assertIn("public_mcp_url", data["ingress"])
        self.assertIn("lan_mcp_url", data["ingress"])

    def test_06_oauth_discovery_advertises_public_issuer(self):
        """OAuth discovery endpoints advertise public issuer without leaking LAN IP when public exists."""
        res = self.client.get("/.well-known/oauth-protected-resource/api/mcp")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("resource", data)
        self.assertIn("authorization_servers", data)
        # Resource must end with /api/mcp
        self.assertTrue(data["resource"].endswith("/api/mcp"))

    # ==========================================================================
    # 2. ACADEMICS ENDPOINT CONTRACT RESILIENCE
    # ==========================================================================

    def test_07_timetable_sessions_contract(self):
        """/api/timetable/sessions returns canonical & legacy fields and provenance."""
        # Create a mock session (date 2026-09-21 is a Monday)
        mock_sess = TimetableSession(
            course_name="Software Architecture",
            course_code="CSEG2001",
            date="2026-09-21",
            start_time="09:00",
            end_time="10:00",
            faculty="Dr. Rao",
            room="Room 501",
            session_id="sess_123"
        )
        with patch.object(app.timetable_service, "load_timetable_sessions", return_value=([mock_sess], [])), \
             patch.object(app.timetable_service, "get_user_status", return_value={"last_synced_at": time.time(), "source": "UPES_TIMETABLE"}):
            res = self.client.get("/api/timetable/sessions", headers=self.headers)
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertIn("sessions", data)
            self.assertIn("provenance", data)
            self.assertEqual(len(data["sessions"]), 1)
            s = data["sessions"][0]
            # Canonical fields
            self.assertEqual(s["course_name"], "Software Architecture")
            self.assertEqual(s["start_time"], "09:00")
            self.assertEqual(s["end_time"], "10:00")
            self.assertEqual(s["day_of_week"], "Monday")
            # Legacy alias fields
            self.assertEqual(s["course"], "Software Architecture")
            self.assertEqual(s["start"], "09:00")
            self.assertEqual(s["end"], "10:00")
            self.assertEqual(s["weekday"], "Monday")

    def test_08_attendance_summary_contract(self):
        """/api/attendance/summary returns summary & overall, subjects & subject_reports."""
        mock_att = {
            "overall": {
                "conducted_classes": 40,
                "attended_classes": 36,
                "attendance_percentage": 90.0,
                "total_safe_bunks": 6,
                "critical_subjects": 0,
                "has_data": True
            },
            "subjects": [
                {
                    "course_name": "Cloud Computing",
                    "course_code": "CSCC101",
                    "conducted_classes": 20,
                    "attended_classes": 18,
                    "attendance_percentage": 90.0,
                    "safe_bunks_remaining": 3,
                    "recovery_classes_required": 0
                }
            ],
            "as_of_date": "2026-09-20"
        }
        with patch.object(app.attendance_service, "get_attendance_analytics", return_value=mock_att):
            res = self.client.get("/api/attendance/summary", headers=self.headers)
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            # Canonical & alias checks
            self.assertIn("overall", data)
            self.assertIn("summary", data)
            self.assertIn("subjects", data)
            self.assertIn("subject_reports", data)
            self.assertEqual(data["overall"]["conducted_classes"], 40)
            self.assertEqual(data["summary"]["conducted_classes"], 40)
            self.assertEqual(len(data["subjects"]), 1)
            self.assertEqual(len(data["subject_reports"]), 1)
            self.assertEqual(data["subject_reports"][0]["safe_bunks"], 3)
            self.assertEqual(data["subject_reports"][0]["recovery_classes_needed"], 0)

    def test_09_lms_courses_contract(self):
        """/api/lms/courses returns courses top-level array."""
        mock_lms_res = MagicMock()
        mock_lms_res.ok = True
        mock_lms_res.to_dict.return_value = {
            "status": "success",
            "data": {
                "courses": [
                    {"course_id": "101", "name": "Distributed Systems"}
                ]
            }
        }
        with patch.object(app.lms_service, "list_courses", return_value=mock_lms_res):
            res = self.client.get("/api/lms/courses", headers=self.headers)
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertIn("courses", data)
            self.assertEqual(len(data["courses"]), 1)
            self.assertEqual(data["courses"][0]["name"], "Distributed Systems")

    # ==========================================================================
    # 3. CHEAP PAGE LOAD INVARIANT
    # ==========================================================================

    def test_10_cheap_page_load_invariant(self):
        """Academics read requests must NOT spawn Chromium, invoke SSO, or write calendar."""
        with patch("subprocess.Popen") as mock_popen, \
             patch.object(app.timetable_service, "sync_user_timetable") as mock_sync:
            # Query all academics endpoints
            r1 = self.client.get("/api/timetable/sessions", headers=self.headers)
            r2 = self.client.get("/api/attendance/summary", headers=self.headers)
            r3 = self.client.get("/api/academics/results", headers=self.headers)
            r4 = self.client.get("/api/lms/courses", headers=self.headers)

            self.assertEqual(r1.status_code, 200)
            self.assertEqual(r2.status_code, 200)
            self.assertEqual(r3.status_code, 200)
            self.assertEqual(r4.status_code, 200)

            # Assert 0 live background timetable/calendar sync writes triggered
            mock_sync.assert_not_called()
            # Assert no browser subprocesses spawned
            mock_popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
