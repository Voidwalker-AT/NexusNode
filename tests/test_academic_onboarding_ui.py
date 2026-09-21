"""
NexusNode — Phase 3.7C Synthetic Multi-User Academic Onboarding & UI Verification Test Suite
Tests:
  1. Self-service password change (/api/auth/change-password & /api/account/password).
  2. Multi-tenant synthetic user_a and user_b onboarding flow with strict tenant isolation.
  3. Authoritative onboarding status state machine branches (GOOGLE_REQUIRED, GOOGLE_EXPIRED,
     UPES_REQUIRED, UPES_INTERACTION_REQUIRED, READY_TO_SYNC, SYNCING, LKG_ONLY, SYNC_FAILED, READY).
  4. Zero-secret leak assertions across all onboarding telemetry.
  5. Synthetic Calendar reconciliation with zero production Calendar modification.
"""

import os
import json
import sqlite3
import tempfile
import unittest
import time
import requests
from unittest.mock import patch, MagicMock

import app as nexus_app
import config
from upes.credentials import UpesCredentialProvider, init_credential_tables
from upes.session import UpesSessionTracker
from upes.auth import UpesAuthManager
from timetable_sync import TimetableService, init_timetable_tables


class TestAcademicOnboardingUI(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="nexus_onboarding_ui_test_")
        self.db_path = os.path.join(self.temp_dir, "nexus_test.db")
        self.orig_db_path = config.DB_PATH
        self.orig_unified_db = config.UNIFIED_DB_FILE
        self.orig_upes_credential_provider = getattr(nexus_app, "upes_credential_provider", None)
        self.orig_upes_session_tracker = getattr(nexus_app, "upes_session_tracker", None)
        self.orig_upes_auth_manager = getattr(nexus_app, "upes_auth_manager", None)
        self.orig_timetable_service = getattr(nexus_app, "timetable_service", None)
        self.orig_attendance_service = getattr(nexus_app, "attendance_service", None)

        config.DB_PATH = self.db_path
        config.UNIFIED_DB_FILE = self.db_path

        # Initialize SQLite tables using unified db routine
        nexus_app.init_unified_db()
        conn = sqlite3.connect(self.db_path)
        init_credential_tables(conn)
        init_timetable_tables(conn)
        conn.close()

        self.conn_factory = lambda: sqlite3.connect(self.db_path)
        self.cred_provider = UpesCredentialProvider(self.conn_factory)
        self.session_tracker = UpesSessionTracker(self.conn_factory)
        self.timetable_service = TimetableService(self.conn_factory)
        self.auth_manager = UpesAuthManager(
            conn_factory=self.conn_factory,
            credential_provider=self.cred_provider,
            timetable_service=self.timetable_service,
            session_tracker=self.session_tracker
        )

        nexus_app.upes_credential_provider = self.cred_provider
        nexus_app.upes_session_tracker = self.session_tracker
        nexus_app.upes_auth_manager = self.auth_manager
        nexus_app.timetable_service = self.timetable_service

        nexus_app.app.config['TESTING'] = True
        self.client = nexus_app.app.test_client()

        # Seed admin and synthetic test users
        self._seed_user("admin", "Admin@1234", role="admin")
        self._seed_user("synth_user_a", "Initial@1234", role="user")
        self._seed_user("synth_user_b", "Initial@5678", role="user")

        self.admin_token = self._login("admin", "Admin@1234")
        self.token_a = self._login("synth_user_a", "Initial@1234")
        self.token_b = self._login("synth_user_b", "Initial@5678")

    def tearDown(self):
        nexus_app.upes_credential_provider = self.orig_upes_credential_provider
        nexus_app.upes_session_tracker = self.orig_upes_session_tracker
        nexus_app.upes_auth_manager = self.orig_upes_auth_manager
        nexus_app.timetable_service = self.orig_timetable_service
        if self.orig_attendance_service:
            nexus_app.attendance_service = self.orig_attendance_service
        config.DB_PATH = self.orig_db_path
        config.UNIFIED_DB_FILE = self.orig_unified_db
        try:
            if os.path.exists(self.temp_dir):
                import shutil
                shutil.rmtree(self.temp_dir, ignore_errors=True)
        except Exception:
            pass

    def _seed_user(self, user_id, password, role="user"):
        pwd_hash, salt = nexus_app.hash_password(password)
        privs = config.ADMIN_DEFAULT_PRIVILEGES if role == 'admin' else config.USER_DEFAULT_PRIVILEGES
        with nexus_app.DB_LOCK:
            conn = self.conn_factory()
            conn.execute(
                "INSERT OR REPLACE INTO users (user_id, password_hash, salt, role, is_disabled, privileges, created_at) VALUES (?, ?, ?, ?, 0, ?, ?)",
                (user_id, pwd_hash, salt, role, json.dumps(privs), 1700000000.0)
            )
            conn.commit()
            conn.close()

    def _login(self, user_id, password):
        user = nexus_app.db_get_user(user_id)
        return nexus_app.create_user_session(user)

    # =========================================================================
    # 1. SELF-SERVICE PASSWORD CHANGE TESTS
    # =========================================================================

    def test_self_service_password_change_success(self):
        """Friend user changes initial password and logs in with new credentials."""
        # 1. Call change password with valid current and new password
        resp = self.client.post(
            "/api/auth/change-password",
            headers={"Authorization": f"Bearer {self.token_a}"},
            json={
                "current_password": "Initial@1234",
                "new_password": "NewSecretPassword@999",
                "confirm_password": "NewSecretPassword@999"
            }
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data.get("status"), "success")

        # 2. Login with old password fails
        login_old = self.client.post(
            "/api/auth/login",
            json={"user_id": "synth_user_a", "password": "Initial@1234"}
        )
        self.assertEqual(login_old.status_code, 401)

        # 3. Login with new password succeeds
        login_new = self.client.post(
            "/api/auth/login",
            json={"user_id": "synth_user_a", "password": "NewSecretPassword@999"}
        )
        self.assertEqual(login_new.status_code, 200)
        self.assertIn("token", login_new.get_json())

    def test_self_service_password_change_rejections(self):
        """Rejects incorrect old password, short password, or confirmation mismatch."""
        # Incorrect current password
        resp1 = self.client.post(
            "/api/auth/change-password",
            headers={"Authorization": f"Bearer {self.token_a}"},
            json={
                "current_password": "WrongPassword!999",
                "new_password": "NewSecretPassword@999"
            }
        )
        self.assertEqual(resp1.status_code, 401)

        # Short new password (<6 chars)
        resp2 = self.client.post(
            "/api/auth/change-password",
            headers={"Authorization": f"Bearer {self.token_a}"},
            json={
                "current_password": "Initial@1234",
                "new_password": "123"
            }
        )
        self.assertEqual(resp2.status_code, 400)

        # Mismatched confirmation
        resp3 = self.client.post(
            "/api/auth/change-password",
            headers={"Authorization": f"Bearer {self.token_a}"},
            json={
                "current_password": "Initial@1234",
                "new_password": "NewSecretPassword@999",
                "confirm_password": "DifferentPassword@999"
            }
        )
        self.assertEqual(resp3.status_code, 400)

    # =========================================================================
    # 2. SYNTHETIC MULTI-USER END-TO-END ONBOARDING & ISOLATION
    # =========================================================================

    def test_synthetic_end_to_end_onboarding_and_tenant_isolation(self):
        """
        Step-by-step synthetic onboarding of synth_user_a.
        Verifies that synth_user_b remains isolated at every step.
        """
        # Step 0: Initial state for both users is GOOGLE_REQUIRED
        stat_a0 = self.client.get("/api/academics/onboarding-status", headers={"Authorization": f"Bearer {self.token_a}"}).get_json()
        stat_b0 = self.client.get("/api/academics/onboarding-status", headers={"Authorization": f"Bearer {self.token_b}"}).get_json()

        self.assertEqual(stat_a0.get("state"), "GOOGLE_REQUIRED")
        self.assertEqual(stat_b0.get("state"), "GOOGLE_REQUIRED")

        # Step 1: synth_user_a connects Google fixture
        self.timetable_service.save_oauth_tokens("synth_user_a", {
            "access_token": "mock_google_token_user_a",
            "refresh_token": "mock_google_refresh_user_a",
            "token_expiry": 9999999999.0
        }, email="user_a@gmail.com")

        stat_a1 = self.client.get("/api/academics/onboarding-status", headers={"Authorization": f"Bearer {self.token_a}"}).get_json()
        stat_b1 = self.client.get("/api/academics/onboarding-status", headers={"Authorization": f"Bearer {self.token_b}"}).get_json()

        self.assertEqual(stat_a1.get("state"), "UPES_REQUIRED")
        self.assertTrue(stat_a1.get("google", {}).get("connected"))
        self.assertEqual(stat_a1.get("google", {}).get("email"), "user_a@gmail.com")

        # synth_user_b MUST remain completely untouched in GOOGLE_REQUIRED
        self.assertEqual(stat_b1.get("state"), "GOOGLE_REQUIRED")
        self.assertFalse(stat_b1.get("google", {}).get("connected"))

        # Step 2: synth_user_a saves UPES institutional email credentials
        save_resp = self.client.post(
            "/api/upes/auth/credentials",
            headers={"Authorization": f"Bearer {self.token_a}"},
            json={
                "username": "anmol.500086789@stu.upes.ac.in",
                "password": "MockPassword@123"
            }
        )
        self.assertEqual(save_resp.status_code, 200)

        stat_a2 = self.client.get("/api/academics/onboarding-status", headers={"Authorization": f"Bearer {self.token_a}"}).get_json()
        stat_b2 = self.client.get("/api/academics/onboarding-status", headers={"Authorization": f"Bearer {self.token_b}"}).get_json()

        self.assertEqual(stat_a2.get("state"), "READY_TO_SYNC")
        self.assertTrue(stat_a2.get("upes", {}).get("credentials_configured"))
        self.assertEqual(stat_a2.get("upes", {}).get("username_hint"), "anm***@stu.upes.ac.in")

        # synth_user_b remains in GOOGLE_REQUIRED
        self.assertEqual(stat_b2.get("state"), "GOOGLE_REQUIRED")

        # Step 3: synth_user_a chooses target calendar
        cal_resp = self.client.post(
            "/api/auth/google/calendar",
            headers={"Authorization": f"Bearer {self.token_a}"},
            json={"calendar_id": "primary"}
        )
        self.assertEqual(cal_resp.status_code, 200)

        # Step 4: synth_user_a runs initial sync with synthetic timetable fixture
        synthetic_timetable = {
            "sessions": [
                {
                    "id": "slot_101",
                    "date": "2026-09-02",
                    "course": "Distributed Systems",
                    "time": "09:00 - 10:00",
                    "room": "Room 501",
                    "faculty": "Dr. Smith"
                }
            ]
        }
        self.timetable_service.upload_timetable("synth_user_a", json.dumps(synthetic_timetable))

        # Mock Google Calendar sync write to ensure no production writes
        def mock_sync_user_timetable(u_id, **kw):
            conn = self.conn_factory()
            conn.execute("""
                INSERT INTO timetable_sync_history (user_id, timestamp, sessions_seen, created_count, updated_count, deleted_count, unchanged_count, error_count, status, details)
                VALUES (?, ?, 1, 1, 0, 0, 0, 0, 'success', '{}')
            """, (u_id, 1700000000.0))
            conn.commit()
            conn.close()
            return {"status": "success", "created": 1, "updated": 0, "unchanged": 0, "deleted": 0, "total": 1, "errors": []}

        with patch.object(nexus_app.timetable_service, "sync_user_timetable", side_effect=mock_sync_user_timetable):
            sync_resp = self.client.post(
                "/api/timetable/sync",
                headers={"Authorization": f"Bearer {self.token_a}"}
            )
            self.assertEqual(sync_resp.status_code, 200)

        stat_a4 = self.client.get("/api/academics/onboarding-status", headers={"Authorization": f"Bearer {self.token_a}"}).get_json()
        stat_b4 = self.client.get("/api/academics/onboarding-status", headers={"Authorization": f"Bearer {self.token_b}"}).get_json()

        # synth_user_a is now fully READY!
        self.assertEqual(stat_a4.get("state"), "READY")
        self.assertTrue(stat_a4.get("timetable", {}).get("has_data"))
        self.assertEqual(stat_a4.get("timetable", {}).get("total_sessions"), 1)

        # synth_user_b is STILL in GOOGLE_REQUIRED!
        self.assertEqual(stat_b4.get("state"), "GOOGLE_REQUIRED")
        self.assertFalse(stat_b4.get("google", {}).get("connected"))

    # =========================================================================
    # 3. ZERO SECRET LEAKAGE VERIFICATION
    # =========================================================================

    def test_zero_secret_leakage_in_all_academic_endpoints(self):
        """Verifies that plaintext credentials, tokens, or encryption tags never leak in JSON responses."""
        SENTINEL_PASSWORD = "UltraSecretPassword999!"
        SENTINEL_TOKEN = "ya29.mock_secret_google_oauth_token"

        self.timetable_service.save_oauth_tokens("synth_user_a", {
            "access_token": SENTINEL_TOKEN,
            "refresh_token": "mock_refresh",
            "token_expiry": 9999999999.0
        }, email="friend@gmail.com")
        self.cred_provider.save_credentials("synth_user_a", "friend.500099999@stu.upes.ac.in", SENTINEL_PASSWORD)

        endpoints = [
            ("/api/academics/onboarding-status", "GET", None),
            ("/api/timetable/onboarding-status", "GET", None),
            ("/api/timetable/status", "GET", None),
            ("/api/upes/auth/status", "GET", None),
            ("/api/upes/auth/credentials/status", "GET", None),
        ]

        for path, method, payload in endpoints:
            if method == "GET":
                resp = self.client.get(path, headers={"Authorization": f"Bearer {self.token_a}"})
            else:
                resp = self.client.post(path, headers={"Authorization": f"Bearer {self.token_a}"}, json=payload)

            raw_text = resp.get_data(as_text=True)
            self.assertNotIn(SENTINEL_PASSWORD, raw_text, f"Secret password leaked in {path}!")
            self.assertNotIn(SENTINEL_TOKEN, raw_text, f"Secret OAuth token leaked in {path}!")

    # =========================================================================
    # 4. LKG AND STALE TIMETABLE WARNING TEST
    # =========================================================================

    def test_lkg_stale_state_machine_evaluation(self):
        """Verifies that when timetable source is LKG or stale, onboarding reports LKG_ONLY/stale."""
        self.timetable_service.save_oauth_tokens("synth_user_a", {
            "access_token": "mock_token",
            "refresh_token": "mock_refresh",
            "token_expiry": 9999999999.0
        }, email="user_a@gmail.com")
        self.cred_provider.save_credentials("synth_user_a", "user_a.500012345@stu.upes.ac.in", "Password@123")

        # Save timetable and record initial sync history
        self.timetable_service.upload_timetable("synth_user_a", json.dumps({"sessions": [{"id": "s1", "course": "CS", "date": "2026-09-02", "time": "09:00 - 10:00"}]}))

        conn = self.conn_factory()
        conn.execute("""
            INSERT INTO timetable_sync_history (user_id, timestamp, sessions_seen, created_count, updated_count, deleted_count, unchanged_count, error_count, status, details)
            VALUES (?, ?, 1, 1, 0, 0, 0, 0, 'success', '{}')
        """, ("synth_user_a", 1700000000.0))
        conn.commit()
        conn.close()

        # Mock UpesAuthManager returning expired session
        with patch.object(nexus_app.upes_session_tracker, "get_safe_status", return_value={"state": "EXPIRED", "is_live_ready": False}):
            stat = self.client.get("/api/academics/onboarding-status", headers={"Authorization": f"Bearer {self.token_a}"}).get_json()
            self.assertEqual(stat.get("state"), "LKG_ONLY")
            self.assertEqual(stat.get("setup_state"), "COMPLETE")
            self.assertEqual(stat.get("health_state"), "DEGRADED_LKG")
            self.assertFalse(stat.get("upes", {}).get("live_session_active"))
            self.assertTrue(stat.get("timetable", {}).get("stale"))

    # =========================================================================
    # 5. PHASE 3.7E STATE SEPARATION & ATTENDANCE RECOVERY TESTS
    # =========================================================================

    def test_setup_vs_health_state_separation(self):
        """Verifies clear separation between setup_state (COMPLETE/INCOMPLETE) and health_state."""
        # Initial user without Google or credentials: setup INCOMPLETE, health GOOGLE_REQUIRED
        stat = self.client.get("/api/academics/onboarding-status", headers={"Authorization": f"Bearer {self.token_a}"}).get_json()
        self.assertEqual(stat.get("setup_state"), "INCOMPLETE")
        self.assertEqual(stat.get("health_state"), "GOOGLE_REQUIRED")

        # Configure Google & credentials
        self.timetable_service.save_oauth_tokens("synth_user_a", {"access_token": "mock_token", "token_expiry": 9999999999.0}, email="a@gmail.com")
        self.cred_provider.save_credentials("synth_user_a", "a.50001@stu.upes.ac.in", "Password@123")
        self.timetable_service.upload_timetable("synth_user_a", json.dumps({"sessions": [{"id": "s1", "course": "Math", "date": "2026-09-01", "time": "10:00 - 11:00"}]}))

        # Record successful initial sync
        conn = self.conn_factory()
        conn.execute("INSERT INTO timetable_sync_history (user_id, timestamp, sessions_seen, created_count, updated_count, deleted_count, unchanged_count, error_count, status, details) VALUES (?, ?, 1, 1, 0, 0, 0, 0, 'success', '{}')", ("synth_user_a", 1700000000.0))
        conn.commit()
        conn.close()

        # Healthy live state
        with patch.object(nexus_app.upes_session_tracker, "get_safe_status", return_value={"state": "LIVE_READY", "is_live_ready": True}):
            stat_healthy = self.client.get("/api/academics/onboarding-status", headers={"Authorization": f"Bearer {self.token_a}"}).get_json()
            self.assertEqual(stat_healthy.get("setup_state"), "COMPLETE")
            self.assertEqual(stat_healthy.get("health_state"), "HEALTHY")
            self.assertTrue(stat_healthy.get("upes", {}).get("live_session_active"))

        # Expired UPES session: setup remains COMPLETE, health degrades to DEGRADED_LKG
        with patch.object(nexus_app.upes_session_tracker, "get_safe_status", return_value={"state": "EXPIRED", "is_live_ready": False}):
            stat_degraded = self.client.get("/api/academics/onboarding-status", headers={"Authorization": f"Bearer {self.token_a}"}).get_json()
            self.assertEqual(stat_degraded.get("setup_state"), "COMPLETE")
            self.assertEqual(stat_degraded.get("health_state"), "DEGRADED_LKG")
            self.assertFalse(stat_degraded.get("upes", {}).get("live_session_active"))

    def test_attendance_sync_expired_session_returns_401_auth_required(self):
        """Attendance sync on expired UPES session returns HTTP 401 with AUTH_REQUIRED status."""
        resp = self.client.post("/api/attendance/sync", headers={"Authorization": f"Bearer {self.token_a}"})
        self.assertEqual(resp.status_code, 401)
        data = resp.get_json()
        self.assertEqual(data.get("status"), "AUTH_REQUIRED")
        self.assertIn("re-authenticate", data.get("message", "").lower())

    def test_today_attendance_timetable_fallback(self):
        """When academic_sessions ledger is empty for today, today_classes is populated from timetable."""
        import datetime
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo("Asia/Kolkata")
            today_str = datetime.datetime.now(tz).strftime("%Y-%m-%d")
        except Exception:
            try:
                import pytz
                tz = pytz.timezone("Asia/Kolkata")
                today_str = datetime.datetime.now(tz).strftime("%Y-%m-%d")
            except Exception:
                today_str = datetime.datetime.now().strftime("%Y-%m-%d")

        tt_data = {
            "sessions": [
                {
                    "id": "s_today_1",
                    "course": "Operating Systems",
                    "course_code": "CSEG2001",
                    "date": today_str,
                    "time": "11:00 - 11:55",
                    "room": "11001",
                    "faculty": "Prof. Test"
                }
            ]
        }
        self.timetable_service.upload_timetable("synth_user_a", json.dumps(tt_data))

        # Re-initialize attendance_service with timetable_service
        import attendance_sync
        nexus_app.attendance_service = attendance_sync.AttendanceService(
            self.conn_factory,
            self.timetable_service.session_broker,
            timetable_service=self.timetable_service
        )

        resp = self.client.get("/api/attendance/summary", headers={"Authorization": f"Bearer {self.token_a}"})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        today_classes = data.get("today_classes", [])
        self.assertEqual(len(today_classes), 1)
        self.assertEqual(today_classes[0].get("course_name"), "Operating Systems")
        self.assertEqual(today_classes[0].get("session_date"), today_str)

    def test_expired_refresh_token_rejection_and_auth_exhaustion(self):
        """When UPES refresh endpoint rejects expired refresh token, state transitions to AUTH_EXHAUSTED/DEGRADED_LKG."""
        self.timetable_service.save_oauth_tokens("synth_user_a", {"access_token": "mock_google", "token_expiry": 9999999999.0}, email="a@gmail.com", calendar_id="primary")
        self.cred_provider.save_credentials("synth_user_a", "a.50001@stu.upes.ac.in", "Password@123")
        self.timetable_service.upload_timetable("synth_user_a", json.dumps({"sessions": [{"id": "s1", "course": "Math", "date": "2026-09-01", "time": "10:00 - 11:00"}]}))

        conn = self.conn_factory()
        conn.execute("INSERT INTO timetable_sync_history (user_id, timestamp, sessions_seen, created_count, updated_count, deleted_count, unchanged_count, error_count, status, details) VALUES (?, ?, 1, 1, 0, 0, 0, 0, 'success', '{}')", ("synth_user_a", 1700000000.0))
        conn.commit()
        conn.close()

        # Save session with expired access token and stale refresh token
        self.auth_manager._save_session_atomic(
            user_id="synth_user_a",
            access_token="expired_tok",
            student_code="50001",
            expires_at=time.time() - 3600,
            refresh_token="stale_refresh_token",
            credential_generation=1
        )

        # Mock refresh rejection
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"StatusCode": 401, "Message": "failed to generate the refresh token."}

        with patch("requests.Session.post", return_value=mock_resp):
            from agent.errors import AuthRequiredError
            with self.assertRaises(AuthRequiredError) as ctx:
                self.auth_manager.ensure_authenticated("synth_user_a", force_login=False)
            self.assertIn("exhausted", str(ctx.exception).lower())

        stat = self.client.get("/api/academics/onboarding-status", headers={"Authorization": f"Bearer {self.token_a}"}).get_json()
        self.assertEqual(stat.get("setup_state"), "COMPLETE")
        self.assertIn(stat.get("health_state"), ("UPES_INTERACTION_REQUIRED", "DEGRADED_LKG"))
        self.assertFalse(stat.get("upes", {}).get("live_session_active"))

    def test_valid_refresh_rotation_and_session_restart_restoration(self):
        """Valid refresh token rotates generation and persists across simulated server restart."""
        now = time.time()
        self.auth_manager._save_session_atomic(
            user_id="synth_user_a",
            access_token="expiring_tok",
            student_code="50001",
            expires_at=now - 100,  # Needs refresh
            refresh_token="valid_refresh_1",
            credential_generation=1
        )

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "StatusCode": 200,
            "Item": {
                "tokenInfo": {
                    "accessToken": "fresh_access_token_gen2",
                    "refreshToken": "rotated_refresh_2",
                    "expiresIn": 7200
                }
            }
        }

        with patch("requests.Session.post", return_value=mock_resp):
            tok, sc, api_url, exp = self.auth_manager.ensure_authenticated("synth_user_a")
            self.assertEqual(tok, "fresh_access_token_gen2")
            self.assertGreater(exp, now)

        # Simulate service restart: instantiate a brand new UpesAuthManager
        new_auth_manager = UpesAuthManager(
            conn_factory=self.conn_factory,
            credential_provider=self.cred_provider,
            timetable_service=self.timetable_service,
            session_tracker=UpesSessionTracker(self.conn_factory)
        )
        # Verify active session is restored directly without network refresh
        restored_tok, restored_sc, _, restored_exp = new_auth_manager.ensure_authenticated("synth_user_a")
        self.assertEqual(restored_tok, "fresh_access_token_gen2")
        self.assertEqual(restored_sc, "50001")

    def test_tier3_idp_session_silent_renewal_success(self):
        """When OAuth refresh token is rejected, valid IdP session cookies silently mint a fresh OAuth bundle."""
        now = time.time()
        self.auth_manager._save_session_atomic(
            user_id="synth_user_a",
            access_token="expired_tok",
            student_code="50001",
            expires_at=now - 100,  # Expired
            refresh_token="rejected_refresh",
            cookies={"idp_session_info": "valid_sso_cookie_123"},
            cookie_expires_at=now + 86400,
            credential_generation=1
        )

        # Mock refresh failure (StatusCode 401)
        mock_refresh_resp = MagicMock()
        mock_refresh_resp.status_code = 200
        mock_refresh_resp.json.return_value = {"StatusCode": 401, "Message": "failed to generate the refresh token."}

        # Mock IdP authorize GET redirect
        mock_auth_resp = MagicMock()
        mock_auth_resp.status_code = 200
        mock_auth_resp.url = "https://myupes-beta.upes.ac.in/connectportal/app/auth/login?code=fresh_auth_code_999"
        mock_auth_resp.history = []

        # Mock Token exchange POST
        mock_token_resp = MagicMock()
        mock_token_resp.status_code = 200
        mock_token_resp.json.return_value = {
            "StatusCode": 200,
            "Item": {
                "Identity": {
                    "AccessToken": "minted_idp_access_token",
                    "RefreshToken": "fresh_rotated_refresh_token",
                    "ExpiresIn": 624597
                },
                "UserInfo": {
                    "StudentCode": "50001"
                }
            }
        }

        def mock_post(url, *args, **kwargs):
            if "refresh-token" in url:
                return mock_refresh_resp
            return mock_token_resp

        with patch("requests.Session.get", return_value=mock_auth_resp), \
             patch("requests.Session.post", side_effect=mock_post):
            tok, sc, api_url, exp = self.auth_manager.ensure_authenticated("synth_user_a")
            self.assertEqual(tok, "minted_idp_access_token")
            self.assertEqual(sc, "50001")
            self.assertGreater(exp, now + 500000)

        # Check endurance metrics
        metrics = self.auth_manager.tracker.get_safe_metrics("synth_user_a")
        self.assertEqual(metrics.get("current_generation"), 2)
        self.assertEqual(metrics.get("autonomy_level"), "LEVEL_3_IDP_RENEWABLE")

    def test_proactive_refresh_safety_and_network_outage_resilience(self):
        """When access token is within 12h proactive margin and refresh hits network outage, existing token is preserved."""
        now = time.time()
        # Token valid for 2 hours (within 12h proactive margin, but still usable)
        self.auth_manager._save_session_atomic(
            user_id="synth_user_a",
            access_token="still_valid_access_tok",
            student_code="50001",
            expires_at=now + 7200,
            refresh_token="valid_refresh",
            credential_generation=1
        )

        # Mock network error on refresh
        with patch("requests.Session.post", side_effect=requests.exceptions.ConnectionError("Connection timed out")):
            tok, sc, api_url, exp = self.auth_manager.ensure_authenticated("synth_user_a")
            # Self-healing: returns existing token without throwing
            self.assertEqual(tok, "still_valid_access_tok")
            self.assertEqual(exp, now + 7200)


if __name__ == "__main__":
    unittest.main()
