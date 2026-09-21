"""
Phase 3.8A Synthetic End-to-End Multi-User Onboarding & Shared Google OAuth Test Suite
=====================================================================================
Validates the complete end-to-end student onboarding workflow:
1. Shared Google OAuth App configuration & status diagnostics (Admin).
2. Admin creates student with Display Name, UPES Email, Google Email, Temporary Password.
3. Student login, mandatory password change (must_change_password: 1 -> 0).
4. Student Google OAuth connection with state-tenant binding and IDOR defense.
5. Student UPES institutional email binding and identity mismatch protection.
6. Multi-student tenant isolation (student_1 vs student_2).
7. Admin session & endurance data preservation.
"""

import json
import os
import secrets
import sqlite3
import time
import unittest
from unittest.mock import patch, MagicMock

import app
import config
import timetable_sync
import upes.auth
import upes.models


class TestMultiUserOnboardingE2E(unittest.TestCase):
    """Authoritative synthetic E2E tests for Phase 3.8A."""

    @classmethod
    def setUpClass(cls):
        app.app.config["TESTING"] = True
        cls.client = app.app.test_client()

    def setUp(self):
        # Create fresh admin token and session for admin testing
        self.admin_user_id = "admin"
        self.admin_token = secrets.token_hex(32)
        with app.SESSIONS_LOCK:
            app.SESSIONS[self.admin_token] = {
                "user_id": self.admin_user_id,
                "role": "admin",
                "privileges": dict(config.ADMIN_DEFAULT_PRIVILEGES),
                "created_at": time.time(),
                "expires_at": time.time() + 86400
            }

        # Clean up test users from DB if existing
        with app.DB_LOCK:
            conn = app.get_db_connection()
            try:
                conn.execute("DELETE FROM users WHERE user_id IN ('test_student_1', 'test_student_2', 'temp_student')")
                conn.execute("DELETE FROM google_oauth_tokens WHERE user_id IN ('test_student_1', 'test_student_2', 'temp_student')")
                conn.execute("DELETE FROM upes_user_credentials WHERE user_id IN ('test_student_1', 'test_student_2', 'temp_student')")
                conn.execute("DELETE FROM upes_auth_sessions WHERE user_id IN ('test_student_1', 'test_student_2', 'temp_student')")
                conn.execute("DELETE FROM user_timetables WHERE user_id IN ('test_student_1', 'test_student_2', 'temp_student')")
                conn.commit()
            finally:
                conn.close()

    def tearDown(self):
        # Clean up test users
        with app.DB_LOCK:
            conn = app.get_db_connection()
            try:
                conn.execute("DELETE FROM users WHERE user_id IN ('test_student_1', 'test_student_2', 'temp_student')")
                conn.execute("DELETE FROM google_oauth_tokens WHERE user_id IN ('test_student_1', 'test_student_2', 'temp_student')")
                conn.execute("DELETE FROM upes_user_credentials WHERE user_id IN ('test_student_1', 'test_student_2', 'temp_student')")
                conn.execute("DELETE FROM upes_auth_sessions WHERE user_id IN ('test_student_1', 'test_student_2', 'temp_student')")
                conn.execute("DELETE FROM user_timetables WHERE user_id IN ('test_student_1', 'test_student_2', 'temp_student')")
                conn.commit()
            finally:
                conn.close()

    # ==========================================================================
    # 1. SHARED GOOGLE OAUTH CONFIGURATION TESTS
    # ==========================================================================

    def test_admin_google_oauth_status_and_config(self):
        """Validates admin endpoints for querying and saving shared Google OAuth app config."""
        headers = {"Authorization": f"Bearer {self.admin_token}"}

        # 1. Query status as admin
        resp = self.client.get("/api/admin/google-oauth/status", headers=headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("preflight_status", data)
        self.assertIn("computed_callback_url", data)
        self.assertIn("redirect_uri", data)

        # 2. Save new shared Google OAuth configuration
        new_client_id = "1234567890-testapps.googleusercontent.com"
        new_secret = "GOCSPX-TestSecretValue12345"
        new_redirect = "http://localhost:5000/api/auth/google/callback"

        save_resp = self.client.post("/api/admin/google-oauth/config", headers=headers, json={
            "client_id": new_client_id,
            "client_secret": new_secret,
            "redirect_uri": new_redirect
        })
        self.assertEqual(save_resp.status_code, 200)
        save_data = save_resp.get_json()
        self.assertEqual(save_data["status"], "success")

        # 3. Verify precedence: DB config returned
        db_cfg = timetable_sync.get_shared_google_oauth_config(app.get_db_connection)
        self.assertEqual(db_cfg["source"], "database")
        self.assertEqual(db_cfg["client_id"], new_client_id)
        self.assertEqual(db_cfg["client_secret"], new_secret)
        self.assertEqual(db_cfg["redirect_uri"], new_redirect)

    def test_non_admin_cannot_access_google_oauth_admin_routes(self):
        """Enforces RBAC: regular user receives 403 Forbidden for admin Google OAuth routes."""
        # Create student session
        student_token = secrets.token_hex(32)
        with app.SESSIONS_LOCK:
            app.SESSIONS[student_token] = {
                "user_id": "test_student_1",
                "role": "user",
                "privileges": {"can_sync_timetable": True},
                "created_at": time.time(),
                "expires_at": time.time() + 86400
            }

        headers = {"Authorization": f"Bearer {student_token}"}
        resp1 = self.client.get("/api/admin/google-oauth/status", headers=headers)
        self.assertEqual(resp1.status_code, 403)

        resp2 = self.client.post("/api/admin/google-oauth/config", headers=headers, json={"client_id": "hack"})
        self.assertEqual(resp2.status_code, 403)

    # ==========================================================================
    # 2. ADMIN CREATES STUDENT ACCOUNT TESTS
    # ==========================================================================

    def test_admin_create_student_validation(self):
        """Validates that admin cannot create a student with invalid UPES identifier format."""
        headers = {"Authorization": f"Bearer {self.admin_token}"}

        # 1. Reject numeric SAP ID alone
        resp_numeric = self.client.post("/api/admin/users", headers=headers, json={
            "user_id": "test_student_1",
            "display_name": "Test Student",
            "upes_email": "500123456",
            "password": "InitialTempPassword123"
        })
        self.assertEqual(resp_numeric.status_code, 400)
        self.assertIn("Invalid UPES", resp_numeric.get_json()["error"])

        # 2. Reject non-UPES domain
        resp_bad_domain = self.client.post("/api/admin/users", headers=headers, json={
            "user_id": "test_student_1",
            "display_name": "Test Student",
            "upes_email": "student@gmail.com",
            "password": "InitialTempPassword123"
        })
        self.assertEqual(resp_bad_domain.status_code, 400)

        # 3. Accept valid institutional email
        resp_valid = self.client.post("/api/admin/users", headers=headers, json={
            "user_id": "test_student_1",
            "display_name": "Test Student",
            "upes_email": "test.500123456@stu.upes.ac.in",
            "google_email": "test.student@gmail.com",
            "password": "InitialTempPassword123",
            "must_change_password": True
        })
        self.assertEqual(resp_valid.status_code, 201)
        data = resp_valid.get_json()
        self.assertEqual(data["user_id"], "test_student_1")
        self.assertTrue(data["must_change_password"])

        # 4. Verify in DB
        user = app.db_get_user("test_student_1")
        self.assertIsNotNone(user)
        self.assertEqual(user["display_name"], "Test Student")
        self.assertEqual(user["upes_email"], "test.500123456@stu.upes.ac.in")
        self.assertEqual(user["google_email"], "test.student@gmail.com")
        self.assertEqual(user["must_change_password"], 1)

    def test_admin_onboarding_status_checklist(self):
        """Validates admin onboarding status checklist endpoint for target student."""
        headers = {"Authorization": f"Bearer {self.admin_token}"}

        # Create student
        self.client.post("/api/admin/users", headers=headers, json={
            "user_id": "test_student_1",
            "display_name": "Rohan Mehra",
            "upes_email": "rohan.500999999@stu.upes.ac.in",
            "google_email": "rohan.mehra@gmail.com",
            "password": "InitialTempPassword123",
            "must_change_password": True
        })

        # Query onboarding checklist
        resp = self.client.get("/api/admin/users/test_student_1/onboarding-status", headers=headers)
        self.assertEqual(resp.status_code, 200)
        checklist = resp.get_json()
        self.assertTrue(checklist["account_created"])
        self.assertTrue(checklist["must_change_password"])
        self.assertFalse(checklist["password_changed"])
        self.assertFalse(checklist["google_connected"])
        self.assertEqual(checklist["google_test_user_email"], "rohan.mehra@gmail.com")
        self.assertEqual(checklist["upes_status"], "CREDENTIALS_REQUIRED")

    # ==========================================================================
    # 3. STUDENT LOGIN & MANDATORY PASSWORD CHANGE TESTS
    # ==========================================================================

    def test_student_mandatory_password_change_flow(self):
        """Validates that student with must_change_password=1 sees security checkpoint and clears it upon change."""
        # 1. Create student
        app.db_create_user(
            user_id="test_student_1",
            password="InitialTempPassword123",
            display_name="Aryan Sharma",
            upes_email="aryan.500888888@stu.upes.ac.in",
            must_change_password=1
        )

        # 2. Student logs in
        login_resp = self.client.post("/api/auth/login", json={
            "username": "test_student_1",
            "password": "InitialTempPassword123"
        })
        self.assertEqual(login_resp.status_code, 200)
        student_token = login_resp.get_json()["token"]
        student_headers = {"Authorization": f"Bearer {student_token}"}

        # 3. Onboarding status reports PASSWORD_CHANGE_REQUIRED
        onb_resp = self.client.get("/api/academics/onboarding-status", headers=student_headers)
        self.assertEqual(onb_resp.status_code, 200)
        onb_data = onb_resp.get_json()
        self.assertEqual(onb_data["health_state"], "PASSWORD_CHANGE_REQUIRED")
        self.assertTrue(onb_data["user_profile"]["must_change_password"])

        # 4. Student changes password
        change_resp = self.client.post("/api/auth/change-password", headers=student_headers, json={
            "current_password": "InitialTempPassword123",
            "new_password": "AryanSecurePersonalPassword2026",
            "confirm_password": "AryanSecurePersonalPassword2026"
        })
        self.assertEqual(change_resp.status_code, 200)

        # 5. Verify must_change_password is now 0 in DB
        user_after = app.db_get_user("test_student_1")
        self.assertEqual(user_after["must_change_password"], 0)

        # 6. Next onboarding status check advances to GOOGLE_REQUIRED
        onb_after = self.client.get("/api/academics/onboarding-status", headers=student_headers).get_json()
        self.assertEqual(onb_after["health_state"], "GOOGLE_REQUIRED")
        self.assertFalse(onb_after["user_profile"]["must_change_password"])

    # ==========================================================================
    # 4. STUDENT GOOGLE OAUTH & CSRF TENANT BINDING TESTS
    # ==========================================================================

    @patch("timetable_sync.GoogleCalendarClient.exchange_code_for_tokens")
    def test_student_google_oauth_callback_and_tenant_isolation(self, mock_exchange):
        """Validates Google OAuth state generation, token exchange, and IDOR prevention."""
        # Create two students
        app.db_create_user(user_id="test_student_1", password="Password123!", display_name="Student One")
        app.db_create_user(user_id="test_student_2", password="Password123!", display_name="Student Two")

        token_1 = secrets.token_hex(32)
        token_2 = secrets.token_hex(32)
        with app.SESSIONS_LOCK:
            app.SESSIONS[token_1] = {"user_id": "test_student_1", "role": "user", "privileges": {"can_sync_timetable": True}, "created_at": time.time(), "expires_at": time.time() + 86400}
            app.SESSIONS[token_2] = {"user_id": "test_student_2", "role": "user", "privileges": {"can_sync_timetable": True}, "created_at": time.time(), "expires_at": time.time() + 86400}

        headers_1 = {"Authorization": f"Bearer {token_1}"}
        headers_2 = {"Authorization": f"Bearer {token_2}"}

        # Student 1 requests authorization URL
        auth_resp = self.client.get("/api/auth/google/authorize", headers=headers_1)
        self.assertEqual(auth_resp.status_code, 200)
        state_token = auth_resp.get_json()["state"]

        # Cross-User Protection: Student 2 attempts to use Student 1's state
        mock_exchange.return_value = {
            "access_token": "ya29.mock_token_s1",
            "refresh_token": "1//mock_refresh_s1",
            "expires_at": time.time() + 3600
        }
        cross_resp = self.client.get(f"/api/auth/google/callback?code=mock_code&state={state_token}", headers=headers_2)
        self.assertEqual(cross_resp.status_code, 403)
        self.assertIn("forbidden", cross_resp.get_json()["error"])

        # Legitimate Student 1 callback
        auth_resp_valid = self.client.get("/api/auth/google/authorize", headers=headers_1)
        valid_state = auth_resp_valid.get_json()["state"]

        callback_resp = self.client.get(f"/api/auth/google/callback?code=mock_code&state={valid_state}", headers=headers_1)
        self.assertIn(callback_resp.status_code, (200, 302))

        # Verify Student 1 has tokens, but Student 2 has none
        tokens_s1 = app.timetable_service.get_oauth_tokens("test_student_1")
        tokens_s2 = app.timetable_service.get_oauth_tokens("test_student_2")
        self.assertIsNotNone(tokens_s1)
        self.assertIsNone(tokens_s2)

    # ==========================================================================
    # 5. STUDENT UPES INSTITUTIONAL IDENTITY BINDING TESTS
    # ==========================================================================

    def test_student_upes_identity_mismatch_protection(self):
        """Validates that a student cannot submit another student's UPES institutional email."""
        app.db_create_user(
            user_id="test_student_1",
            password="Password123!",
            display_name="Kavya Singh",
            upes_email="kavya.500777777@stu.upes.ac.in"
        )

        student_token = secrets.token_hex(32)
        with app.SESSIONS_LOCK:
            app.SESSIONS[student_token] = {
                "user_id": "test_student_1",
                "role": "user",
                "privileges": {"can_sync_timetable": True},
                "created_at": time.time(),
                "expires_at": time.time() + 86400
            }

        headers = {"Authorization": f"Bearer {student_token}"}

        # 1. Attempt to submit mismatched UPES email
        mismatch_resp = self.client.post("/api/upes/auth/credentials", headers=headers, json={
            "username": "other.500111111@stu.upes.ac.in",
            "password": "UpesPassword123"
        })
        self.assertEqual(mismatch_resp.status_code, 400)
        self.assertEqual(mismatch_resp.get_json()["error"], "identity_mismatch")

        # 2. Submit matching UPES institutional email
        match_resp = self.client.post("/api/upes/auth/credentials", headers=headers, json={
            "username": "kavya.500777777@stu.upes.ac.in",
            "password": "UpesPassword123"
        })
        self.assertEqual(match_resp.status_code, 200)
        self.assertEqual(match_resp.get_json()["status"], "success")

        # Verify credential status
        cred_status = app.upes_credential_provider.get_credential_status("test_student_1")
        self.assertTrue(cred_status["configured"])
        self.assertEqual(cred_status["configured_identifier_format"], "FULL_EMAIL")

    # ==========================================================================
    # 6. MULTI-TENANT ISOLATION & ADMIN ENDURANCE PRESERVATION
    # ==========================================================================

    def test_multi_student_tenant_isolation_and_admin_preservation(self):
        """
        Validates complete multi-tenant isolation across two student accounts,
        and verifies that the primary admin session remains intact.
        """
        # 1. Create two student tenants
        app.db_create_user(user_id="test_student_1", password="Password123!", display_name="Student A", upes_email="studenta.500111@stu.upes.ac.in")
        app.db_create_user(user_id="test_student_2", password="Password123!", display_name="Student B", upes_email="studentb.500222@stu.upes.ac.in")

        # Mock sessions in user_timetables table for Student 1 only
        mock_raw = json.dumps([
            {
                "date": "2026-09-02",
                "startTime": "09:00",
                "endTime": "10:00",
                "subject": "Cloud Computing",
                "courseCode": "CSEG101",
                "room": "10101",
                "faculty": "Prof. Smith"
            }
        ])

        with app.DB_LOCK:
            conn = app.get_db_connection()
            try:
                conn.execute("""
                    INSERT INTO user_timetables (user_id, raw_json, updated_at)
                    VALUES ('test_student_1', ?, 1700000000.0)
                """, (mock_raw,))
                conn.commit()
            finally:
                conn.close()

        # Query sessions for Student 1
        s1_sessions, _ = app.timetable_service.load_timetable_sessions("test_student_1")
        # In test mode without fallback file, s2 has no raw_json
        with patch("os.path.exists", return_value=False):
            s2_sessions, _ = app.timetable_service.load_timetable_sessions("test_student_2")

        self.assertEqual(len(s1_sessions), 1)
        self.assertEqual(len(s2_sessions), 0)

        # Verify admin account still exists and is healthy
        admin_user = app.db_get_user("admin")
        self.assertIsNotNone(admin_user)
        self.assertEqual(admin_user["role"], "admin")


if __name__ == "__main__":
    unittest.main()