"""
NexusNode — Phase 3.2D Zero-Touch UPES Authentication Unit Tests
Tests 5-layer domain separation, session crypto, single-flight refresh,
password minimization, endurance tracking, identity binding, and failure states.
"""

import time
import os
import tempfile
import sqlite3
import threading
import unittest
from unittest.mock import MagicMock, patch

import config
from agent.errors import (
    AuthRequiredError,
    SessionExpiredError,
    SecurityChallengeError,
    UpstreamError,
)
from upes.models import (
    IdentifierFormat,
    CredentialIdentity,
    AutonomyLevel,
    ResolvedStudentIdentity,
)
from upes.crypto import UpesSessionCrypto
from upes.credentials import UpesCredentialProvider, UpesCredentialCrypto, init_credential_tables
from upes.tracker import UpesEnduranceTracker, init_tracker_tables
from upes.session import UpesSessionTracker, UpesSessionState
from upes.auth import UpesAuthManager, AuthState, AuthFailureReason
from upes.router import UpesExecutionRouter


class TestUpesZeroTouchAuth(unittest.TestCase):

    def setUp(self):
        # Create temp SQLite file for connection factory isolation
        self.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        self.temp_db.close()
        self.db_path = self.temp_db.name

        self.conn_factory = lambda: sqlite3.connect(self.db_path)
        
        # Initialize tables
        conn = self.conn_factory()
        init_credential_tables(conn)
        init_tracker_tables(conn)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS upes_auth_sessions (
                user_id TEXT PRIMARY KEY,
                encrypted_access_token TEXT,
                student_code TEXT,
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
        self.tracker = UpesEnduranceTracker(self.conn_factory)
        self.auth_manager = UpesAuthManager(
            conn_factory=self.conn_factory,
            credential_provider=self.cred_provider,
            session_tracker=self.session_tracker,
            tracker=self.tracker
        )

    def tearDown(self):
        try:
            os.remove(self.db_path)
        except OSError:
            pass

    # --------------------------------------------------------------------------
    # 1. Cryptographic Domain Separation
    # --------------------------------------------------------------------------
    def test_01_session_crypto_domain_separation_and_tamper_resistance(self):
        sample_session = {"access_token": "valid_token_xyz", "scope": "openid"}
        sample_creds = {"username": "user@stu.upes.ac.in", "password": "secret_password"}

        # Encrypt session using UpesSessionCrypto
        enc_session = UpesSessionCrypto.encrypt(sample_session)
        self.assertIsInstance(enc_session, str)
        self.assertNotIn("valid_token_xyz", enc_session)

        # Decrypt session using UpesSessionCrypto -> Success
        dec_session = UpesSessionCrypto.decrypt(enc_session)
        self.assertIsNotNone(dec_session)
        self.assertEqual(dec_session["access_token"], "valid_token_xyz")
        self.assertEqual(dec_session["domain"], "nexusnode/upes/session/v1")

        # Encrypt credentials using UpesCredentialCrypto
        enc_creds = UpesCredentialCrypto.encrypt(sample_creds)
        self.assertNotIn("secret_password", enc_creds)

        # Cross-Domain Isolation:
        # 1. UpesSessionCrypto CANNOT decrypt UpesCredentialCrypto ciphertexts
        self.assertIsNone(UpesSessionCrypto.decrypt(enc_creds))

        # 2. UpesCredentialCrypto CANNOT decrypt UpesSessionCrypto ciphertexts
        self.assertIsNone(UpesCredentialCrypto.decrypt(enc_session))

    # --------------------------------------------------------------------------
    # 2. Safe Credential Identity (No Secrets)
    # --------------------------------------------------------------------------
    def test_02_credential_identity_contains_no_encrypted_passwords(self):
        self.cred_provider.save_credentials("admin", "ANMOL.11794@stu.upes.ac.in", "my_real_password_123")
        identity = self.cred_provider.get_credential_identity("admin")
        status = self.cred_provider.get_credential_status("admin")

        # Verify identity model has no password fields
        self.assertFalse(hasattr(identity, "password"))
        self.assertFalse(hasattr(identity, "encrypted_password"))
        self.assertEqual(identity.configured_format, IdentifierFormat.FULL_EMAIL)
        self.assertEqual(identity.expected_format, IdentifierFormat.FULL_EMAIL)
        self.assertFalse(identity.mismatch)

        # Verify status dictionary NEVER leaks plaintext or encrypted password
        self.assertNotIn("my_real_password_123", str(status))
        self.assertNotIn("encrypted_credentials", status)
        self.assertTrue(status["has_stored_credentials"])

    # --------------------------------------------------------------------------
    # 3. Safe Identifier Format Detection & Mismatch Reporting
    # --------------------------------------------------------------------------
    def test_03_safe_identifier_format_detection_and_mismatch(self):
        # Case A: Full Email
        id_email = CredentialIdentity.from_hint_or_username("user1", "ANMOL.11794@stu.upes.ac.in")
        self.assertEqual(id_email.configured_format, IdentifierFormat.FULL_EMAIL)
        self.assertFalse(id_email.mismatch)

        # Case B: Numeric SAP ID
        id_sap = CredentialIdentity.from_hint_or_username("user2", "590011794")
        self.assertEqual(id_sap.configured_format, IdentifierFormat.NUMERIC_SAP_ID)
        self.assertTrue(id_sap.mismatch)

        # Case C: Unknown / Short
        id_unk = CredentialIdentity.from_hint_or_username("user3", "admin")
        self.assertEqual(id_unk.configured_format, IdentifierFormat.UNKNOWN)
        self.assertFalse(id_unk.mismatch)

    # --------------------------------------------------------------------------
    # 4. Import Authenticated Context & Identity Binding
    # --------------------------------------------------------------------------
    @patch("requests.get")
    def test_04_import_authenticated_context_validates_profile_and_persists(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "StatusCode": 200,
            "Items": [{
                "StudentId": "3a678d8e-8817-41e6-b1a8-5a3ec6ee4948",
                "GlobalId": "590011794",
                "UserId": 30054,
                "EmailId": "ANMOL.11794@stu.upes.ac.in",
                "FirstName": "ANMOL",
                "LastName": "SINGH",
                "CampusCode": "UPES",
                "CourseCode": "BTECH"
            }]
        }
        mock_get.return_value = mock_resp

        now = time.time()
        res = self.auth_manager.import_authenticated_context(
            user_id="admin",
            access_token="valid_test_access_jwt",
            refresh_token="valid_test_refresh_token",
            cookies={"idp_session_info": "session_uuid_123"},
            expires_at=now + 624597.0,
            cookie_expires_at=now + 36000.0
        )

        self.assertEqual(res["status"], "AUTHENTICATED")
        self.assertNotIn("valid_test_access_jwt", str(res))
        self.assertNotIn("valid_test_refresh_token", str(res))
        self.assertIn("3a67***4948", res["identity"]["student_id_masked"])

        # Check session status in database
        status = self.session_tracker.get_safe_status("admin")
        self.assertTrue(status["configured"])
        self.assertEqual(status["state"], "AUTHENTICATED")
        self.assertTrue(status["is_live_ready"])

    # --------------------------------------------------------------------------
    # 5. Import Expired Token Rejection
    # --------------------------------------------------------------------------
    def test_05_import_expired_token_rejected(self):
        now = time.time()
        with self.assertRaises(AuthRequiredError):
            self.auth_manager.import_authenticated_context(
                user_id="admin",
                access_token="expired_token_abc",
                expires_at=now - 3600.0
            )

    # --------------------------------------------------------------------------
    # 6. Import Identity Mismatch Rejection
    # --------------------------------------------------------------------------
    @patch("requests.get")
    def test_06_import_mismatched_student_identity_rejected(self, mock_get):
        # Configure credentials for student A
        self.cred_provider.save_credentials("admin", "ANMOL.11794@stu.upes.ac.in", "pw123")

        # Mock profile returning student B
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "StatusCode": 200,
            "Items": [{
                "StudentId": "99999999-8817-41e6-b1a8-5a3ec6ee4948",
                "GlobalId": "500099999",
                "UserId": 99999,
                "EmailId": "OTHER.STUDENT@stu.upes.ac.in",
                "FirstName": "OTHER",
                "LastName": "STUDENT"
            }]
        }
        mock_get.return_value = mock_resp

        now = time.time()
        with self.assertRaises(AuthRequiredError) as cm:
            self.auth_manager.import_authenticated_context(
                user_id="admin",
                access_token="valid_other_token",
                expires_at=now + 3600.0
            )
        self.assertIn("does not match configured", str(cm.exception))

    # --------------------------------------------------------------------------
    # 7. Valid OAuth Token Never Invokes Password Provider
    # --------------------------------------------------------------------------
    def test_07_valid_oauth_token_never_invokes_password_provider(self):
        now = time.time()
        # Seed an active OAuth session
        self.auth_manager._save_session_atomic(
            user_id="admin",
            access_token="active_jwt_token",
            student_code="3a678d8e-8817-41e6-b1a8-5a3ec6ee4948",
            expires_at=now + 100000.0
        )

        # Mock credential_provider to fail test if get_credentials is ever called
        self.cred_provider.get_credentials = MagicMock(side_effect=AssertionError("Password provider MUST NOT be called for valid OAuth token!"))

        tok, code, url, exp = self.auth_manager.ensure_authenticated("admin")
        self.assertEqual(tok, "active_jwt_token")
        self.assertEqual(code, "3a678d8e-8817-41e6-b1a8-5a3ec6ee4948")
        self.cred_provider.get_credentials.assert_not_called()

    # --------------------------------------------------------------------------
    # 8. Single-Flight Token Refresh Serialization
    # --------------------------------------------------------------------------
    def test_08_single_flight_refresh_serialization(self):
        now = time.time()
        # Seed an expiring session that triggers refresh
        self.auth_manager._save_session_atomic(
            user_id="admin",
            access_token="expiring_token",
            student_code="student_uuid",
            expires_at=now + 100.0,  # Within margin
            refresh_token="refresh_tok_1",
            cookies={"idp_session_info": "idp_cookie"},
            cookie_expires_at=now + 36000.0,
            credential_generation=1
        )

        refresh_call_count = 0
        def fake_refresh(refresh_token, cookies):
            nonlocal refresh_call_count
            refresh_call_count += 1
            time.sleep(0.05)  # Simulate network latency
            return {
                "access_token": f"new_token_gen_{refresh_call_count}",
                "refresh_token": f"new_refresh_gen_{refresh_call_count}",
                "expires_at": time.time() + 624597.0,
                "cookies": cookies,
                "cookie_expires_at": None,
                "student_code": "student_uuid"
            }

        self.auth_manager._refresh_direct_http = MagicMock(side_effect=fake_refresh)

        results = []
        def caller():
            tok, code, url, exp = self.auth_manager.ensure_authenticated("admin")
            results.append(tok)

        threads = [threading.Thread(target=caller) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Exactly ONE refresh executed across all 5 threads
        self.assertEqual(refresh_call_count, 1)
        self.assertEqual(len(results), 5)
        self.assertTrue(all(r == results[0] for r in results))

    # --------------------------------------------------------------------------
    # 9. Proactive Refresh and Generation Progression
    # --------------------------------------------------------------------------
    def test_09_proactive_refresh_and_generation_progression(self):
        now = time.time()
        self.auth_manager._save_session_atomic(
            user_id="admin",
            access_token="old_access_token",
            student_code="student_uuid",
            expires_at=now + 100.0,
            refresh_token="gen1_refresh_token",
            cookies={"idp_session_info": "session_cookie"},
            cookie_expires_at=now + 36000.0,
            credential_generation=1
        )

        self.auth_manager._refresh_direct_http = MagicMock(return_value={
            "access_token": "gen2_access_token",
            "refresh_token": "gen2_refresh_token",
            "expires_at": now + 624597.0,
            "cookies": {"idp_session_info": "session_cookie"},
            "cookie_expires_at": now + 36000.0,
            "student_code": "student_uuid"
        })

        tok, code, url, exp = self.auth_manager.ensure_authenticated("admin")
        self.assertEqual(tok, "gen2_access_token")

        # Verify generation progressed to 2
        status = self.session_tracker.get_safe_status("admin")
        self.assertEqual(status["credential_generation"], 2)

    # --------------------------------------------------------------------------
    # 10. Refresh Does NOT Invoke Password Provider
    # --------------------------------------------------------------------------
    def test_10_refresh_does_not_invoke_password_provider(self):
        now = time.time()
        self.auth_manager._save_session_atomic(
            user_id="admin",
            access_token="expiring_token",
            student_code="student_uuid",
            expires_at=now + 100.0,
            refresh_token="refresh_token_1",
            credential_generation=1
        )

        self.auth_manager._refresh_direct_http = MagicMock(return_value={
            "access_token": "refreshed_access_token",
            "refresh_token": "refreshed_refresh_token",
            "expires_at": now + 624597.0,
            "cookies": {},
            "cookie_expires_at": None,
            "student_code": "student_uuid"
        })

        self.cred_provider.get_credentials = MagicMock(side_effect=AssertionError("Password provider MUST NOT be called during refresh!"))

        tok, code, url, exp = self.auth_manager.ensure_authenticated("admin")
        self.assertEqual(tok, "refreshed_access_token")
        self.cred_provider.get_credentials.assert_not_called()

    # --------------------------------------------------------------------------
    # 11. Refresh Network Error Preserves Valid Session
    # --------------------------------------------------------------------------
    def test_11_refresh_network_error_preserves_valid_session(self):
        import requests
        now = time.time()
        self.auth_manager._save_session_atomic(
            user_id="admin",
            access_token="valid_current_token",
            student_code="student_uuid",
            expires_at=now + 100.0,
            refresh_token="refresh_token_xyz",
            credential_generation=1
        )

        # Simulate network error on refresh
        self.auth_manager._refresh_direct_http = MagicMock(
            side_effect=requests.exceptions.ConnectionError("Connection to UPES timed out")
        )

        with self.assertRaises(AuthRequiredError) as cm:
            self.auth_manager.ensure_authenticated("admin")
        self.assertIn("NETWORK_ERROR", str(cm.exception))

        # Verify session was NOT wiped
        bundle = self.auth_manager._load_session_bundle("admin")
        self.assertIsNotNone(bundle)
        self.assertEqual(bundle["access_token"], "valid_current_token")

    # --------------------------------------------------------------------------
    # 12. AUTH_EXHAUSTED Does NOT Automatically Fall Back to Password Login
    # --------------------------------------------------------------------------
    def test_12_auth_exhausted_does_not_automatically_call_password_login(self):
        now = time.time()
        # Expired session with dead refresh token
        self.auth_manager._save_session_atomic(
            user_id="admin",
            access_token="expired_token",
            student_code="student_uuid",
            expires_at=now - 500.0,
            refresh_token="rejected_refresh_token",
            credential_generation=1
        )

        # Refresh is rejected by upstream
        self.auth_manager._refresh_direct_http = MagicMock(
            side_effect=SessionExpiredError("failed to generate refresh token")
        )

        # Spy on get_credentials to ensure password login is NOT automatically attempted
        self.cred_provider.get_credentials = MagicMock(side_effect=AssertionError("Password provider MUST NOT be called on AUTH_EXHAUSTED!"))

        with self.assertRaises(AuthRequiredError) as cm:
            self.auth_manager.ensure_authenticated("admin")
        
        self.assertIn("exhausted", str(cm.exception).lower())
        self.cred_provider.get_credentials.assert_not_called()

        # Check status reflects AUTH_EXHAUSTED
        status = self.auth_manager.get_status("admin")
        self.assertEqual(status["state"], AuthState.AUTH_EXHAUSTED.value)

    # --------------------------------------------------------------------------
    # 13. Endurance Tracker Metrics & Zero Secret Leakage
    # --------------------------------------------------------------------------
    def test_13_endurance_tracker_metrics_and_zero_secret_leakage(self):
        now = time.time()
        self.tracker.record_import("admin", generation=1, access_expires_at=now + 624597.0, idp_cookie_expires_at=now + 36000.0)
        self.tracker.record_live_api_success("admin")
        self.tracker.record_refresh_success("admin", new_generation=2, new_access_expires_at=now + 624597.0, idp_expired_at_refresh=False)

        metrics = self.tracker.get_safe_metrics("admin")
        self.assertTrue(metrics["tracking_active"])
        self.assertEqual(metrics["current_generation"], 2)
        self.assertEqual(metrics["generation_count"], 2)
        self.assertEqual(metrics["refresh_count"], 1)
        self.assertIsNotNone(metrics["last_live_api_success"])

        # String representation checks: NO secret leakage
        s = str(metrics)
        self.assertNotIn("token", s.lower())
        self.assertNotIn("password", s.lower())
        self.assertNotIn("cookie", s.lower().replace("cookie_expires_at", "").replace("cookie_ttl_seconds", ""))

    # --------------------------------------------------------------------------
    # 14. Autonomy Level Calculation
    # --------------------------------------------------------------------------
    def test_14_autonomy_level_calculation(self):
        now = time.time()
        self.tracker.record_import("admin", generation=1, access_expires_at=now + 624597.0)
        m1 = self.tracker.get_safe_metrics("admin")
        self.assertEqual(m1["autonomy_level"], AutonomyLevel.LEVEL_1_TOKEN_ONLY.value)

        # Level 2: Refresh with active IdP
        self.tracker.record_refresh_success("admin", new_generation=2, new_access_expires_at=now + 624597.0, idp_expired_at_refresh=False)
        m2 = self.tracker.get_safe_metrics("admin")
        self.assertEqual(m2["autonomy_level"], AutonomyLevel.LEVEL_2_IDP_REFRESH.value)

        # Level 3: Refresh after IdP expiry
        self.tracker.record_refresh_success("admin", new_generation=3, new_access_expires_at=now + 624597.0, idp_expired_at_refresh=True)
        m3 = self.tracker.get_safe_metrics("admin")
        self.assertEqual(m3["autonomy_level"], AutonomyLevel.LEVEL_3_INDEPENDENT_REFRESH.value)

        # Level 4: Refresh after IdP expiry + service restart + device reboot
        self.tracker.record_service_restart("admin")
        self.tracker.record_device_reboot("admin")
        self.tracker.record_refresh_success("admin", new_generation=4, new_access_expires_at=now + 624597.0, idp_expired_at_refresh=True)
        m4 = self.tracker.get_safe_metrics("admin")
        self.assertEqual(m4["autonomy_level"], AutonomyLevel.LEVEL_4_RESTART_SURVIVED.value)

    # --------------------------------------------------------------------------
    # 15. Service Restart Reloads Encrypted Session
    # --------------------------------------------------------------------------
    def test_15_service_restart_reloads_encrypted_session(self):
        now = time.time()
        self.auth_manager._save_session_atomic(
            user_id="admin",
            access_token="restart_persisted_token",
            student_code="student_uuid_reboot",
            expires_at=now + 500000.0
        )

        # Instantiate a completely new AuthManager pointing to same DB (simulating process restart)
        new_auth_manager = UpesAuthManager(
            conn_factory=self.conn_factory,
            credential_provider=self.cred_provider,
            session_tracker=UpesSessionTracker(self.conn_factory),
            tracker=UpesEnduranceTracker(self.conn_factory)
        )

        tok, code, url, exp = new_auth_manager.ensure_authenticated("admin")
        self.assertEqual(tok, "restart_persisted_token")
        self.assertEqual(code, "student_uuid_reboot")

    # --------------------------------------------------------------------------
    # 16. Transactional Atomic Session Persistence
    # --------------------------------------------------------------------------
    def test_16_transactional_atomic_session_persistence(self):
        now = time.time()
        self.auth_manager._save_session_atomic(
            user_id="admin",
            access_token="atomic_token_1",
            student_code="uuid_1",
            expires_at=now + 600000.0,
            credential_generation=1,
            last_refresh_status="initial"
        )

        bundle1 = self.auth_manager._load_session_bundle("admin")
        self.assertEqual(bundle1["access_token"], "atomic_token_1")
        self.assertEqual(bundle1["credential_generation"], 1)

        # Overwrite with generation 2
        self.auth_manager._save_session_atomic(
            user_id="admin",
            access_token="atomic_token_2",
            student_code="uuid_1",
            expires_at=now + 624597.0,
            credential_generation=2,
            last_refresh_status="gen2_saved"
        )

        bundle2 = self.auth_manager._load_session_bundle("admin")
        self.assertEqual(bundle2["access_token"], "atomic_token_2")
        self.assertEqual(bundle2["credential_generation"], 2)

    # --------------------------------------------------------------------------
    # 17. Event Emission Lifecycle
    # --------------------------------------------------------------------------
    def test_17_event_emission_lifecycle(self):
        events = []
        self.auth_manager.add_event_listener(lambda ev, data: events.append((ev, data)))

        now = time.time()
        self.auth_manager._save_session_atomic(
            user_id="admin",
            access_token="old_token",
            expires_at=now + 50.0,
            refresh_token="ref_token"
        )

        self.auth_manager._refresh_direct_http = MagicMock(return_value={
            "access_token": "new_refreshed_tok",
            "expires_at": now + 624597.0,
            "student_code": "uuid_ev"
        })

        self.auth_manager.ensure_authenticated("admin")

        event_names = [e[0] for e in events]
        self.assertIn("upes.refresh_started", event_names)
        self.assertIn("upes.refresh_succeeded", event_names)

    # --------------------------------------------------------------------------
    # 18. Direct-HTTP Login CAPTCHA Challenge Classification
    # --------------------------------------------------------------------------
    @patch("requests.Session.post")
    def test_18_direct_http_login_captcha_challenge_classification(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.json.return_value = {
            "type": "https://tools.ietf.org/html/rfc7231#section-6.5.1",
            "title": "One or more validation errors occurred.",
            "status": 400,
            "errors": {"Captcha": ["The Captcha field is required."]}
        }
        mock_post.return_value = mock_resp

        with self.assertRaises(SecurityChallengeError):
            self.auth_manager._login_direct_http("user", "pass")

    # --------------------------------------------------------------------------
    # 19. Circuit Breaker Resets on Successful Import
    # --------------------------------------------------------------------------
    @patch("requests.get")
    def test_19_circuit_breaker_resets_on_successful_import(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "StatusCode": 200,
            "Items": [{
                "StudentId": "3a678d8e-8817-41e6-b1a8-5a3ec6ee4948",
                "GlobalId": "590011794",
                "UserId": 30054,
                "EmailId": "ANMOL.11794@stu.upes.ac.in",
                "FirstName": "ANMOL",
                "LastName": "SINGH"
            }]
        }
        mock_get.return_value = mock_resp

        # Trip circuit breaker
        self.auth_manager.circuit_breaker.record_failure(AuthFailureReason.SECURITY_CHALLENGE)
        is_open, reason, _ = self.auth_manager.circuit_breaker.is_open()
        self.assertTrue(is_open)

        # Import session
        self.auth_manager.import_authenticated_context(
            user_id="admin",
            access_token="valid_jwt",
            expires_at=time.time() + 624597.0
        )

        # Circuit breaker should now be closed
        is_open_after, _, _ = self.auth_manager.circuit_breaker.is_open()
        self.assertFalse(is_open_after)

    # --------------------------------------------------------------------------
    # 20. Router Execution with Imported OAuth Session
    # --------------------------------------------------------------------------
    def test_20_router_execution_with_imported_oauth_session(self):
        now = time.time()
        self.auth_manager._save_session_atomic(
            user_id="admin",
            access_token="live_jwt_token",
            student_code="3a678d8e-8817-41e6-b1a8-5a3ec6ee4948",
            expires_at=now + 624597.0
        )

        mock_attendance_service = MagicMock()
        mock_attendance_service.get_attendance_analytics.return_value = {
            "has_data": True,
            "last_synced_at": now,
            "overall_percentage": 88.5
        }

        router = UpesExecutionRouter(
            conn_factory=self.conn_factory,
            attendance_service=mock_attendance_service,
            session_tracker=self.session_tracker,
            auth_manager=self.auth_manager
        )

        res = router.execute("upes.get_attendance", user_id="admin")
        self.assertTrue(res.ok)
        self.assertEqual(res.source, "live")
        self.assertFalse(res.stale)
        self.assertEqual(res.data["overall_percentage"], 88.5)


if __name__ == "__main__":
    unittest.main()
