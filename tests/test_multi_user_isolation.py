"""
NexusNode — Multi-User Tenant Isolation & IDOR Defense Test Suite
Phase 3.7B: Multi-User Self-Service Security Foundation

Verifies strict tenant isolation across:
1. UPES Credential Storage, Cryptographic Domain Separation & Identifier Validation
2. Timetable Sessions, Uploads, Event Mapping & Distributed Locks
3. Attendance Summaries, Ledgers & Manual Punches
4. Google OAuth State Tokens, Session Binding & Calendar Selection
5. Background Multi-Tenant Scheduler Isolation
6. Explicit Admin Route Access Control (Admin allowed, regular user rejected)
"""

import base64
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
from upes.credentials import UpesCredentialProvider, UpesCredentialCrypto
from upes.models import IdentifierFormat


class MultiUserIsolationBaseTestCase(unittest.TestCase):
    def setUp(self):
        # Create isolated temporary database
        self.test_dir = tempfile.mkdtemp(prefix="nexus_multiuser_test_")
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

        # Initialize schema
        self.init_db()

        # Initialize services
        self.timetable_service = timetable_sync.TimetableService(conn_factory=lambda: sqlite3.connect(self.db_path))
        self.attendance_service = attendance_sync.AttendanceService(conn_factory=lambda: sqlite3.connect(self.db_path))
        self.credential_provider = UpesCredentialProvider(conn_factory=lambda: sqlite3.connect(self.db_path))

        nexus_app.timetable_service = self.timetable_service
        nexus_app.attendance_service = self.attendance_service
        nexus_app.upes_credential_provider = self.credential_provider

        # Setup Flask test client
        nexus_app.app.config["TESTING"] = True
        self.client = nexus_app.app.test_client()

        # Setup synthetic sessions
        self.token_user_a = "token_user_a_" + secrets.token_hex(16)
        self.token_user_b = "token_user_b_" + secrets.token_hex(16)
        self.token_admin = "token_admin_" + secrets.token_hex(16)

        with nexus_app.SESSIONS_LOCK:
            nexus_app.SESSIONS[self.token_user_a] = {
                "user_id": "user_a",
                "username": "user_a",
                "role": "user",
                "privileges": {"can_sync_timetable": True, "can_view_lms": True},
                "expires_at": time.time() + 3600,
                "is_disabled": 0
            }
            nexus_app.SESSIONS[self.token_user_b] = {
                "user_id": "user_b",
                "username": "user_b",
                "role": "user",
                "privileges": {"can_sync_timetable": True, "can_view_lms": True},
                "expires_at": time.time() + 3600,
                "is_disabled": 0
            }
            nexus_app.SESSIONS[self.token_admin] = {
                "user_id": "admin",
                "username": "admin",
                "role": "admin",
                "privileges": {"can_sync_timetable": True, "can_view_lms": True, "can_manage_settings": True},
                "expires_at": time.time() + 3600,
                "is_disabled": 0
            }

    def tearDown(self):
        with nexus_app.SESSIONS_LOCK:
            nexus_app.SESSIONS.pop(self.token_user_a, None)
            nexus_app.SESSIONS.pop(self.token_user_b, None)
            nexus_app.SESSIONS.pop(self.token_admin, None)

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


