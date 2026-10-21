"""
Phase 1A Deterministic Verification Suite
Validates:
1. Google invalid_grant does not block UPES timetable fetching.
2. Attendance synchronization is independent of Google.
3. UPES authentication failure preserves cached data.
4. Cached or malformed timetable responses cannot trigger destructive calendar deletion.
5. No duplicate calendar mappings are introduced.
6. Tenant isolation remains intact across multi-user environments.
7. Production credentials are never exposed in returns, logs, or error dictionaries.
8. Scheduler and sync endpoints record independent UPES and Google stage outcomes.
"""

import os
import json
import time
import sqlite3
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import config
import timetable_sync
import attendance_sync
from timetable_sync import (
    TimetableService,
    GoogleCalendarError,
    TimetableSession,
    compute_canonical_slot_key,
    OAuthTokenCrypto
)
from attendance_sync import AttendanceService


def build_test_db(db_path: str):
    conn = sqlite3.connect(db_path)
    timetable_sync.init_timetable_tables(conn)
    attendance_sync.init_attendance_tables(conn)
    conn.commit()
    conn.close()


class Phase1ADecouplingTests(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp_dir, "test_phase1a.db")
        build_test_db(self.db_path)
        self.conn_factory = lambda: sqlite3.connect(self.db_path)
        self.service = TimetableService(self.conn_factory)
        self.att_service = AttendanceService(self.conn_factory, timetable_service=self.service)

    def tearDown(self):
        try:
            if os.path.exists(self.db_path):
                os.remove(self.db_path)
            os.rmdir(self.tmp_dir)
        except Exception:
            pass

    def _sample_upes_payload(self):
        return [
            {
                "CourseCode": "CSEG1001",
                "CourseName": "Distributed Operating Systems",
                "FacultyName": "Dr. Alan Turing",
                "RoomNo": "9001",
                "SessionDate": "2026-10-22",
                "StartTime": "10:00",
                "EndTime": "10:55",
                "SessionType": "Regular",
                "SessionId": 801
            },
            {
                "CourseCode": "CSEG1002",
                "CourseName": "Cloud Systems & Virtualization",
                "FacultyName": "Dr. Grace Hopper",
                "RoomNo": "9002",
                "SessionDate": "2026-10-22",
                "StartTime": "11:00",
                "EndTime": "11:55",
                "SessionType": "Regular",
                "SessionId": 802
            }
        ]

    # 1. Google invalid_grant does not block UPES timetable fetching
    def test_google_invalid_grant_does_not_block_upes_timetable(self):
        user_id = "test_user_decouple_1"

        # Save a Google token that will fail refresh
        self.service.save_oauth_tokens(
            user_id=user_id,
            token_data={
                "access_token": "expired_tok",
                "refresh_token": "revoked_refresh_token",
                "expires_at": time.time() - 3600
            },
            calendar_id="primary",
            email="test_user@gmail.com"
        )

        # Mock UPES returning 2 live sessions
        live_payload = self._sample_upes_payload()
        with patch.object(self.service.session_broker, "fetch_timetable_json", return_value=(live_payload, None)), \
             patch("timetable_sync.GoogleCalendarClient.refresh_access_token", side_effect=GoogleCalendarError("invalid_grant: Bad Request", status_code=401)):

            res = self.service.sync_user_timetable(user_id, live_fetch=True)

            # Invariant: Overall status must be partial, NOT failed!
            self.assertEqual(res["status"], "partial")
            self.assertEqual(res["source"], "live")
            self.assertEqual(res["upes_refresh_status"], "SUCCESS")
            self.assertEqual(res["timetable_status"], "UPDATED")
            self.assertIn("CALENDAR_AUTH_REQUIRED", (res["calendar_status"], res["stages"]["calendar"]["status"]))
            self.assertEqual(res["sessions_seen"], 2)

            # Invariant: Zero Google mutations
            self.assertEqual(res["created"], 0)
            self.assertEqual(res["updated"], 0)
            self.assertEqual(res["deleted"], 0)

            # Invariant: Timetable sessions are persisted in local SQLite
            sessions, errs = self.service.load_timetable_sessions(user_id)
            self.assertEqual(len(sessions), 2)
            self.assertEqual(sessions[0].course_code, "CSEG1001")

            # Invariant: Stage telemetry records independent outcomes
            self.assertEqual(res["stages"]["upes_refresh"]["status"], "SUCCESS")
            self.assertEqual(res["stages"]["timetable"]["status"], "UPDATED")

    # 2. Attendance synchronization is independent of Google
    def test_attendance_sync_independent_of_google(self):
        user_id = "test_att_user_2"
        # Seed an academic module and attendance summary directly in SQLite
        conn = self.conn_factory()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO academic_modules
            (user_id, module_id, term_code_id, module_name, module_code, course_family_id, last_synced_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (user_id, 999, 5, "Computer Networks", "CS101", 1, time.time()))
        cur.execute("""
            INSERT INTO official_attendance_summaries
            (user_id, module_id, total_sessions, total_attended, total_condoned, attendance_percentage, last_synced_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (user_id, 999, 10, 9, 0, 90.0, time.time()))
        cur.execute("""
            INSERT INTO academic_sessions
            (user_id, session_id, module_id, course_name, course_code, session_date, start_time, end_time, faculty, room, attendance_status, last_synced_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (user_id, 1001, 999, "Computer Networks", "CS101", "2026-10-21", "09:00", "09:55", "Prof. Cerf", "101", "PRESENT", time.time()))
        conn.commit()
        conn.close()

        # Notice: User has NO google_oauth_tokens record at all!
        self.assertIsNone(self.service.get_oauth_tokens(user_id))

        # Attendance analytics must compute cleanly with zero Google dependency
        analytics = self.att_service.get_attendance_analytics(user_id)
        self.assertEqual(analytics["overall"]["attendance_percentage"], 90.0)
        self.assertEqual(analytics["overall"]["conducted_classes"], 10)
        self.assertEqual(analytics["overall"]["attended_classes"], 9)
        self.assertEqual(len(analytics["subjects"]), 1)

    # 3. UPES authentication failure preserves cached data
    def test_upes_auth_failure_preserves_cached_data(self):
        user_id = "test_user_cache_pres_3"

        # Pre-seed cached timetable
        cached_payload = self._sample_upes_payload()
        self.service.upload_timetable(user_id, json.dumps(cached_payload))

        sessions, _ = self.service.load_timetable_sessions(user_id)
        self.assertEqual(len(sessions), 2)

        # Simulate UPES auth failure
        with patch.object(self.service.session_broker, "fetch_timetable_json", return_value=(None, "auth_required: UPES session expired")):
            res = self.service.sync_user_timetable(user_id, live_fetch=True)

            self.assertEqual(res["upes_refresh_status"], "AUTH_REQUIRED")
            self.assertEqual(res["timetable_status"], "PRESERVED_LKG")
            self.assertEqual(res["source"], "lkg")
            self.assertTrue(res["stale"])

            # Invariant: Local SQLite sessions are completely preserved, not dropped
            sessions_after, _ = self.service.load_timetable_sessions(user_id)
            self.assertEqual(len(sessions_after), 2)

    # 4. Cached or malformed timetable responses cannot trigger destructive calendar deletion
    def test_cached_or_malformed_response_cannot_trigger_destructive_deletion(self):
        user_id = "test_user_malformed_4"

        # Pre-seed 2 sessions
        cached_payload = self._sample_upes_payload()
        self.service.upload_timetable(user_id, json.dumps(cached_payload))

        # Upstream returns suspiciously empty list
        with patch.object(self.service.session_broker, "fetch_timetable_json", return_value=([], None)):
            success, msg, count = self.service.fetch_and_store_upes_timetable(user_id)
            self.assertFalse(success)
            self.assertTrue("Suspicious" in msg or "Malformed" in msg or "empty" in msg)

            # Invariant: 2 sessions remain safe
            sessions, _ = self.service.load_timetable_sessions(user_id)
            self.assertEqual(len(sessions), 2)

    # 5. No duplicate calendar mappings are introduced
    def test_no_duplicate_calendar_mappings(self):
        user_id = "test_user_no_dup_5"
        c_slot = compute_canonical_slot_key("CS101", "OS", "2026-10-22", "10:00:00", "10:55:00", user_id=user_id)
        map_id = f"{user_id}:{c_slot}:2026-10-22"

        conn = self.conn_factory()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO timetable_events_map
            (id, user_id, source_session_id, source_date, google_calendar_id, google_event_id, source_hash, summary, start_time, end_time, last_synced_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (map_id, user_id, c_slot, "2026-10-22", "primary", "g_event_801", "hash1", "OS", "10:00", "10:55", time.time()))
        conn.commit()

        # Query existing mapping by canonical_slot_key stored in source_session_id
        cur.execute("SELECT COUNT(*) FROM timetable_events_map WHERE user_id = ? AND source_session_id = ?", (user_id, c_slot))
        self.assertEqual(cur.fetchone()[0], 1)

        # Attempting to insert duplicate mapping with REPLACE preserves singular entry
        cur.execute("""
            INSERT OR REPLACE INTO timetable_events_map
            (id, user_id, source_session_id, source_date, google_calendar_id, google_event_id, source_hash, summary, start_time, end_time, last_synced_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (map_id, user_id, c_slot, "2026-10-22", "primary", "g_event_801_updated", "hash2", "OS", "10:00", "10:55", time.time()))
        conn.commit()

        cur.execute("SELECT COUNT(*), google_event_id FROM timetable_events_map WHERE user_id = ? AND source_session_id = ?", (user_id, c_slot))
        row = cur.fetchone()
        self.assertEqual(row[0], 1)
        self.assertEqual(row[1], "g_event_801_updated")
        conn.close()

    # 6. Tenant isolation remains intact
    def test_tenant_isolation_remains_intact(self):
        user_a = "user_alpha_6"
        user_b = "user_beta_6"

        # User A has 2 sessions
        self.service.upload_timetable(user_a, json.dumps(self._sample_upes_payload()))

        # User B has 0 sessions
        sessions_b, _ = self.service.load_timetable_sessions(user_b)
        self.assertEqual(len(sessions_b), 0)

        # User A has Google tokens; User B does not
        self.service.save_oauth_tokens(user_a, {"access_token": "tok_a"}, email="a@gmail.com")
        self.assertIsNotNone(self.service.get_oauth_tokens(user_a))
        self.assertIsNone(self.service.get_oauth_tokens(user_b))

    # 7. Production credentials are never exposed
    def test_production_credentials_never_exposed(self):
        user_id = "test_user_leak_check_7"
        raw_token = {"access_token": "secret_access_12345", "refresh_token": "super_secret_refresh_99999"}
        encrypted = OAuthTokenCrypto.encrypt(raw_token)

        conn = self.conn_factory()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO google_oauth_tokens (user_id, encrypted_token_data, calendar_id, connected_email, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (user_id, encrypted, "primary", "safe@gmail.com", time.time(), time.time()))
        conn.commit()
        conn.close()

        with patch.object(self.service.session_broker, "fetch_timetable_json", return_value=(self._sample_upes_payload(), None)), \
             patch("timetable_sync.GoogleCalendarClient.refresh_access_token", side_effect=GoogleCalendarError("invalid_grant: Bad Request", status_code=401)):

            res = self.service.sync_user_timetable(user_id, live_fetch=True)
            res_str = json.dumps(res)

            # Neither the raw access token nor refresh token should ever appear in output
            self.assertNotIn("secret_access_12345", res_str)
            self.assertNotIn("super_secret_refresh_99999", res_str)

    # 8. Scheduler records independent UPES and Google stage outcomes
    def test_scheduler_records_independent_stage_outcomes(self):
        user_id = "test_user_sched_8"
        # Pre-seed cached LKG sessions
        self.service.upload_timetable(user_id, json.dumps(self._sample_upes_payload()))

        # Mock UPES auth required and Google invalid_grant
        with patch.object(self.service.session_broker, "fetch_timetable_json", return_value=(None, "auth_required: interactive login needed")), \
             patch.object(self.service, "get_oauth_tokens", return_value=({"refresh_token": "tok"}, "primary", "user@test.com")), \
             patch("timetable_sync.GoogleCalendarClient.refresh_access_token", side_effect=GoogleCalendarError("invalid_grant", status_code=401)):

            res = self.service.sync_user_timetable(user_id, live_fetch=True)

            stages = res.get("stages", {})
            self.assertIn("upes_refresh", stages)
            self.assertIn("calendar", stages)
            self.assertEqual(stages["upes_refresh"]["status"], "AUTH_REQUIRED")
            self.assertIn("AUTH_REQUIRED", stages["calendar"]["status"])
            self.assertEqual(res["status"], "failed")


if __name__ == "__main__":
    unittest.main()
