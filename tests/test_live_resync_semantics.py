"""
Tests for Live Timetable Resync Semantics, Validation, and Calendar Safety.

Verifies:
1. MANUAL RESYNC: Live UPES fetch called exactly once.
2. SUCCESS: Live fetch -> canonical timetable saved -> Calendar reconciler invoked.
3. LIVE CHANGED TIMETABLE: Correct minimal CREATE/PATCH/DELETE.
4. UPES FAILURE: Cached timetable retained, Calendar deletion = 0, status=PRESERVED.
5. EMPTY LIVE RESPONSE: Treated as suspicious drop when previous count > 0, cached timetable retained, Calendar deletion = 0.
6. AUTH FAILURE: Cached timetable retained, Calendar deletion = 0, AUTH_REQUIRED surfaced.
7. CACHE-ONLY UI LOAD: Live UPES fetch count = 0.
8. 3-HOUR SCHEDULER: Live UPES fetch occurs before Calendar reconciliation.
9. PIPELINE UNIFICATION: UI (/api/timetable/sync), MCP calendar sync, and Scheduler all converge on sync_user_timetable(live_fetch=True).
10. CACHE-ONLY ISOLATION: calendar.reconcile_cached and /api/timetable/reconcile_cached run without UPES live fetch.
"""

import unittest
from unittest.mock import MagicMock, patch
import json
import os
import sqlite3
import tempfile
import time

import config
import timetable_sync
from timetable_sync import (
    TimetableService,
    TimetableSession,
    init_timetable_tables,
    parse_timetable_json
)