class TestMultiUserCredentialIsolation(MultiUserIsolationBaseTestCase):
    """Tests IDOR defense and tenant isolation on UPES credentials."""

    def test_credential_storage_and_read_isolation(self):
        # Save credentials for user_a and user_b
        self.credential_provider.save_credentials("user_a", "alice.59001@stu.upes.ac.in", "AlicePass123!")
        self.credential_provider.save_credentials("user_b", "bob.59002@stu.upes.ac.in", "BobPass456!")

        # User A reads status
        resp_a = self.client.get(
            "/api/upes/auth/credentials/status",
            headers={"Authorization": f"Bearer {self.token_user_a}"}
        )
        self.assertEqual(resp_a.status_code, 200)
        data_a = resp_a.get_json()["credentials"]
        self.assertTrue(data_a["configured"])
        self.assertTrue(data_a["username_hint"].startswith("ali***@stu.upes.ac.in") or "alice" in data_a["username_hint"] or "@" in data_a["username_hint"])

        # User B reads status
        resp_b = self.client.get(
            "/api/upes/auth/credentials/status",
            headers={"Authorization": f"Bearer {self.token_user_b}"}
        )
        self.assertEqual(resp_b.status_code, 200)
        data_b = resp_b.get_json()["credentials"]
        self.assertTrue(data_b["configured"])
        self.assertTrue(data_b["username_hint"].startswith("bob***@stu.upes.ac.in") or "bob" in data_b["username_hint"] or "@" in data_b["username_hint"])

    def test_cross_tenant_query_override_rejected(self):
        # User A attempts to inspect User B credentials via ?user_id=user_b
        resp = self.client.get(
            "/api/upes/auth/credentials/status?user_id=user_b",
            headers={"Authorization": f"Bearer {self.token_user_a}"}
        )
        self.assertEqual(resp.status_code, 403)
        self.assertIn("Cross-tenant access forbidden", resp.get_json()["message"])

    def test_cross_tenant_body_override_rejected(self):
        # User A attempts to overwrite User B credentials via JSON body
        resp = self.client.post(
            "/api/upes/auth/credentials",
            headers={"Authorization": f"Bearer {self.token_user_a}"},
            json={
                "user_id": "user_b",
                "username": "hacked.59002@stu.upes.ac.in",
                "password": "HackedPassword123!"
            }
        )
        self.assertEqual(resp.status_code, 403)
        self.assertIn("Cross-tenant access forbidden", resp.get_json()["message"])

    def test_cross_tenant_credential_deletion_rejected(self):
        self.credential_provider.save_credentials("user_b", "bob.59002@stu.upes.ac.in", "BobPass456!")

        # User A attempts to delete User B credentials
        resp = self.client.delete(
            "/api/upes/auth/credentials?user_id=user_b",
            headers={"Authorization": f"Bearer {self.token_user_a}"}
        )
        self.assertEqual(resp.status_code, 403)

        # Confirm user_b credentials remain untouched
        b_creds = self.credential_provider.get_credentials("user_b")
        self.assertIsNotNone(b_creds)
        self.assertEqual(b_creds[0], "bob.59002@stu.upes.ac.in")

    def test_identifier_format_full_email_enforcement(self):
        # Submitting numeric SAP ID must be rejected with HTTP 400
        resp_numeric = self.client.post(
            "/api/upes/auth/credentials",
            headers={"Authorization": f"Bearer {self.token_user_a}"},
            json={
                "username": "590011794",
                "password": "ValidPassword123!"
            }
        )
        self.assertEqual(resp_numeric.status_code, 400)
        data = resp_numeric.get_json()
        self.assertEqual(data["error"], "invalid_identifier_format")
        self.assertIn("institutional student email", data["message"])

        # Submitting valid institutional email must succeed
        resp_email = self.client.post(
            "/api/upes/auth/credentials",
            headers={"Authorization": f"Bearer {self.token_user_a}"},
            json={
                "username": "alice.590011794@stu.upes.ac.in",
                "password": "ValidPassword123!"
            }
        )
        self.assertEqual(resp_email.status_code, 200)
        self.assertEqual(resp_email.get_json()["status"], "success")

    def test_cryptographic_domain_separation(self):
        enc_blob = UpesCredentialCrypto.encrypt({"username": "alice@stu.upes.ac.in", "password": "SecretPass123!"})
        decrypted = UpesCredentialCrypto.decrypt(enc_blob)
        self.assertIsNotNone(decrypted)
        self.assertEqual(decrypted["username"], "alice@stu.upes.ac.in")
        self.assertEqual(decrypted["password"], "SecretPass123!")
        self.assertEqual(decrypted["domain"], "nexusnode/upes/credentials/v1")


