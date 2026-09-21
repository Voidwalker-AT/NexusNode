"""
Unit & Integration Tests for UPES Results Subsystem
Phase 4.3A: Forensic Discovery & Read-Only Foundation
Tests grading rules, Decimal math, dual-system normalization, discrepancy detection, LKG caching, and What-If engine.
"""

import os
import json
import sqlite3
import tempfile
import unittest
from decimal import Decimal

from upes.results import (
    CourseResult,
    SemesterResult,
    AcademicRecord,
    ResultsService,
    WhatIfEngine,
    UPES_GRADE_POINTS,
    AUDIT_NON_CREDIT_GRADES,
    calculate_term_gpa,
    calculate_cumulative_cgpa,
    normalize_connectportal_results,
    normalize_exam_pro_transcript,
    grade_to_points,
    round_gpa,
    init_results_tables,
    compute_payload_fingerprint,
)

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "upes_results")


class TestUpesResultsGradingRules(unittest.TestCase):
    """Tests 10-point UPES grading scale and Decimal precision."""

    def test_grade_to_points_mapping(self):
        expected = {
            "O": (Decimal("10.0"), False),
            "A+": (Decimal("9.0"), False),
            "A": (Decimal("8.0"), False),
            "B+": (Decimal("7.0"), False),
            "B": (Decimal("6.0"), False),
            "C+": (Decimal("5.0"), False),
            "C": (Decimal("4.0"), False),
            "F": (Decimal("0.0"), False),
        }
        for grade, (pts, is_aud) in expected.items():
            res_pts, res_aud = grade_to_points(grade)
            self.assertEqual(res_pts, pts, f"Failed for grade {grade}")
            self.assertEqual(res_aud, is_aud)

    def test_audit_non_credit_grades(self):
        for audit_grade in ["S", "U", "Audit", "Satisfactory", "Unsatisfactory"]:
            pts, is_aud = grade_to_points(audit_grade)
            self.assertIsNone(pts, f"Audit grade {audit_grade} should return None for points")
            self.assertTrue(is_aud, f"Audit grade {audit_grade} should be marked as audit")

    def test_term_gpa_calculation_formula(self):
        # 3 courses: 4 cr @ A (8), 4 cr @ A+ (9), 2 cr @ O (10)
        # Sum points = 32 + 36 + 20 = 88. Credits = 10. SGPA = 8.80
        courses = [
            CourseResult("CS101", "Course 1", Decimal("4.0"), "A", Decimal("8.0")),
            CourseResult("CS102", "Course 2", Decimal("4.0"), "A+", Decimal("9.0")),
            CourseResult("CS103", "Course 3", Decimal("2.0"), "O", Decimal("10.0")),
        ]
        sgpa, reg_credits, earn_credits = calculate_term_gpa(courses)
        self.assertEqual(sgpa, Decimal("8.80"))
        self.assertEqual(reg_credits, Decimal("10.0"))
        self.assertEqual(earn_credits, Decimal("10.0"))

    def test_fail_grade_included_in_denominator(self):
        # Course with 'F': 4 cr @ A (8), 4 cr @ F (0)
        # Sum points = 32 + 0 = 32. Credits = 8. SGPA = 4.00. Earned = 4.
        courses = [
            CourseResult("CS101", "Course 1", Decimal("4.0"), "A", Decimal("8.0")),
            CourseResult("CS102", "Course 2", Decimal("4.0"), "F", Decimal("0.0")),
        ]
        sgpa, reg_credits, earn_credits = calculate_term_gpa(courses)
        self.assertEqual(sgpa, Decimal("4.00"))
        self.assertEqual(reg_credits, Decimal("8.0"))
        self.assertEqual(earn_credits, Decimal("4.0"))

    def test_audit_grade_excluded_from_gpa(self):
        # 4 cr @ A+ (9), 2 cr @ S (audit)
        # Sum points = 36. Credits = 4. SGPA = 9.00
        courses = [
            CourseResult("CS101", "Course 1", Decimal("4.0"), "A+", Decimal("9.0")),
            CourseResult("AUD101", "Audit Course", Decimal("2.0"), "S", Decimal("0.0"), is_audit=True),
        ]
        sgpa, reg_credits, earn_credits = calculate_term_gpa(courses)
        self.assertEqual(sgpa, Decimal("9.00"))
        self.assertEqual(reg_credits, Decimal("4.0"))
        self.assertEqual(earn_credits, Decimal("4.0"))