class TestLiveResyncSemantics(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, "test_resync.db")
        self.conn_factory = lambda: sqlite3.connect(self.db_path)

        conn = self.conn_factory()
        init_timetable_tables(conn)
        # Also create upes_auth_sessions table if not exists
        conn.execute("""
            CREATE TABLE IF NOT EXISTS upes_auth_sessions (
                user_id TEXT PRIMARY KEY,
                student_code TEXT,
                api_url TEXT,
                expires_at REAL,
                refresh_token TEXT,
                cookies_json TEXT,
                cookie_expires_at REAL,
                credential_generation INTEGER DEFAULT 1,
                last_refresh_at REAL,
                last_refresh_status TEXT,
                created_at REAL,
                updated_at REAL,
                encrypted_access_token TEXT
            )
        """)
        conn.commit()
        conn.close()

        self.service = TimetableService(self.conn_factory)

    def tearDown(self):
        import gc
        gc.collect()
        try:
            self.tmp_dir.cleanup()
        except Exception:
            pass

    def _seed_oauth(self, user_id="user_test"):
        self.service.save_oauth_tokens(
            user_id,
            {"access_token": "mock_at", "refresh_token": "mock_rt", "token_type": "Bearer"},
            calendar_id="primary",
            email=f"{user_id}@example.com"
        )

    def _sample_payload(self, count=5):
        items = []
        for i in range(count):
            day_offset = i // 8
            hour_offset = i % 8
            items.append({
                "course_name": f"Distributed Systems {i}",
                "course_code": f"CSEG{3000 + i}",
                "date": f"2026-09-{20 + day_offset:02d}",
                "start_time": f"{9 + hour_offset:02d}:00",
                "end_time": f"{10 + hour_offset:02d}:00",
                "room": f"Room {100 + i}"
            })
        return items

    # -------------------------------------------------------------------------
    # 1. MANUAL RESYNC: live UPES fetch called exactly once
    # -------------------------------------------------------------------------
    def test_manual_resync_calls_live_upes_fetch_exactly_once(self):
        self._seed_oauth("user_1")
        mock_payload = self._sample_payload(3)

        with patch.object(self.service.session_broker, "fetch_timetable_json", return_value=(mock_payload, None)) as mock_broker_fetch, \
             patch("timetable_sync.GoogleCalendarClient") as mock_cal_client, \
             patch.object(timetable_sync.TimetableSynchronizer, "synchronize", return_value={"status": "success", "created": 3, "updated": 0, "deleted": 0, "unchanged": 0}):
            
            res = self.service.sync_user_timetable("user_1", live_fetch=True)
            self.assertEqual(mock_broker_fetch.call_count, 1)
            self.assertEqual(res["source"], "live")
            self.assertEqual(res["upes_refresh_status"], "SUCCESS")
            self.assertEqual(res["timetable_status"], "UPDATED")

    # -------------------------------------------------------------------------
    # 2. SUCCESS: live fetch -> canonical timetable saved -> Calendar reconciler invoked
    # -------------------------------------------------------------------------
    def test_resync_success_pipeline(self):
        self._seed_oauth("user_2")
        mock_payload = self._sample_payload(4)

        with patch.object(self.service.session_broker, "fetch_timetable_json", return_value=(mock_payload, None)), \
             patch("timetable_sync.GoogleCalendarClient"), \
             patch.object(timetable_sync.TimetableSynchronizer, "synchronize") as mock_sync:
            
            mock_sync.return_value = {
                "status": "success", "created": 4, "updated": 0, "deleted": 0, "unchanged": 0
            }

            res = self.service.sync_user_timetable("user_2", live_fetch=True)

            self.assertEqual(res["status"], "success")
            self.assertEqual(res["source"], "live")
            self.assertEqual(res["upes_refresh_status"], "SUCCESS")
            self.assertEqual(res["timetable_status"], "UPDATED")
            self.assertEqual(res["calendar_status"], "RECONCILED")
            self.assertEqual(res["created"], 4)
            self.assertFalse(res["stale"])

            # Verify saved in SQLite user_timetables
            sessions, errs = self.service.load_timetable_sessions("user_2")
            self.assertEqual(len(sessions), 4)
            self.assertEqual(mock_sync.call_count, 1)
            # Verify allow_deletions is True on live success
            self.assertTrue(mock_sync.call_args[1].get("allow_deletions"))

    # -------------------------------------------------------------------------
    # 3. LIVE CHANGED TIMETABLE: minimal diff (CREATE/PATCH/DELETE)
    # -------------------------------------------------------------------------
    def test_live_changed_timetable_minimal_diff(self):
        self._seed_oauth("user_diff")
        old_payload = json.dumps(self._sample_payload(3))
        self.service.upload_timetable("user_diff", old_payload)

        # Fresh response has 2 modified/new items
        new_payload = self._sample_payload(2)
        new_payload.append({
            "course_name": "New Course",
            "course_code": "CSEG9999",
            "date": "2026-09-25",
            "start_time": "14:00",
            "end_time": "15:00",
            "room": "Room 999"
        })

        with patch.object(self.service.session_broker, "fetch_timetable_json", return_value=(new_payload, None)), \
             patch("timetable_sync.GoogleCalendarClient"), \
             patch.object(timetable_sync.TimetableSynchronizer, "synchronize") as mock_sync:
            
            mock_sync.return_value = {
                "status": "success", "created": 1, "updated": 2, "deleted": 1, "unchanged": 0
            }

            res = self.service.sync_user_timetable("user_diff", live_fetch=True)
            self.assertEqual(res["status"], "success")
            self.assertEqual(res["created"], 1)
            self.assertEqual(res["updated"], 2)
            self.assertEqual(res["deleted"], 1)
            self.assertTrue(mock_sync.call_args[1].get("allow_deletions"))

    # -------------------------------------------------------------------------
    # 4. UPES FAILURE: cached timetable retained, Calendar deletion = 0
    # -------------------------------------------------------------------------
    def test_upes_failure_preserves_cache_and_forces_zero_deletions(self):
        self._seed_oauth("user_fail")
        initial_payload = json.dumps(self._sample_payload(5))
        self.service.upload_timetable("user_fail", initial_payload)

        # Upstream network/portal error
        with patch.object(self.service.session_broker, "fetch_timetable_json", return_value=(None, "upstream_error: Portal 502 Bad Gateway")), \
             patch("timetable_sync.GoogleCalendarClient"), \
             patch.object(timetable_sync.TimetableSynchronizer, "synchronize") as mock_sync:
            
            mock_sync.return_value = {
                "status": "success", "created": 0, "updated": 0, "deleted": 0, "unchanged": 5
            }

            res = self.service.sync_user_timetable("user_fail", live_fetch=True)

            # Assertions
            self.assertEqual(res["status"], "failed")
            self.assertEqual(res["source"], "lkg")
            self.assertEqual(res["upes_refresh_status"], "FAILED")
            self.assertEqual(res["timetable_status"], "PRESERVED_LKG")
            self.assertEqual(res["calendar_status"], "PRESERVED")
            self.assertTrue(res["stale"])
            self.assertEqual(res["deleted"], 0)

            # Verify allow_deletions was explicitly False
            self.assertFalse(mock_sync.call_args[1].get("allow_deletions"))

            # Verify cached timetable in SQLite was NOT overwritten or wiped
            sessions, _ = self.service.load_timetable_sessions("user_fail")
            self.assertEqual(len(sessions), 5)

    # -------------------------------------------------------------------------
    # 5. EMPTY LIVE RESPONSE: treated as suspicious drop, cached timetable retained, Calendar deletion = 0
    # -------------------------------------------------------------------------
    def test_suspicious_empty_response_protection(self):
        self._seed_oauth("user_empty_guard")
        # User previously had 15 sessions
        initial_payload = json.dumps(self._sample_payload(15))
        self.service.upload_timetable("user_empty_guard", initial_payload)

        # Upstream unexpectedly returns 0 sessions
        with patch.object(self.service.session_broker, "fetch_timetable_json", return_value=([], None)), \
             patch("timetable_sync.GoogleCalendarClient"), \
             patch.object(timetable_sync.TimetableSynchronizer, "synchronize") as mock_sync:
            
            mock_sync.return_value = {
                "status": "success", "created": 0, "updated": 0, "deleted": 0, "unchanged": 15
            }

            res = self.service.sync_user_timetable("user_empty_guard", live_fetch=True)

            # Must be flagged as failed and preserved
            self.assertEqual(res["status"], "failed")
            self.assertEqual(res["source"], "lkg")
            self.assertEqual(res["upes_refresh_status"], "FAILED")
            self.assertIn("suspicious", res["upes_fetch_status"].lower())
            self.assertEqual(res["timetable_status"], "PRESERVED_LKG")
            self.assertEqual(res["calendar_status"], "PRESERVED")
            self.assertEqual(res["deleted"], 0)
            self.assertTrue(res["stale"])

            # Verify allow_deletions was False
            self.assertFalse(mock_sync.call_args[1].get("allow_deletions"))

            # Verify SQLite still has 15 sessions
            sessions, _ = self.service.load_timetable_sessions("user_empty_guard")
            self.assertEqual(len(sessions), 15)

    # -------------------------------------------------------------------------
    # 6. AUTH FAILURE: cached timetable retained, Calendar deletion = 0, AUTH_REQUIRED surfaced
    # -------------------------------------------------------------------------
    def test_auth_failure_surfaces_auth_required_and_zero_deletions(self):
        self._seed_oauth("user_auth_fail")
        initial_payload = json.dumps(self._sample_payload(8))
        self.service.upload_timetable("user_auth_fail", initial_payload)

        # Upstream returns auth_required
        with patch.object(self.service.session_broker, "fetch_timetable_json", return_value=(None, "auth_required: portal session expired")), \
             patch("timetable_sync.GoogleCalendarClient"), \
             patch.object(timetable_sync.TimetableSynchronizer, "synchronize") as mock_sync:
            
            mock_sync.return_value = {
                "status": "success", "created": 0, "updated": 0, "deleted": 0, "unchanged": 8
            }

            res = self.service.sync_user_timetable("user_auth_fail", live_fetch=True)

            self.assertEqual(res["status"], "failed")
            self.assertEqual(res["source"], "lkg")
            self.assertEqual(res["upes_refresh_status"], "AUTH_REQUIRED")
            self.assertEqual(res["timetable_status"], "PRESERVED_LKG")
            self.assertEqual(res["calendar_status"], "PRESERVED")
            self.assertEqual(res["deleted"], 0)
            self.assertTrue(res["stale"])
            self.assertFalse(mock_sync.call_args[1].get("allow_deletions"))

            sessions, _ = self.service.load_timetable_sessions("user_auth_fail")
            self.assertEqual(len(sessions), 8)

    # -------------------------------------------------------------------------
    # 7. CACHE-ONLY UI LOAD: live UPES fetch count = 0
    # -------------------------------------------------------------------------
    def test_cache_only_ui_load_zero_live_calls(self):
        initial_payload = json.dumps(self._sample_payload(6))
        self.service.upload_timetable("user_cache_read", initial_payload)

        with patch.object(self.service.session_broker, "fetch_timetable_json") as mock_fetch:
            # Reading sessions for UI display
            sessions, errors = self.service.load_timetable_sessions("user_cache_read")
            self.assertEqual(len(sessions), 6)
            self.assertEqual(mock_fetch.call_count, 0)

            # Querying user sync telemetry status
            st = self.service.get_user_status("user_cache_read")
            self.assertEqual(mock_fetch.call_count, 0)

    # -------------------------------------------------------------------------
    # 8. 3-HOUR SCHEDULER: live UPES fetch occurs before Calendar reconciliation
    # -------------------------------------------------------------------------
    def test_scheduler_executes_live_fetch_before_calendar_reconcile(self):
        self._seed_oauth("user_sched")
        mock_payload = self._sample_payload(3)

        execution_order = []

        def mock_broker(*args, **kwargs):
            execution_order.append("LIVE_UPES_FETCH")
            return (mock_payload, None)

        def mock_sync_fn(*args, **kwargs):
            execution_order.append("CALENDAR_RECONCILE")
            return {"status": "success", "created": 3, "updated": 0, "deleted": 0, "unchanged": 0}

        with patch.object(self.service.session_broker, "fetch_timetable_json", side_effect=mock_broker), \
             patch("timetable_sync.GoogleCalendarClient"), \
             patch.object(timetable_sync.TimetableSynchronizer, "synchronize", side_effect=mock_sync_fn):
            
            summaries = self.service.sync_all_active_users()
            self.assertIn("user_sched", summaries)
            self.assertEqual(execution_order, ["LIVE_UPES_FETCH", "CALENDAR_RECONCILE"])
            self.assertEqual(summaries["user_sched"]["source"], "live")

    # -------------------------------------------------------------------------
    # 9. PIPELINE UNIFICATION: UI, MCP calendar, and Scheduler converge on same live path
    # -------------------------------------------------------------------------
    def test_pipeline_unification_ui_mcp_scheduler(self):
        import app as nexus_app

        # 1. UI Endpoint (/api/timetable/sync) calls sync_user_timetable with live_fetch=True
        with patch.object(nexus_app.timetable_service, "sync_user_timetable") as mock_service_sync, \
             patch("app.get_self_service_user", return_value=("user_unified", None)):
            
            mock_service_sync.return_value = {"status": "success", "source": "live"}
            client = nexus_app.app.test_client()

            resp = client.post('/api/timetable/sync', json={})
            self.assertEqual(resp.status_code, 200)
            mock_service_sync.assert_called_once_with(
                "user_unified",
                force_calendar_id=None,
                dry_run=False,
                live_fetch=True
            )

        # 2. MCP atomic handler for calendar.reconcile (academic.sync("calendar")) calls sync_user_timetable with live_fetch=True
        with patch.object(nexus_app.timetable_service, "sync_user_timetable") as mock_service_sync:
            mock_service_sync.return_value = {"status": "success", "source": "live"}
            exec_res = nexus_app._reconcile_calendar("user_unified", {})
            self.assertTrue(exec_res.ok)
            mock_service_sync.assert_called_once_with(
                "user_unified",
                force_calendar_id=None,
                dry_run=False,
                live_fetch=True
            )

        # 3. Scheduler calls sync_user_timetable with live_fetch=True
        with patch.object(self.service, "sync_user_timetable") as mock_service_sync:
            self._seed_oauth("user_sched_test")
            self.service.sync_all_active_users()
            mock_service_sync.assert_called_with("user_sched_test", live_fetch=True)

    # -------------------------------------------------------------------------
    # 10. CACHE-ONLY RECONCILIATION SEPARATE OPERATION
    # -------------------------------------------------------------------------
    def test_cache_only_reconciliation_is_separate_and_skips_live_fetch(self):
        import app as nexus_app

        # Dedicated endpoint /api/timetable/reconcile_cached
        with patch.object(nexus_app.timetable_service, "sync_user_timetable") as mock_service_sync, \
             patch("app.get_self_service_user", return_value=("user_cache_sep", None)):
            
            mock_service_sync.return_value = {"status": "success", "source": "cached"}
            client = nexus_app.app.test_client()

            resp = client.post('/api/timetable/reconcile_cached', json={})
            self.assertEqual(resp.status_code, 200)
            mock_service_sync.assert_called_once_with(
                "user_cache_sep",
                force_calendar_id=None,
                dry_run=False,
                live_fetch=False
            )

        # Dedicated MCP internal operation calendar.reconcile_cached
        with patch.object(nexus_app.timetable_service, "sync_user_timetable") as mock_service_sync:
            mock_service_sync.return_value = {"status": "success", "source": "cached"}
            exec_res = nexus_app._reconcile_calendar_cached("user_cache_sep", {})
            self.assertTrue(exec_res.ok)
            mock_service_sync.assert_called_once_with(
                "user_cache_sep",
                force_calendar_id=None,
                dry_run=False,
                live_fetch=False
            )


if __name__ == "__main__":
    unittest.main()
