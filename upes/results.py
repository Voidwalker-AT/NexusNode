"""
NexusNode — UPES Academic Results, SGPA/CGPA & Performance Analysis Module
Phase 4.3A: Forensic Discovery & Read-Only Foundation

Provides:
1. Domain models (CourseResult, SemesterResult, AcademicRecord, WhatIfScenario).
2. Authoritative 10-point UPES grading rules and high-precision Decimal GPA math.
3. Dual-system normalization (ConnectPortal studentprogramprogress + Exam-Pro).
4. Discrepancy detection between official reported GPAs and calculated values.
5. Privacy-preserving SQLite storage with SHA-256 payload fingerprinting (no raw PII/JSON).
6. Multi-tenant ResultsService with LKG fallback caching and ephemeral What-If projection.
"""

import time
import json
import hashlib
import logging
import sqlite3
from decimal import Decimal, ROUND_HALF_UP
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, List, Optional, Tuple, Callable

import requests
import config

logger = logging.getLogger("UPES_RESULTS")

# ==============================================================================
# 1. AUTHORITATIVE UPES 10-POINT GRADING RULES
# ==============================================================================

# UPES Official 10-Point Letter Grade Scale
UPES_GRADE_POINTS: Dict[str, Decimal] = {
    "O": Decimal("10.0"),
    "A+": Decimal("9.0"),
    "A": Decimal("8.0"),
    "B+": Decimal("7.0"),
    "B": Decimal("6.0"),
    "C+": Decimal("5.0"),
    "C": Decimal("4.0"),
    "F": Decimal("0.0"),
}

# Non-credit / Audit grades excluded from SGPA / CGPA denominator and numerator
AUDIT_NON_CREDIT_GRADES = {"S", "U", "AUDIT", "SATISFACTORY", "UNSATISFACTORY"}

def round_gpa(val: Decimal, places: int = 2) -> Decimal:
    """Rounds a Decimal value using standard academic ROUND_HALF_UP."""
    q = Decimal("10") ** -places
    return val.quantize(q, rounding=ROUND_HALF_UP)

def grade_to_points(letter_grade: str, fallback_point: Optional[float] = None) -> Tuple[Optional[Decimal], bool]:
    """
    Maps letter grade to grade point.
    Returns (grade_point, is_audit).
    If the grade is an audit/non-credit grade, returns (None, True).
    If grade is unrecognized but fallback_point is provided, uses fallback_point.
    """
    normalized = letter_grade.strip().upper() if letter_grade else ""
    if normalized in AUDIT_NON_CREDIT_GRADES:
        return None, True
    if normalized in UPES_GRADE_POINTS:
        return UPES_GRADE_POINTS[normalized], False
    if fallback_point is not None and fallback_point >= 0:
        return Decimal(str(fallback_point)), False
    return Decimal("0.0"), False


# ==============================================================================
# 2. DOMAIN DATA MODELS
# ==============================================================================

@dataclass
class CourseResult:
    course_code: str
    course_name: str
    credits: Decimal
    letter_grade: str
    grade_point: Decimal
    status: str = "Passed"
    attempt: int = 1
    is_backlog: bool = False
    is_audit: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "course_code": self.course_code,
            "course_name": self.course_name,
            "credits": float(self.credits),
            "letter_grade": self.letter_grade,
            "grade_point": float(self.grade_point),
            "status": self.status,
            "attempt": self.attempt,
            "is_backlog": self.is_backlog,
            "is_audit": self.is_audit,
        }

@dataclass
class SemesterResult:
    term_id: str
    semester_name: str
    academic_year: str
    official_sgpa: Optional[Decimal]
    calculated_sgpa: Decimal
    official_cgpa: Optional[Decimal]
    calculated_cgpa: Decimal
    credits_registered: Decimal
    credits_earned: Decimal
    status: str = "Passed"
    courses: List[CourseResult] = field(default_factory=list)
    provenance: str = "live"  # "live", "cache", "lkg"
    is_stale: bool = False
    discrepancy: bool = False
    discrepancy_details: Optional[str] = None
    payload_fingerprint: Optional[str] = None
    fetched_at: float = 0.0

    @property
    def sgpa(self) -> Decimal:
        return self.official_sgpa if self.official_sgpa is not None else self.calculated_sgpa

    def to_dict(self) -> Dict[str, Any]:
        return {
            "term_id": self.term_id,
            "semester_name": self.semester_name,
            "academic_year": self.academic_year,
            "official_sgpa": float(self.official_sgpa) if self.official_sgpa is not None else None,
            "calculated_sgpa": float(self.calculated_sgpa),
            "sgpa": float(self.sgpa),
            "official_cgpa": float(self.official_cgpa) if self.official_cgpa is not None else None,
            "calculated_cgpa": float(self.calculated_cgpa),
            "credits_registered": float(self.credits_registered),
            "credits_earned": float(self.credits_earned),
            "status": self.status,
            "course_count": len(self.courses),
            "courses": [c.to_dict() for c in self.courses],
            "provenance": self.provenance,
            "is_stale": self.is_stale,
            "discrepancy": self.discrepancy,
            "discrepancy_details": self.discrepancy_details,
            "payload_fingerprint": self.payload_fingerprint,
            "fetched_at": self.fetched_at,
        }