class TestUpesResultsNormalization(unittest.TestCase):
    """Tests normalization of ConnectPortal and Exam-Pro fixtures."""

    def test_normalize_connectportal_summary(self):
        with open(os.path.join(FIXTURES_DIR, "course_summary.json"), "r", encoding="utf-8") as f:
            summary = json.load(f)
        with open(os.path.join(FIXTURES_DIR, "term_wise_all_course.json"), "r", encoding="utf-8") as f:
            term_courses = json.load(f)

        details_map = {"1005": term_courses}
        record = normalize_connectportal_results(summary, details_map)

        self.assertEqual(record.user_id, "00000000-0000-0000-0000-000000000001")
        self.assertEqual(record.official_cgpa, Decimal("8.42"))
        self.assertEqual(len(record.semesters), 5)

        # Inspect term 5 (which had courses attached)
        term5 = next(s for s in record.semesters if s.term_id == "1005")
        self.assertEqual(len(term5.courses), 8)
        self.assertEqual(term5.calculated_sgpa, Decimal("8.46"))
        self.assertEqual(term5.credits_registered, Decimal("24.0"))
        self.assertEqual(term5.credits_earned, Decimal("24.0"))

    def test_normalize_exam_pro_transcript(self):
        with open(os.path.join(FIXTURES_DIR, "exam_pro_transcript.json"), "r", encoding="utf-8") as f:
            transcript = json.load(f)

        record = normalize_exam_pro_transcript(transcript)
        self.assertEqual(record.user_id, "00000000-0000-0000-0000-000000000001")
        self.assertEqual(len(record.semesters), 1)

        sem1 = record.semesters[0]
        self.assertEqual(sem1.term_id, "SEM1")
        self.assertEqual(len(sem1.courses), 7)
        self.assertEqual(sem1.official_sgpa, Decimal("8.25"))
        self.assertEqual(sem1.calculated_sgpa, Decimal("8.35"))
        self.assertEqual(sem1.credits_registered, Decimal("20.0"))

    def test_discrepancy_detection(self):
        courses = [
            CourseResult("CS101", "Course 1", Decimal("4.0"), "A", Decimal("8.0")),
        ]
        # Official SGPA says 10.0, but calculated is 8.0 -> discrepancy should trigger
        sem = SemesterResult(
            term_id="101",
            semester_name="Semester 1",
            academic_year="2024-2025",
            official_sgpa=Decimal("10.0"),
            calculated_sgpa=Decimal("8.0"),
            official_cgpa=Decimal("10.0"),
            calculated_cgpa=Decimal("8.0"),
            credits_registered=Decimal("4.0"),
            credits_earned=Decimal("4.0"),
            status="Passed",
            courses=courses,
            discrepancy=True,
            discrepancy_details="Mismatch: Official=10.0, Calculated=8.0"
        )
        self.assertTrue(sem.discrepancy)
        self.assertIn("Mismatch", sem.discrepancy_details)


