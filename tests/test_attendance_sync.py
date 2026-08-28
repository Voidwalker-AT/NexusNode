"""
tests/test_attendance_sync.py — Comprehensive Unit & Integration Test Suite
for Authoritative UPES Attendance & Classroom Card-Punch Engine.
"""

import os
import sys
import json
import time
import sqlite3
import tempfile
import unittest
from unittest.mock import MagicMock, patch

# Ensure server root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import config
import attendance_sync
from attendance_sync import (
    calculate_safe_bunks,
    calculate_recovery_classes,
    compute_attendance_percentage,
    init_attendance_tables,
    AttendanceService,
    AttendanceSyncLease
)


class TestAttendanceMathematics(unittest.TestCase):
    """Verifies safe bunk and recovery class algorithms across boundary conditions."""

    def test_safe_bunks_standard_75(self):
        # 17 attended out of 17 conducted -> 5 safe bunks
        # (17 / (17 + 5) = 17/22 = 77.27% >= 75%, 17/23 = 73.91% < 75%)
        self.assertEqual(calculate_safe_bunks(17, 17, 0.75), 5)

        # 9 attended out of 10 conducted -> 2 safe bunks
        # (9 / 12 = 75.0%, 9/13 = 69.23%)
        self.assertEqual(calculate_safe_bunks(9, 10, 0.75), 2)

        # 8 attended out of 10 conducted -> 0 safe bunks
        # (8 / 10 = 80%, 8 / 11 = 72.72% < 75%)
        self.assertEqual(calculate_safe_bunks(8, 10, 0.75), 0)

        # Exactly on threshold: 3 attended out of 4 conducted -> 0 safe bunks
        # (3 / 4 = 75.0%, 3 / 5 = 60.0%)
        self.assertEqual(calculate_safe_bunks(3, 4, 0.75), 0)

    def test_safe_bunks_below_threshold(self):
        # 1 attended out of 2 conducted (50%) -> 0 safe bunks
        self.assertEqual(calculate_safe_bunks(1, 2, 0.75), 0)

        # 0 attended out of 5 conducted -> 0 safe bunks
        self.assertEqual(calculate_safe_bunks(0, 5, 0.75), 0)

    def test_safe_bunks_zero_conducted(self):
        # 0 conducted -> 0 safe bunks (cannot bunk when no classes held)
        self.assertEqual(calculate_safe_bunks(0, 0, 0.75), 0)

    def test_safe_bunks_custom_thresholds(self):
        # 10 attended out of 10 conducted with 80% threshold:
        # 10 / (10 + 2) = 10/12 = 83.3% >= 80%, 10/13 = 76.9% < 80% -> 2 bunks
        self.assertEqual(calculate_safe_bunks(10, 10, 0.80), 2)

        # 10 attended out of 10 conducted with 90% threshold:
        # 10 / (10 + 1) = 10/11 = 90.9% >= 90%, 10/12 = 83.3% < 90% -> 1 bunk
        self.assertEqual(calculate_safe_bunks(10, 10, 0.90), 1)

    def test_recovery_classes_standard_75(self):
        # 1 attended out of 2 conducted (50%):
        # Needs (0.75*2 - 1) / 0.25 = (1.5 - 1)/0.25 = 2 classes
        # Check: (1 + 2) / (2 + 2) = 3/4 = 75.0%
        self.assertEqual(calculate_recovery_classes(1, 2, 0.75), 2)

        # 0 attended out of 1 conducted (0%):
        # Needs (0.75*1 - 0) / 0.25 = 3 classes
        # Check: (0 + 3) / (1 + 3) = 3/4 = 75.0%
        self.assertEqual(calculate_recovery_classes(0, 1, 0.75), 3)

        # 7 attended out of 10 conducted (70%):
        # Needs (0.75*10 - 7) / 0.25 = 0.5 / 0.25 = 2 classes
        # Check: (7 + 2) / (10 + 2) = 9/12 = 75.0%
        self.assertEqual(calculate_recovery_classes(7, 10, 0.75), 2)

    def test_recovery_classes_already_safe(self):
        # 10 attended out of 10 conducted -> 0 recovery
        self.assertEqual(calculate_recovery_classes(10, 10, 0.75), 0)

        # 9 attended out of 10 conducted -> 0 recovery
        self.assertEqual(calculate_recovery_classes(9, 10, 0.75), 0)

        # 0 conducted -> 0 recovery
        self.assertEqual(calculate_recovery_classes(0, 0, 0.75), 0)

    def test_compute_attendance_percentage(self):
        self.assertEqual(compute_attendance_percentage(9, 10), 90.0)
        self.assertEqual(compute_attendance_percentage(8, 10, condoned=1), 90.0)
        self.assertIsNone(compute_attendance_percentage(0, 0))
        self.assertEqual(compute_attendance_percentage(1, 3), 33.33)

    def test_compute_attendance_percentage_semantics(self):
        """Verify that 0 conducted returns None (undefined/not started) rather than false 100%."""
        self.assertIsNone(compute_attendance_percentage(0, 0))
        self.assertIsNone(compute_attendance_percentage(0, -1))
        self.assertEqual(compute_attendance_percentage(0, 5), 0.0)
        self.assertEqual(compute_attendance_percentage(5, 5), 100.0)


