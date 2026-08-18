"""
NexusNode — UPES Timetable & Google Calendar Synchronization Test Suite
Comprehensive testing covering:
1. Tolerant UPES JSON parsing & normalized data model.
2. Authenticated AES-GCM OAuth Token encryption/decryption at rest.
3. CSRF-safe OAuth state lifecycle and token exchange.
4. Deterministic event identity, idempotent reconciliation, and delta updates.
5. Vanished session managed event deletion.
6. Multi-user security isolation & RBAC boundaries.
7. Database-backed distributed lease locks & concurrent sync prevention.
8. 3-hour scheduler integration & restart persistence.
"""

import datetime
import json
import os
import secrets
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

import config
import timetable_sync
from timetable_sync import (
    GoogleCalendarClient,
    GoogleCalendarError,
    OAuthTokenCrypto,
    TimetableService,
    TimetableSession,
    TimetableSynchronizer,
    normalize_upes_session,
    parse_timetable_json,
)


class MockGoogleCalendarClient:
    """Mock Google Calendar client simulating remote calendar events."""

    def __init__(self, user_id="test_user"):
        self.user_id = user_id
        self.events = {}  # event_id -> event_dict
        self.calls = {
            "create": 0,
            "update": 0,
            "delete": 0,
            "list": 0
        }

    def list_calendars(self):
        self.calls["list"] += 1
        return [{"id": "primary", "summary": "Primary Calendar", "primary": True}]

    def create_event(self, calendar_id: str, session: TimetableSession, user_id: str):
        self.calls["create"] += 1
        event_id = f"g_evt_{session.session_id}_{session.date.replace('-', '')}"
        body = {
            "id": event_id,
            "summary": f"[{session.course_code}] {session.course_name}" if session.course_code else session.course_name,
            "location": session.room,
            "description": f"Faculty: {session.faculty}",
            "start": {"dateTime": session.get_start_iso()},
            "end": {"dateTime": session.get_end_iso()},
            "extendedProperties": {
                "private": {
                    "nexusnode_managed": "true",
                    "nexusnode_user_id": user_id,
                    "nexusnode_session_id": session.session_id,
                    "nexusnode_date": session.date
                }
            }
        }
        self.events[event_id] = body
        return body

    def update_event(self, calendar_id: str, event_id: str, session: TimetableSession, user_id: str):
        self.calls["update"] += 1
        if event_id not in self.events:
            raise GoogleCalendarError("Event not found", status_code=404)
        body = self.events[event_id]
        body["location"] = session.room
        body["start"] = {"dateTime": session.get_start_iso()}
        body["end"] = {"dateTime": session.get_end_iso()}
        return body

    def delete_event(self, calendar_id: str, event_id: str):
        self.calls["delete"] += 1
        if event_id in self.events:
            del self.events[event_id]
        return True


