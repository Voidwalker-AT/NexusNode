"""
Comprehensive Unit and Integration Test Suite for UPES Authentication Manager (Phase 3.2).
Covers all 36 test criteria specified in Phase 3.2.
"""

import os
import time
import json
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch, MagicMock

import config
import app as nexus_app
from upes.credentials import UpesCredentialProvider, UpesCredentialCrypto, init_credential_tables
from upes.auth import UpesAuthManager, AuthState, AuthFailureReason, AuthCircuitBreaker
from upes.session import UpesSessionTracker, UpesSessionState
from upes.router import UpesExecutionRouter
from agent.models import ExecutionResult
from agent.errors import (
    AuthRequiredError,
    SessionExpiredError,
    SecurityChallengeError,
    UpstreamError
)


class MockTimetableService:
    def __init__(self, conn_factory):
        self.conn_factory = conn_factory
        self.sessions_store = {}

    def get_full_upes_session(self, user_id: str):
        conn = self.conn_factory()
        try:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("SELECT * FROM upes_auth_sessions WHERE user_id = ?", (user_id,))
            row = cur.fetchone()
            if not row:
                return self.sessions_store.get(user_id)
            return {
                "user_id": row["user_id"],
                "access_token": row["encrypted_access_token"],
                "student_code": row["student_code"],
                "api_url": row["api_url"],
                "expires_at": row["expires_at"],
                "refresh_token": row["encrypted_refresh_token"],
                "cookies": json.loads(row["encrypted_cookies"]) if row["encrypted_cookies"] else {},
                "cookie_expires_at": row["cookie_expires_at"],
                "credential_generation": row["credential_generation"],
                "last_refresh_at": row["last_refresh_at"],
                "last_refresh_status": row["last_refresh_status"]
            }
        finally:
            conn.close()

    def save_upes_session(self, user_id, access_token, student_code, api_url=None, expires_at=None,
                          refresh_token=None, cookies=None, cookie_expires_at=None,
                          credential_generation=1, last_refresh_at=None, last_refresh_status=None):
        now = time.time()
        conn = self.conn_factory()
        try:
            conn.execute("""
                INSERT INTO upes_auth_sessions (
                    user_id, encrypted_access_token, student_code, api_url, expires_at,
                    encrypted_refresh_token, encrypted_cookies, cookie_expires_at,
                    credential_generation, last_refresh_at, last_refresh_status,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    encrypted_access_token = excluded.encrypted_access_token,
                    student_code = excluded.student_code,
                    api_url = excluded.api_url,
                    expires_at = excluded.expires_at,
                    encrypted_refresh_token = excluded.encrypted_refresh_token,
                    encrypted_cookies = excluded.encrypted_cookies,
                    cookie_expires_at = excluded.cookie_expires_at,
                    credential_generation = excluded.credential_generation,
                    last_refresh_at = excluded.last_refresh_at,
                    last_refresh_status = excluded.last_refresh_status,
                    updated_at = excluded.updated_at
            """, (
                user_id, access_token, student_code, api_url, expires_at,
                refresh_token, json.dumps(cookies) if cookies else None, cookie_expires_at,
                credential_generation, last_refresh_at or now, last_refresh_status,
                now, now
            ))
            conn.commit()
        finally:
            conn.close()

        self.sessions_store[user_id] = {
            "user_id": user_id,
            "access_token": access_token,
            "student_code": student_code,
            "api_url": api_url,
            "expires_at": expires_at,
            "refresh_token": refresh_token,
            "cookies": cookies or {},
            "cookie_expires_at": cookie_expires_at,
            "credential_generation": credential_generation,
            "last_refresh_at": last_refresh_at or now,
            "last_refresh_status": last_refresh_status
        }

    def sync_timetable(self, user_id: str):
        return {"status": "success", "sessions_seen": 42}

    def load_timetable_sessions(self, user_id: str, rolling_two_weeks: bool = True):
        return [{"id": "slot1", "course": "Cloud Computing", "room": "9101"}]