class TestAttendanceDatabaseAndService(unittest.TestCase):
    """Tests SQLite persistence, service orchestration, and multi-user isolation."""

    def setUp(self):
        self.temp_db_fd, self.temp_db_path = tempfile.mkstemp(suffix=".db")
        os.close(self.temp_db_fd)
        
        def conn_factory():
            c = sqlite3.connect(self.temp_db_path, timeout=10.0)
            c.row_factory = sqlite3.Row
            return c

        self.conn_factory = conn_factory
        conn = self.conn_factory()
        init_attendance_tables(conn)
        conn.close()
        self.service = AttendanceService(self.conn_factory)

    def tearDown(self):
        try:
            if os.path.exists(self.temp_db_path):
                os.remove(self.temp_db_path)
        except Exception:
            pass

    def test_database_initialization_idempotent(self):
        conn = self.conn_factory()
        init_attendance_tables(conn)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = {r[0] for r in cur.fetchall()}
        conn.close()
        expected = {
            "academic_terms",
            "academic_modules",
            "official_attendance_summaries",
            "academic_sessions",
            "attendance_sync_history",
            "attendance_sync_locks"
        }
        self.assertTrue(expected.issubset(tables))

    def test_attendance_status_empty(self):
        status = self.service.get_attendance_status("user_test")
        self.assertEqual(status["user_id"], "user_test")
        self.assertEqual(status["sync_status"], "NEVER_SYNCED")
        self.assertEqual(status["modules_count"], 0)
        self.assertEqual(status["sessions_count"], 0)
        self.assertIsNone(status["current_term"])

    def test_multi_user_isolation(self):
        now = time.time()
        conn = self.conn_factory()
        # Seed user_1 data
        conn.execute("""
            INSERT INTO academic_modules (user_id, module_id, term_code_id, module_name, module_code, course_family_id, last_synced_at)
            VALUES ('user_1', 101, 5, 'Cryptography and Network Security', 'CSEG3001', 593, ?)
        """, (now,))
        conn.execute("""
            INSERT INTO official_attendance_summaries (user_id, module_id, total_sessions, total_attended, total_condoned, attendance_percentage, last_synced_at)
            VALUES ('user_1', 101, 10, 9, 0, 90.0, ?)
        """, (now,))
        conn.execute("""
            INSERT INTO academic_sessions (user_id, session_id, module_id, course_name, course_code, session_date, start_time, end_time, faculty, room, attendance_status, attendance_subtype, punch_in_time, last_synced_at)
            VALUES ('user_1', 9991, 101, 'Cryptography and Network Security', 'CSEG3001', '2026-08-27', '10:00', '10:55', 'Dr. Smith', '1102', 'PRESENT', 'CRA', '10:01', ?)
        """, (now,))

        # Seed user_2 data
        conn.execute("""
            INSERT INTO academic_modules (user_id, module_id, term_code_id, module_name, module_code, course_family_id, last_synced_at)
            VALUES ('user_2', 202, 5, 'Distributed Systems', 'CSEG3002', 593, ?)
        """, (now,))
        conn.execute("""
            INSERT INTO official_attendance_summaries (user_id, module_id, total_sessions, total_attended, total_condoned, attendance_percentage, last_synced_at)
            VALUES ('user_2', 202, 10, 6, 0, 60.0, ?)
        """, (now,))
        conn.commit()
        conn.close()

        # Query user_1
        analytics_1 = self.service.get_attendance_analytics("user_1")
        self.assertEqual(analytics_1["overall"]["attended_classes"], 9)
        self.assertEqual(analytics_1["overall"]["conducted_classes"], 10)
        self.assertEqual(len(analytics_1["subjects"]), 1)
        self.assertEqual(analytics_1["subjects"][0]["module_id"], 101)
        self.assertEqual(analytics_1["subjects"][0]["safe_bunks_remaining"], 2)

        # Query user_2
        analytics_2 = self.service.get_attendance_analytics("user_2")
        self.assertEqual(analytics_2["overall"]["attended_classes"], 6)
        self.assertEqual(analytics_2["overall"]["conducted_classes"], 10)
        self.assertEqual(len(analytics_2["subjects"]), 1)
        self.assertEqual(analytics_2["subjects"][0]["module_id"], 202)
        self.assertEqual(analytics_2["subjects"][0]["recovery_classes_required"], 6)

        # Query user_3 (non-existent)
        analytics_3 = self.service.get_attendance_analytics("user_3")
        self.assertEqual(analytics_3["overall"]["conducted_classes"], 0)
        self.assertEqual(len(analytics_3["subjects"]), 0)

    def test_cra_card_punch_and_subtype_mapping(self):
        now = time.time()
        conn = self.conn_factory()
        conn.execute("""
            INSERT INTO academic_sessions (
                user_id, session_id, module_id, course_name, session_date, start_time, end_time,
                faculty, room, attendance_status, attendance_subtype, punch_in_time, last_synced_at
            ) VALUES (
                'user_test', 8881, 101, 'Mobile Application Development', '2026-08-28', '11:00', '11:55',
                'Prof. Sharma', '4101', 'PRESENT', 'CRA', '11:02', ?
            )
        """, (now,))
        conn.commit()
        conn.close()

        sessions = self.service.get_sessions("user_test")
        self.assertEqual(len(sessions), 1)
        s = sessions[0]
        self.assertEqual(s["session_id"], 8881)
        self.assertEqual(s["attendance_subtype"], "CRA")
        self.assertEqual(s["punch_in_time"], "11:02")
        self.assertEqual(s["attendance_status"], "PRESENT")

    def test_session_id_collision_prevention(self):
        # Two different sessions held on the same day for the same course
        now = time.time()
        conn = self.conn_factory()
        conn.execute("""
            INSERT INTO academic_sessions (
                user_id, session_id, module_id, course_name, session_date, start_time, end_time,
                faculty, room, attendance_status, attendance_subtype, punch_in_time, last_synced_at
            ) VALUES
            ('user_test', 1001, 101, 'Machine Learning', '2026-08-25', '10:00', '10:55', 'Faculty A', '101', 'PRESENT', 'CRA', '10:01', ?),
            ('user_test', 1002, 101, 'Machine Learning', '2026-08-25', '14:00', '14:55', 'Faculty A', '101', 'ABSENT', 'CRA', '', ?)
        """, (now, now))
        conn.commit()
        conn.close()

        sessions = self.service.get_sessions("user_test")
        self.assertEqual(len(sessions), 2)
        statuses = {s["session_id"]: s["attendance_status"] for s in sessions}
        self.assertEqual(statuses[1001], "PRESENT")
        self.assertEqual(statuses[1002], "ABSENT")