class TestMultiUserTimetableIsolation(MultiUserIsolationBaseTestCase):
    """Tests IDOR defense and tenant isolation on Timetable endpoints."""

    def test_timetable_session_read_isolation(self):
        # Upload timetable for User A (Physics on Monday)
        tt_a = [
            {
                "date": "2026-09-07",
                "start_time": "09:00",
                "end_time": "10:00",
                "course_name": "Applied Physics",
                "course_code": "PHYS101",
                "faculty": "Dr. Raman",
                "room": "R101",
                "session_id": "sess_phys_1"
            }
        ]
        self.timetable_service.upload_timetable("user_a", json.dumps(tt_a))

        # Upload timetable for User B (Chemistry on Tuesday)
        tt_b = [
            {
                "date": "2026-09-08",
                "start_time": "10:00",
                "end_time": "11:00",
                "course_name": "Organic Chemistry",
                "course_code": "CHEM101",
                "faculty": "Dr. Curie",
                "room": "R202",
                "session_id": "sess_chem_1"
            }
        ]
        self.timetable_service.upload_timetable("user_b", json.dumps(tt_b))

        # User A reads timetable sessions -> gets only Physics
        resp_a = self.client.get(
            "/api/timetable/sessions",
            headers={"Authorization": f"Bearer {self.token_user_a}"}
        )
        self.assertEqual(resp_a.status_code, 200)
        data_a = resp_a.get_json()
        self.assertEqual(data_a["total_sessions"], 1)
        self.assertEqual(data_a["sessions"][0]["course_code"], "PHYS101")

        # User B reads timetable sessions -> gets only Chemistry
        resp_b = self.client.get(
            "/api/timetable/sessions",
            headers={"Authorization": f"Bearer {self.token_user_b}"}
        )
        self.assertEqual(resp_b.status_code, 200)
        data_b = resp_b.get_json()
        self.assertEqual(data_b["total_sessions"], 1)
        self.assertEqual(data_b["sessions"][0]["course_code"], "CHEM101")

    def test_cross_tenant_timetable_sessions_override_rejected(self):
        resp = self.client.get(
            "/api/timetable/sessions?user_id=user_b",
            headers={"Authorization": f"Bearer {self.token_user_a}"}
        )
        self.assertEqual(resp.status_code, 403)
        self.assertIn("Cross-tenant access forbidden", resp.get_json()["message"])

    def test_cross_tenant_timetable_sync_override_rejected(self):
        resp = self.client.post(
            "/api/timetable/sync",
            headers={"Authorization": f"Bearer {self.token_user_a}"},
            json={"user_id": "user_b"}
        )
        self.assertEqual(resp.status_code, 403)
        self.assertIn("Cross-tenant access forbidden", resp.get_json()["message"])

    def test_timetable_events_map_compound_key_isolation(self):
        # Insert mappings for both users with the exact same slot ID and date
        conn = sqlite3.connect(self.db_path)
        with conn:
            conn.execute("""
                INSERT INTO timetable_events_map (id, user_id, source_session_id, source_date, google_calendar_id, google_event_id, source_hash, status, last_synced_at)
                VALUES ('user_a:slot_100:2026-09-07', 'user_a', 'slot_100', '2026-09-07', 'primary', 'g_event_alice', 'hash_a', 'synced', 1000.0),
                       ('user_b:slot_100:2026-09-07', 'user_b', 'slot_100', '2026-09-07', 'primary', 'g_event_bob', 'hash_b', 'synced', 1000.0)
            """)
        conn.close()

        # Query user_a mappings
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT google_event_id FROM timetable_events_map WHERE user_id = ?", ("user_a",))
        rows_a = cur.fetchall()
        self.assertEqual(len(rows_a), 1)
        self.assertEqual(rows_a[0][0], "g_event_alice")

        cur.execute("SELECT google_event_id FROM timetable_events_map WHERE user_id = ?", ("user_b",))
        rows_b = cur.fetchall()
        self.assertEqual(len(rows_b), 1)
        self.assertEqual(rows_b[0][0], "g_event_bob")
        conn.close()

    def test_per_tenant_sync_lock_isolation(self):
        # User A acquires lock
        lock_a = timetable_sync.DatabaseSyncLease(conn_factory=lambda: sqlite3.connect(self.db_path), user_id="user_a", timeout_seconds=60)
        acquired_a = lock_a.acquire()
        self.assertTrue(acquired_a)

        # User B simultaneously acquires lock for User B -> MUST succeed (no cross-tenant blocking)
        lock_b = timetable_sync.DatabaseSyncLease(conn_factory=lambda: sqlite3.connect(self.db_path), user_id="user_b", timeout_seconds=60)
        acquired_b = lock_b.acquire()
        self.assertTrue(acquired_b)

        # Attempting second lock for User A -> MUST fail
        lock_a_dup = timetable_sync.DatabaseSyncLease(conn_factory=lambda: sqlite3.connect(self.db_path), user_id="user_a", timeout_seconds=60)
        self.assertFalse(lock_a_dup.acquire())

        lock_a.release()
        lock_b.release()