class TestTimetableParser(unittest.TestCase):
    """Verifies tolerant UPES JSON parsing and timezone-aware normalization."""

    def test_parse_standard_upes_payload(self):
        payload = [
            {
                "course_name": "Distributed Systems",
                "course_code": "CS301",
                "date": "2026-08-20",
                "start_time": "09:00:00",
                "end_time": "10:00:00",
                "room": "Room 501",
                "faculty": "Dr. Sharma",
                "session_id": "sess_101"
            },
            {
                "course_name": "Cloud Computing Lab",
                "course_code": "CS302",
                "date": "2026-08-20",
                "start_time": "10:00:00",
                "end_time": "12:00:00",
                "room": "Lab 3",
                "faculty": "Prof. Verma"
            }
        ]

        sessions, errors = parse_timetable_json(payload)
        self.assertEqual(len(sessions), 2)
        self.assertEqual(len(errors), 0)

        s1 = sessions[0]
        self.assertEqual(s1.course_name, "Distributed Systems")
        self.assertEqual(s1.course_code, "CS301")
        self.assertEqual(s1.date, "2026-08-20")
        self.assertEqual(s1.start_time, "09:00:00")
        self.assertEqual(s1.end_time, "10:00:00")
        self.assertEqual(s1.room, "Room 501")
        self.assertEqual(s1.faculty, "Dr. Sharma")
        self.assertEqual(s1.session_id, "sess_101")

        # Session without ID gets deterministic ID
        s2 = sessions[1]
        self.assertTrue(len(s2.session_id) > 0)

    def test_parse_varied_field_names(self):
        payload = {
            "timetable": [
                {
                    "subject": "Compiler Design",
                    "subjectCode": "CS401",
                    "slotDate": "20/08/2026",
                    "timeFrom": "02:00 PM",
                    "timeTo": "03:00 PM",
                    "venue": "Audi 2",
                    "instructor": "Dr. Gupta"
                }
            ]
        }

        sessions, errors = parse_timetable_json(payload)
        self.assertEqual(len(sessions), 1)
        self.assertEqual(len(errors), 0)

        s = sessions[0]
        self.assertEqual(s.course_name, "Compiler Design")
        self.assertEqual(s.course_code, "CS401")
        self.assertEqual(s.date, "2026-08-20")
        self.assertEqual(s.start_time, "14:00:00")
        self.assertEqual(s.end_time, "15:00:00")
        self.assertEqual(s.room, "Audi 2")
        self.assertEqual(s.faculty, "Dr. Gupta")

    def test_parse_combined_time_slot(self):
        item = {
            "title": "Machine Learning",
            "date": "2026-08-21",
            "time": "09:00 AM - 10:30 AM",
            "location": "Room 102"
        }
        session = normalize_upes_session(item)
        self.assertIsNotNone(session)
        self.assertEqual(session.course_name, "Machine Learning")
        self.assertEqual(session.start_time, "09:00:00")
        self.assertEqual(session.end_time, "10:30:00")

    def test_timezone_aware_iso_generation(self):
        s = TimetableSession(
            course_name="Cybersecurity",
            course_code="CS501",
            date="2026-08-22",
            start_time="11:00:00",
            end_time="12:00:00",
            room="Lab 1",
            faculty="Dr. Singh",
            session_id="sess_cyber"
        )
        iso_start = s.get_start_iso("Asia/Kolkata")
        self.assertIn("2026-08-22T11:00:00+05:30", iso_start)

    def test_malformed_session_skipped_gracefully(self):
        payload = [
            {"course_name": "Valid Course", "date": "2026-08-20", "start_time": "09:00", "end_time": "10:00"},
            {"course_name": "Invalid Course", "date": "invalid-date"},
            {"course_name": "", "date": "2026-08-20", "start_time": "10:00", "end_time": "11:00"}
        ]
        sessions, errors = parse_timetable_json(payload)
        self.assertEqual(len(sessions), 1)
        self.assertEqual(len(errors), 2)


class TestTokenCryptoAndState(unittest.TestCase):
    """Verifies AES-GCM encryption at rest and CSRF state security."""

    def test_aes_gcm_token_encryption_roundtrip(self):
        sample_token = {
            "access_token": "ya29.a0AfH6SM...",
            "refresh_token": "1//04...",
            "token_type": "Bearer",
            "expires_at": time.time() + 3600
        }
        encrypted = OAuthTokenCrypto.encrypt(sample_token)
        self.assertIsInstance(encrypted, str)
        self.assertNotIn("ya29", encrypted)
        self.assertNotIn("refresh_token", encrypted)

        decrypted = OAuthTokenCrypto.decrypt(encrypted)
        self.assertIsNotNone(decrypted)
        self.assertEqual(decrypted["access_token"], sample_token["access_token"])
        self.assertEqual(decrypted["refresh_token"], sample_token["refresh_token"])

    def test_tampered_ciphertext_fails_decryption(self):
        sample_token = {"access_token": "secret_token_123"}
        encrypted = OAuthTokenCrypto.encrypt(sample_token)

        # Corrupt the encrypted payload
        tampered = encrypted[:-4] + "AAAA"
        decrypted = OAuthTokenCrypto.decrypt(tampered)
        self.assertIsNone(decrypted)