class TestAttendanceSyncMocked(unittest.TestCase):
    """Tests end-to-end sync workflow with mock UPES responses and lease locking."""

    def setUp(self):
        self.temp_db_fd, self.temp_db_path = tempfile.mkstemp(suffix=".db")
        os.close(self.temp_db_fd)
        
        def conn_factory():
            c = sqlite3.connect(self.temp_db_path, timeout=10.0)
            c.row_factory = sqlite3.Row
            return c

        self.conn_factory = conn_factory
        conn = self.conn_factory()
        init_attendance_tables(conn)
        conn.close()

        self.mock_broker = MagicMock()
        self.mock_broker.service.get_upes_session.return_value = (
            "mock_access_token", "student-uuid-1234", "test_user", time.time() + 3600
        )
        self.service = AttendanceService(self.conn_factory, session_broker=self.mock_broker)

    def tearDown(self):
        try:
            if os.path.exists(self.temp_db_path):
                os.remove(self.temp_db_path)
        except Exception:
            pass

    @patch("attendance_sync.execute_upes_attendance_request")
    def test_sync_successful_pipeline(self, mock_exec):
        # 1. Dropdown response
        mock_dropdown = {
            "CourseFamilyDropdownList": [
                {
                    "CourseFamilyId": 593,
                    "CourseFamilyName": "B.Tech CSE",
                    "TermDropdownDetailsList": [
                        {
                            "TermCodeId": 5,
                            "TermCode": "Semester 5",
                            "IsCurrentTerm": True,
                            "TermStartDate": "2026-06-15T00:00:00",
                            "TermEndDate": "2026-12-30T00:00:00",
                            "ModuleDropdownDetailsList": [
                                {"ModuleId": 87945, "ModuleName": "Cryptography and Network Security"}
                            ]
                        }
                    ]
                }
            ]
        }

        # 2. Module Attendance response
        mock_summary = {
            "AttendanceSummary": {
                "TotalSessionCount": 10,
                "TotalAttendance": 9,
                "TotalCondonedAttendanceCount": 0,
                "TotalPresentPercentage": 90.0,
                "TotalPresentPercentageTermWise": 90.0
            },
            "AttendanceInfo": [
                {
                    "AttendanceDetails": [
                        {
                            "SessionId": 554321,
                            "SessionDate": "2026-08-27T00:00:00",
                            "SessionTime": "10:00 - 10:55",
                            "FacultyNames": "Dr. Alice",
                            "AttendanceStatus": "PRESENT",
                            "AttendanceSubTypeCode": "CRA",
                            "StudentPunchInTime": "10:01",
                            "AdditionalDetails": {
                                "ClassRoom": "1102",
                                "Mode": "Class Room",
                                "SessionStatus": "On-Time"
                            }
                        }
                    ]
                }
            ]
        }

        mock_exec.side_effect = [
            (mock_dropdown, None),  # Dropdown call
            (mock_summary, None)    # Module summary call
        ]

        result = self.service.sync_user_attendance("test_user")
        self.assertEqual(result["status"], "ACTIVE")
        self.assertEqual(result["modules_synced"], 1)
        self.assertEqual(result["sessions_synced"], 1)

        # Verify DB content
        status = self.service.get_attendance_status("test_user")
        self.assertEqual(status["sync_status"], "ACTIVE")
        self.assertEqual(status["modules_count"], 1)
        self.assertEqual(status["sessions_count"], 1)
        self.assertEqual(status["current_term"]["term_code"], "Semester 5")

        analytics = self.service.get_attendance_analytics("test_user")
        self.assertEqual(analytics["overall"]["attendance_percentage"], 90.0)
        self.assertEqual(analytics["subjects"][0]["course_name"], "Cryptography and Network Security")
        self.assertEqual(analytics["subjects"][0]["safe_bunks_remaining"], 2)

    @patch("attendance_sync.execute_upes_attendance_request")
    def test_sync_partial_failure_preserves_lkg(self, mock_exec):
        # Seed previous LKG data for module 101 and 102
        now = time.time()
        conn = self.conn_factory()
        conn.execute("""
            INSERT INTO academic_modules (user_id, module_id, term_code_id, module_name, course_family_id, last_synced_at)
            VALUES ('test_user', 101, 5, 'Module A', 593, ?),
                   ('test_user', 102, 5, 'Module B', 593, ?)
        """, (now, now))
        conn.execute("""
            INSERT INTO official_attendance_summaries (user_id, module_id, total_sessions, total_attended, total_condoned, attendance_percentage, last_synced_at)
            VALUES ('test_user', 101, 5, 5, 0, 100.0, ?),
                   ('test_user', 102, 5, 4, 0, 80.0, ?)
        """, (now, now))
        conn.commit()
        conn.close()

        mock_dropdown = {
            "CourseFamilyDropdownList": [
                {
                    "CourseFamilyId": 593,
                    "TermDropdownDetailsList": [
                        {
                            "TermCodeId": 5,
                            "TermCode": "Semester 5",
                            "IsCurrentTerm": True,
                            "ModuleDropdownDetailsList": [
                                {"ModuleId": 101, "ModuleName": "Module A"},
                                {"ModuleId": 102, "ModuleName": "Module B"}
                            ]
                        }
                    ]
                }
            ]
        }

        # Module A succeeds, Module B returns 500 network error
        mock_summary_a = {
            "AttendanceSummary": {
                "TotalSessionCount": 6,
                "TotalAttendance": 6,
                "TotalPresentPercentage": 100.0
            },
            "AttendanceInfo": []
        }

        mock_exec.side_effect = [
            (mock_dropdown, None),
            (mock_summary_a, None),
            (None, "HTTP 500 Internal Server Error")
        ]

        result = self.service.sync_user_attendance("test_user")
        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(result["modules_synced"], 1)
        self.assertEqual(len(result["failed_modules"]), 1)

        # Verify Module B's previous state is preserved
        conn = self.conn_factory()
        cur = conn.cursor()
        cur.execute("SELECT total_sessions, total_attended FROM official_attendance_summaries WHERE user_id = 'test_user' AND module_id = 102")
        row = cur.fetchone()
        conn.close()
        self.assertEqual(row[0], 5)
        self.assertEqual(row[1], 4)

    def test_sync_lease_lock_concurrency(self):
        lease1 = AttendanceSyncLease(self.conn_factory, "user_concurrent", lease_seconds=60)
        lease2 = AttendanceSyncLease(self.conn_factory, "user_concurrent", lease_seconds=60)

        self.assertTrue(lease1.acquire())
        # Second acquisition should fail while lease1 is active
        self.assertFalse(lease2.acquire())

        lease1.release()
        # After release, lease2 can acquire
        self.assertTrue(lease2.acquire())
        lease2.release()

    def test_scheduler_failure_isolation_cases(self):
        import app as flask_app
        task_obj = {"logs": []}

        # Case A: Both succeed
        with patch.object(flask_app.timetable_service, "sync_all_active_users", return_value={"admin": {"created": 1}}), \
             patch.object(flask_app.attendance_service, "sync_all_active_users", return_value={"admin": {"modules_synced": 9}}):
            flask_app.run_timetable_sync_job(task_obj)
            self.assertTrue(any("Timetable sync completed" in log for log in task_obj["logs"]))
            self.assertTrue(any("Attendance sync completed" in log for log in task_obj["logs"]))

        # Case B: Timetable succeeds, Attendance fails
        task_obj_b = {"logs": []}
        with patch.object(flask_app.timetable_service, "sync_all_active_users", return_value={"admin": {"created": 1}}), \
             patch.object(flask_app.attendance_service, "sync_all_active_users", side_effect=Exception("Attendance DB error")):
            flask_app.run_timetable_sync_job(task_obj_b)
            self.assertTrue(any("Timetable sync completed" in log for log in task_obj_b["logs"]))
            self.assertTrue(any("Attendance sync job error" in log for log in task_obj_b["logs"]))

        # Case C: Timetable fails, Attendance succeeds
        task_obj_c = {"logs": []}
        with patch.object(flask_app.timetable_service, "sync_all_active_users", side_effect=Exception("Calendar API Down")), \
             patch.object(flask_app.attendance_service, "sync_all_active_users", return_value={"admin": {"modules_synced": 9}}):
            flask_app.run_timetable_sync_job(task_obj_c)
            self.assertTrue(any("Timetable sync job error" in log for log in task_obj_c["logs"]))
            self.assertTrue(any("Attendance sync completed" in log for log in task_obj_c["logs"]))


if __name__ == "__main__":
    unittest.main()
