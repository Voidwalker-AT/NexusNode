"""
Integration Tests for Academic Results REST Endpoints
Phase 4.3A: Results REST API Contracts, Authentication & Tenant Scoping
"""

import unittest
import json
from decimal import Decimal
import secrets

import config
from app import app, get_db_connection, results_service, create_user_session
from upes.results import CourseResult, SemesterResult, AcademicRecord, init_results_tables


import os
import tempfile
import sqlite3

class TestResultsApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config["TESTING"] = True
        cls.client = app.test_client()
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.db_path = os.path.join(cls.temp_dir.name, "test_results_isolated.db")
        cls.orig_db_path = config.DB_PATH
        config.DB_PATH = cls.db_path
        config.UNIFIED_DB_FILE = cls.db_path
        
        # Production DB guard: verify this test is not using production DB
        assert "nexus_unified.db" not in cls.db_path, "FATAL: Test must not use production DB!"
        
        # Initialize schema in isolated test DB
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
        # Create authenticated admin session token
        self.admin_token = create_user_session({
            "user_id": "test_admin",
            "role": "admin",
            "privileges": {"*": True}
        })
        self.headers = {"Authorization": f"Bearer {self.admin_token}"}

        # Seed test data for 'test_admin' user in isolated DB
        c1 = [
            CourseResult("CS101", "Operating Systems", Decimal("4.0"), "A", Decimal("8.0")),
            CourseResult("CS102", "Networks", Decimal("4.0"), "A+", Decimal("9.0")),
        ]
        s1 = SemesterResult(
            term_id="SEM1",
            semester_name="Semester I",
            academic_year="2024-2025",
            official_sgpa=Decimal("8.50"),
            calculated_sgpa=Decimal("8.50"),
            official_cgpa=Decimal("8.50"),
            calculated_cgpa=Decimal("8.50"),
            credits_registered=Decimal("8.0"),
            credits_earned=Decimal("8.0"),
            status="Passed",
            courses=c1,
            provenance="live"
        )
        record = AcademicRecord(
            user_id="test_admin",
            official_cgpa=Decimal("8.50"),
            calculated_cgpa=Decimal("8.50"),
            total_credits_registered=Decimal("8.0"),
            total_credits_earned=Decimal("8.0"),
            semesters=[s1],
            provenance="live"
        )
        results_service.store_academic_record(record)

    def test_unauthenticated_requests_blocked(self):
        endpoints = [
            ('/api/academics/results', 'GET'),
            ('/api/academics/results/SEM1', 'GET'),
            ('/api/academics/performance', 'GET'),
            ('/api/academics/what-if', 'POST'),
            ('/api/academics/results/sync', 'POST'),
        ]
        for url, method in endpoints:
            if method == 'GET':
                resp = self.client.get(url)
            else:
                resp = self.client.post(url, json={})
            self.assertEqual(resp.status_code, 401, f"Expected 401 for unauthenticated {method} {url}")

    def test_get_academic_results_authenticated(self):
        resp = self.client.get('/api/academics/results', headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["user_id"], "test_admin")
        self.assertEqual(data["calculated_cgpa"], 8.5)
        self.assertEqual(len(data["semesters"]), 1)
        self.assertEqual(data["semesters"][0]["term_id"], "SEM1")
        self.assertEqual(len(data["semesters"][0]["courses"]), 2)

    def test_get_term_results(self):
        # Existing term
        resp = self.client.get('/api/academics/results/SEM1', headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["term_id"], "SEM1")
        self.assertEqual(len(data["courses"]), 2)

        # Nonexistent term
        resp_404 = self.client.get('/api/academics/results/NONEXISTENT', headers=self.headers)
        self.assertEqual(resp_404.status_code, 404)

    def test_get_performance_summary(self):
        resp = self.client.get('/api/academics/performance', headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["has_results"])
        self.assertEqual(data["calculated_cgpa"], 8.5)
        self.assertEqual(data["total_courses"], 2)
        self.assertEqual(data["passed_courses"], 2)
        self.assertEqual(data["pass_rate_percentage"], 100.0)

    def test_what_if_scenario_projection(self):
        payload = {
            "hypothetical_courses": [
                {"course_code": "CS201", "credits": 4.0, "letter_grade": "O"}
            ]
        }
        resp = self.client.post('/api/academics/what-if', json=payload, headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["current_cgpa"], 8.5)
        self.assertEqual(data["projected_term_sgpa"], 10.0)
        self.assertEqual(data["projected_cgpa"], 9.0)
        self.assertEqual(data["cgpa_delta"], 0.5)

    def test_what_if_target_cgpa(self):
        payload = {
            "target_cgpa": 9.0,
            "future_credits": 4.0
        }
        resp = self.client.post('/api/academics/what-if', json=payload, headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["is_feasible"])
        self.assertEqual(data["required_average_grade_point"], 10.0)
        self.assertEqual(data["recommended_minimum_grade"], "O")

    def test_what_if_invalid_payload(self):
        resp = self.client.post('/api/academics/what-if', json={"invalid_key": "data"}, headers=self.headers)
        self.assertEqual(resp.status_code, 400)


if __name__ == "__main__":
    unittest.main()