@dataclass
class AcademicRecord:
    user_id: str
    official_cgpa: Optional[Decimal]
    calculated_cgpa: Decimal
    total_credits_registered: Decimal
    total_credits_earned: Decimal
    semesters: List[SemesterResult] = field(default_factory=list)
    provenance: str = "live"
    is_stale: bool = False
    discrepancies: List[Dict[str, Any]] = field(default_factory=list)
    last_synced_at: float = 0.0

    @property
    def cgpa(self) -> Decimal:
        return self.official_cgpa if self.official_cgpa is not None else self.calculated_cgpa

    @property
    def last_updated(self) -> float:
        return self.last_synced_at

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "official_cgpa": float(self.official_cgpa) if self.official_cgpa is not None else None,
            "calculated_cgpa": float(self.calculated_cgpa),
            "cgpa": float(self.cgpa),
            "total_credits_registered": float(self.total_credits_registered),
            "total_credits_earned": float(self.total_credits_earned),
            "semester_count": len(self.semesters),
            "semesters": [s.to_dict() for s in self.semesters],
            "provenance": self.provenance,
            "is_stale": self.is_stale,
            "discrepancies": self.discrepancies,
            "has_discrepancy": len(self.discrepancies) > 0,
            "last_synced_at": self.last_synced_at,
        }


# ==============================================================================
# 3. HIGH-PRECISION GPA MATH & NORMALIZATION ENGINES
# ==============================================================================

def calculate_term_gpa(courses: List[CourseResult]) -> Tuple[Decimal, Decimal, Decimal]:
    """
    Calculates SGPA for a list of course results using Decimal precision.
    Returns: (sgpa, credits_registered, credits_earned)
    Rules:
      - Denominator credits include courses graded 'F', but exclude audit ('S'/'U').
      - Numerator is sum(credits * grade_point).
      - Earned credits include courses with grade_point > 0 (excludes 'F' and 'U').
    """
    total_points = Decimal("0.0")
    denom_credits = Decimal("0.0")
    earned_credits = Decimal("0.0")

    for c in courses:
        if c.is_audit:
            # Audit courses do not affect GPA or earned credits
            continue
        c_credits = c.credits
        denom_credits += c_credits
        total_points += (c_credits * c.grade_point)
        if c.grade_point > Decimal("0.0"):
            earned_credits += c_credits

    if denom_credits > Decimal("0.0"):
        sgpa = round_gpa(total_points / denom_credits, places=2)
    else:
        sgpa = Decimal("0.0")

    return sgpa, denom_credits, earned_credits

def calculate_cumulative_cgpa(semesters: List[SemesterResult]) -> Decimal:
    """
    Calculates cumulative CGPA across all completed semesters.
    Weighted by credit points across all non-audit courses.
    """
    total_points = Decimal("0.0")
    denom_credits = Decimal("0.0")

    for sem in semesters:
        for c in sem.courses:
            if c.is_audit:
                continue
            denom_credits += c.credits
            total_points += (c.credits * c.grade_point)

    if denom_credits > Decimal("0.0"):
        return round_gpa(total_points / denom_credits, places=2)
    return Decimal("0.0")