class TestTimetableServiceAndSyncEngine(unittest.TestCase):
    """Verifies SQLite persistence, idempotency, deltas, and multi-user isolation."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_nexus.db")

        import sqlite3
        def get_test_conn():
            c = sqlite3.connect(self.db_path)
            c.row_factory = sqlite3.Row
            return c

        self.conn_factory = get_test_conn

        # Init DB schema
        conn = self.conn_factory()
        timetable_sync.init_timetable_tables(conn)
        conn.close()

        self.service = TimetableService(self.conn_factory)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_oauth_token_storage_and_disconnection(self):
        user_id = "alice"
        tokens = {
            "access_token": "token_alice",
            "refresh_token": "refresh_alice",
            "expires_at": time.time() + 3600
        }

        self.service.save_oauth_tokens(user_id, tokens, calendar_id="cal_alice", email="alice@gmail.com")
        retrieved = self.service.get_oauth_tokens(user_id)
        self.assertIsNotNone(retrieved)
        token_data, cal_id, email = retrieved
        self.assertEqual(token_data["access_token"], "token_alice")
        self.assertEqual(cal_id, "cal_alice")
        self.assertEqual(email, "alice@gmail.com")

        # Disconnect Google
        self.service.disconnect_google(user_id)
        self.assertIsNone(self.service.get_oauth_tokens(user_id))

    def test_csrf_state_token_lifecycle(self):
        user_id = "bob"
        state = self.service.create_oauth_state(user_id)
        self.assertTrue(len(state) > 20)

        # Valid consumption
        consumed_user = self.service.validate_and_consume_state(state)
        self.assertEqual(consumed_user, user_id)

        # Replay attack prevention: second consumption fails
        replayed_user = self.service.validate_and_consume_state(state)
        self.assertIsNone(replayed_user)

    def test_idempotent_synchronization(self):
        """Zero duplicate guarantee: running sync twice without change creates 0 events."""
        user_id = "charlie"
        mock_client = MockGoogleCalendarClient(user_id=user_id)

        sessions = [
            TimetableSession("OS", "CS201", "2026-08-25", "09:00:00", "10:00:00", "R1", "Dr. A", "s1"),
            TimetableSession("DBMS", "CS202", "2026-08-25", "10:00:00", "11:00:00", "R2", "Dr. B", "s2")
        ]

        synchronizer = TimetableSynchronizer(self.conn_factory, user_id, mock_client)

        # First synchronization run
        res1 = synchronizer.synchronize(sessions)
        self.assertEqual(res1["created"], 2)
        self.assertEqual(res1["updated"], 0)
        self.assertEqual(res1["unchanged"], 0)
        self.assertEqual(res1["deleted"], 0)
        self.assertEqual(mock_client.calls["create"], 2)

        # Second synchronization run (Strict Idempotency Verification!)
        res2 = synchronizer.synchronize(sessions)
        self.assertEqual(res2["created"], 0)
        self.assertEqual(res2["updated"], 0)
        self.assertEqual(res2["unchanged"], 2)
        self.assertEqual(res2["deleted"], 0)
        self.assertEqual(mock_client.calls["create"], 2)  # Zero new API calls!

    def test_modified_session_delta_update(self):
        """Changing room or time triggers an update instead of creating a duplicate."""
        user_id = "david"
        mock_client = MockGoogleCalendarClient(user_id=user_id)
        synchronizer = TimetableSynchronizer(self.conn_factory, user_id, mock_client)

        initial = [
            TimetableSession("Networks", "CS303", "2026-08-26", "09:00:00", "10:00:00", "Room 101", "Prof. X", "s_net")
        ]
        res1 = synchronizer.synchronize(initial)
        self.assertEqual(res1["created"], 1)

        # Room changed from Room 101 -> Room 202
        modified = [
            TimetableSession("Networks", "CS303", "2026-08-26", "09:00:00", "10:00:00", "Room 202", "Prof. X", "s_net")
        ]
        res2 = synchronizer.synchronize(modified)
        self.assertEqual(res2["created"], 0)
        self.assertEqual(res2["updated"], 1)
        self.assertEqual(res2["unchanged"], 0)
        self.assertEqual(mock_client.calls["update"], 1)

    def test_vanished_session_deletion(self):
        """When a session disappears from timetable, its managed event is deleted."""
        user_id = "eva"
        mock_client = MockGoogleCalendarClient(user_id=user_id)
        synchronizer = TimetableSynchronizer(self.conn_factory, user_id, mock_client)

        sessions_day1 = [
            TimetableSession("AI", "CS401", "2026-08-27", "09:00:00", "10:00:00", "R1", "Dr. Y", "s_ai"),
            TimetableSession("Web Dev", "CS402", "2026-08-27", "11:00:00", "12:00:00", "R2", "Dr. Z", "s_web")
        ]
        synchronizer.synchronize(sessions_day1)
        self.assertEqual(len(mock_client.events), 2)

        # AI session removed from timetable
        sessions_day2 = [
            TimetableSession("Web Dev", "CS402", "2026-08-27", "11:00:00", "12:00:00", "R2", "Dr. Z", "s_web")
        ]
        res = synchronizer.synchronize(sessions_day2)
        self.assertEqual(res["created"], 0)
        self.assertEqual(res["deleted"], 1)
        self.assertEqual(res["unchanged"], 1)
        self.assertEqual(mock_client.calls["delete"], 1)
        self.assertEqual(len(mock_client.events), 1)

    def test_multi_user_security_isolation(self):
        """User A and User B cannot access each other's tokens or event mappings."""
        # Alice
        self.service.save_oauth_tokens("alice", {"token": "alice_tok"}, email="alice@test.com")
        self.service.upload_timetable("alice", json.dumps([
            {"course_name": "Alice Course", "date": "2026-08-28", "start_time": "09:00", "end_time": "10:00"}
        ]))

        # Bob
        self.service.save_oauth_tokens("bob", {"token": "bob_tok"}, email="bob@test.com")
        self.service.upload_timetable("bob", json.dumps([
            {"course_name": "Bob Course", "date": "2026-08-28", "start_time": "11:00", "end_time": "12:00"}
        ]))

        alice_sess, _ = self.service.load_timetable_sessions("alice")
        bob_sess, _ = self.service.load_timetable_sessions("bob")

        self.assertEqual(len(alice_sess), 1)
        self.assertEqual(alice_sess[0].course_name, "Alice Course")

        self.assertEqual(len(bob_sess), 1)
        self.assertEqual(bob_sess[0].course_name, "Bob Course")

    def test_concurrent_synchronization_lease_lock(self):
        """Database lease lock prevents simultaneous sync runs for the same user."""
        lease1 = timetable_sync.DatabaseSyncLease(self.conn_factory, "frank", timeout_seconds=60)
        lease2 = timetable_sync.DatabaseSyncLease(self.conn_factory, "frank", timeout_seconds=60)

        self.assertTrue(lease1.acquire())
        # Second lease attempt for same user must fail
        self.assertFalse(lease2.acquire())

        # Release first lease
        lease1.release()
        # Now second lease succeeds
        self.assertTrue(lease2.acquire())
        lease2.release()


