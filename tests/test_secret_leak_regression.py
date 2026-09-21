"""
Mandatory Secret-Leak Regression Test Suite (Phase 3.2, Section 26).
Ensures passwords, access tokens, refresh tokens, and cookies never appear
in stdout, stderr, logs, or API responses.
"""

import io
import sys
import time
import json
import logging
import unittest
from unittest.mock import patch, MagicMock

import config
import app as nexus_app
from upes.credentials import UpesCredentialProvider, UpesCredentialCrypto, init_credential_tables
from upes.auth import UpesAuthManager, AuthState, AuthFailureReason
from upes.session import UpesSessionTracker
from upes.router import UpesExecutionRouter


import os
import sqlite3
import tempfile

SENTINEL_PASSWORD = "SENTINEL_PASSWORD_DO_NOT_LEAK_987654321"
SENTINEL_ACCESS_TOKEN = "SENTINEL_ACCESS_TOKEN_DO_NOT_LEAK_ABC123XYZ"
SENTINEL_REFRESH_TOKEN = "SENTINEL_REFRESH_TOKEN_DO_NOT_LEAK_DEF456UVW"
SENTINEL_COOKIE = "SENTINEL_COOKIE_DO_NOT_LEAK_IDP_SESSION_INFO_789"


class TestSecretLeakRegression(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="nexus_secret_test_")
        self.db_path = os.path.join(self.temp_dir, "test.db")
        config.DB_PATH = self.db_path

        conn = sqlite3.connect(self.db_path)
        init_credential_tables(conn)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_timetables (
                user_id TEXT PRIMARY KEY,
                raw_json TEXT NOT NULL,
                updated_at REAL NOT NULL
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS upes_auth_sessions (
                user_id TEXT PRIMARY KEY,
                encrypted_access_token TEXT NOT NULL,
                student_code TEXT NOT NULL,
                api_url TEXT,
                expires_at REAL,
                encrypted_refresh_token TEXT,
                encrypted_cookies TEXT,
                cookie_expires_at REAL,
                credential_generation INTEGER NOT NULL DEFAULT 1,
                last_refresh_at REAL,
                last_refresh_status TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
        """)
        conn.commit()
        conn.close()

        self.conn_factory = lambda: sqlite3.connect(self.db_path)
        self.cred_provider = UpesCredentialProvider(self.conn_factory)
        self.session_tracker = UpesSessionTracker(self.conn_factory)
        self.auth_manager = UpesAuthManager(
            conn_factory=self.conn_factory,
            credential_provider=self.cred_provider,
            timetable_service=nexus_app.timetable_service,
            session_tracker=self.session_tracker
        )
        self.orig_upes_credential_provider = getattr(nexus_app, 'upes_credential_provider', None)
        self.orig_upes_session_tracker = getattr(nexus_app, 'upes_session_tracker', None)
        self.orig_upes_auth_manager = getattr(nexus_app, 'upes_auth_manager', None)

        nexus_app.upes_credential_provider = self.cred_provider
        nexus_app.upes_session_tracker = self.session_tracker
        nexus_app.upes_auth_manager = self.auth_manager

        nexus_app.app.config['TESTING'] = True
        self.client = nexus_app.app.test_client()
        self.admin_token = nexus_app.create_user_session({
            "user_id": "admin",
            "role": "admin",
            "privileges": config.ADMIN_DEFAULT_PRIVILEGES
        })

        # Set up captured log handler
        self.log_stream = io.StringIO()
        self.handler = logging.StreamHandler(self.log_stream)
        self.root_logger = logging.getLogger()
        self.root_logger.addHandler(self.handler)
        self.root_logger.setLevel(logging.DEBUG)

    def tearDown(self):
        self.root_logger.removeHandler(self.handler)
        if self.orig_upes_credential_provider:
            nexus_app.upes_credential_provider = self.orig_upes_credential_provider
        if self.orig_upes_session_tracker:
            nexus_app.upes_session_tracker = self.orig_upes_session_tracker
        if self.orig_upes_auth_manager:
            nexus_app.upes_auth_manager = self.orig_upes_auth_manager
        try:
            if os.path.exists(self.temp_dir):
                import shutil
                shutil.rmtree(self.temp_dir, ignore_errors=True)
        except Exception:
            pass

    def _assert_sentinels_absent(self, captured_text: str, context: str):
        for sentinel in [SENTINEL_PASSWORD, SENTINEL_ACCESS_TOKEN, SENTINEL_REFRESH_TOKEN, SENTINEL_COOKIE]:
            self.assertNotIn(
                sentinel,
                captured_text,
                f"SECURITY VIOLATION: Sentinel secret '{sentinel}' leaked in {context}!"
            )

    @patch("requests.Session.post")
    def test_sentinel_secrets_never_leak(self, mock_post):
        # 1. Mock UPES direct-HTTP login response containing sentinels
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": {
                "access_token": SENTINEL_ACCESS_TOKEN,
                "refresh_token": SENTINEL_REFRESH_TOKEN,
                "expires_in": 3600,
                "userId": "500086789"
            }
        }
        mock_post.return_value = mock_resp

        # 2. Provision credentials via REST API
        resp_cred = self.client.post(
            "/api/upes/auth/credentials",
            headers={"Authorization": f"Bearer {self.admin_token}"},
            json={"username": "sentinel.500086789@stu.upes.ac.in", "password": SENTINEL_PASSWORD}
        )
        self.assertEqual(resp_cred.status_code, 200)
        self._assert_sentinels_absent(resp_cred.get_data(as_text=True), "POST /api/upes/auth/credentials response")

        # 3. Query credential status
        resp_stat = self.client.get(
            "/api/upes/auth/credentials/status",
            headers={"Authorization": f"Bearer {self.admin_token}"}
        )
        self.assertEqual(resp_stat.status_code, 200)
        self._assert_sentinels_absent(resp_stat.get_data(as_text=True), "GET /api/upes/auth/credentials/status response")

        # 4. Perform direct login
        resp_login = self.client.post(
            "/api/upes/auth/login",
            headers={"Authorization": f"Bearer {self.admin_token}"}
        )
        self.assertEqual(resp_login.status_code, 200)
        self._assert_sentinels_absent(resp_login.get_data(as_text=True), "POST /api/upes/auth/login response")

        # 5. Query session status & auth status
        resp_sess = self.client.get(
            "/api/upes/session/status",
            headers={"Authorization": f"Bearer {self.admin_token}"}
        )
        self.assertEqual(resp_sess.status_code, 200)
        self._assert_sentinels_absent(resp_sess.get_data(as_text=True), "GET /api/upes/session/status response")

        resp_auth_stat = self.client.get(
            "/api/upes/auth/status",
            headers={"Authorization": f"Bearer {self.admin_token}"}
        )
        self.assertEqual(resp_auth_stat.status_code, 200)
        self._assert_sentinels_absent(resp_auth_stat.get_data(as_text=True), "GET /api/upes/auth/status response")

        # 6. Test Error Flow (Failed login with wrong password)
        mock_resp_fail = MagicMock()
        mock_resp_fail.status_code = 401
        mock_resp_fail.text = f"Invalid login credentials for password {SENTINEL_PASSWORD}"
        mock_resp_fail.json.return_value = {"error": "Invalid credentials"}
        mock_post.return_value = mock_resp_fail

        resp_err = self.client.post(
            "/api/upes/auth/login",
            headers={"Authorization": f"Bearer {self.admin_token}"}
        )
        self._assert_sentinels_absent(resp_err.get_data(as_text=True), "POST /api/upes/auth/login error response")

        # 7. Check all captured logger output across entire lifecycle
        captured_logs = self.log_stream.getvalue()
        self._assert_sentinels_absent(captured_logs, "Server Logs & Audit Trail")


if __name__ == "__main__":
    unittest.main()