def compute_payload_fingerprint(data: Any) -> str:
    """Computes SHA-256 hash of normalized serialized payload for provenance verification."""
    raw = json.dumps(data, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()

def normalize_connectportal_results(
    summary_data: Dict[str, Any],
    term_details_map: Dict[str, List[Dict[str, Any]]],
    provenance: str = "live",
    is_stale: bool = False
) -> AcademicRecord:
    """
    Normalizes ConnectPortal API Gateway payload (System A) into an AcademicRecord.
    summary_data: output from /studentprogramprogress/course-summary
    term_details_map: termId -> list of course details from /studentprogramprogress/term-wise-all-course
    """
    user_id = summary_data.get("StudentUniqueId", "student")
    off_cgpa_raw = summary_data.get("CGPA")
    official_cgpa = Decimal(str(off_cgpa_raw)) if off_cgpa_raw is not None else None

    tagged_sems = summary_data.get("TaggedSemesters") or []
    semesters: List[SemesterResult] = []
    discrepancies: List[Dict[str, Any]] = []

    cumulative_points = Decimal("0.0")
    cumulative_credits = Decimal("0.0")

    now = time.time()

    for sem_info in tagged_sems:
        term_id = str(sem_info.get("TermId", ""))
        term_name = sem_info.get("TermName") or sem_info.get("TermCode") or f"Term {term_id}"
        acad_year = sem_info.get("AcademicYear", "")
        off_sgpa_raw = sem_info.get("SGPA")
        off_sgpa = Decimal(str(off_sgpa_raw)) if off_sgpa_raw is not None else None
        off_term_cgpa_raw = sem_info.get("CGPA")
        off_term_cgpa = Decimal(str(off_term_cgpa_raw)) if off_term_cgpa_raw is not None else None

        course_raw_list = term_details_map.get(term_id, [])
        courses: List[CourseResult] = []

        for cr in course_raw_list:
            code = str(cr.get("ModuleCode") or cr.get("CourseCode") or "").strip()
            name = str(cr.get("ModuleName") or cr.get("CourseName") or code).strip()
            cred_val = Decimal(str(cr.get("CreditPoint") or cr.get("Credits") or 0.0))
            grade = str(cr.get("GradeObtained") or cr.get("Grade") or "F").strip().upper()
            gp_raw = cr.get("GradePoints") or cr.get("GradePoint")
            fb_gp = float(gp_raw) if gp_raw is not None else None

            gp, is_aud = grade_to_points(grade, fb_gp)
            actual_gp = gp if gp is not None else Decimal("0.0")
            status = cr.get("Status") or ("Passed" if actual_gp > Decimal("0.0") else "Failed")

            courses.append(CourseResult(
                course_code=code,
                course_name=name,
                credits=cred_val,
                letter_grade=grade,
                grade_point=actual_gp,
                status=status,
                attempt=int(cr.get("Attempt") or 1),
                is_backlog=bool(cr.get("IsBacklog") or False),
                is_audit=is_aud
            ))

        calc_sgpa, reg_credits, earn_credits = calculate_term_gpa(courses)

        for c in courses:
            if not c.is_audit:
                cumulative_credits += c.credits
                cumulative_points += (c.credits * c.grade_point)

        running_cgpa = round_gpa(cumulative_points / cumulative_credits, 2) if cumulative_credits > 0 else Decimal("0.0")

        # Discrepancy check
        has_disc = False
        disc_details = None
        if off_sgpa is not None and abs(off_sgpa - calc_sgpa) > Decimal("0.01"):
            has_disc = True
            disc_details = f"Term {term_id} SGPA discrepancy: Official={off_sgpa}, Calculated={calc_sgpa}"
            discrepancies.append({
                "term_id": term_id,
                "type": "SGPA_MISMATCH",
                "official": float(off_sgpa),
                "calculated": float(calc_sgpa),
                "difference": float(abs(off_sgpa - calc_sgpa))
            })

        sem_fp = compute_payload_fingerprint({"term": term_id, "courses": [c.to_dict() for c in courses]})

        semesters.append(SemesterResult(
            term_id=term_id,
            semester_name=term_name,
            academic_year=acad_year,
            official_sgpa=off_sgpa,
            calculated_sgpa=calc_sgpa,
            official_cgpa=off_term_cgpa,
            calculated_cgpa=running_cgpa,
            credits_registered=reg_credits,
            credits_earned=earn_credits,
            status=sem_info.get("Status", "Passed"),
            courses=courses,
            provenance=provenance,
            is_stale=is_stale,
            discrepancy=has_disc,
            discrepancy_details=disc_details,
            payload_fingerprint=sem_fp,
            fetched_at=now
        ))

    overall_calc_cgpa = round_gpa(cumulative_points / cumulative_credits, 2) if cumulative_credits > 0 else Decimal("0.0")
    total_reg = sum(s.credits_registered for s in semesters)
    total_earn = sum(s.credits_earned for s in semesters)

    if official_cgpa is not None and abs(official_cgpa - overall_calc_cgpa) > Decimal("0.01"):
        discrepancies.append({
            "term_id": "OVERALL",
            "type": "CGPA_MISMATCH",
            "official": float(official_cgpa),
            "calculated": float(overall_calc_cgpa),
            "difference": float(abs(official_cgpa - overall_calc_cgpa))
        })

    return AcademicRecord(
        user_id=user_id,
        official_cgpa=official_cgpa,
        calculated_cgpa=overall_calc_cgpa,
        total_credits_registered=total_reg,
        total_credits_earned=total_earn,
        semesters=semesters,
        provenance=provenance,
        is_stale=is_stale,
        discrepancies=discrepancies,
        last_synced_at=now
    )

def normalize_exam_pro_transcript(
    transcript_resp: Dict[str, Any],
    provenance: str = "live",
    is_stale: bool = False
) -> AcademicRecord:
    """
    Normalizes Exam-Pro transcript response (System B) into an AcademicRecord.
    """
    user_id = transcript_resp.get("StudentUniqueId", "student")
    t_data = transcript_resp.get("TranscriptData") or []

    semesters: List[SemesterResult] = []
    discrepancies: List[Dict[str, Any]] = []
    cumulative_points = Decimal("0.0")
    cumulative_credits = Decimal("0.0")
    now = time.time()

    for idx, term in enumerate(t_data, 1):
        term_id = str(term.get("TermCode") or str(idx))
        term_name = term.get("TermName") or f"Semester {idx}"
        acad_year = term.get("AcademicYear", "")
        off_sgpa_raw = term.get("SGPA")
        off_sgpa = Decimal(str(off_sgpa_raw)) if off_sgpa_raw is not None else None
        off_cgpa_raw = term.get("CGPA")
        off_cgpa = Decimal(str(off_cgpa_raw)) if off_cgpa_raw is not None else None

        courses: List[CourseResult] = []
        for c in term.get("Courses") or []:
            code = str(c.get("CourseCode") or "").strip()
            name = str(c.get("CourseName") or code).strip()
            credits_val = Decimal(str(c.get("Credits") or 0.0))
            grade = str(c.get("Grade") or "F").strip().upper()
            gp_raw = c.get("GradePoint")
            fb_gp = float(gp_raw) if gp_raw is not None else None

            gp, is_aud = grade_to_points(grade, fb_gp)
            actual_gp = gp if gp is not None else Decimal("0.0")
            status = c.get("ResultStatus") or ("PASS" if actual_gp > Decimal("0.0") else "FAIL")
            is_backlog = bool(c.get("IsBacklog") or c.get("NonRegularExamStatus") != "Regular")

            courses.append(CourseResult(
                course_code=code,
                course_name=name,
                credits=credits_val,
                letter_grade=grade,
                grade_point=actual_gp,
                status=status,
                attempt=int(c.get("Attempt") or 1),
                is_backlog=is_backlog,
                is_audit=is_aud
            ))

        calc_sgpa, reg_credits, earn_credits = calculate_term_gpa(courses)
        for c in courses:
            if not c.is_audit:
                cumulative_credits += c.credits
                cumulative_points += (c.credits * c.grade_point)

        running_cgpa = round_gpa(cumulative_points / cumulative_credits, 2) if cumulative_credits > 0 else Decimal("0.0")

        has_disc = False
        disc_details = None
        if off_sgpa is not None and abs(off_sgpa - calc_sgpa) > Decimal("0.01"):
            has_disc = True
            disc_details = f"Term {term_id} SGPA discrepancy: Official={off_sgpa}, Calculated={calc_sgpa}"
            discrepancies.append({
                "term_id": term_id,
                "type": "SGPA_MISMATCH",
                "official": float(off_sgpa),
                "calculated": float(calc_sgpa),
                "difference": float(abs(off_sgpa - calc_sgpa))
            })

        sem_fp = compute_payload_fingerprint({"term": term_id, "courses": [c.to_dict() for c in courses]})

        semesters.append(SemesterResult(
            term_id=term_id,
            semester_name=term_name,
            academic_year=acad_year,
            official_sgpa=off_sgpa,
            calculated_sgpa=calc_sgpa,
            official_cgpa=off_cgpa,
            calculated_cgpa=running_cgpa,
            credits_registered=reg_credits,
            credits_earned=earn_credits,
            status="Passed",
            courses=courses,
            provenance=provenance,
            is_stale=is_stale,
            discrepancy=has_disc,
            discrepancy_details=disc_details,
            payload_fingerprint=sem_fp,
            fetched_at=now
        ))

    overall_calc_cgpa = round_gpa(cumulative_points / cumulative_credits, 2) if cumulative_credits > 0 else Decimal("0.0")
    total_reg = sum(s.credits_registered for s in semesters)
    total_earn = sum(s.credits_earned for s in semesters)
    latest_official_cgpa = semesters[-1].official_cgpa if semesters else None

    return AcademicRecord(
        user_id=user_id,
        official_cgpa=latest_official_cgpa,
        calculated_cgpa=overall_calc_cgpa,
        total_credits_registered=total_reg,
        total_credits_earned=total_earn,
        semesters=semesters,
        provenance=provenance,
        is_stale=is_stale,
        discrepancies=discrepancies,
        last_synced_at=now
    )


# ==============================================================================
# 4. DATABASE INITIALIZATION & SCHEMA HELPERS
# ==============================================================================

def init_results_tables(conn: sqlite3.Connection):
    """Initializes normalized academic results tables and indices if not present."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS academic_results (
            user_id TEXT NOT NULL,
            term_id TEXT NOT NULL,
            semester_name TEXT NOT NULL,
            academic_year TEXT,
            official_sgpa REAL,
            calculated_sgpa REAL,
            official_cgpa REAL,
            calculated_cgpa REAL,
            credits_registered REAL NOT NULL DEFAULT 0.0,
            credits_earned REAL NOT NULL DEFAULT 0.0,
            status TEXT DEFAULT 'Passed',
            payload_fingerprint TEXT,
            provenance TEXT DEFAULT 'live',
            is_stale INTEGER DEFAULT 0,
            discrepancy INTEGER DEFAULT 0,
            discrepancy_details TEXT,
            last_synced_at REAL NOT NULL,
            PRIMARY KEY (user_id, term_id)
        );
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_acad_results_user ON academic_results(user_id);")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS academic_result_courses (
            user_id TEXT NOT NULL,
            term_id TEXT NOT NULL,
            course_code TEXT NOT NULL,
            course_name TEXT NOT NULL,
            credits REAL NOT NULL DEFAULT 0.0,
            letter_grade TEXT NOT NULL,
            grade_point REAL NOT NULL DEFAULT 0.0,
            status TEXT DEFAULT 'Passed',
            attempt INTEGER DEFAULT 1,
            is_backlog INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, term_id, course_code),
            FOREIGN KEY (user_id, term_id) REFERENCES academic_results(user_id, term_id) ON DELETE CASCADE
        );
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_acad_courses_user_term ON academic_result_courses(user_id, term_id);")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS academic_result_sync_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            timestamp REAL NOT NULL,
            source TEXT NOT NULL,
            status TEXT NOT NULL,
            terms_synced INTEGER DEFAULT 0,
            courses_synced INTEGER DEFAULT 0,
            duration_ms REAL DEFAULT 0.0,
            details TEXT
        );
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_acad_sync_history_user ON academic_result_sync_history(user_id, timestamp DESC);")


# ==============================================================================
# 5. WHAT-IF PROJECTION ENGINE
# ==============================================================================

class WhatIfEngine:
    """Calculates ephemeral GPA scenarios without database mutations."""

    @staticmethod
    def project_scenario(
        current_record: AcademicRecord,
        hypothetical_courses: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Calculates projected semester SGPA and cumulative CGPA based on hypothetical grades.
        hypothetical_courses: [{"course_code": "CS101", "credits": 4.0, "letter_grade": "A+"}, ...]
        """
        # Calculate current total points and credits from completed semesters
        current_points = Decimal("0.0")
        current_credits = Decimal("0.0")

        for sem in current_record.semesters:
            for c in sem.courses:
                if not c.is_audit:
                    current_credits += c.credits
                    current_points += (c.credits * c.grade_point)

        hypo_points = Decimal("0.0")
        hypo_credits = Decimal("0.0")
        evaluated_hypo = []

        for hc in hypothetical_courses:
            code = str(hc.get("course_code") or "").strip()
            name = str(hc.get("course_name") or code).strip()
            credits_val = Decimal(str(hc.get("credits") or 0.0))
            grade = str(hc.get("letter_grade") or "F").strip().upper()
            gp, is_aud = grade_to_points(grade)
            actual_gp = gp if gp is not None else Decimal("0.0")

            if not is_aud:
                hypo_credits += credits_val
                hypo_points += (credits_val * actual_gp)

            evaluated_hypo.append({
                "course_code": code,
                "course_name": name,
                "credits": float(credits_val),
                "letter_grade": grade,
                "grade_point": float(actual_gp),
                "is_audit": is_aud
            })

        projected_sgpa = round_gpa(hypo_points / hypo_credits, 2) if hypo_credits > 0 else Decimal("0.0")
        new_total_points = current_points + hypo_points
        new_total_credits = current_credits + hypo_credits
        projected_cgpa = round_gpa(new_total_points / new_total_credits, 2) if new_total_credits > 0 else Decimal("0.0")

        delta = projected_cgpa - current_record.calculated_cgpa

        return {
            "current_cgpa": float(current_record.calculated_cgpa),
            "current_credits": float(current_credits),
            "projected_term_sgpa": float(projected_sgpa),
            "projected_term_credits": float(hypo_credits),
            "projected_cgpa": float(projected_cgpa),
            "projected_total_credits": float(new_total_credits),
            "cgpa_delta": float(delta),
            "evaluated_courses": evaluated_hypo
        }

    @staticmethod
    def calculate_target_cgpa(
        current_record: AcademicRecord,
        target_cgpa: float,
        future_credits: float
    ) -> Dict[str, Any]:
        """
        Calculates the average grade point required across remaining credits to reach target CGPA.
        Formula:
          Required_GP = (Target_CGPA * (Current_Credits + Future_Credits) - Current_Points) / Future_Credits
        """
        current_points = Decimal("0.0")
        current_credits = Decimal("0.0")

        for sem in current_record.semesters:
            for c in sem.courses:
                if not c.is_audit:
                    current_credits += c.credits
                    current_points += (c.credits * c.grade_point)

        target = Decimal(str(target_cgpa))
        future_c = Decimal(str(future_credits))

        if future_c <= Decimal("0.0"):
            return {
                "feasible": False,
                "error": "Future credits must be greater than 0."
            }

        total_future_credits = current_credits + future_c
        required_total_points = target * total_future_credits
        required_future_points = required_total_points - current_points
        required_avg_gp = round_gpa(required_future_points / future_c, 2)

        is_feasible = (Decimal("0.0") <= required_avg_gp <= Decimal("10.0"))

        recommended_grade = "O"
        for g_letter, g_val in sorted(UPES_GRADE_POINTS.items(), key=lambda x: x[1]):
            if g_val >= required_avg_gp:
                recommended_grade = g_letter
                break

        return {
            "current_cgpa": float(current_record.calculated_cgpa),
            "current_credits": float(current_credits),
            "target_cgpa": float(target),
            "future_credits": float(future_c),
            "required_average_grade_point": float(required_avg_gp),
            "recommended_minimum_grade": recommended_grade if is_feasible else "IMPOSSIBLE",
            "is_feasible": is_feasible,
            "max_achievable_cgpa": float(round_gpa((current_points + (future_c * Decimal("10.0"))) / total_future_credits, 2))
        }


# ==============================================================================
# 6. RESULTS SERVICE (PERSISTENCE, LKG FALLBACK, MULTI-TENANT)
# ==============================================================================

class ResultsService:
    """
    Authoritative Results Service for NexusNode.
    Handles Direct HTTP gateway calls, SQLite persistence, LKG fallback caching,
    and What-If scenario projections.
    """

    def __init__(self, conn_factory: Callable[[], sqlite3.Connection], session_broker=None):
        self.conn_factory = conn_factory
        self.session_broker = session_broker
        self._ensure_schema()

    def _ensure_schema(self):
        conn = self.conn_factory()
        try:
            init_results_tables(conn)
            conn.commit()
        finally:
            conn.close()

    def store_academic_record(self, record: AcademicRecord):
        """Persists normalized academic record into SQLite, replacing older entries for this user."""
        conn = self.conn_factory()
        try:
            with conn:
                # 1. Clear existing results for this user (transactional replace)
                conn.execute("DELETE FROM academic_result_courses WHERE user_id = ?", (record.user_id,))
                conn.execute("DELETE FROM academic_results WHERE user_id = ?", (record.user_id,))

                # 2. Insert semester results
                for sem in record.semesters:
                    conn.execute("""
                        INSERT INTO academic_results (
                            user_id, term_id, semester_name, academic_year, official_sgpa,
                            calculated_sgpa, official_cgpa, calculated_cgpa, credits_registered,
                            credits_earned, status, payload_fingerprint, provenance, is_stale,
                            discrepancy, discrepancy_details, last_synced_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        record.user_id,
                        sem.term_id,
                        sem.semester_name,
                        sem.academic_year,
                        float(sem.official_sgpa) if sem.official_sgpa is not None else None,
                        float(sem.calculated_sgpa),
                        float(sem.official_cgpa) if sem.official_cgpa is not None else None,
                        float(sem.calculated_cgpa),
                        float(sem.credits_registered),
                        float(sem.credits_earned),
                        sem.status,
                        sem.payload_fingerprint,
                        sem.provenance,
                        1 if sem.is_stale else 0,
                        1 if sem.discrepancy else 0,
                        sem.discrepancy_details,
                        record.last_synced_at
                    ))

                    # 3. Insert course records
                    for c in sem.courses:
                        conn.execute("""
                            INSERT INTO academic_result_courses (
                                user_id, term_id, course_code, course_name, credits,
                                letter_grade, grade_point, status, attempt, is_backlog
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            record.user_id,
                            sem.term_id,
                            c.course_code,
                            c.course_name,
                            float(c.credits),
                            c.letter_grade,
                            float(c.grade_point),
                            c.status,
                            c.attempt,
                            1 if c.is_backlog else 0
                        ))
        finally:
            conn.close()

    def get_user_results(self, user_id: str) -> AcademicRecord:
        """Loads cached/LKG results from SQLite for a user."""
        conn = self.conn_factory()
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT term_id, semester_name, academic_year, official_sgpa, calculated_sgpa,
                       official_cgpa, calculated_cgpa, credits_registered, credits_earned,
                       status, payload_fingerprint, provenance, is_stale, discrepancy,
                       discrepancy_details, last_synced_at
                FROM academic_results
                WHERE user_id = ?
                ORDER BY term_id ASC
            """, (user_id,))
            sem_rows = cur.fetchall()

            if not sem_rows:
                return AcademicRecord(
                    user_id=user_id,
                    official_cgpa=None,
                    calculated_cgpa=Decimal("0.0"),
                    total_credits_registered=Decimal("0.0"),
                    total_credits_earned=Decimal("0.0"),
                    semesters=[],
                    provenance="empty",
                    is_stale=False,
                    last_synced_at=0.0
                )

            semesters: List[SemesterResult] = []
            discrepancies = []
            latest_sync = 0.0

            for s in sem_rows:
                t_id = s[0]
                latest_sync = max(latest_sync, float(s[15]))

                # Fetch courses for term
                cur.execute("""
                    SELECT course_code, course_name, credits, letter_grade, grade_point,
                           status, attempt, is_backlog
                    FROM academic_result_courses
                    WHERE user_id = ? AND term_id = ?
                    ORDER BY course_code ASC
                """, (user_id, t_id))
                c_rows = cur.fetchall()

                courses = []
                for cr in c_rows:
                    gp, is_aud = grade_to_points(cr[3], cr[4])
                    courses.append(CourseResult(
                        course_code=cr[0],
                        course_name=cr[1],
                        credits=Decimal(str(cr[2])),
                        letter_grade=cr[3],
                        grade_point=Decimal(str(cr[4])),
                        status=cr[5],
                        attempt=cr[6],
                        is_backlog=bool(cr[7]),
                        is_audit=is_aud
                    ))

                sem_res = SemesterResult(
                    term_id=t_id,
                    semester_name=s[1],
                    academic_year=s[2] or "",
                    official_sgpa=Decimal(str(s[3])) if s[3] is not None else None,
                    calculated_sgpa=Decimal(str(s[4])),
                    official_cgpa=Decimal(str(s[5])) if s[5] is not None else None,
                    calculated_cgpa=Decimal(str(s[6])),
                    credits_registered=Decimal(str(s[7])),
                    credits_earned=Decimal(str(s[8])),
                    status=s[9],
                    courses=courses,
                    provenance=s[11],
                    is_stale=bool(s[12]),
                    discrepancy=bool(s[13]),
                    discrepancy_details=s[14],
                    payload_fingerprint=s[10],
                    fetched_at=float(s[15])
                )
                semesters.append(sem_res)
                if sem_res.discrepancy:
                    discrepancies.append({
                        "term_id": t_id,
                        "type": "SGPA_MISMATCH",
                        "official": float(sem_res.official_sgpa) if sem_res.official_sgpa else None,
                        "calculated": float(sem_res.calculated_sgpa)
                    })

            calc_cgpa = calculate_cumulative_cgpa(semesters)
            total_reg = sum(sem.credits_registered for sem in semesters)
            total_earn = sum(sem.credits_earned for sem in semesters)
            off_cgpa = semesters[-1].official_cgpa if semesters else None

            is_stale = any(s.is_stale for s in semesters)
            prov = semesters[0].provenance if semesters else "cache"

            return AcademicRecord(
                user_id=user_id,
                official_cgpa=off_cgpa,
                calculated_cgpa=calc_cgpa,
                total_credits_registered=total_reg,
                total_credits_earned=total_earn,
                semesters=semesters,
                provenance=prov,
                is_stale=is_stale,
                discrepancies=discrepancies,
                last_synced_at=latest_sync
            )
        finally:
            conn.close()

    def get_term_results(self, user_id: str, term_id: str) -> Optional[SemesterResult]:
        """Returns results for a specific semester."""
        record = self.get_user_results(user_id)
        for s in record.semesters:
            if s.term_id == term_id:
                return s
        return None

    def get_performance_summary(self, user_id: str) -> Dict[str, Any]:
        """Computes analytical trends, strongest/weakest terms, and standing."""
        record = self.get_user_results(user_id)
        if not record.semesters:
            return {
                "has_results": False,
                "message": "No academic results available for this account."
            }

        valid_sems = [s for s in record.semesters if s.calculated_sgpa > 0]
        strongest = max(valid_sems, key=lambda s: s.calculated_sgpa) if valid_sems else None
        weakest = min(valid_sems, key=lambda s: s.calculated_sgpa) if valid_sems else None

        backlog_courses = []
        for s in record.semesters:
            for c in s.courses:
                if c.is_backlog or c.letter_grade == "F":
                    backlog_courses.append({
                        "term_id": s.term_id,
                        "course_code": c.course_code,
                        "course_name": c.course_name,
                        "grade": c.letter_grade
                    })

        total_courses = sum(len(s.courses) for s in record.semesters)
        passed_courses = sum(1 for s in record.semesters for c in s.courses if c.grade_point > 0)

        pass_rate = round((passed_courses / total_courses * 100.0), 1) if total_courses > 0 else 0.0

        return {
            "has_results": True,
            "official_cgpa": float(record.official_cgpa) if record.official_cgpa else None,
            "calculated_cgpa": float(record.calculated_cgpa),
            "total_credits_earned": float(record.total_credits_earned),
            "total_credits_registered": float(record.total_credits_registered),
            "total_courses": total_courses,
            "passed_courses": passed_courses,
            "pass_rate_percentage": pass_rate,
            "backlog_count": len(backlog_courses),
            "backlogs": backlog_courses,
            "strongest_semester": {
                "term_id": strongest.term_id,
                "semester_name": strongest.semester_name,
                "sgpa": float(strongest.calculated_sgpa)
            } if strongest else None,
            "weakest_semester": {
                "term_id": weakest.term_id,
                "semester_name": weakest.semester_name,
                "sgpa": float(weakest.calculated_sgpa)
            } if weakest else None,
            "discrepancies": record.discrepancies,
            "provenance": record.provenance,
            "is_stale": record.is_stale,
            "last_synced_at": record.last_synced_at
        }

    def fetch_live_results(self, user_id: str) -> Tuple[bool, Optional[AcademicRecord], str]:
        """
        Attempts to fetch live results from UPES ConnectPortal API Gateway or Exam-Pro.
        Returns: (success, AcademicRecord, status_message)
        """
        auth_bundle = None
        if self.session_broker:
            try:
                auth_bundle = self.session_broker.get_session(user_id)
            except Exception as e:
                logger.warning(f"Error fetching session for {user_id}: {e}")

        # If no active broker or session, check fallback config for admin
        token = auth_bundle.access_token if auth_bundle else None
        student_id = auth_bundle.student_unique_id if auth_bundle else None

        if not token and user_id == "admin":
            token = config.UPES_ACCESS_TOKEN
            student_id = config.UPES_STUDENT_CODE

        if not token or not student_id:
            return False, None, "UPES access token or student ID not available"

        headers = {
            "Authorization": f"Bearer {token}",
            "x-applicationname": "connectportal",
            "x-requestfrom": "web",
            "x-appsecret": "ku7GUMtyT8er51rTfTc7HC",
            "x-studentUniqueId": student_id,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }

        base_url = "https://myupes-beta.upes.ac.in/apigateway"

        try:
            # 1. Try System A: ConnectPortal Course Progress Summary
            summary_url = f"{base_url}/connect-portal/api/studentprogramprogress/course-summary/{student_id}"
            resp = requests.get(summary_url, headers=headers, timeout=12)

            if resp.status_code == 200:
                summary_data = resp.json()
                tagged = summary_data.get("TaggedSemesters") or []
                term_details = {}

                # Fetch details for each tagged semester
                for sem in tagged:
                    t_id = sem.get("TermId")
                    if t_id:
                        detail_url = f"{base_url}/connect-portal/api/studentprogramprogress/term-wise-all-course/{student_id}/{t_id}"
                        try:
                            d_resp = requests.get(detail_url, headers=headers, timeout=10)
                            if d_resp.status_code == 200:
                                term_details[str(t_id)] = d_resp.json()
                        except Exception as de:
                            logger.warning(f"Failed to fetch term {t_id} courses: {de}")

                record = normalize_connectportal_results(summary_data, term_details, provenance="live", is_stale=False)
                record.user_id = user_id
                self.store_academic_record(record)
                return True, record, "Live results synchronized via ConnectPortal API Gateway"

            elif resp.status_code == 401:
                return False, None, "UPES session token expired (HTTP 401)"

            # 2. Try System B: Exam-Pro Transcript Fallback
            exam_pro_url = f"{base_url}/integratons/api/data/exam-pro"
            payload = {
                "StudentUniqueId": student_id,
                "TermCode": "ALL",
                "ActivityCode": "transcript"
            }
            ep_resp = requests.post(exam_pro_url, json=payload, headers=headers, timeout=12)
            if ep_resp.status_code == 200:
                ep_data = ep_resp.json()
                record = normalize_exam_pro_transcript(ep_data, provenance="live", is_stale=False)
                record.user_id = user_id
                self.store_academic_record(record)
                return True, record, "Live results synchronized via Exam-Pro service"

            return False, None, f"Upstream returned HTTP {resp.status_code}"

        except Exception as e:
            return False, None, f"Network/Upstream error: {str(e)}"

    def sync_user_results(self, user_id: str, force: bool = False) -> Dict[str, Any]:
        """
        Synchronizes results for a user.
        Attempts live fetch first; on failure, falls back to stored LKG with is_stale=True.
        """
        t0 = time.time()
        success, live_record, msg = self.fetch_live_results(user_id)
        duration = round((time.time() - t0) * 1000, 2)

        conn = self.conn_factory()
        try:
            if success and live_record:
                # Record successful sync
                with conn:
                    conn.execute("""
                        INSERT INTO academic_result_sync_history (
                            user_id, timestamp, source, status, terms_synced, courses_synced, duration_ms, details
                        ) VALUES (?, ?, 'live', 'SUCCESS', ?, ?, ?, ?)
                    """, (
                        user_id,
                        time.time(),
                        len(live_record.semesters),
                        sum(len(s.courses) for s in live_record.semesters),
                        duration,
                        msg
                    ))
                return {
                    "status": "success",
                    "source": "live",
                    "message": msg,
                    "record": live_record.to_dict(),
                    "duration_ms": duration
                }
            else:
                # Fallback to LKG
                cached_record = self.get_user_results(user_id)
                if cached_record.semesters:
                    cached_record.provenance = "lkg"
                    cached_record.is_stale = True
                    # Update DB with LKG status
                    with conn:
                        conn.execute("UPDATE academic_results SET provenance = 'lkg', is_stale = 1 WHERE user_id = ?", (user_id,))
                        conn.execute("""
                            INSERT INTO academic_result_sync_history (
                                user_id, timestamp, source, status, terms_synced, courses_synced, duration_ms, details
                            ) VALUES (?, ?, 'lkg', 'DEGRADED', ?, ?, ?, ?)
                        """, (
                            user_id,
                            time.time(),
                            len(cached_record.semesters),
                            sum(len(s.courses) for s in cached_record.semesters),
                            duration,
                            f"Live fetch failed ({msg}); serving LKG cached records"
                        ))
                    return {
                        "status": "degraded",
                        "source": "lkg",
                        "message": f"Live fetch failed: {msg}. Serving LKG cached records.",
                        "record": cached_record.to_dict(),
                        "duration_ms": duration
                    }
                else:
                    with conn:
                        conn.execute("""
                            INSERT INTO academic_result_sync_history (
                                user_id, timestamp, source, status, terms_synced, courses_synced, duration_ms, details
                            ) VALUES (?, ?, 'none', 'FAILED', 0, 0, ?, ?)
                        """, (user_id, time.time(), duration, msg))
                    return {
                        "status": "failed",
                        "source": "none",
                        "message": f"Results fetch failed: {msg} (no cached records)",
                        "record": None,
                        "duration_ms": duration
                    }
        finally:
            conn.close()

    def sync_all_active_users(self) -> Dict[str, Any]:
        """Synchronizes academic results across all active users."""
        conn = self.conn_factory()
        users = set()
        try:
            cur = conn.cursor()
            cur.execute("SELECT DISTINCT user_id FROM upes_auth_sessions")
            for r in cur.fetchall():
                users.add(r[0])
            cur.execute("SELECT DISTINCT user_id FROM academic_results")
            for r in cur.fetchall():
                users.add(r[0])
            if config.UPES_ACCESS_TOKEN and config.UPES_STUDENT_CODE:
                users.add("admin")
        finally:
            conn.close()

        summaries = {}
        for uid in sorted(users):
            try:
                summaries[uid] = self.sync_user_results(uid)
            except Exception as e:
                summaries[uid] = {
                    "status": "failed",
                    "source": "error",
                    "message": str(e),
                    "record": None
                }
        return summaries