class TestMultiUserAttendanceIsolation(MultiUserIsolationBaseTestCase):
    """Tests IDOR defense and tenant isolation on Attendance records."""

    def test_attendance_punches_isolation(self):
        # Record punch for user_a
        self.timetable_service.record_punch(
            user_id="user_a",
            course_name="Data Structures",
            course_code="CS201",
            punch_date="2026-09-01",
            punch_time="09:15:00",
            status="present"
        )

        # Record punch for user_b
        self.timetable_service.record_punch(
            user_id="user_b",
            course_name="Operating Systems",
            course_code="CS202",
            punch_date="2026-09-01",
            punch_time="10:15:00",
            status="present"
        )

        # User A reads punches
        resp_a = self.client.get(
            "/api/attendance/punches",
            headers={"Authorization": f"Bearer {self.token_user_a}"}
        )
        self.assertEqual(resp_a.status_code, 200)
        punches_a = resp_a.get_json()["punches"]
        self.assertEqual(len(punches_a), 1)
        self.assertEqual(punches_a[0]["course_code"], "CS201")

        # User B reads punches
        resp_b = self.client.get(
            "/api/attendance/punches",
            headers={"Authorization": f"Bearer {self.token_user_b}"}
        )
        self.assertEqual(resp_b.status_code, 200)
        punches_b = resp_b.get_json()["punches"]
        self.assertEqual(len(punches_b), 1)
        self.assertEqual(punches_b[0]["course_code"], "CS202")

    def test_cross_tenant_punch_override_rejected(self):
        resp = self.client.post(
            "/api/attendance/punch",
            headers={"Authorization": f"Bearer {self.token_user_a}"},
            json={
                "user_id": "user_b",
                "course_code": "CS999",
                "course_name": "Malicious Punch"
            }
        )
        self.assertEqual(resp.status_code, 403)
        self.assertIn("Cross-tenant access forbidden", resp.get_json()["message"])

    def test_attendance_punch_delete_isolation(self):
        # User B records a punch
        rec_b = self.timetable_service.record_punch(
            user_id="user_b",
            course_name="Operating Systems",
            course_code="CS202",
            punch_date="2026-09-01",
            punch_time="10:15:00",
            status="present"
        )
        punch_id_b = rec_b["id"]

        # User A attempts to delete User B's punch -> returns 404 (not found under user_a scope)
        resp = self.client.delete(
            f"/api/attendance/punch/{punch_id_b}",
            headers={"Authorization": f"Bearer {self.token_user_a}"}
        )
        self.assertEqual(resp.status_code, 404)

        # Punch for user_b still exists
        punches_b = self.timetable_service.get_punches("user_b")
        self.assertEqual(len(punches_b), 1)