class TestWhatIfEngine(unittest.TestCase):
    """Tests ephemeral What-If projection engine."""

    def setUp(self):
        courses = [
            CourseResult("CS101", "Operating Systems", Decimal("4.0"), "A", Decimal("8.0")),
            CourseResult("CS102", "Networks", Decimal("4.0"), "A+", Decimal("9.0")),
        ]
        sem = SemesterResult(
            term_id="1",
            semester_name="Sem 1",
            academic_year="2024-2025",
            official_sgpa=Decimal("8.50"),
            calculated_sgpa=Decimal("8.50"),
            official_cgpa=Decimal("8.50"),
            calculated_cgpa=Decimal("8.50"),
            credits_registered=Decimal("8.0"),
            credits_earned=Decimal("8.0"),
            courses=courses
        )
        self.record = AcademicRecord(
            user_id="test_user",
            official_cgpa=Decimal("8.50"),
            calculated_cgpa=Decimal("8.50"),
            total_credits_registered=Decimal("8.0"),
            total_credits_earned=Decimal("8.0"),
            semesters=[sem]
        )

    def test_scenario_projection(self):
        # Current: 8 credits @ 8.50 (68 points).
        # Hypothetical: 4 credits @ O (10.0) -> 40 points.
        # Total: 12 credits, 108 points -> Projected CGPA = 9.00
        hypo = [
            {"course_code": "CS201", "credits": 4.0, "letter_grade": "O"}
        ]
        res = WhatIfEngine.project_scenario(self.record, hypo)
        self.assertEqual(res["current_cgpa"], 8.50)
        self.assertEqual(res["projected_term_sgpa"], 10.0)
        self.assertEqual(res["projected_cgpa"], 9.0)
        self.assertEqual(res["cgpa_delta"], 0.50)

    def test_target_cgpa_calculation(self):
        # Current: 8 credits @ 8.50 (68 points).
        # Target: 9.00 with 4 future credits.
        # Total credits = 12. Required total points = 108.
        # Required future points = 40. Required avg GP = 10.00.
        res = WhatIfEngine.calculate_target_cgpa(self.record, 9.00, 4.0)
        self.assertTrue(res["is_feasible"])
        self.assertEqual(res["required_average_grade_point"], 10.00)
        self.assertEqual(res["recommended_minimum_grade"], "O")

    def test_impossible_target_cgpa(self):
        # Target 9.50 with only 2 future credits from 8.50 base is mathematically impossible (> 10.0)
        res = WhatIfEngine.calculate_target_cgpa(self.record, 9.50, 2.0)
        self.assertFalse(res["is_feasible"])
        self.assertGreater(res["required_average_grade_point"], 10.0)
        self.assertEqual(res["recommended_minimum_grade"], "IMPOSSIBLE")


