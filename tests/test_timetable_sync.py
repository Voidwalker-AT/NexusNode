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

import base64
import datetime
import json
import os
import secrets
import sqlite3
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

    def test_parse_native_upes_api_response(self):
        """Verifies parsing of the exact JSON response returned by UPES /api/timetable endpoint."""
        raw_upes_response = [
            {
                "SlotDate": "2026-08-19",
                "SlotStartTime": "09:15 AM",
                "SlotEndTime": "05:00 PM",
                "ModuleList": [
                    {
                        "ModuleName": "Leadership and Team Building",
                        "ModuleCode": "HUMN1001"
                    }
                ],
                "TeacherList": [
                    {
                        "Name": "Dr. Anderson",
                        "Code": "T101"
                    }
                ],
                "FloorPlanDetails": {
                    "VenueName": "5001(5001)",
                    "VenueCode": "5001",
                    "VenueCategoryCode": "CR"
                },
                "SessionId": "upes_sess_001"
            }
        ]

        sessions, errors = parse_timetable_json(raw_upes_response)
        self.assertEqual(len(sessions), 1)
        self.assertEqual(len(errors), 0)

        s = sessions[0]
        self.assertEqual(s.course_name, "Leadership and Team Building")
        self.assertEqual(s.course_code, "HUMN1001")
        self.assertEqual(s.date, "2026-08-19")
        self.assertEqual(s.start_time, "09:15:00")
        self.assertEqual(s.end_time, "17:00:00")
        self.assertEqual(s.room, "5001(5001)")
        self.assertEqual(s.faculty, "Dr. Anderson")
        self.assertEqual(s.session_id, "upes_sess_001")


    def test_weekday_schedule_parsing(self):
        import datetime
        ref = datetime.date(2026, 8, 19)  # Wednesday
        item_wed = {
            "course": "Leadership and Team Building",
            "day": "Wednesday",
            "time": "09:15 AM - 05:00 PM",
            "room": "5001(5001)",
            "faculty": "Dr. Anderson"
        }
        item_thu1 = {
            "course": "Distributed Systems",
            "day": "Thursday",
            "time": "09:00 AM - 10:00 AM",
            "room": "Room 501",
            "faculty": "Dr. Sharma"
        }
        item_thu2 = {
            "course": "Advanced Algorithms",
            "day": "Thursday",
            "time": "10:00 AM - 11:00 AM",
            "room": "Room 502",
            "faculty": "Prof. Rao"
        }
        item_thu3 = {
            "course": "Database Internals",
            "day": "Thursday",
            "time": "11:15 AM - 12:15 PM",
            "room": "Room 503",
            "faculty": "Dr. Mehta"
        }
        item_thu4 = {
            "course": "Network Security Lab",
            "day": "Thursday",
            "time": "02:00 PM - 04:00 PM",
            "room": "Lab 4",
            "faculty": "Prof. Kapoor"
        }

        payload = [item_wed, item_thu1, item_thu2, item_thu3, item_thu4]
        sessions, errors = parse_timetable_json(payload, ref_date=ref)
        self.assertEqual(len(sessions), 5)
        self.assertEqual(len(errors), 0)

        # Wednesday session
        wed_sessions = [s for s in sessions if s.date == "2026-08-19"]
        self.assertEqual(len(wed_sessions), 1)
        self.assertEqual(wed_sessions[0].course_name, "Leadership and Team Building")
        self.assertEqual(wed_sessions[0].start_time, "09:15:00")
        self.assertEqual(wed_sessions[0].end_time, "17:00:00")
        self.assertEqual(wed_sessions[0].room, "5001(5001)")

        # Thursday sessions (4 classes)
        thu_sessions = [s for s in sessions if s.date == "2026-08-20"]
        self.assertEqual(len(thu_sessions), 4)

    def test_nested_day_dict_parsing(self):
        import datetime
        ref = datetime.date(2026, 8, 19)
        payload = {
            "Wednesday": [
                {"name": "Class A", "time": "09:00-10:00", "room": "101"}
            ],
            "Thursday": [
                {"name": "Class B", "time": "09:00-10:00", "room": "102"},
                {"name": "Class C", "time": "10:00-11:00", "room": "103"},
                {"name": "Class D", "time": "11:00-12:00", "room": "104"},
                {"name": "Class E", "time": "14:00-16:00", "room": "Lab 1"}
            ]
        }
        sessions, errors = parse_timetable_json(payload, ref_date=ref)
        self.assertEqual(len(sessions), 5)
        self.assertEqual(len(errors), 0)
        self.assertEqual(len([s for s in sessions if s.date == "2026-08-19"]), 1)
        self.assertEqual(len([s for s in sessions if s.date == "2026-08-20"]), 4)



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
        finally:
            conn.close()

        # Execute scheduled job function directly
        task_obj = {'logs': []}
        app.run_timetable_sync_job(task_obj)
        self.assertTrue(any("Timetable sync completed" in log for log in task_obj['logs']))

    def test_save_and_delete_upes_portal_session_endpoint(self):
        # 1. Save UPES portal session via endpoint
        payload = {
            "access_token": "test_upes_token_xyz",
            "student_code": "3a678d8e-8817-41e6-b1a8-5a3ec6ee4948"
        }
        res = self.client.post("/api/maintenance/timetable/upes/session", headers=self.admin_headers, json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "success")

        # 2. Check status shows configured without exposing raw token
        status_res = self.client.get("/api/maintenance/timetable/status", headers=self.admin_headers)
        self.assertEqual(status_res.status_code, 200)
        st_data = status_res.get_json()
        self.assertTrue(st_data["upes_configured"])
        self.assertNotIn("test_upes_token_xyz", json.dumps(st_data))

        # 3. Delete UPES portal session
        del_res = self.client.delete("/api/maintenance/timetable/upes/session", headers=self.admin_headers)
        self.assertEqual(del_res.status_code, 200)

        # 4. Status reflects not configured
        status_res2 = self.client.get("/api/maintenance/timetable/status", headers=self.admin_headers)
        self.assertFalse(status_res2.get_json()["upes_configured"])

    @patch("timetable_sync.fetch_upes_timetable")
    def test_trigger_upes_fetch_endpoint(self, mock_fetch):
        # Configure session first
        self.app.timetable_service.save_upes_session("admin", "tok123", "3a678d8e-8817-41e6-b1a8-5a3ec6ee4948")
        mock_fetch.return_value = ([
            {
                "SlotDate": "2026-08-19",
                "SlotStartTime": "09:15 AM",
                "SlotEndTime": "05:00 PM",
                "ModuleList": [{"ModuleName": "Leadership and Team Building", "ModuleCode": "HUMN1001"}],
                "TeacherList": [{"Name": "Dr. Anderson"}],
                "FloorPlanDetails": {"VenueName": "5001(5001)"},
                "SessionId": "sess_live_01"
            }
        ], None)

        res = self.client.post("/api/maintenance/timetable/upes/fetch", headers=self.admin_headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["sessions_count"], 1)

        # Verify sessions loaded
        sessions_res = self.client.get("/api/maintenance/timetable/sessions", headers=self.admin_headers)
        self.assertEqual(sessions_res.status_code, 200)
        s_data = sessions_res.get_json()
        self.assertEqual(s_data["total_sessions"], 1)
        self.assertEqual(s_data["sessions"][0]["course"], "Leadership and Team Building")
        self.assertEqual(s_data["sessions"][0]["room"], "5001(5001)")


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


