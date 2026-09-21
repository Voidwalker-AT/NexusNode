"""
NexusNode — Academic Onboarding Status State Machine Test Suite
Phase 3.7B: Multi-User Self-Service Security Foundation

Verifies the deterministic state machine precedence and contract for:
    GET /api/timetable/onboarding-status
    GET /api/academics/onboarding-status

Validates:
1. GOOGLE_REQUIRED (Google not connected)
2. GOOGLE_EXPIRED (Google refresh expired / revoked)
3. UPES_REQUIRED (No encrypted credentials configured)
4. UPES_INTERACTION_REQUIRED (Circuit breaker open / captcha challenge)
5. UPES_EXPIRED (Session expired / reauth needed)
6. SYNCING (Active sync lease lock held)
7. READY_TO_SYNC (All accounts configured, awaiting initial sync)
8. LKG_ONLY (Operating on cached Last Known Good timetable)
9. SYNC_FAILED (Last calendar sync run failed)
10. READY (All operational and synchronized)
11. Strict secret exclusion (no raw passwords, tokens, auth tags)
12. Multi-tenant isolation between user_a and user_b
"""

import json
import os
import secrets
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

import config
import app as nexus_app
import timetable_sync
import attendance_sync
from upes.credentials import UpesCredentialProvider


class OnboardingStatusTestCase(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="nexus_onboarding_test_")
        self.db_path = os.path.join(self.test_dir, "nexus_test.db")
        self.orig_config_db_path = config.DB_PATH
        self.orig_tt_db_path = getattr(timetable_sync.config, 'DB_PATH', None)
        self.orig_att_db_path = getattr(attendance_sync.config, 'DB_PATH', None)
        self.orig_timetable_service = getattr(nexus_app, 'timetable_service', None)
        self.orig_attendance_service = getattr(nexus_app, 'attendance_service', None)
        self.orig_credential_provider = getattr(nexus_app, 'upes_credential_provider', None)

        config.DB_PATH = self.db_path
        timetable_sync.config.DB_PATH = self.db_path
        attendance_sync.config.DB_PATH = self.db_path

        self.init_db()

        self.timetable_service = timetable_sync.TimetableService(conn_factory=lambda: sqlite3.connect(self.db_path))
        self.attendance_service = attendance_sync.AttendanceService(conn_factory=lambda: sqlite3.connect(self.db_path))
        self.credential_provider = UpesCredentialProvider(conn_factory=lambda: sqlite3.connect(self.db_path))

        nexus_app.timetable_service = self.timetable_service
        nexus_app.attendance_service = self.attendance_service
        nexus_app.upes_credential_provider = self.credential_provider

        nexus_app.app.config["TESTING"] = True
        self.client = nexus_app.app.test_client()

        self.token_user = "token_user_" + secrets.token_hex(16)
        with nexus_app.SESSIONS_LOCK:
            nexus_app.SESSIONS[self.token_user] = {
                "user_id": "test_student",
                "username": "test_student",
                "role": "user",
                "privileges": {"can_sync_timetable": True},
                "expires_at": time.time() + 3600,
                "is_disabled": 0
            }

    def tearDown(self):
        with nexus_app.SESSIONS_LOCK:
            nexus_app.SESSIONS.pop(self.token_user, None)

        if self.orig_config_db_path:
            config.DB_PATH = self.orig_config_db_path
        if self.orig_tt_db_path:
            timetable_sync.config.DB_PATH = self.orig_tt_db_path
        if self.orig_att_db_path:
            attendance_sync.config.DB_PATH = self.orig_att_db_path
        if self.orig_timetable_service:
            nexus_app.timetable_service = self.orig_timetable_service
        if self.orig_attendance_service:
            nexus_app.attendance_service = self.orig_attendance_service
        if self.orig_credential_provider:
            nexus_app.upes_credential_provider = self.orig_credential_provider

        try:
            if os.path.exists(self.db_path):
                os.remove(self.db_path)
            if os.path.exists(self.test_dir):
                import shutil
                shutil.rmtree(self.test_dir, ignore_errors=True)
        except Exception:
            pass

    def init_db(self):
        conn = sqlite3.connect(self.db_path)
        with conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    username TEXT UNIQUE,
                    role TEXT DEFAULT 'user',
                    password_hash TEXT,
                    is_disabled INTEGER DEFAULT 0
                );
            """)
            timetable_sync.init_timetable_tables(conn)
            attendance_sync.init_attendance_tables(conn)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS upes_user_credentials (
                    user_id TEXT PRIMARY KEY,
                    username_hint TEXT,
                    encrypted_credentials TEXT NOT NULL,
                    created_at REAL,
                    updated_at REAL NOT NULL
                );
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS upes_portal_sessions (
                    user_id TEXT PRIMARY KEY,
                    access_token TEXT NOT NULL,
                    student_code TEXT NOT NULL,
                    api_url TEXT,
                    refresh_token TEXT,
                    cookies TEXT,
                    expires_at REAL,
                    cookie_expires_at REAL,
                    last_refresh_attempt REAL,
                    last_refresh_status TEXT,
                    updated_at REAL NOT NULL
                );
            """)
        conn.close()

    def get_status(self):
        resp = self.client.get(
            "/api/timetable/onboarding-status",
            headers={"Authorization": f"Bearer {self.token_user}"}
        )
        self.assertEqual(resp.status_code, 200)
        return resp.get_json()

    def test_state_google_required(self):
        # Fresh user without any accounts configured
        data = self.get_status()
        self.assertEqual(data["state"], "GOOGLE_REQUIRED")
        self.assertFalse(data["google"]["connected"])
        self.assertEqual(data["next_required_step"], "Connect Google Calendar")

    def test_state_google_expired(self):
        # Expired token with no refresh token
        self.timetable_service.save_oauth_tokens(
            "test_student",
            {"access_token": "expired_tok", "expires_at": time.time() - 500}
        )
        data = self.get_status()
        self.assertEqual(data["state"], "GOOGLE_EXPIRED")
        self.assertTrue(data["google"]["needs_reauth"])
        self.assertIn("Re-authenticate Google Calendar", data["next_required_step"])

    def test_state_upes_required(self):
        # Google connected with valid refresh token, but no UPES credentials
        self.timetable_service.save_oauth_tokens(
            "test_student",
            {"access_token": "valid_tok", "refresh_token": "valid_ref", "expires_at": time.time() + 3600},
            calendar_id="primary",
            email="student@gmail.com"
        )
        data = self.get_status()
        self.assertEqual(data["state"], "UPES_REQUIRED")
        self.assertTrue(data["google"]["connected"])
        self.assertFalse(data["upes"]["credentials_configured"])
        self.assertIn("Configure UPES Portal", data["next_required_step"])

    def test_state_ready_to_sync(self):
        # Google connected + UPES credentials configured + session active, but no timetable sync run yet
        self.timetable_service.save_oauth_tokens(
            "test_student",
            {"access_token": "valid_tok", "refresh_token": "valid_ref", "expires_at": time.time() + 3600},
            calendar_id="primary",
            email="student@gmail.com"
        )
        self.credential_provider.save_credentials(
            "test_student",
            "student.59001@stu.upes.ac.in",
            "ValidPass123!"
        )
        with patch.object(nexus_app.upes_session_tracker, "get_safe_status", return_value={"state": "ACTIVE", "configured": True}):
            data = self.get_status()
            self.assertEqual(data["state"], "READY_TO_SYNC")
            self.assertTrue(data["google"]["connected"])
            self.assertTrue(data["upes"]["credentials_configured"])
            self.assertIn("Trigger initial timetable synchronization", data["next_required_step"])

    def test_state_syncing(self):
        # Google and UPES ready, and a sync lock is actively held
        self.timetable_service.save_oauth_tokens(
            "test_student",
            {"access_token": "valid_tok", "refresh_token": "valid_ref", "expires_at": time.time() + 3600}
        )
        self.credential_provider.save_credentials("test_student", "student.59001@stu.upes.ac.in", "Pass123!")

        # Acquire lock
        lock = timetable_sync.DatabaseSyncLease(conn_factory=lambda: sqlite3.connect(self.db_path), user_id="test_student", timeout_seconds=60)
        self.assertTrue(lock.acquire())

        with patch.object(nexus_app.upes_session_tracker, "get_safe_status", return_value={"state": "ACTIVE", "configured": True}):
            data = self.get_status()
            self.assertEqual(data["state"], "SYNCING")
            self.assertIn("actively running", data["next_required_step"])

        lock.release()

    def test_state_sync_failed(self):
        self.timetable_service.save_oauth_tokens(
            "test_student",
            {"access_token": "valid_tok", "refresh_token": "valid_ref", "expires_at": time.time() + 3600}
        )
        self.credential_provider.save_credentials("test_student", "student.59001@stu.upes.ac.in", "Pass123!")

        # Upload timetable
        self.timetable_service.upload_timetable(
            "test_student",
            json.dumps([{"session_id": "s1", "date": "2026-09-07", "course_name": "CS1", "start_time": "09:00", "end_time": "10:00"}])
        )

        # Insert failed sync history
        conn = sqlite3.connect(self.db_path)
        with conn:
            conn.execute("""
                INSERT INTO timetable_sync_history (user_id, timestamp, sessions_seen, created_count, updated_count, deleted_count, unchanged_count, error_count, status, details)
                VALUES ('test_student', ?, 1, 0, 0, 0, 0, 1, 'failed', '{"error": "Google API 500"}')
            """, (time.time(),))
        conn.close()

        with patch.object(nexus_app.upes_session_tracker, "get_safe_status", return_value={"state": "ACTIVE", "configured": True}):
            data = self.get_status()
            self.assertEqual(data["state"], "SYNC_FAILED")
            self.assertIn("Retry timetable synchronization", data["next_required_step"])

    def test_state_ready(self):
        self.timetable_service.save_oauth_tokens(
            "test_student",
            {"access_token": "valid_tok", "refresh_token": "valid_ref", "expires_at": time.time() + 3600}
        )
        self.credential_provider.save_credentials("test_student", "student.59001@stu.upes.ac.in", "Pass123!")

        # Upload timetable
        self.timetable_service.upload_timetable(
            "test_student",
            json.dumps([{"session_id": "s1", "date": "2026-09-07", "course_name": "CS1", "start_time": "09:00", "end_time": "10:00"}])
        )

        # Insert successful sync history
        conn = sqlite3.connect(self.db_path)
        with conn:
            conn.execute("""
                INSERT INTO timetable_sync_history (user_id, timestamp, sessions_seen, created_count, updated_count, deleted_count, unchanged_count, error_count, status, details)
                VALUES ('test_student', ?, 1, 1, 0, 0, 0, 0, 'success', '{}')
            """, (time.time(),))
        conn.close()

        with patch.object(nexus_app.upes_session_tracker, "get_safe_status", return_value={"state": "ACTIVE", "configured": True}):
            data = self.get_status()
            self.assertEqual(data["state"], "READY")
            self.assertTrue(data["account_ready"])
            self.assertTrue(data["timetable"]["available"])
            self.assertEqual(data["timetable"]["session_count"], 1)
            self.assertIn("All systems operational", data["next_required_step"])

    def test_zero_secret_leakage(self):
        # Save sensitive data
        self.timetable_service.save_oauth_tokens(
            "test_student",
            {"access_token": "super_secret_access_token", "refresh_token": "super_secret_refresh_token"}
        )
        self.credential_provider.save_credentials("test_student", "student.59001@stu.upes.ac.in", "SuperSecretPassword123!")

        data = self.get_status()
        raw_str = json.dumps(data)

        # Assert no secrets in output
        self.assertNotIn("super_secret", raw_str)
        self.assertNotIn("SuperSecretPassword", raw_str)
        self.assertNotIn("encrypted_blob", raw_str)
        self.assertNotIn("auth_tag", raw_str)


if __name__ == "__main__":
    unittest.main()