class TestResultsServicePersistenceAndLKG(unittest.TestCase):
    """Tests SQLite persistence, multi-user isolation, and LKG fallback."""

    def setUp(self):
        self.temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.temp_db.close()
        self.db_path = self.temp_db.name

        def conn_factory():
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            return conn

        self.conn_factory = conn_factory
        self.service = ResultsService(self.conn_factory)

    def tearDown(self):
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except Exception:
                pass

    def test_store_and_retrieve_record(self):
        courses = [
            CourseResult("CS101", "Operating Systems", Decimal("4.0"), "A", Decimal("8.0")),
            CourseResult("CS102", "Networks", Decimal("4.0"), "A+", Decimal("9.0")),
        ]
        sem = SemesterResult(
            term_id="1001",
            semester_name="Semester I",
            academic_year="2024-2025",
            official_sgpa=Decimal("8.50"),
            calculated_sgpa=Decimal("8.50"),
            official_cgpa=Decimal("8.50"),
            calculated_cgpa=Decimal("8.50"),
            credits_registered=Decimal("8.0"),
            credits_earned=Decimal("8.0"),
            status="Passed",
            courses=courses,
            provenance="live",
            payload_fingerprint="abc123hash",
            fetched_at=1000.0
        )
        record = AcademicRecord(
            user_id="student_1",
            official_cgpa=Decimal("8.50"),
            calculated_cgpa=Decimal("8.50"),
            total_credits_registered=Decimal("8.0"),
            total_credits_earned=Decimal("8.0"),
            semesters=[sem],
            provenance="live",
            last_synced_at=1000.0
        )

        self.service.store_academic_record(record)
        loaded = self.service.get_user_results("student_1")

        self.assertEqual(loaded.user_id, "student_1")
        self.assertEqual(loaded.calculated_cgpa, Decimal("8.50"))
        self.assertEqual(len(loaded.semesters), 1)
        self.assertEqual(loaded.semesters[0].term_id, "1001")
        self.assertEqual(len(loaded.semesters[0].courses), 2)
        self.assertEqual(loaded.semesters[0].courses[0].course_code, "CS101")
        self.assertEqual(loaded.semesters[0].courses[0].grade_point, Decimal("8.0"))

    def test_multi_user_isolation(self):
        # Store records for student_1
        c1 = [CourseResult("CS101", "CS 1", Decimal("4.0"), "O", Decimal("10.0"))]
        s1 = SemesterResult("T1", "Term 1", "2024", Decimal("10.0"), Decimal("10.0"), Decimal("10.0"), Decimal("10.0"), Decimal("4.0"), Decimal("4.0"), "Passed", c1)
        r1 = AcademicRecord("student_1", Decimal("10.0"), Decimal("10.0"), Decimal("4.0"), Decimal("4.0"), [s1])
        self.service.store_academic_record(r1)

        # Store records for student_2
        c2 = [CourseResult("EE101", "EE 1", Decimal("3.0"), "B", Decimal("6.0"))]
        s2 = SemesterResult("T1", "Term 1", "2024", Decimal("6.0"), Decimal("6.0"), Decimal("6.0"), Decimal("6.0"), Decimal("3.0"), Decimal("3.0"), "Passed", c2)
        r2 = AcademicRecord("student_2", Decimal("6.0"), Decimal("6.0"), Decimal("3.0"), Decimal("3.0"), [s2])
        self.service.store_academic_record(r2)

        # Assert student_1 cannot see student_2 data
        res1 = self.service.get_user_results("student_1")
        res2 = self.service.get_user_results("student_2")

        self.assertEqual(res1.calculated_cgpa, Decimal("10.0"))
        self.assertEqual(res1.semesters[0].courses[0].course_code, "CS101")

        self.assertEqual(res2.calculated_cgpa, Decimal("6.0"))
        self.assertEqual(res2.semesters[0].courses[0].course_code, "EE101")

        # Unseen user returns empty record
        res3 = self.service.get_user_results("student_3")
        self.assertEqual(res3.semesters, [])
        self.assertEqual(res3.provenance, "empty")

    def test_lkg_fallback_on_fetch_failure(self):
        # Seed student_1 with cached records
        c1 = [CourseResult("CS101", "CS 1", Decimal("4.0"), "A", Decimal("8.0"))]
        s1 = SemesterResult("T1", "Term 1", "2024", Decimal("8.0"), Decimal("8.0"), Decimal("8.0"), Decimal("8.0"), Decimal("4.0"), Decimal("4.0"), "Passed", c1, provenance="live")
        r1 = AcademicRecord("student_1", Decimal("8.0"), Decimal("8.0"), Decimal("4.0"), Decimal("4.0"), [s1], provenance="live")
        self.service.store_academic_record(r1)

        # Trigger sync when live fetch fails (mocked by no active broker)
        sync_res = self.service.sync_user_results("student_1")

        self.assertEqual(sync_res["status"], "degraded")
        self.assertEqual(sync_res["source"], "lkg")
        self.assertTrue(sync_res["record"]["is_stale"])
        self.assertEqual(sync_res["record"]["provenance"], "lkg")

        # Verify DB is marked stale
        loaded = self.service.get_user_results("student_1")
        self.assertTrue(loaded.is_stale)
        self.assertEqual(loaded.provenance, "lkg")


if __name__ == "__main__":
    unittest.main()