class TestMultiUserGoogleOAuthIsolation(MultiUserIsolationBaseTestCase):
    """Tests Google OAuth CSRF state binding and session defense-in-depth."""

    def test_oauth_state_binding_and_consumption(self):
        state_token_a = self.timetable_service.create_oauth_state("user_a")
        self.assertTrue(len(state_token_a) >= 32)

        # State belongs to user_a
        consumed_user = self.timetable_service.validate_and_consume_state(state_token_a)
        self.assertEqual(consumed_user, "user_a")

        # Single-use: Replaying consumed state fails
        replayed = self.timetable_service.validate_and_consume_state(state_token_a)
        self.assertIsNone(replayed)

    def test_oauth_callback_session_mismatch_rejected(self):
        state_token_a = self.timetable_service.create_oauth_state("user_a")

        # User B active session hits callback with User A's state token
        with patch.object(timetable_sync.GoogleCalendarClient, "exchange_code_for_tokens", return_value={"access_token": "mock_tok"}):
            resp = self.client.get(
                f"/api/auth/google/callback?code=mock_code&state={state_token_a}",
                headers={"Authorization": f"Bearer {self.token_user_b}"}
            )
            self.assertEqual(resp.status_code, 403)
            self.assertIn("OAuth state was generated by a different user session", resp.get_json()["message"])

    def test_oauth_callback_matching_session_succeeds(self):
        state_token_a = self.timetable_service.create_oauth_state("user_a")

        with patch.object(timetable_sync.GoogleCalendarClient, "exchange_code_for_tokens", return_value={"access_token": "mock_tok"}):
            resp = self.client.get(
                f"/api/auth/google/callback?code=mock_code&state={state_token_a}&format=json",
                headers={"Authorization": f"Bearer {self.token_user_a}"}
            )
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.get_json()["user_id"], "user_a")

            # Tokens stored strictly for user_a
            info_a = self.timetable_service.get_oauth_tokens("user_a")
            self.assertIsNotNone(info_a)
            info_b = self.timetable_service.get_oauth_tokens("user_b")
            self.assertIsNone(info_b)

    def test_google_calendar_selection_isolation(self):
        # Save tokens for user_a and user_b
        self.timetable_service.save_oauth_tokens("user_a", {"access_token": "tok_a"}, calendar_id="cal_alice")
        self.timetable_service.save_oauth_tokens("user_b", {"access_token": "tok_b"}, calendar_id="cal_bob")

        # User A updates calendar
        resp_a = self.client.post(
            "/api/auth/google/calendar",
            headers={"Authorization": f"Bearer {self.token_user_a}"},
            json={"calendar_id": "cal_alice_new"}
        )
        self.assertEqual(resp_a.status_code, 200)

        # Confirm user_a calendar updated, user_b untouched
        info_a = self.timetable_service.get_oauth_tokens("user_a")
        self.assertEqual(info_a[1], "cal_alice_new")

        info_b = self.timetable_service.get_oauth_tokens("user_b")
        self.assertEqual(info_b[1], "cal_bob")


class TestMultiTenantSchedulerIsolation(MultiUserIsolationBaseTestCase):
    """Tests sequential multi-tenant scheduler failure containment."""

    def test_sync_all_active_users_error_isolation(self):
        # Configure tokens for user_a and user_b
        self.timetable_service.save_oauth_tokens("user_a", {"access_token": "tok_a"})
        self.timetable_service.save_oauth_tokens("user_b", {"access_token": "tok_b"})

        # Mock sync_user_timetable so user_a raises an exception but user_b succeeds
        def mock_sync(user_id, force_calendar_id=None):
            if user_id == "user_a":
                raise RuntimeError("Simulated network crash for user_a")
            return {"user_id": "user_b", "status": "success", "sessions_seen": 5}

        with patch.object(self.timetable_service, "sync_user_timetable", side_effect=mock_sync):
            summaries = self.timetable_service.sync_all_active_users()
            self.assertIn("user_a", summaries)
            self.assertIn("user_b", summaries)
            self.assertEqual(summaries["user_a"]["status"], "failed")
            self.assertIn("Simulated network crash", summaries["user_a"]["errors"][0])
            self.assertEqual(summaries["user_b"]["status"], "success")


class TestAdminTargetedRoutes(MultiUserIsolationBaseTestCase):
    """Tests that admin-targeted endpoints require admin and operate on target user."""

    def test_admin_can_access_target_user_status(self):
        resp = self.client.get(
            "/api/admin/users/user_a/timetable/status",
            headers={"Authorization": f"Bearer {self.token_admin}"}
        )
        self.assertEqual(resp.status_code, 200)

    def test_regular_user_cannot_access_admin_routes(self):
        resp = self.client.get(
            "/api/admin/users/user_b/timetable/status",
            headers={"Authorization": f"Bearer {self.token_user_a}"}
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.get_json()["error"], "permission_denied")


if __name__ == "__main__":
    unittest.main()
