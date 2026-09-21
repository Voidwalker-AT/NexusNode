"""
Unit and Integration Tests for Phase 3.5 Attendance Projection, Punch History, and Timetable Export
"""

import os
import shutil
import tempfile
import sqlite3
import unittest

import config
from upes.router import UpesExecutionRouter
from attendance_sync import init_attendance_tables
from timetable_sync import init_timetable_tables


class TestUPESAnalyticsAndTimetable(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="nexus_upes_phase35_")
        self.orig_vault = getattr(config, "AGENT_VAULT_ROOT", None)
        config.AGENT_VAULT_ROOT = self.test_dir

        self.db_path = os.path.join(self.test_dir, "test.db")
        conn = sqlite3.connect(self.db_path)
        init_attendance_tables(conn)
        init_timetable_tables(conn)

        # Seed test attendance records
        conn.execute("""
            INSERT INTO academic_modules (user_id, module_id, term_code_id, module_name, module_code, course_family_id, last_synced_at)
            VALUES ('admin', 101, 1, 'AI and Multimedia', 'CSEG301', 1, 1725000000.0);
        """)
        conn.execute("""
            INSERT INTO official_attendance_summaries (user_id, module_id, total_sessions, total_attended, attendance_percentage, last_synced_at)
            VALUES ('admin', 101, 20, 18, 90.0, 1725000000.0);
        """)
        
        # Seed test punch records
        conn.execute("""
            INSERT INTO academic_sessions (
                user_id, session_id, module_id, course_name, course_code, session_date,
                start_time, end_time, faculty, room, attendance_status, attendance_subtype, punch_in_time, last_synced_at
            ) VALUES (
                'admin', 9001, 101, 'AI and Multimedia', 'CSEG301', '2026-08-30',
                '09:00:00', '10:00:00', 'Dr. Sharma', 'Room 101', 'Present', 'CRA', '09:02', 1725000000.0
            );
        """)

        # Seed test timetable record
        conn.execute("""
            INSERT INTO user_timetables (user_id, raw_json, updated_at)
            VALUES ('admin', ?, 1725000000.0);
        """, (json_tt := '[{"date": "2026-08-30", "start_time": "09:00:00", "end_time": "10:00:00", "course_name": "AI and Multimedia", "course_code": "CSEG301", "room": "101", "faculty": "Dr. Sharma", "is_online": false}]',))

        conn.commit()
        conn.close()

        # Mock timetable service
        mock_tt_svc = type("MockTT", (), {
            "load_timetable_sessions": lambda self, uid, **kw: ([
                type("MockSession", (), {
                    "session_id": "s1",
                    "course_name": "AI and Multimedia",
                    "course_code": "CSEG301",
                    "date": "2026-08-30",
                    "start_time": "09:00:00",
                    "end_time": "10:00:00",
                    "room": "101",
                    "faculty": "Dr. Sharma",
                    "is_online": False,
                    "get_start_iso": lambda self: "2026-08-30T09:00:00",
                    "get_end_iso": lambda self: "2026-08-30T10:00:00"
                })()
            ], "LIVE")
        })()

        self.router = UpesExecutionRouter(
            conn_factory=lambda: sqlite3.connect(self.db_path),
            timetable_service=mock_tt_svc
        )

    def tearDown(self):
        if self.orig_vault:
            config.AGENT_VAULT_ROOT = self.orig_vault
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def test_calculate_attendance_safe_bunks(self):
        # 18 attended out of 20 total = 90%. Target = 75%
        # Formula: floor((18 - 0.75 * 20) / 0.75) = floor((18 - 15) / 0.75) = floor(3 / 0.75) = 4 safe bunks.
        res = self.router.execute("upes.calculate_attendance", "admin", {
            "course": "AI and Multimedia",
            "target_percentage": 75.0
        })
        self.assertTrue(res.ok)
        self.assertEqual(res.data["current_attended"], 18)
        self.assertEqual(res.data["current_total"], 20)
        self.assertEqual(res.data["current_percentage"], 90.0)
        self.assertEqual(res.data["classes_can_miss_before_target"], 4)
        self.assertEqual(res.data["classes_needed_for_target"], 0)

    def test_calculate_attendance_what_if_missing_next_class(self):
        # What if student misses 1 future class:
        # A' = 18, T' = 21 -> projected = 18/21 = 85.71%
        res = self.router.execute("upes.calculate_attendance", "admin", {
            "course": "AI and Multimedia",
            "future_missed": 1,
            "target_percentage": 75.0
        })
        self.assertTrue(res.ok)
        self.assertEqual(res.data["projected_attended"], 18)
        self.assertEqual(res.data["projected_total"], 21)
        self.assertEqual(res.data["projected_percentage"], 85.71)
        self.assertEqual(res.data["classes_can_miss_before_target"], 3)

    def test_get_punches_history(self):
        res = self.router.execute("upes.get_punches", "admin", {"date": "2026-08-30"})
        self.assertTrue(res.ok)
        self.assertEqual(res.source, "local")
        self.assertEqual(res.data["total_returned"], 1)
        punch = res.data["punches"][0]
        self.assertEqual(punch["punch_in_time"], "09:02")
        self.assertEqual(punch["attendance_subtype"], "CRA")
        self.assertEqual(punch["course_name"], "AI and Multimedia")

    def test_export_timetable_pdf(self):
        res = self.router.execute("upes.export_timetable", "admin", {
            "format": "pdf",
            "destination_path": "Timetable/test_tt.pdf"
        })
        self.assertTrue(res.ok)
        self.assertEqual(res.data["format"], "pdf")
        self.assertTrue(os.path.isfile(os.path.join(self.test_dir, "Timetable", "test_tt.pdf")))

    def test_export_timetable_csv(self):
        res = self.router.execute("upes.export_timetable", "admin", {
            "format": "csv",
            "destination_path": "Timetable/test_tt.csv"
        })
        self.assertTrue(res.ok)
        self.assertEqual(res.data["format"], "csv")
        self.assertTrue(os.path.isfile(os.path.join(self.test_dir, "Timetable", "test_tt.csv")))


if __name__ == "__main__":
    unittest.main()