class MockAttendanceService:
    def __init__(self):
        self.sync_called = False

    def sync_user_attendance(self, user_id: str):
        self.sync_called = True
        return {"status": "SUCCESS", "records_synced": 5}

    def get_attendance_analytics(self, user_id: str, threshold: float = 0.75):
        return {"has_data": True, "aggregate_percentage": 88.5, "last_synced_at": time.time()}


class TestUpesAuthManagerComprehensive(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_auth.db")

        def conn_factory():
            c = sqlite3.connect(self.db_path)
            c.row_factory = sqlite3.Row
            return c

        self.conn_factory = conn_factory
        conn = self.conn_factory()
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

        self.cred_provider = UpesCredentialProvider(self.conn_factory)
        self.session_tracker = UpesSessionTracker(self.conn_factory)
        self.timetable_service = MockTimetableService(self.conn_factory)
        self.attendance_service = MockAttendanceService()
        self.auth_manager = UpesAuthManager(
            conn_factory=self.conn_factory,
            credential_provider=self.cred_provider,
            timetable_service=self.timetable_service,
            session_tracker=self.session_tracker
        )
        self.router = UpesExecutionRouter(
            conn_factory=self.conn_factory,
            attendance_service=self.attendance_service,
            timetable_service=self.timetable_service,
            session_tracker=self.session_tracker,
            auth_manager=self.auth_manager
        )

        nexus_app.app.config['TESTING'] = True
        self.client = nexus_app.app.test_client()

        # Wire app singletons to isolated test database instances
        nexus_app.upes_credential_provider = self.cred_provider
        nexus_app.upes_auth_manager = self.auth_manager
        nexus_app.upes_session_tracker = self.session_tracker

        self.admin_token = nexus_app.create_user_session({
            "user_id": "admin",
            "role": "admin",
            "privileges": config.ADMIN_DEFAULT_PRIVILEGES
        })
        self.user_token = nexus_app.create_user_session({
            "user_id": "test_student",
            "role": "user",
            "privileges": config.USER_DEFAULT_PRIVILEGES
        })

    def tearDown(self):
        try:
            for f in os.listdir(self.temp_dir):
                os.remove(os.path.join(self.temp_dir, f))
            os.rmdir(self.temp_dir)
        except Exception:
            pass

    # 1. Encrypted credential storage
    def test_01_encrypted_credential_storage(self):
        self.cred_provider.save_credentials("admin", "500086789", "super_secret_pwd")
        conn = self.conn_factory()
        cur = conn.cursor()
        cur.execute("SELECT encrypted_credentials FROM upes_user_credentials WHERE user_id = 'admin'")
        row = cur.fetchone()
        self.assertIsNotNone(row)
        self.assertNotIn("super_secret_pwd", row["encrypted_credentials"])
        
        # Test decryption
        decrypted = UpesCredentialCrypto.decrypt(row["encrypted_credentials"])
        self.assertEqual(decrypted["username"], "500086789")
        self.assertEqual(decrypted["password"], "super_secret_pwd")

    # 2. Credential API never echoes password
    def test_02_credential_api_never_echoes_password(self):
        resp = self.client.post(
            "/api/upes/auth/credentials",
            headers={"Authorization": f"Bearer {self.admin_token}"},
            json={"username": "student.500086789@stu.upes.ac.in", "password": "sensitive_student_password"}
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_data(as_text=True)
        self.assertNotIn("sensitive_student_password", body)

    # 3. Credential status exposes metadata only
    def test_03_credential_status_exposes_metadata_only(self):
        self.cred_provider.save_credentials("admin", "student.500086789@stu.upes.ac.in", "my_secret_pwd_val")
        resp = self.client.get(
            "/api/upes/auth/credentials/status",
            headers={"Authorization": f"Bearer {self.admin_token}"}
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["credentials"]["configured"])
        self.assertIn("@stu.upes.ac.in", data["credentials"]["username_hint"])
        self.assertTrue(data["credentials"]["has_stored_credentials"])
        self.assertNotIn("my_secret_pwd_val", str(data))

    # 4. Wrong RBAC cannot configure credentials
    def test_04_wrong_rbac_cannot_configure_credentials(self):
        no_priv_token = nexus_app.create_user_session({
            "user_id": "test_nopriv",
            "role": "user",
            "privileges": {"can_sync_timetable": False}
        })
        resp = self.client.post(
            "/api/upes/auth/credentials",
            headers={"Authorization": f"Bearer {no_priv_token}"},
            json={"username": "student.500086789@stu.upes.ac.in", "password": "pwd"}
        )
        self.assertEqual(resp.status_code, 403)

    # 5. AuthManager valid-session reuse
    def test_05_auth_manager_valid_session_reuse(self):
        now = time.time()
        self.timetable_service.save_upes_session(
            user_id="admin",
            access_token="tok_valid_123",
            student_code="500086789",
            expires_at=now + 3600
        )
        tok, code, url, exp = self.auth_manager.ensure_authenticated("admin")
        self.assertEqual(tok, "tok_valid_123")
        self.assertEqual(code, "500086789")

    # 6. AuthManager token refresh
    @patch.object(UpesAuthManager, "_refresh_direct_http")
    def test_06_auth_manager_token_refresh(self, mock_refresh):
        now = time.time()
        mock_refresh.return_value = {
            "access_token": "tok_refreshed_999",
            "refresh_token": "rt_new_456",
            "expires_at": now + 3600,
            "student_code": "500086789",
            "cookies": {"idp_session_info": "sso_cookie_abc"},
            "cookie_expires_at": now + 30000
        }
        # Session is near expiry (100 seconds left < 300 margin)
        self.timetable_service.save_upes_session(
            user_id="admin",
            access_token="tok_old",
            student_code="500086789",
            expires_at=now + 100,
            refresh_token="rt_old",
            cookies={"idp_session_info": "sso_cookie_abc"},
            cookie_expires_at=now + 30000
        )
        tok, code, url, exp = self.auth_manager.ensure_authenticated("admin")
        self.assertEqual(tok, "tok_refreshed_999")
        mock_refresh.assert_called_once()

    # 7. Refresh rejection -> AUTH_EXHAUSTED under autonomous operation, login on force_login=True
    @patch.object(UpesAuthManager, "_login_direct_http")
    @patch.object(UpesAuthManager, "_refresh_direct_http")
    def test_07_refresh_rejection_escalates_to_full_login(self, mock_refresh, mock_login):
        now = time.time()
        mock_refresh.side_effect = SessionExpiredError("invalid_grant")
        mock_login.return_value = {
            "access_token": "tok_from_login",
            "refresh_token": "rt_from_login",
            "expires_at": now + 3600,
            "student_code": "500086789",
            "cookies": {"idp_session_info": "cookie_new"},
            "cookie_expires_at": now + 36000
        }
        self.cred_provider.save_credentials("admin", "500086789", "pwd")
        self.timetable_service.save_upes_session(
            user_id="admin",
            access_token="tok_old",
            student_code="500086789",
            expires_at=now + 50,
            refresh_token="rt_bad",
            cookies={"idp_session_info": "cookie_old"},
            cookie_expires_at=now + 1000
        )

        # Autonomous mode: exhausts without automatic password login (User Directive 1)
        with self.assertRaises(AuthRequiredError) as cm:
            self.auth_manager.ensure_authenticated("admin", force_login=False)
        self.assertIn("exhausted", str(cm.exception).lower())
        mock_login.assert_not_called()

        # Explicit force_login mode: executes direct login
        tok, code, url, exp = self.auth_manager.ensure_authenticated("admin", force_login=True)
        self.assertEqual(tok, "tok_from_login")
        mock_login.assert_called_once()

    # 8. Expired session -> AUTH_EXHAUSTED under autonomous operation, login on force_login=True
    @patch.object(UpesAuthManager, "_login_direct_http")
    def test_08_expired_session_triggers_full_login(self, mock_login):
        now = time.time()
        mock_login.return_value = {
            "access_token": "tok_new_login",
            "refresh_token": "rt_new_login",
            "expires_at": now + 3600,
            "student_code": "500086789",
            "cookies": {},
            "cookie_expires_at": now + 36000
        }
        self.cred_provider.save_credentials("admin", "500086789", "pwd")
        # Stored session is completely expired with no refresh token
        self.timetable_service.save_upes_session(
            user_id="admin",
            access_token="tok_expired",
            student_code="500086789",
            expires_at=now - 500
        )
        
        # Autonomous mode: exhausts
        with self.assertRaises(AuthRequiredError):
            self.auth_manager.ensure_authenticated("admin", force_login=False)
        mock_login.assert_not_called()

        # Forced mode: executes login
        tok, code, url, exp = self.auth_manager.ensure_authenticated("admin", force_login=True)
        self.assertEqual(tok, "tok_new_login")
        mock_login.assert_called_once()

    # 9. Concurrent callers cause exactly one login
    @patch.object(UpesAuthManager, "_login_direct_http")
    def test_09_concurrent_callers_single_login(self, mock_login):
        now = time.time()
        login_calls = []

        def slow_login(*args, **kwargs):
            time.sleep(0.1)
            login_calls.append(1)
            return {
                "access_token": "tok_concurrent_success",
                "refresh_token": "rt_concurrent",
                "expires_at": now + 3600,
                "student_code": "500086789",
                "cookies": {},
                "cookie_expires_at": now + 36000
            }

        mock_login.side_effect = slow_login
        self.cred_provider.save_credentials("admin", "500086789", "pwd")

        results = []
        threads = []
        for _ in range(5):
            def worker():
                tok, _, _, _ = self.auth_manager.ensure_authenticated("admin")
                results.append(tok)
            t = threading.Thread(target=worker)
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        self.assertEqual(len(results), 5)
        self.assertTrue(all(r == "tok_concurrent_success" for r in results))
        self.assertEqual(len(login_calls), 1)

    # 10. Invalid credentials classification
    @patch("requests.Session.post")
    def test_10_invalid_credentials_classification(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.text = "Invalid username or password."
        mock_resp.json.return_value = {"error": "Invalid credentials"}
        mock_post.return_value = mock_resp

        self.cred_provider.save_credentials("admin", "500086789", "wrong_pwd")
        with self.assertRaises(AuthRequiredError):
            self.auth_manager.ensure_authenticated("admin", force_login=True)

        status = self.auth_manager.get_status("admin")
        self.assertEqual(status["circuit"]["last_error"], "INVALID_CREDENTIALS")

    # 11. Network failure classification
    @patch("requests.Session.post")
    def test_11_network_failure_classification(self, mock_post):
        import requests.exceptions
        mock_post.side_effect = requests.exceptions.ConnectionError("Connection refused")

        self.cred_provider.save_credentials("admin", "500086789", "pwd")
        with self.assertRaises(AuthRequiredError):
            self.auth_manager.ensure_authenticated("admin", force_login=True)

        self.assertEqual(self.auth_manager.circuit_breaker.last_failure_reason, AuthFailureReason.NETWORK_ERROR)

    # 12. Security challenge classification
    @patch("requests.Session.post")
    def test_12_security_challenge_classification(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.text = "Cloudflare Turnstile verification challenge required."
        mock_post.return_value = mock_resp

        self.cred_provider.save_credentials("admin", "500086789", "pwd")
        with self.assertRaises(SecurityChallengeError):
            self.auth_manager.ensure_authenticated("admin", force_login=True)

        self.assertEqual(self.auth_manager.circuit_breaker.last_failure_reason, AuthFailureReason.SECURITY_CHALLENGE)

    # 13. Login-flow-change classification
    @patch("requests.Session.post")
    def test_13_login_flow_change_classification(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = json.dumps({"status": "ok", "unexpected_payload": True})
        mock_resp.json.return_value = {"status": "ok", "unexpected_payload": True}
        mock_post.return_value = mock_resp

        self.cred_provider.save_credentials("admin", "500086789", "pwd")
        with self.assertRaises(AuthRequiredError):
            self.auth_manager.ensure_authenticated("admin", force_login=True)

        self.assertEqual(self.auth_manager.circuit_breaker.last_failure_reason, AuthFailureReason.LOGIN_FLOW_CHANGED)

    # 14. Login JSON/state parser
    @patch("requests.Session.post")
    def test_14_login_json_parser_success(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": {
                "access_token": "tok_parsed_abc",
                "refresh_token": "rt_parsed_xyz",
                "expires_in": 7200,
                "userId": "500086789"
            }
        }
        mock_post.return_value = mock_resp

        self.cred_provider.save_credentials("admin", "500086789", "pwd")
        tok, code, url, exp = self.auth_manager.ensure_authenticated("admin", force_login=True)
        self.assertEqual(tok, "tok_parsed_abc")
        self.assertEqual(code, "500086789")

    # 15. No TLS verification disabling
    @patch("requests.Session.post")
    def test_15_no_tls_verification_disabling(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": {"access_token": "tok", "expires_in": 3600}}
        mock_post.return_value = mock_resp

        self.cred_provider.save_credentials("admin", "500086789", "pwd")
        self.auth_manager.ensure_authenticated("admin", force_login=True)

        # Assert verify=True was passed to post call
        kwargs = mock_post.call_args[1]
        self.assertTrue(kwargs.get("verify", False))

    # 16-19. Circuit breaker logic
    def test_16_to_19_circuit_breaker_lifecycle(self):
        cb = AuthCircuitBreaker(failure_threshold=3, cooldown_seconds=2.0)
        self.assertFalse(cb.is_open()[0])

        # Record network failures
        cb.record_failure(AuthFailureReason.NETWORK_ERROR)
        self.assertFalse(cb.is_open()[0])
        cb.record_failure(AuthFailureReason.NETWORK_ERROR)
        self.assertFalse(cb.is_open()[0])
        cb.record_failure(AuthFailureReason.NETWORK_ERROR)
        
        # Now circuit opens
        is_open, reason, retry_after = cb.is_open()
        self.assertTrue(is_open)
        self.assertEqual(reason, "NETWORK_ERROR")

        # Cooldown recovery
        time.sleep(2.1)
        self.assertFalse(cb.is_open()[0])

        # Immediate trip on INVALID_CREDENTIALS
        cb.record_failure(AuthFailureReason.INVALID_CREDENTIALS)
        is_open, reason, _ = cb.is_open()
        self.assertTrue(is_open)
        self.assertEqual(reason, "INVALID_CREDENTIALS")

        # Reset on success
        cb.record_success()
        self.assertFalse(cb.is_open()[0])

    # 20. Session tracker updates after auth
    @patch.object(UpesAuthManager, "_login_direct_http")
    def test_20_session_tracker_updates_after_auth(self, mock_login):
        now = time.time()
        mock_login.return_value = {
            "access_token": "tok_tracked",
            "refresh_token": "rt_tracked",
            "expires_at": now + 3600,
            "student_code": "500086789",
            "cookies": {},
            "cookie_expires_at": now + 36000
        }
        self.cred_provider.save_credentials("admin", "500086789", "pwd")
        self.auth_manager.ensure_authenticated("admin", force_login=True)

        stat = self.session_tracker.get_safe_status("admin")
        self.assertEqual(stat["state"], "AUTHENTICATED")
        self.assertEqual(stat["student_code_masked"], "5000***6789")

    # 21-23. Status API hides secrets
    def test_21_to_23_status_api_hides_tokens_and_cookies(self):
        now = time.time()
        self.timetable_service.save_upes_session(
            user_id="admin",
            access_token="secret_access_jwt_xyz",
            student_code="500086789",
            expires_at=now + 3600,
            refresh_token="secret_refresh_token_123",
            cookies={"idp_session_info": "secret_cookie_val"}
        )
        resp = self.client.get(
            "/api/upes/auth/status",
            headers={"Authorization": f"Bearer {self.admin_token}"}
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_data(as_text=True)
        self.assertNotIn("secret_access_jwt_xyz", body)
        self.assertNotIn("secret_refresh_token_123", body)
        self.assertNotIn("secret_cookie_val", body)

    # 24. Timetable reauth -> live fetch
    @patch.object(UpesAuthManager, "_login_direct_http")
    def test_24_timetable_reauth_live_fetch(self, mock_login):
        now = time.time()
        mock_login.return_value = {
            "access_token": "tok_fresh",
            "refresh_token": "rt_fresh",
            "expires_at": now + 3600,
            "student_code": "500086789",
            "cookies": {},
            "cookie_expires_at": now + 36000
        }
        self.cred_provider.save_credentials("admin", "500086789", "pwd")
        result = self.router.execute("upes.get_timetable", user_id="admin")
        self.assertTrue(result.ok)
        self.assertEqual(result.source, "live")
        self.assertFalse(result.stale)

    # 25. Timetable reauth failure -> explicit LKG stale result
    def test_25_timetable_reauth_failure_explicit_lkg_stale(self):
        # Insert LKG timetable in DB
        conn = self.conn_factory()
        conn.execute("INSERT INTO user_timetables (user_id, raw_json, updated_at) VALUES ('admin', '[]', 1700000000.0)")
        conn.commit()
        conn.close()

        # No credentials configured -> reauth fails
        result = self.router.execute("upes.get_timetable", user_id="admin")
        self.assertTrue(result.ok)
        self.assertEqual(result.source, "lkg")
        self.assertTrue(result.stale)
        self.assertIn("warning", result.metadata)

    # 26. Attendance reauth -> live fetch
    @patch.object(UpesAuthManager, "_login_direct_http")
    def test_26_attendance_reauth_live_fetch(self, mock_login):
        now = time.time()
        mock_login.return_value = {
            "access_token": "tok_fresh_att",
            "refresh_token": "rt_fresh_att",
            "expires_at": now + 3600,
            "student_code": "500086789",
            "cookies": {},
            "cookie_expires_at": now + 36000
        }
        self.cred_provider.save_credentials("admin", "500086789", "pwd")
        result = self.router.execute("upes.get_attendance", user_id="admin", params={"force_sync": True})
        self.assertTrue(result.ok)
        self.assertEqual(result.source, "live")
        self.assertFalse(result.stale)
        self.assertTrue(self.attendance_service.sync_called)

    # 27-28. Simultaneous sync shares auth
    @patch.object(UpesAuthManager, "_login_direct_http")
    def test_28_simultaneous_timetable_and_attendance_shares_auth(self, mock_login):
        now = time.time()
        mock_login.return_value = {
            "access_token": "tok_shared_sync",
            "refresh_token": "rt_shared",
            "expires_at": now + 3600,
            "student_code": "500086789",
            "cookies": {},
            "cookie_expires_at": now + 36000
        }
        self.cred_provider.save_credentials("admin", "500086789", "pwd")
        
        # Ensure session is created
        tok1, _, _, _ = self.auth_manager.ensure_authenticated("admin")
        tok2, _, _, _ = self.auth_manager.ensure_authenticated("admin")
        self.assertEqual(tok1, tok2)
        self.assertEqual(mock_login.call_count, 1)

    # 29. Manual login endpoint
    @patch.object(UpesAuthManager, "_login_direct_http")
    def test_29_manual_login_endpoint(self, mock_login):
        now = time.time()
        mock_login.return_value = {
            "access_token": "tok_manual_login",
            "refresh_token": "rt_manual",
            "expires_at": now + 3600,
            "student_code": "500086789",
            "cookies": {},
            "cookie_expires_at": now + 36000
        }
        self.cred_provider.save_credentials("admin", "500086789", "pwd")
        resp = self.client.post(
            "/api/upes/auth/login",
            headers={"Authorization": f"Bearer {self.admin_token}"}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["status"], "success")

    # 30. Manual refresh endpoint
    @patch.object(UpesAuthManager, "_refresh_direct_http")
    def test_30_manual_refresh_endpoint(self, mock_refresh):
        now = time.time()
        mock_refresh.return_value = {
            "access_token": "tok_manual_ref",
            "refresh_token": "rt_manual_ref",
            "expires_at": now + 3600,
            "student_code": "500086789",
            "cookies": {"idp_session_info": "cookie_val"},
            "cookie_expires_at": now + 30000
        }
        self.timetable_service.save_upes_session(
            user_id="admin",
            access_token="tok_old",
            student_code="500086789",
            expires_at=now + 50,
            refresh_token="rt_old",
            cookies={"idp_session_info": "cookie_val"},
            cookie_expires_at=now + 30000
        )
        resp = self.client.post(
            "/api/upes/auth/refresh",
            headers={"Authorization": f"Bearer {self.admin_token}"}
        )
        self.assertEqual(resp.status_code, 200)

    # 31-32. Logout behavior
    def test_31_and_32_logout_clears_runtime_preserves_credentials(self):
        now = time.time()
        self.cred_provider.save_credentials("admin", "500086789", "pwd")
        self.timetable_service.save_upes_session("admin", "tok_active", "500086789", expires_at=now + 3600)
        
        # Execute logout
        resp = self.client.post(
            "/api/upes/auth/logout",
            headers={"Authorization": f"Bearer {self.admin_token}"}
        )
        self.assertEqual(resp.status_code, 200)
        
        # Runtime session is deleted from auth manager / DB
        self.assertTrue(self.cred_provider.has_credentials("admin"))

    # 33. Delete credentials removes stored credential material
    def test_33_delete_credentials(self):
        self.cred_provider.save_credentials("admin", "500086789", "pwd")
        self.assertTrue(self.cred_provider.has_credentials("admin"))

        resp = self.client.delete(
            "/api/upes/auth/credentials",
            headers={"Authorization": f"Bearer {self.admin_token}"}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(self.cred_provider.has_credentials("admin"))

    # 34-35. Audit log contains no password or token
    def test_34_and_35_audit_log_never_contains_secrets(self):
        with patch("app.log_event") as mock_log:
            self.client.post(
                "/api/upes/auth/credentials",
                headers={"Authorization": f"Bearer {self.admin_token}"},
                json={"username": "500086789", "password": "super_secret_audit_pwd"}
            )
            for call in mock_log.call_args_list:
                log_text = str(call)
                self.assertNotIn("super_secret_audit_pwd", log_text)

    # 36. Simulated 10-hour expiry recovery
    @patch.object(UpesAuthManager, "_login_direct_http")
    def test_36_simulated_10_hour_expiry_recovery(self, mock_login):
        now = time.time()
        mock_login.return_value = {
            "access_token": "tok_gen2_10h_later",
            "refresh_token": "rt_gen2",
            "expires_at": now + 10 * 3600 + 3600,
            "student_code": "500086789",
            "cookies": {},
            "cookie_expires_at": now + 20 * 3600
        }
        self.cred_provider.save_credentials("admin", "500086789", "pwd")
        
        # State at T0: active session
        self.timetable_service.save_upes_session("admin", "tok_gen1", "500086789", expires_at=now + 3600)
        
        # State at T+10h: token expired, cookie expired
        self.timetable_service.save_upes_session(
            "admin",
            "tok_gen1",
            "500086789",
            expires_at=now - 10,
            cookie_expires_at=now - 10
        )
        
        # T+10h query triggers fresh direct-HTTP SSO login when forced
        tok, code, url, exp = self.auth_manager.ensure_authenticated("admin", force_login=True)
        self.assertEqual(tok, "tok_gen2_10h_later")
        mock_login.assert_called_once()

    # 37. 3-step OAuth redirect and token exchange flow
    @patch("requests.Session.post")
    @patch("requests.Session.get")
    def test_37_three_step_oauth_redirect_and_token_exchange(self, mock_get, mock_post):
        # Step 1: Form login returns StatusCode 200 and redirectUrl
        step1_resp = MagicMock()
        step1_resp.status_code = 200
        step1_resp.json.return_value = {
            "StatusCode": 200,
            "Item": {
                "redirectUrl": "https://myupes-beta.upes.ac.in/sso/oauth/authorize?client_id=1&state=xyz"
            }
        }

        # Step 2: GET redirectUrl returns code
        step2_resp = MagicMock()
        step2_resp.status_code = 200
        step2_resp.url = "https://myupes-beta.upes.ac.in/oneportal/app/auth/redirect-login?code=auth_code_999"
        step2_resp.history = []
        mock_get.return_value = step2_resp

        # Step 3: POST /oauth2/access_token with code returns tokens
        step3_resp = MagicMock()
        step3_resp.status_code = 200
        step3_resp.json.return_value = {
            "StatusCode": 200,
            "Item": {
                "AccessToken": "access_token_3step_live",
                "RefreshToken": "refresh_token_3step_live",
                "ExpiresIn": 3600,
                "UserInfo": {
                    "StudentCode": "500086789",
                    "EmailId": "student@stu.upes.ac.in"
                }
            }
        }

        mock_post.side_effect = [step1_resp, step3_resp]

        self.cred_provider.save_credentials("admin", "student@stu.upes.ac.in", "my_portal_password")
        tok, code, url, exp = self.auth_manager.ensure_authenticated("admin", force_login=True)

        self.assertEqual(tok, "access_token_3step_live")
        self.assertEqual(code, "500086789")
        self.assertEqual(mock_post.call_count, 2)
        mock_get.assert_called_once()

    # 38. HTTP 500 classified as UPSTREAM_ERROR / UPES_UNAVAILABLE (not INVALID_CREDENTIALS)
    @patch("requests.Session.post")
    def test_38_http_500_classified_as_upstream_error_not_invalid_credentials(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"
        mock_post.return_value = mock_resp

        self.cred_provider.save_credentials("admin", "student@stu.upes.ac.in", "my_portal_password")

        with self.assertRaises(AuthRequiredError) as ctx:
            self.auth_manager.ensure_authenticated("admin", force_login=True)

        self.assertIn("UPES_UNAVAILABLE", str(ctx.exception))
        self.assertNotIn("INVALID_CREDENTIALS", str(ctx.exception))
        self.assertEqual(self.auth_manager.circuit_breaker.last_failure_reason, AuthFailureReason.UPES_UNAVAILABLE)

    # 39. Security / CAPTCHA challenge classified as SECURITY_CHALLENGE
    @patch("requests.Session.post")
    def test_39_security_challenge_classified_as_interaction_required(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.json.return_value = {"errors": {"Captcha": "The Captcha field is required."}}
        mock_post.return_value = mock_resp

        self.cred_provider.save_credentials("admin", "student@stu.upes.ac.in", "my_portal_password")

        with self.assertRaises(SecurityChallengeError) as ctx:
            self.auth_manager.ensure_authenticated("admin", force_login=True)

        self.assertIn("challenge required", str(ctx.exception).lower())
        self.assertEqual(self.auth_manager.circuit_breaker.last_failure_reason, AuthFailureReason.SECURITY_CHALLENGE)


if __name__ == "__main__":
    unittest.main()

