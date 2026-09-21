"""
Multi-User Isolation Tests for Academic Results Subsystem
Phase 4.3A: Tenant Partitioning & Cross-Account Read Prevention
"""

import unittest
from decimal import Decimal

from app import app, results_service, create_user_session
from upes.results import CourseResult, SemesterResult, AcademicRecord, init_results_tables


import os
import tempfile
import sqlite3
import config

class TestResultsMultiUserIsolation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config["TESTING"] = True
        cls.client = app.test_client()
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.db_path = os.path.join(cls.temp_dir.name, "test_multi_user_results.db")
        cls.orig_db_path = config.DB_PATH
        config.DB_PATH = cls.db_path
        config.UNIFIED_DB_FILE = cls.db_path
        
        # Production DB guard: verify this test is not using production DB
        assert "nexus_unified.db" not in cls.db_path, "FATAL: Test must not use production DB!"
        
        from app import init_unified_db
        init_unified_db()
        
        cls.orig_results_conn = results_service.conn_factory
        results_service.conn_factory = lambda: sqlite3.connect(cls.db_path)
        with sqlite3.connect(cls.db_path) as conn:
            init_results_tables(conn)

    @classmethod
    def tearDownClass(cls):
        results_service.conn_factory = cls.orig_results_conn
        config.DB_PATH = cls.orig_db_path
        config.UNIFIED_DB_FILE = cls.orig_db_path
        import gc
        gc.collect()
        try:
            cls.temp_dir.cleanup()
        except Exception:
            pass

    def setUp(self):
        # Create student_a session
        self.token_a = create_user_session({
            "user_id": "student_a",
            "role": "student",
            "privileges": {}
        })
        self.headers_a = {"Authorization": f"Bearer {self.token_a}"}

        # Create student_b session
        self.token_b = create_user_session({
            "user_id": "student_b",
            "role": "student",
            "privileges": {}
        })
        self.headers_b = {"Authorization": f"Bearer {self.token_b}"}

        # Seed student_a record (CGPA 9.5)
        ca = [CourseResult("CS101", "Algorithms", Decimal("4.0"), "O", Decimal("10.0"))]
        sa = SemesterResult("SEM1", "Semester I", "2024", Decimal("10.0"), Decimal("10.0"), Decimal("10.0"), Decimal("10.0"), Decimal("4.0"), Decimal("4.0"), "Passed", ca)
        ra = AcademicRecord("student_a", Decimal("10.0"), Decimal("10.0"), Decimal("4.0"), Decimal("4.0"), [sa])
        results_service.store_academic_record(ra)

        # Seed student_b record (CGPA 6.0)
        cb = [CourseResult("EE101", "Circuits", Decimal("3.0"), "B", Decimal("6.0"))]
        sb = SemesterResult("SEM1", "Semester I", "2024", Decimal("6.0"), Decimal("6.0"), Decimal("6.0"), Decimal("6.0"), Decimal("3.0"), Decimal("3.0"), "Passed", cb)
        rb = AcademicRecord("student_b", Decimal("6.0"), Decimal("6.0"), Decimal("3.0"), Decimal("3.0"), [sb])
        results_service.store_academic_record(rb)

    def test_student_a_sees_only_own_results(self):
        resp = self.client.get('/api/academics/results', headers=self.headers_a)
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["user_id"], "student_a")
        self.assertEqual(data["calculated_cgpa"], 10.0)
        self.assertEqual(data["semesters"][0]["courses"][0]["course_code"], "CS101")

        # Verify performance endpoint isolation
        resp_p = self.client.get('/api/academics/performance', headers=self.headers_a)
        self.assertEqual(resp_p.status_code, 200)
        data_p = resp_p.get_json()
        self.assertEqual(data_p["calculated_cgpa"], 10.0)

    def test_student_b_sees_only_own_results(self):
        resp = self.client.get('/api/academics/results', headers=self.headers_b)
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["user_id"], "student_b")
        self.assertEqual(data["calculated_cgpa"], 6.0)
        self.assertEqual(data["semesters"][0]["courses"][0]["course_code"], "EE101")

        # Verify performance endpoint isolation
        resp_p = self.client.get('/api/academics/performance', headers=self.headers_b)
        self.assertEqual(resp_p.status_code, 200)
        data_p = resp_p.get_json()
        self.assertEqual(data_p["calculated_cgpa"], 6.0)

    def test_cross_tenant_term_query_isolated(self):
        # Both students have SEM1, but course content must be strictly isolated
        resp_a = self.client.get('/api/academics/results/SEM1', headers=self.headers_a)
        data_a = resp_a.get_json()
        self.assertEqual(data_a["courses"][0]["course_code"], "CS101")

        resp_b = self.client.get('/api/academics/results/SEM1', headers=self.headers_b)
        data_b = resp_b.get_json()
        self.assertEqual(data_b["courses"][0]["course_code"], "EE101")

    def test_what_if_isolated_to_authenticated_student(self):
        # A's What-If must use A's base record (10.0), not B's
        payload = {"target_cgpa": 9.5, "future_credits": 4.0}
        resp_a = self.client.post('/api/academics/what-if', json=payload, headers=self.headers_a)
        data_a = resp_a.get_json()
        self.assertEqual(data_a["current_cgpa"], 10.0)

        # B's What-If must use B's base record (6.0), not A's
        resp_b = self.client.post('/api/academics/what-if', json=payload, headers=self.headers_b)
        data_b = resp_b.get_json()
        self.assertEqual(data_b["current_cgpa"], 6.0)


if __name__ == "__main__":
    unittest.main()