class TestFlaskTimetableRoutes(unittest.TestCase):
    """Verifies REST endpoints, RBAC enforcement, upload size limits, and status telemetry."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="nexus_timetable_test_")
        self.db_path = os.path.join(self.test_dir, "test_nexus.db")
        self.rag_path = os.path.join(self.test_dir, "test_rag.db")
        self.storage_dir = os.path.join(self.test_dir, "storage_vault")
        os.makedirs(self.storage_dir, exist_ok=True)

        self._orig_db = config.UNIFIED_DB_FILE
        self._orig_rag = config.RAG_DB_FILE
        self._orig_storage = config.STORAGE_DIR
        config.UNIFIED_DB_FILE = self.db_path
        config.RAG_DB_FILE = self.rag_path
        config.STORAGE_DIR = self.storage_dir

        import app
        self.app = app
        app.init_unified_db()

        self.client = app.app.test_client()
        app.SESSIONS.clear()
        app.FAILED_LOGINS.clear()

        admin_user = app.db_get_user("admin")
        self.admin_token = app.create_user_session(admin_user)
        self.admin_headers = {
            "Authorization": f"Bearer {self.admin_token}"
        }

    def tearDown(self):
        config.UNIFIED_DB_FILE = self._orig_db
        config.RAG_DB_FILE = self._orig_rag
        config.STORAGE_DIR = self._orig_storage
        self.app.SESSIONS.clear()
        self.app.FAILED_LOGINS.clear()
        import shutil
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_unauthenticated_requests_rejected(self):
        res = self.client.get("/api/maintenance/timetable/status")
        self.assertEqual(res.status_code, 401)

        res2 = self.client.post("/api/maintenance/timetable/sync")
        self.assertEqual(res2.status_code, 401)

        res3 = self.client.post("/api/maintenance/timetable/upload")
        self.assertEqual(res3.status_code, 401)

    def test_admin_sync_status_endpoint(self):
        res = self.client.get("/api/maintenance/timetable/status", headers=self.admin_headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("google_connected", data)
        self.assertIn("sync_interval_seconds", data)
        self.assertEqual(data["sync_interval_seconds"], 10800)

    def test_timetable_upload_endpoint(self):
        timetable_data = [
            {
                "course_name": "Software Engineering",
                "course_code": "SE101",
                "date": "2026-08-29",
                "start_time": "10:00:00",
                "end_time": "11:00:00",
                "room": "Room 401",
                "faculty": "Prof. Rao"
            }
        ]

        upload_res = self.client.post(
            "/api/maintenance/timetable/upload",
            headers=self.admin_headers,
            json=timetable_data
        )
        self.assertEqual(upload_res.status_code, 200)
        data = upload_res.get_json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["sessions_count"], 1)

    def test_oversized_upload_rejected(self):
        oversized_data = "x" * (config.TIMETABLE_MAX_UPLOAD_BYTES + 5000)
        res = self.client.post(
            "/api/maintenance/timetable/upload",
            headers=self.admin_headers,
            data=oversized_data
        )
        self.assertEqual(res.status_code, 413)

    def test_oauth_callback_invalid_state_rejected(self):
        res = self.client.get("/api/auth/google/callback?code=mock_code&state=invalid_csrf_state")
        self.assertEqual(res.status_code, 400)
        data = res.get_json()
        self.assertIn("Invalid or expired", data["error"])

    def test_oauth_disconnect_endpoint(self):
        # Save mock token first
        app = self.app
        app.timetable_service.save_oauth_tokens("admin", {"access_token": "mock"}, email="admin@google.com")
        self.assertIsNotNone(app.timetable_service.get_oauth_tokens("admin"))

        res = self.client.post("/api/auth/google/disconnect", headers=self.admin_headers)
        self.assertEqual(res.status_code, 200)
        self.assertIsNone(app.timetable_service.get_oauth_tokens("admin"))

    def test_regular_user_sync_rbac(self):
        # Create normal user with can_sync_timetable
        app = self.app
        app.db_create_user("student1", "Password@123", role="user", privileges=["can_sync_timetable"])
        user_obj = app.db_get_user("student1")
        user_token = app.create_user_session(user_obj)
        user_headers = {"Authorization": f"Bearer {user_token}"}

        # Query own status -> 200
        res = self.client.get("/api/maintenance/timetable/status", headers=user_headers)
        self.assertEqual(res.status_code, 200)

        # Upload timetable for self -> 200
        res = self.client.post(
            "/api/maintenance/timetable/upload",
            headers=user_headers,
            json=[{"course_name": "Math", "date": "2026-08-30", "start_time": "09:00", "end_time": "10:00"}]
        )
        self.assertEqual(res.status_code, 200)

        # User without can_sync_timetable -> 403
        app.db_create_user("student2", "Password@123", role="user", privileges=[])
        u2 = app.db_get_user("student2")
        u2_tok = app.create_user_session(u2)
        res = self.client.get("/api/maintenance/timetable/status", headers={"Authorization": f"Bearer {u2_tok}"})
        self.assertEqual(res.status_code, 403)

    def test_scheduler_seeding_and_job_execution(self):
        app = self.app
        conn = app.get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT id, interval_seconds, enabled FROM scheduled_jobs WHERE id = 'job_timetable_sync'")
            row = cur.fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["interval_seconds"], 10800)
            self.assertEqual(row["enabled"], 1)
        finally:
            conn.close()

        # Execute scheduled job function directly
        task_obj = {'logs': []}
        app.run_timetable_sync_job(task_obj)
        self.assertTrue(any("Timetable sync completed" in log for log in task_obj['logs']))


class TestGoogleApiClientResilience(unittest.TestCase):
    """Verifies exponential backoff, rate limiting, and 401 token refresh in GoogleCalendarClient."""

    @patch("requests.request")
    def test_client_token_auto_refresh_on_401(self, mock_request):
        token_data = {
            "access_token": "expired_tok",
            "refresh_token": "valid_refresh_tok",
            "expires_at": time.time() + 3600
        }

        client = GoogleCalendarClient(token_data, "user_resilience")
        client.refresh_access_token = MagicMock(return_value="refreshed_tok")

        resp_401 = MagicMock()
        resp_401.status_code = 401
        resp_401.json.return_value = {"error": {"message": "Invalid Credentials"}}

        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.json.return_value = {"items": [{"id": "primary", "summary": "Main"}]}

        mock_request.side_effect = [resp_401, resp_200]

        calendars = client.list_calendars()
        self.assertEqual(len(calendars), 1)
        client.refresh_access_token.assert_called_once()

    @patch("requests.request")
    def test_client_rate_limiting_retry_429(self, mock_request):
        token_data = {
            "access_token": "valid_tok",
            "expires_at": time.time() + 3600
        }
        client = GoogleCalendarClient(token_data, "user_429")

        resp_429 = MagicMock()
        resp_429.status_code = 429
        resp_429.json.return_value = {"error": {"message": "Rate Limit Exceeded"}}

        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.json.return_value = {"items": []}

        mock_request.side_effect = [resp_429, resp_200]

        with patch("time.sleep") as mock_sleep:
            calendars = client.list_calendars()
            self.assertEqual(calendars, [])
            mock_sleep.assert_called_once()

    @patch("requests.request")
    def test_client_non_retryable_400_raises_error(self, mock_request):
        token_data = {
            "access_token": "valid_tok",
            "expires_at": time.time() + 3600
        }
        client = GoogleCalendarClient(token_data, "user_400")

        resp_400 = MagicMock()
        resp_400.status_code = 400
        resp_400.json.return_value = {"error": {"message": "Bad Request: Invalid query"}}

        mock_request.return_value = resp_400

        with self.assertRaises(GoogleCalendarError) as ctx:
            client.list_calendars()
        self.assertEqual(ctx.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