class TestUpesApiClient(unittest.TestCase):
    """Tests for fetch_upes_timetable API client."""

    @patch("requests.post")
    def test_fetch_upes_timetable_success(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [
            {
                "SlotDate": "2026-08-19",
                "SlotStartTime": "09:15 AM",
                "SlotEndTime": "05:00 PM",
                "ModuleList": [{"ModuleName": "Leadership and Team Building", "ModuleCode": "HUMN1001"}],
                "TeacherList": [{"Name": "Dr. Anderson"}],
                "FloorPlanDetails": {"VenueName": "5001(5001)"},
                "SessionId": "sess_upes_01"
            },
            {
                "SlotDate": "2026-08-20",
                "SlotStartTime": "09:00 AM",
                "SlotEndTime": "10:00 AM",
                "ModuleList": [{"ModuleName": "Distributed Systems", "ModuleCode": "CS301"}],
                "TeacherList": [{"Name": "Dr. Sharma"}],
                "FloorPlanDetails": {"VenueName": "5002"},
                "SessionId": "sess_upes_02"
            }
        ]
        mock_post.return_value = mock_resp

        items, err = timetable_sync.fetch_upes_timetable("mock_bearer_token", "3a678d8e-8817-41e6-b1a8-5a3ec6ee4948")
        self.assertIsNone(err)
        self.assertIsNotNone(items)
        self.assertEqual(len(items), 2)

        # Verify request parameters & headers
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertIn("Authorization", kwargs["headers"])
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer mock_bearer_token")
        self.assertEqual(kwargs["headers"]["x-applicationname"], "connectportal")
        self.assertEqual(kwargs["headers"]["x-requestfrom"], "web")
        self.assertEqual(kwargs["headers"]["x-studentuniqueid"], "3a678d8e-8817-41e6-b1a8-5a3ec6ee4948")
        self.assertEqual(kwargs["json"]["ActivityCode"], "student")
        self.assertEqual(kwargs["json"]["TimeTableContextDetails"]["StudentCode"], "3a678d8e-8817-41e6-b1a8-5a3ec6ee4948")

    @patch("requests.post")
    def test_fetch_upes_timetable_auth_required_401(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_post.return_value = mock_resp

        items, err = timetable_sync.fetch_upes_timetable("expired_token", "SAP12345")
        self.assertIsNone(items)
        self.assertIn("auth_required", err)

    @patch("requests.post")
    def test_fetch_upes_timetable_missing_token_or_code(self, mock_post):
        items, err = timetable_sync.fetch_upes_timetable("", "SAP12345")
        self.assertIsNone(items)
        self.assertIn("auth_required", err)

        items, err = timetable_sync.fetch_upes_timetable("token", "")
        self.assertIsNone(items)
        self.assertIn("missing_student_code", err)

    @patch("requests.post")
    def test_fetch_upes_timetable_network_error(self, mock_post):
        import requests
class TestUpesSessionAndService(unittest.TestCase):
    """Tests for UPES encrypted session persistence and last-known-good timetable preservation."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_nexus.db")
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        timetable_sync.init_timetable_tables(conn)
        conn.close()

        def conn_factory():
            import sqlite3
            c = sqlite3.connect(self.db_path)
            c.row_factory = sqlite3.Row
            return c

        self.service = TimetableService(conn_factory)
        # Isolate unit tests from live browser instances on localhost:9222
        self.service.session_broker.browser_bridge.is_cdp_available = lambda: False

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_save_and_get_upes_session(self):
        self.service.save_upes_session("user_upes", "secret_bearer_token_123", "500099999")
        session = self.service.get_upes_session("user_upes")
        self.assertIsNotNone(session)
        token, sap_id, url, exp = session
        self.assertEqual(token, "secret_bearer_token_123")
        self.assertEqual(sap_id, "500099999")

        # Verify encrypted in SQLite directly
        conn = self.service.conn_factory()
        cur = conn.cursor()
        cur.execute("SELECT encrypted_access_token FROM upes_auth_sessions WHERE user_id = 'user_upes'")
        row = cur.fetchone()
        self.assertIsNotNone(row)
        self.assertNotIn("secret_bearer_token_123", row[0])
        conn.close()

    def test_get_upes_session_nonexistent(self):
        self.assertIsNone(self.service.get_upes_session("no_such_user"))

    def test_delete_upes_session(self):
        self.service.save_upes_session("user_del", "token_del", "500011111")
        self.assertIsNotNone(self.service.get_upes_session("user_del"))
        self.service.delete_upes_session("user_del")
        self.assertIsNone(self.service.get_upes_session("user_del"))

    def test_jwt_expiration_decoding(self):
        # 1. Valid future JWT
        future_exp = time.time() + 3600
        payload_bytes = json.dumps({"sub": "student_123", "exp": future_exp}).encode("utf-8")
        payload_b64 = base64.urlsafe_b64encode(payload_bytes).decode("ascii").rstrip("=")
        jwt_token = f"eyJhbGciOiJIUzI1NiJ9.{payload_b64}.mock_signature"

        decoded = timetable_sync.decode_jwt_expiration(jwt_token)
        self.assertIsNotNone(decoded)
        self.assertAlmostEqual(decoded, future_exp, places=1)

        # 2. Invalid JWT strings
        self.assertIsNone(timetable_sync.decode_jwt_expiration("not_a_jwt"))
        self.assertIsNone(timetable_sync.decode_jwt_expiration(""))
        self.assertIsNone(timetable_sync.decode_jwt_expiration(None))

    @patch("timetable_sync.fetch_upes_timetable")
    def test_proactive_expiry_rejection_without_network_call(self, mock_fetch):
        # Construct an expired JWT (expired 10 minutes ago)
        past_exp = time.time() - 600
        payload_bytes = json.dumps({"sub": "student_123", "exp": past_exp}).encode("utf-8")
        payload_b64 = base64.urlsafe_b64encode(payload_bytes).decode("ascii").rstrip("=")
        expired_jwt = f"eyJhbGciOiJIUzI1NiJ9.{payload_b64}.mock_sig"

        self.service.save_upes_session("user_expired", expired_jwt, "3a678d8e-8817-41e6-b1a8-5a3ec6ee4948")
        success, msg, count = self.service.fetch_and_store_upes_timetable("user_expired")

        self.assertFalse(success)
        self.assertIn("auth_required", msg)
        self.assertIn("expired", msg)
        self.assertEqual(count, 0)

        # Ensure NO network call was made
        mock_fetch.assert_not_called()

    @patch("timetable_sync.fetch_upes_timetable")
    def test_fetch_and_store_preserves_last_known_good_on_failure(self, mock_fetch):
        # 1. Store good timetable first
        good_payload = json.dumps([
            {"course_name": "Operating Systems", "date": "2026-08-25", "start_time": "10:00", "end_time": "11:00"}
        ])
        self.service.upload_timetable("user_lkg", good_payload)
        sessions_initial, _ = self.service.load_timetable_sessions("user_lkg")
        self.assertEqual(len(sessions_initial), 1)

        # 2. Mock network failure on fetch
        mock_fetch.return_value = (None, "network_error: Connection timed out")
        self.service.save_upes_session("user_lkg", "valid_token", "500012345")

        success, msg, count = self.service.fetch_and_store_upes_timetable("user_lkg")
        self.assertFalse(success)
        self.assertIn("network_error", msg)
        self.assertEqual(count, 0)

        # 3. Verify previous good timetable was NOT deleted
        sessions, _ = self.service.load_timetable_sessions("user_lkg")
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0].course_name, "Operating Systems")

    def test_upes_session_broker_status_and_fetch(self):
        broker = self.service.session_broker

        # Unconfigured user
        st_unconf = broker.get_session_status("no_user")
        self.assertFalse(st_unconf["configured"])
        self.assertEqual(st_unconf["status"], "not_configured")

        # Configured user with active token
        future_exp = time.time() + 7200
        payload_bytes = json.dumps({"sub": "student_broker", "exp": future_exp}).encode("utf-8")
        payload_b64 = base64.urlsafe_b64encode(payload_bytes).decode("ascii").rstrip("=")
        active_jwt = f"eyJhbGciOiJIUzI1NiJ9.{payload_b64}.mock_sig"

        self.service.save_upes_session("user_broker", active_jwt, "3a678d8e-8817-41e6-b1a8-5a3ec6ee4948")
        st_conf = broker.get_session_status("user_broker")
        self.assertTrue(st_conf["configured"])
        self.assertEqual(st_conf["status"], "active")
        self.assertGreater(st_conf["ttl_seconds"], 0)
        self.assertEqual(st_conf["student_code_masked"], "3a6***")


class TestGoogleCalendarReconciliationStaleCleanup(unittest.TestCase):
    """Verifies that Google Calendar reconciliation cleans up vanished/mock events."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_recon.db")
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        timetable_sync.init_timetable_tables(conn)
        conn.close()

        def conn_factory():
            import sqlite3
            c = sqlite3.connect(self.db_path)
            c.row_factory = sqlite3.Row
            return c

        self.conn_factory = conn_factory
        self.mock_client = MockGoogleCalendarClient("test_user_recon")
        self.synchronizer = TimetableSynchronizer(self.conn_factory, "test_user_recon", self.mock_client, "primary")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_stale_mock_event_deleted_on_reconciliation(self):
        # 1. Pre-seed a mock event in SQLite mapping table and mock Google Calendar
        conn = self.conn_factory()
        now = time.time()
        conn.execute("""
            INSERT INTO timetable_events_map
            (id, user_id, source_session_id, source_date, google_calendar_id, google_event_id, source_hash, summary, start_time, end_time, last_synced_at, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, ("map_old_mock", "test_user_recon", "sess_101", "2026-08-20", "primary", "g_mock_evt_101", "old_hash", "[CS301] Distributed Systems", "09:00:00", "10:00:00", now, "synced"))
        conn.commit()
        conn.close()

        self.mock_client.events["g_mock_evt_101"] = {
            "id": "g_mock_evt_101",
            "summary": "[CS301] Distributed Systems",
            "description": "Mock description",
            "start": {"dateTime": "2026-08-20T15:30:00+05:30", "timeZone": "Asia/Kolkata"},
            "end": {"dateTime": "2026-08-20T16:30:00+05:30", "timeZone": "Asia/Kolkata"},
            "extendedProperties": {"private": {"nexusnode_managed": "true"}}
        }

        # 2. Provide the REAL UPES Thursday sessions (where sess_101 does NOT exist)
        new_sessions = [
            TimetableSession(
                course_name="Real Distributed Systems",
                course_code="CS401",
                date="2026-08-20",
                start_time="09:00:00",
                end_time="10:00:00",
                room="5001",
                faculty="Dr. Gupta",
                session_id="real_sess_thu_01"
            ),
            TimetableSession(
                course_name="Compiler Design",
                course_code="CS402",
                date="2026-08-20",
                start_time="10:00:00",
                end_time="11:00:00",
                room="5002",
                faculty="Dr. Gupta",
                session_id="real_sess_thu_02"
            ),
            TimetableSession(
                course_name="Computer Networks",
                course_code="CS403",
                date="2026-08-20",
                start_time="11:30:00",
                end_time="12:30:00",
                room="5003",
                faculty="Dr. Gupta",
                session_id="real_sess_thu_03"
            ),
            TimetableSession(
                course_name="Cyber Security",
                course_code="CS404",
                date="2026-08-20",
                start_time="14:00:00",
                end_time="15:00:00",
                room="5005",
                faculty="Dr. Gupta",
                session_id="real_sess_thu_04"
            )
        ]

        # 3. Synchronize
        summary = self.synchronizer.synchronize(new_sessions)

        # 4. Verify mock event was deleted from Google Calendar and mapping
        self.assertEqual(summary["deleted"], 1)
        self.assertEqual(summary["created"], 4)
        self.assertNotIn("g_mock_evt_101", self.mock_client.events)
        self.assertEqual(self.mock_client.calls["delete"], 1)

        # Verify in DB that old mapping is marked cancelled
        conn = self.conn_factory()
        cur = conn.cursor()
        cur.execute("SELECT status FROM timetable_events_map WHERE id = 'map_old_mock'")
        self.assertEqual(cur.fetchone()[0], "cancelled")
        conn.close()


class TestUpesBrowserSessionBridge(unittest.TestCase):
    """Verifies Chrome CDP bridge discovery, sessionStorage extraction, and session renewal."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_bridge.db")
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        timetable_sync.init_timetable_tables(conn)
        conn.close()

        def conn_factory():
            import sqlite3
            c = sqlite3.connect(self.db_path)
            c.row_factory = sqlite3.Row
            return c

        self.conn_factory = conn_factory
        self.service = TimetableService(self.conn_factory)
        self.bridge = self.service.session_broker.browser_bridge

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _make_jwt(self, exp_timestamp: float) -> str:
        payload = json.dumps({"sub": "student_test", "exp": exp_timestamp}).encode("utf-8")
        payload_b64 = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
        return f"eyJhbGciOiJIUzI1NiJ9.{payload_b64}.test_signature"

    def test_cdp_available_and_unavailable(self):
        with unittest.mock.patch("timetable_sync.requests.get") as mock_get:
            mock_get.return_value = unittest.mock.Mock(status_code=200, json=lambda: [{"type": "page"}])
            self.assertTrue(self.bridge.is_cdp_available())
            self.assertEqual(len(self.bridge.list_browser_targets()), 1)

            mock_get.side_effect = Exception("Connection refused")
            self.assertFalse(self.bridge.is_cdp_available())
            self.assertEqual(len(self.bridge.list_browser_targets()), 0)

    def test_find_upes_target(self):
        targets = [
            {"id": "1", "type": "page", "title": "Google Search", "url": "https://www.google.com"},
            {"id": "2", "type": "page", "title": "GitHub", "url": "https://github.com"},
            {"id": "3", "type": "page", "title": "UPES Student Portal", "url": "https://myupes-beta.upes.ac.in/connectportal/user/student/curriculum-scheduling", "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/3"}
        ]
        with unittest.mock.patch.object(self.bridge, "list_browser_targets", return_value=targets):
            target = self.bridge.find_upes_target()
            self.assertIsNotNone(target)
            self.assertEqual(target["id"], "3")

    def test_bridge_rejects_expired_browser_jwt(self):
        expired_jwt = self._make_jwt(time.time() - 3600)
        target = {"webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/test", "url": "https://myupes-beta.upes.ac.in/"}
        eval_payload = json.dumps({
            "jwt": json.dumps({"Identity": {"AccessToken": expired_jwt}}),
            "student": json.dumps({"StudentCode": "3a678d8e-8817-41e6-b1a8-5a3ec6ee4948"})
        })

        with unittest.mock.patch.object(self.bridge, "is_cdp_available", return_value=True), \
             unittest.mock.patch.object(self.bridge, "find_upes_target", return_value=target), \
             unittest.mock.patch.object(self.bridge, "evaluate_in_target", return_value=eval_payload):
            acquired = self.bridge.acquire_session_from_browser("test_user")
            self.assertIsNone(acquired)
            self.assertEqual(self.bridge.last_check_status, "browser_session_expired")

    def test_bridge_acquires_and_persists_valid_session(self):
        valid_jwt = self._make_jwt(time.time() + 36000)
        target = {"webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/test", "url": "https://myupes-beta.upes.ac.in/"}
        eval_payload = json.dumps({
            "jwt": json.dumps({"Identity": {"AccessToken": valid_jwt}}),
            "student": json.dumps({"StudentCode": "3a678d8e-8817-41e6-b1a8-5a3ec6ee4948"})
        })

        with unittest.mock.patch.object(self.bridge, "is_cdp_available", return_value=True), \
             unittest.mock.patch.object(self.bridge, "find_upes_target", return_value=target), \
             unittest.mock.patch.object(self.bridge, "evaluate_in_target", return_value=eval_payload):
            acquired = self.bridge.acquire_session_from_browser("test_user_fresh")
            self.assertIsNotNone(acquired)
            token, student_code, api_url, exp = acquired
            self.assertEqual(token, valid_jwt)
            self.assertEqual(student_code, "3a678d8e-8817-41e6-b1a8-5a3ec6ee4948")
            self.assertEqual(self.bridge.last_check_status, "acquired_successfully")

            # Verify persisted in SQLite
            stored = self.service.get_upes_session("test_user_fresh")
            self.assertIsNotNone(stored)
            self.assertEqual(stored[0], valid_jwt)

    def test_broker_auto_refreshes_from_bridge_when_stored_expired(self):
        # 1. Store expired token in DB
        expired_jwt = self._make_jwt(time.time() - 7200)
        self.service.save_upes_session("user_auto_refresh", expired_jwt, "3a678d8e-8817-41e6-b1a8-5a3ec6ee4948", expires_at=time.time() - 7200)

        # 2. Mock fresh session from browser bridge
        fresh_jwt = self._make_jwt(time.time() + 14400)
        target = {"webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/test", "url": "https://myupes-beta.upes.ac.in/"}
        eval_payload = json.dumps({
            "jwt": json.dumps({"Identity": {"AccessToken": fresh_jwt}}),
            "student": json.dumps({"StudentCode": "3a678d8e-8817-41e6-b1a8-5a3ec6ee4948"})
        })

        # 3. Mock UPES API response for fresh token
        mock_raw_sessions = [{"ModuleList": [{"ModuleName": "Compiler Design"}], "SlotDate": "2026-08-20"}]

        with unittest.mock.patch.object(self.bridge, "is_cdp_available", return_value=True), \
             unittest.mock.patch.object(self.bridge, "find_upes_target", return_value=target), \
             unittest.mock.patch.object(self.bridge, "evaluate_in_target", return_value=eval_payload), \
             unittest.mock.patch("timetable_sync.fetch_upes_timetable", return_value=(mock_raw_sessions, None)) as mock_fetch:

            items, err = self.service.session_broker.fetch_timetable_json("user_auto_refresh")
            self.assertIsNone(err)
            self.assertEqual(items, mock_raw_sessions)
            mock_fetch.assert_called_once()
            # Verify fetch was called with fresh JWT
            self.assertEqual(mock_fetch.call_args[0][0], fresh_jwt)

            # Verify SQLite stored session was automatically updated with fresh JWT
            updated = self.service.get_upes_session("user_auto_refresh")
            self.assertEqual(updated[0], fresh_jwt)

    def test_broker_preserves_last_known_good_when_bridge_unavailable(self):
        # 1. Pre-seed last known good timetable
        good_payload = json.dumps([
            {"course_name": "Real Distributed Systems", "date": "2026-08-19", "start_time": "09:00", "end_time": "10:00"}
        ])
        self.service.upload_timetable("user_lkg", good_payload)

        # 2. Store expired token and CDP unavailable
        expired_jwt = self._make_jwt(time.time() - 3600)
        self.service.save_upes_session("user_lkg", expired_jwt, "3a678d8e-8817-41e6-b1a8-5a3ec6ee4948", expires_at=time.time() - 3600)

        with unittest.mock.patch.object(self.bridge, "is_cdp_available", return_value=False):
            success, msg, count = self.service.fetch_and_store_upes_timetable("user_lkg")
            self.assertFalse(success)
            self.assertIn("auth_required", msg)

            # Verify last-known-good timetable in SQLite is preserved!
            stored_sessions, _ = self.service.load_timetable_sessions("user_lkg", rolling_two_weeks=False)
            self.assertEqual(len(stored_sessions), 1)
            self.assertEqual(stored_sessions[0].course_name, "Real Distributed Systems")


class TestRollingTwoWeekTimetableAndRBAC(unittest.TestCase):
    """Verifies rolling two-week timetable windows, deduplication, anomaly protection, and RBAC."""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, "test_two_week.db")
        self.conn_factory = lambda: sqlite3.connect(self.db_path)

        conn = self.conn_factory()
        timetable_sync.init_timetable_tables(conn)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                password_hash TEXT,
                salt TEXT,
                role TEXT,
                is_disabled INTEGER DEFAULT 0,
                privileges TEXT,
                created_at REAL
            )
        """)
        conn.close()
        self.service = TimetableService(self.conn_factory)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_two_week_date_window_calculation(self):
        # Anchor to a fixed Wednesday: 2026-08-19
        ref_dt = datetime.date(2026, 8, 19)
        w1_s, w1_e, w2_s, w2_e = timetable_sync.get_rolling_two_week_window(ref_dt)

        self.assertEqual(w1_s, datetime.date(2026, 8, 17))  # Monday
        self.assertEqual(w1_e, datetime.date(2026, 8, 23))  # Sunday
        self.assertEqual(w2_s, datetime.date(2026, 8, 24))  # Monday
        self.assertEqual(w2_e, datetime.date(2026, 8, 30))  # Sunday

    def test_date_normalization_formats(self):
        # Native UPES Month string
        self.assertEqual(timetable_sync._normalize_date_string("2026-Aug-03"), "2026-08-03")
        self.assertEqual(timetable_sync._normalize_date_string("2026-Aug-24"), "2026-08-24")
        self.assertEqual(timetable_sync._normalize_date_string("2026-Sep-15"), "2026-09-15")
        self.assertEqual(timetable_sync._normalize_date_string("2026-10-31"), "2026-10-31")
        self.assertEqual(timetable_sync._normalize_date_string("24/08/2026"), "2026-08-24")
        self.assertEqual(timetable_sync._normalize_date_string("2026-08-19T09:15:00Z"), "2026-08-19")

    def test_cross_week_deterministic_identity(self):
        # Two identical classes on two different Mondays (Week 1 and Week 2)
        raw_w1 = {
            "course_name": "Deep Learning",
            "course_code": "CSAI3027P_5",
            "SlotDate": "2026-Aug-17",
            "SlotStartTime": "09:00 AM",
            "SlotEndTime": "09:55 AM",
            "FloorPlanDetails": {"VenueName": "11213"},
            "TeacherList": [{"Name": "Amit Panwar"}]
        }
        raw_w2 = {
            "course_name": "Deep Learning",
            "course_code": "CSAI3027P_5",
            "SlotDate": "2026-Aug-24",
            "SlotStartTime": "09:00 AM",
            "SlotEndTime": "09:55 AM",
            "FloorPlanDetails": {"VenueName": "11213"},
            "TeacherList": [{"Name": "Amit Panwar"}]
        }

        s1 = normalize_upes_session(raw_w1)
        s2 = normalize_upes_session(raw_w2)

        self.assertIsNotNone(s1)
        self.assertIsNotNone(s2)
        self.assertEqual(s1.date, "2026-08-17")
        self.assertEqual(s2.date, "2026-08-24")

        # Distinct session IDs and deterministic hashes across weeks
        self.assertNotEqual(s1.session_id, s2.session_id)
        self.assertNotEqual(s1.deterministic_hash, s2.deterministic_hash)

    def test_two_week_filtering_and_merge(self):
        raw_schedule = [
            # Past session
            {"course_name": "Old Class", "SlotDate": "2026-Aug-03", "SlotStartTime": "09:00 AM", "SlotEndTime": "10:00 AM"},
            # Week 1 session
            {"course_name": "Week 1 Class", "SlotDate": "2026-Aug-19", "SlotStartTime": "09:00 AM", "SlotEndTime": "10:00 AM"},
            # Week 2 session
            {"course_name": "Week 2 Class", "SlotDate": "2026-Aug-26", "SlotStartTime": "09:00 AM", "SlotEndTime": "10:00 AM"},
            # Future session (beyond 2 weeks)
            {"course_name": "Future Class", "SlotDate": "2026-Sep-15", "SlotStartTime": "09:00 AM", "SlotEndTime": "10:00 AM"},
        ]

        self.service.upload_timetable("user_2w", json.dumps(raw_schedule))

        # Test full load
        all_sessions, _ = self.service.load_timetable_sessions("user_2w", rolling_two_weeks=False)
        self.assertEqual(len(all_sessions), 4)

        # Test rolling 2-week window filtering
        w1_s = datetime.date(2026, 8, 17)
        w2_e = datetime.date(2026, 8, 30)
        filtered = timetable_sync.filter_sessions_by_window(all_sessions, w1_s, w2_e)
        self.assertEqual(len(filtered), 2)
        self.assertEqual(filtered[0].course_name, "Week 1 Class")
        self.assertEqual(filtered[1].course_name, "Week 2 Class")

    def test_reconciliation_preserves_past_and_future_outside_window(self):
        # 1. Seed existing managed mappings in DB for Past (Aug 03), Current (Aug 19), Future (Sep 15)
        now = time.time()
        conn = self.conn_factory()
        conn.execute("""
            INSERT INTO timetable_events_map
            (id, user_id, source_session_id, source_date, google_calendar_id, google_event_id, source_hash, summary, start_time, end_time, last_synced_at, status)
            VALUES
            ('user_pres:s_past:2026-08-03', 'user_pres', 's_past', '2026-08-03', 'primary', 'g_past', 'h1', 'Past Class', '09:00:00', '10:00:00', ?, 'synced'),
            ('user_pres:s_curr:2026-08-19', 'user_pres', 's_curr', '2026-08-19', 'primary', 'g_curr', 'h2', 'Current Class', '09:00:00', '10:00:00', ?, 'synced'),
            ('user_pres:s_fut:2026-09-15', 'user_pres', 's_fut', '2026-09-15', 'primary', 'g_fut', 'h3', 'Future Class', '09:00:00', '10:00:00', ?, 'synced')
        """, (now, now, now))
        conn.commit()
        conn.close()

        # 2. Sync incoming two-week sessions covering only Aug 17 to Aug 30
        mock_cal = MockGoogleCalendarClient("user_pres")
        syncer = TimetableSynchronizer(self.conn_factory, "user_pres", mock_cal, "primary")

        incoming_sessions = [
            TimetableSession("Current Class", "CS101", "2026-08-19", "09:00:00", "10:00:00", "101", "Prof A", "s_curr", "upes", {})
        ]

        result = syncer.synchronize(incoming_sessions)

        # 3. Verify: Past (Aug 03) and Future (Sep 15) MUST NOT be deleted
        self.assertEqual(result["deleted"], 0)
        self.assertEqual(mock_cal.calls["delete"], 0)

        conn = self.conn_factory()
        cur = conn.cursor()
        cur.execute("SELECT source_date, status FROM timetable_events_map WHERE user_id = 'user_pres'")
        statuses = dict(cur.fetchall())
        conn.close()

        self.assertEqual(statuses.get("2026-08-03"), "synced")
        self.assertEqual(statuses.get("2026-09-15"), "synced")

    def test_anomaly_protection_empty_payload_preserves_lkg(self):
        # 1. Seed valid timetable
        lkg_data = json.dumps([{"course_name": "Valid LKG Class", "date": "2026-08-19", "start_time": "09:00", "end_time": "10:00"}])
        self.service.upload_timetable("user_anom", lkg_data)

        # 2. Mock broker returning empty list
        with unittest.mock.patch.object(self.service.session_broker, "fetch_timetable_json", return_value=([], None)):
            success, msg, count = self.service.fetch_and_store_upes_timetable("user_anom")
            self.assertFalse(success)
            self.assertTrue("malformed" in msg.lower() or "empty" in msg.lower() or "no session items" in msg.lower())

            # Verify LKG schedule was preserved
            sessions, _ = self.service.load_timetable_sessions("user_anom", rolling_two_weeks=False)
            self.assertEqual(len(sessions), 1)
            self.assertEqual(sessions[0].course_name, "Valid LKG Class")


if __name__ == "__main__":
    unittest.main()
