"""
attendance_sync.py — Authoritative UPES Attendance & Classroom Card-Punch Engine.

Architecture:
- Ingests official academic structure from UPES API Gateway (/student-attendance/attendancedropdown).
- Ingests official attendance summaries and granular session ledgers (/student-attendance/studentattendancesummary).
- Reuses authenticated UPES browser session bridge and encrypted credentials via UpesSessionBroker.
- Maps in-classroom RFID reader card punches (AttendanceSubTypeCode: "CRA", StudentPunchInTime: "HH:MM").
- Persists data to SQLite (config.UNIFIED_DB_FILE) with zero ORM overhead.
- Implements generic safe bunk and recovery mathematics with configurable threshold (default 75%).
- Correlates future scheduled timetable classes for attendance projections without mutating official ledger.
"""

import os
import sys
import json
import time
import math
import secrets
import logging
import urllib.request
import urllib.error
import datetime
from typing import Dict, Any, List, Optional, Tuple

import config

logger = logging.getLogger("nexusnode.attendance_sync")
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] [ATTENDANCE] %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


# ==============================================================================
# 1. DATABASE SCHEMA & MIGRATIONS (DIRECT SQLITE — NO ORM)
# ==============================================================================

def init_attendance_tables(conn):
    """
    Initializes normalized SQLite tables for official UPES attendance,
    session records, and synchronization history.
    """
    # 1. Academic Terms Table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS academic_terms (
            user_id TEXT NOT NULL,
            term_code_id INTEGER NOT NULL,
            term_code TEXT NOT NULL,
            term_name TEXT,
            course_family_id INTEGER NOT NULL,
            start_date TEXT,
            end_date TEXT,
            is_current INTEGER NOT NULL DEFAULT 0,
            last_synced_at REAL NOT NULL,
            PRIMARY KEY (user_id, term_code_id, course_family_id)
        );
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_terms_user_current ON academic_terms (user_id, is_current);")

    # 2. Academic Modules Table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS academic_modules (
            user_id TEXT NOT NULL,
            module_id INTEGER NOT NULL,
            term_code_id INTEGER NOT NULL,
            module_name TEXT NOT NULL,
            module_code TEXT,
            course_family_id INTEGER NOT NULL,
            last_synced_at REAL NOT NULL,
            PRIMARY KEY (user_id, module_id)
        );
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_modules_user_term ON academic_modules (user_id, term_code_id);")

    # 3. Official Attendance Summaries Table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS official_attendance_summaries (
            user_id TEXT NOT NULL,
            module_id INTEGER NOT NULL,
            total_sessions INTEGER NOT NULL DEFAULT 0,
            total_attended INTEGER NOT NULL DEFAULT 0,
            total_condoned INTEGER NOT NULL DEFAULT 0,
            attendance_percentage REAL NOT NULL DEFAULT 0.0,
            term_attendance_percentage REAL,
            last_synced_at REAL NOT NULL,
            PRIMARY KEY (user_id, module_id)
        );
    """)

    # 4. Granular Academic Sessions Ledger Table (Keyed by native SessionId)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS academic_sessions (
            user_id TEXT NOT NULL,
            session_id INTEGER NOT NULL,
            module_id INTEGER NOT NULL,
            course_name TEXT NOT NULL,
            course_code TEXT,
            session_date TEXT NOT NULL,
            start_time TEXT,
            end_time TEXT,
            faculty TEXT,
            room TEXT,
            virtual_room TEXT,
            mode TEXT,
            session_type TEXT,
            session_status TEXT,
            attendance_status TEXT NOT NULL,
            attendance_subtype TEXT,
            punch_in_time TEXT,
            reason_json TEXT,
            last_synced_at REAL NOT NULL,
            PRIMARY KEY (user_id, session_id)
        );
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user_module ON academic_sessions (user_id, module_id);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user_date ON academic_sessions (user_id, session_date);")

    # 5. Attendance Synchronization History
    conn.execute("""
        CREATE TABLE IF NOT EXISTS attendance_sync_history (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            timestamp REAL NOT NULL,
            modules_synced INTEGER NOT NULL,
            sessions_synced INTEGER NOT NULL,
            status TEXT NOT NULL,
            details TEXT
        );
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_att_history_user ON attendance_sync_history (user_id, timestamp);")

    # 6. Synchronization Locks (Distributed DB Lease for Attendance Sync)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS attendance_sync_locks (
            user_id TEXT PRIMARY KEY,
            locked_at REAL NOT NULL,
            expires_at REAL NOT NULL,
            lock_token TEXT NOT NULL
        );
    """)


# ==============================================================================
# 2. CONSTANTS & API CONTRACTS
# ==============================================================================

UPES_ATTENDANCE_DROPDOWN_URL = "https://myupes-beta.upes.ac.in/apigateway/student-attendance/attendancedropdown"
UPES_ATTENDANCE_SUMMARY_URL = "https://myupes-beta.upes.ac.in/apigateway/student-attendance/studentattendancesummary"
UPES_CLIENT_SECRET_DEFAULT = "ku7GUMtyT8er51rTfTc7HC"

# Subtype Mappings
SUBTYPE_DESCRIPTIONS = {
    "CRA": "Classroom Reader Attendance",
    "OA": "Online / Alternative Attendance",
    "MANUAL": "Local Legacy Punch"
}


# ==============================================================================
# 3. GENERIC ATTENDANCE & SAFE BUNK MATHEMATICS
# ==============================================================================

def calculate_safe_bunks(attended: int, conducted: int, threshold: float = 0.75) -> int:
    """
    Calculates the maximum number of future consecutive classes a student can safely miss
    while keeping attendance percentage >= threshold.
    
    Formula:
        A / (C + B) >= T  =>  A >= T*C + T*B  =>  T*B <= A - T*C  =>  B = floor((A - T*C) / T)
    """
    if threshold <= 0.0 or threshold >= 1.0:
        return 0
    if conducted <= 0 or attended <= 0:
        return 0
    
    # Check if currently at or above threshold
    numerator = attended - (threshold * conducted)
    if numerator < 0:
        return 0
    
    bunks = math.floor(numerator / threshold)
    return max(0, int(bunks))


def calculate_recovery_classes(attended: int, conducted: int, threshold: float = 0.75) -> int:
    """
    Calculates the minimum number of consecutive upcoming classes a student must attend
    to raise attendance percentage to >= threshold when currently below threshold.
    
    Formula:
        (A + R) / (C + R) >= T  =>  A + R >= T*C + T*R  =>  R*(1 - T) >= T*C - A  =>  R = ceil((T*C - A) / (1 - T))
    """
    if threshold <= 0.0 or threshold >= 1.0:
        return 0
    if conducted <= 0:
        return 0
    
    current_pct = attended / conducted
    if current_pct >= threshold:
        return 0
    
    numerator = (threshold * conducted) - attended
    denominator = 1.0 - threshold
    if denominator <= 0:
        return 0
    
    recovery = math.ceil(numerator / denominator)
    return max(0, int(recovery))


def compute_attendance_percentage(attended: int, conducted: int, condoned: int = 0) -> float:
    """Computes round-off attendance percentage handling C=0 gracefully."""
    effective_attended = attended + condoned
    if conducted <= 0:
        return 100.0
    pct = (effective_attended / conducted) * 100.0
    return round(min(100.0, max(0.0, pct)), 2)


# ==============================================================================
# 4. HTTP CLIENT FOR AUTHORITATIVE UPES ATTENDANCE
# ==============================================================================

def execute_upes_attendance_request(
    endpoint_url: str,
    payload: Dict[str, Any],
    access_token: str,
    student_uuid: str,
    client_secret: str = UPES_CLIENT_SECRET_DEFAULT,
    timeout: int = 15
) -> Tuple[Optional[Any], Optional[str]]:
    """
    Executes an authenticated JSON POST request to UPES Attendance API Gateway.
    Injects mandatory microservice headers discovered in Phase 1.
    Never logs or exposes tokens or secrets.
    """
    req_headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {access_token}",
        "x-applicationname": "connectportal",
        "x-requestfrom": "web",
        "x-appsecret": client_secret,
        "x-studentUniqueId": student_uuid
    }

    try:
        body_bytes = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(endpoint_url, data=body_bytes, headers=req_headers, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.status
            raw_text = resp.read().decode("utf-8")
            if status != 200:
                return None, f"HTTP {status}: {raw_text[:200]}"
            try:
                data = json.loads(raw_text)
                return data, None
            except Exception as e:
                return None, f"invalid_json: Failed to parse response: {str(e)}"
    except urllib.error.HTTPError as he:
        status_code = he.code
        err_body = ""
        try:
            err_body = he.read().decode("utf-8", errors="ignore")
        except Exception:
            pass
        if status_code in (401, 403):
            return None, f"auth_required: HTTP {status_code} Unauthorized from UPES API."
        return None, f"http_error_{status_code}: {err_body[:200]}"
    except urllib.error.URLError as ue:
        return None, f"network_error: {str(ue.reason)}"
    except Exception as ex:
        return None, f"request_failed: {str(ex)}"


# ==============================================================================
# 5. DISTRIBUTED SYNC LEASE LOCK (SQLITE-BACKED)
# ==============================================================================

class AttendanceSyncLease:
    """Ensures single-flight attendance synchronization per user."""

    def __init__(self, conn_factory, user_id: str, lease_seconds: int = 120):
        self.conn_factory = conn_factory
        self.user_id = user_id
        self.lease_seconds = lease_seconds
        self.token = secrets.token_hex(16)
        self.acquired = False

    def acquire(self) -> bool:
        now = time.time()
        conn = self.conn_factory()
        try:
            cur = conn.cursor()
            cur.execute("SELECT locked_at, expires_at, lock_token FROM attendance_sync_locks WHERE user_id = ?", (self.user_id,))
            row = cur.fetchone()
            if row:
                _, expires_at, _ = row
                if now < expires_at:
                    return False
            cur.execute("""
                INSERT INTO attendance_sync_locks (user_id, locked_at, expires_at, lock_token)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    locked_at = excluded.locked_at,
                    expires_at = excluded.expires_at,
                    lock_token = excluded.lock_token
            """, (self.user_id, now, now + self.lease_seconds, self.token))
            conn.commit()
            self.acquired = True
            return True
        finally:
            conn.close()

    def release(self):
        if not self.acquired:
            return
        conn = self.conn_factory()
        try:
            conn.execute("DELETE FROM attendance_sync_locks WHERE user_id = ? AND lock_token = ?", (self.user_id, self.token))
            conn.commit()
        finally:
            conn.close()


# ==============================================================================
# 6. ATTENDANCE SERVICE (CORE ORCHESTRATION & ANALYTICS)
# ==============================================================================

class AttendanceService:
    """
    Authoritative Attendance Service for NexusNode.
    Owns academic hierarchy ingestion, attendance ledger synchronization,
    classroom card-punch tracking, and safe bunk analytics.
    """

    def __init__(self, conn_factory, session_broker=None):
        self.conn_factory = conn_factory
        self.session_broker = session_broker

    def get_attendance_status(self, user_id: str) -> Dict[str, Any]:
        """Returns non-sensitive health and synchronization status for a user."""
        conn = self.conn_factory()
        try:
            cur = conn.cursor()
            # 1. Check last sync history
            cur.execute("""
                SELECT timestamp, modules_synced, sessions_synced, status, details
                FROM attendance_sync_history
                WHERE user_id = ?
                ORDER BY timestamp DESC LIMIT 1
            """, (user_id,))
            last_sync_row = cur.fetchone()

            # 2. Count modules and sessions in database
            cur.execute("SELECT COUNT(*) FROM academic_modules WHERE user_id = ?", (user_id,))
            modules_count = cur.fetchone()[0]

            cur.execute("SELECT COUNT(*) FROM academic_sessions WHERE user_id = ?", (user_id,))
            sessions_count = cur.fetchone()[0]

            cur.execute("SELECT COUNT(*) FROM academic_sessions WHERE user_id = ? AND punch_in_time != ''", (user_id,))
            punches_count = cur.fetchone()[0]

            # 3. Check current term
            cur.execute("SELECT term_code, term_name, start_date, end_date FROM academic_terms WHERE user_id = ? AND is_current = 1 LIMIT 1", (user_id,))
            term_row = cur.fetchone()
            current_term = {
                "term_code": term_row[0],
                "term_name": term_row[1],
                "start_date": term_row[2],
                "end_date": term_row[3]
            } if term_row else None

            last_sync = None
            sync_state = "NEVER_SYNCED"
            if last_sync_row:
                ts, m_synced, s_synced, st, det = last_sync_row
                det_obj = {}
                try:
                    det_obj = json.loads(det) if det else {}
                except Exception:
                    pass
                last_sync = {
                    "timestamp": ts,
                    "modules_synced": m_synced,
                    "sessions_synced": s_synced,
                    "status": st,
                    "error": det_obj.get("error")
                }
                sync_state = st

            # Evaluate freshness: if sync older than 24 hours, mark STALE
            now = time.time()
            if last_sync and sync_state == "ACTIVE" and (now - last_sync["timestamp"]) > 86400:
                sync_state = "STALE"

            auth_status = self.session_broker.get_session_status(user_id) if self.session_broker else {}

            return {
                "user_id": user_id,
                "sync_status": sync_state,
                "auth_status": auth_status.get("auth_status", "UNKNOWN"),
                "auth_details": auth_status,
                "modules_count": modules_count,
                "sessions_count": sessions_count,
                "punches_count": punches_count,
                "current_term": current_term,
                "last_sync": last_sync
            }
        finally:
            conn.close()

    def sync_user_attendance(self, user_id: str) -> Dict[str, Any]:
        """
        Executes live synchronization of UPES academic structure, official attendance summaries,
        and session ledgers for all enrolled modules in the current term.
        Preserves last-known-good state on partial failures.
        """
        lease = AttendanceSyncLease(self.conn_factory, user_id)
        if not lease.acquire():
            return {
                "status": "LOCKED",
                "message": f"Attendance synchronization already active for user '{user_id}'.",
                "modules_synced": 0,
                "sessions_synced": 0
            }

        now = time.time()
        try:
            # 1. Resolve UPES Session & Credentials via Broker State Machine
            if not self.session_broker:
                return {"status": "ERROR", "message": "UpesSessionBroker not configured on service."}

            session_tuple = None
            auth_err = None

            if hasattr(self.session_broker, "resolve_session"):
                try:
                    res = self.session_broker.resolve_session(user_id)
                    if isinstance(res, tuple) and len(res) == 2:
                        session_tuple, auth_err = res
                except Exception:
                    pass

            if not session_tuple and hasattr(self.session_broker, "service"):
                try:
                    direct = self.session_broker.service.get_upes_session(user_id)
                    if direct and isinstance(direct, (tuple, list)) and len(direct) >= 4:
                        session_tuple = direct
                        auth_err = None
                except Exception:
                    pass

            if auth_err or not session_tuple:
                bridge_status = getattr(getattr(self.session_broker, "browser_bridge", None), "last_check_status", "unknown")
                self._record_sync_history(user_id, now, 0, 0, "AUTH_REQUIRED", {"error": f"No valid UPES session ({auth_err}). Bridge: {bridge_status}"})
                return {
                    "status": "AUTH_REQUIRED",
                    "message": f"No valid UPES portal session available ({auth_err}). Please log in to UPES Connect Portal."
                }

            token, student_uuid, _, expires_at = session_tuple

            # 2. Fetch Academic Hierarchy & Dropdown
            dd_data, dd_err = execute_upes_attendance_request(
                UPES_ATTENDANCE_DROPDOWN_URL,
                {"StudentUniqueID": student_uuid},
                token,
                student_uuid
            )

            # If token was invalidated server-side, attempt one reacquisition via broker
            if dd_err and "auth_required" in dd_err:
                session_tuple, auth_err = self.session_broker.resolve_session(user_id)
                if session_tuple:
                    token, student_uuid, _, expires_at = session_tuple
                    dd_data, dd_err = execute_upes_attendance_request(
                        UPES_ATTENDANCE_DROPDOWN_URL,
                        {"StudentUniqueID": student_uuid},
                        token,
                        student_uuid
                    )

            if dd_err or not dd_data:
                err_msg = f"Failed to fetch academic dropdown: {dd_err}"
                self._record_sync_history(user_id, now, 0, 0, "ERROR", {"error": err_msg})
                return {"status": "ERROR", "message": err_msg}

            # 3. Parse Terms & Locate Active Term
            term_list = []
            current_term_obj = None
            fam_list = dd_data if isinstance(dd_data, list) else dd_data.get("CourseFamilyDropdownList", [dd_data])

            for fam in fam_list:
                fam_id = fam.get("CourseFamilyId", 0)
                for t in fam.get("TermDropdownDetailsList", []):
                    is_curr = bool(t.get("IsCurrentTerm", False))
                    term_entry = {
                        "user_id": user_id,
                        "term_code_id": t.get("TermCodeId", 0),
                        "term_code": t.get("TermCode", ""),
                        "term_name": t.get("TermCode", ""),
                        "course_family_id": fam_id,
                        "start_date": t.get("TermStartDate", "").split("T")[0] if t.get("TermStartDate") else None,
                        "end_date": t.get("TermEndDate", "").split("T")[0] if t.get("TermEndDate") else None,
                        "is_current": 1 if is_curr else 0,
                        "modules": t.get("ModuleDropdownDetailsList", [])
                    }
                    term_list.append(term_entry)
                    if is_curr:
                        current_term_obj = term_entry

            if not current_term_obj and term_list:
                # Fallback to the highest term_code_id
                current_term_obj = max(term_list, key=lambda x: x["term_code_id"])
                current_term_obj["is_current"] = 1

            if not current_term_obj:
                err_msg = "No valid academic terms discovered in UPES dropdown."
                self._record_sync_history(user_id, now, 0, 0, "ERROR", {"error": err_msg})
                return {"status": "ERROR", "message": err_msg}

            # 4. Save Academic Terms to Database
            conn = self.conn_factory()
            try:
                for t in term_list:
                    conn.execute("""
                        INSERT INTO academic_terms (
                            user_id, term_code_id, term_code, term_name,
                            course_family_id, start_date, end_date, is_current, last_synced_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(user_id, term_code_id, course_family_id) DO UPDATE SET
                            term_code = excluded.term_code,
                            term_name = excluded.term_name,
                            start_date = excluded.start_date,
                            end_date = excluded.end_date,
                            is_current = excluded.is_current,
                            last_synced_at = excluded.last_synced_at
                    """, (
                        user_id, t["term_code_id"], t["term_code"], t["term_name"],
                        t["course_family_id"], t["start_date"], t["end_date"], t["is_current"], now
                    ))
                conn.commit()
            finally:
                conn.close()

            # 5. Process Modules in the Current Term
            modules = current_term_obj.get("modules", [])
            term_start = current_term_obj.get("start_date") or "2026-01-01"
            term_end = current_term_obj.get("end_date") or "2026-12-31"
            today_str = datetime.date.today().strftime("%Y-%m-%d")

            modules_synced = 0
            total_sessions_synced = 0
            failed_modules = []

            for mod in modules:
                m_id = mod.get("ModuleId")
                m_name = (mod.get("ModuleName") or "").strip()
                if not m_id:
                    continue

                # Fetch attendance summary and sessions for this module
                mod_payload = {
                    "StudentUniqueID": student_uuid,
                    "CourseFamilyId": current_term_obj["course_family_id"],
                    "TermCodeId": current_term_obj["term_code_id"],
                    "CourseList": [{"ID": m_id, "Name": m_name}],
                    "StartDate": term_start,
                    "EndDate": today_str,
                    "TermStartDate": term_start,
                    "TermEndDate": term_end
                }

                att_data, att_err = execute_upes_attendance_request(
                    UPES_ATTENDANCE_SUMMARY_URL,
                    mod_payload,
                    token,
                    student_uuid
                )

                if att_err or not att_data:
                    logger.warning("Failed to fetch attendance for module %s (%s): %s", m_id, m_name, att_err)
                    failed_modules.append({"module_id": m_id, "module_name": m_name, "error": att_err})
                    continue

                # Parse summary
                summary_data = att_data.get("AttendanceSummary") or {}
                tot_conducted = int(summary_data.get("TotalSessionCount", 0))
                tot_attended = int(summary_data.get("TotalAttendance", 0))
                tot_condoned = int(summary_data.get("TotalCondonedAttendanceCount", 0))
                att_pct = float(summary_data.get("TotalPresentPercentage", 0.0))
                term_pct = float(summary_data.get("TotalPresentPercentageTermWise", att_pct))

                # Parse granular sessions
                info_list = att_data.get("AttendanceInfo") or []
                sess_records = []
                for info in info_list:
                    for s in info.get("AttendanceDetails") or []:
                        s_id = s.get("SessionId")
                        if not s_id:
                            continue
                        
                        s_date = s.get("SessionDate", "").split("T")[0] if s.get("SessionDate") else ""
                        s_time = s.get("SessionTime", "")
                        start_t, end_t = "", ""
                        if "-" in s_time:
                            parts = s_time.split("-")
                            start_t, end_t = parts[0].strip(), parts[1].strip()

                        add_details = s.get("AdditionalDetails") or {}
                        room_val = add_details.get("ClassRoom") or ""
                        virt_val = add_details.get("VirtualRoom") or ""
                        mode_val = add_details.get("Mode") or "Class Room"
                        sess_status = add_details.get("SessionStatus") or "On-Time"
                        reason_list = add_details.get("Reason") or []

                        sess_records.append({
                            "session_id": int(s_id),
                            "module_id": m_id,
                            "course_name": m_name,
                            "course_code": "",
                            "session_date": s_date,
                            "start_time": start_t,
                            "end_time": end_t,
                            "faculty": (s.get("FacultyNames") or "").strip(),
                            "room": room_val,
                            "virtual_room": virt_val,
                            "mode": mode_val,
                            "session_type": s.get("SessionType") or "Regular",
                            "session_status": sess_status,
                            "attendance_status": (s.get("AttendanceStatus") or "UNKNOWN").upper(),
                            "attendance_subtype": s.get("AttendanceSubTypeCode") or "",
                            "punch_in_time": (s.get("StudentPunchInTime") or "").strip(),
                            "reason_json": json.dumps(reason_list)
                        })

                # Persist module, summary, and sessions atomically in SQLite
                conn = self.conn_factory()
                try:
                    # Upsert module
                    conn.execute("""
                        INSERT INTO academic_modules (
                            user_id, module_id, term_code_id, module_name, module_code, course_family_id, last_synced_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(user_id, module_id) DO UPDATE SET
                            module_name = excluded.module_name,
                            term_code_id = excluded.term_code_id,
                            course_family_id = excluded.course_family_id,
                            last_synced_at = excluded.last_synced_at
                    """, (user_id, m_id, current_term_obj["term_code_id"], m_name, "", current_term_obj["course_family_id"], now))

                    # Upsert official summary
                    conn.execute("""
                        INSERT INTO official_attendance_summaries (
                            user_id, module_id, total_sessions, total_attended, total_condoned,
                            attendance_percentage, term_attendance_percentage, last_synced_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(user_id, module_id) DO UPDATE SET
                            total_sessions = excluded.total_sessions,
                            total_attended = excluded.total_attended,
                            total_condoned = excluded.total_condoned,
                            attendance_percentage = excluded.attendance_percentage,
                            term_attendance_percentage = excluded.term_attendance_percentage,
                            last_synced_at = excluded.last_synced_at
                    """, (user_id, m_id, tot_conducted, tot_attended, tot_condoned, att_pct, term_pct, now))

                    # Upsert individual sessions
                    for sr in sess_records:
                        conn.execute("""
                            INSERT INTO academic_sessions (
                                user_id, session_id, module_id, course_name, course_code,
                                session_date, start_time, end_time, faculty, room, virtual_room,
                                mode, session_type, session_status, attendance_status,
                                attendance_subtype, punch_in_time, reason_json, last_synced_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            ON CONFLICT(user_id, session_id) DO UPDATE SET
                                module_id = excluded.module_id,
                                course_name = excluded.course_name,
                                session_date = excluded.session_date,
                                start_time = excluded.start_time,
                                end_time = excluded.end_time,
                                faculty = excluded.faculty,
                                room = excluded.room,
                                virtual_room = excluded.virtual_room,
                                mode = excluded.mode,
                                session_type = excluded.session_type,
                                session_status = excluded.session_status,
                                attendance_status = excluded.attendance_status,
                                attendance_subtype = excluded.attendance_subtype,
                                punch_in_time = excluded.punch_in_time,
                                reason_json = excluded.reason_json,
                                last_synced_at = excluded.last_synced_at
                        """, (
                            user_id, sr["session_id"], sr["module_id"], sr["course_name"], sr["course_code"],
                            sr["session_date"], sr["start_time"], sr["end_time"], sr["faculty"], sr["room"],
                            sr["virtual_room"], sr["mode"], sr["session_type"], sr["session_status"],
                            sr["attendance_status"], sr["attendance_subtype"], sr["punch_in_time"],
                            sr["reason_json"], now
                        ))

                    conn.commit()
                    modules_synced += 1
                    total_sessions_synced += len(sess_records)
                finally:
                    conn.close()

            # 6. Determine Final Sync Status
            final_status = "ACTIVE"
            if failed_modules:
                final_status = "PARTIAL" if modules_synced > 0 else "ERROR"

            self._record_sync_history(
                user_id, now, modules_synced, total_sessions_synced, final_status,
                {"failed_modules": failed_modules, "total_modules": len(modules)}
            )

            return {
                "status": final_status,
                "message": f"Successfully synchronized {modules_synced}/{len(modules)} modules ({total_sessions_synced} sessions).",
                "modules_synced": modules_synced,
                "sessions_synced": total_sessions_synced,
                "failed_modules": failed_modules
            }

        except Exception as e:
            logger.exception("Unexpected error during attendance sync: %s", str(e))
            self._record_sync_history(user_id, now, 0, 0, "ERROR", {"error": str(e)})
            return {"status": "ERROR", "message": f"Sync failed: {str(e)}"}
        finally:
            lease.release()

    def _record_sync_history(self, user_id: str, timestamp: float, modules_synced: int, sessions_synced: int, status: str, details: Dict[str, Any]):
        """Records an entry in attendance_sync_history."""
        conn = self.conn_factory()
        try:
            conn.execute("""
                INSERT INTO attendance_sync_history (id, user_id, timestamp, modules_synced, sessions_synced, status, details)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                f"att_sync_{int(timestamp)}_{secrets.token_hex(4)}",
                user_id, timestamp, modules_synced, sessions_synced, status, json.dumps(details)
            ))
            conn.commit()
        except Exception:
            pass
        finally:
            conn.close()

    def get_attendance_analytics(self, user_id: str, threshold: float = 0.75) -> Dict[str, Any]:
        """
        Computes authoritative attendance metrics, safe bunks, recovery classes,
        today's live schedule, and upcoming timetable projections.
        """
        conn = self.conn_factory()
        try:
            cur = conn.cursor()

            # 1. Fetch all modules and official summaries for user
            cur.execute("""
                SELECT m.module_id, m.module_name, m.module_code,
                       s.total_sessions, s.total_attended, s.total_condoned,
                       s.attendance_percentage, s.term_attendance_percentage, s.last_synced_at
                FROM academic_modules m
                LEFT JOIN official_attendance_summaries s ON m.module_id = s.module_id AND m.user_id = s.user_id
                WHERE m.user_id = ?
                ORDER BY m.module_name ASC
            """, (user_id,))
            mod_rows = cur.fetchall()

            # 2. Fetch session stats grouped by module
            cur.execute("""
                SELECT module_id,
                       COUNT(*) as total_logged,
                       SUM(CASE WHEN attendance_status = 'PRESENT' THEN 1 ELSE 0 END) as present_count,
                       SUM(CASE WHEN attendance_status = 'ABSENT' THEN 1 ELSE 0 END) as absent_count,
                       SUM(CASE WHEN attendance_status = 'CONDONED' THEN 1 ELSE 0 END) as condoned_count
                FROM academic_sessions
                WHERE user_id = ?
                GROUP BY module_id
            """, (user_id,))
            session_stats = {r[0]: {"total": r[1], "present": r[2], "absent": r[3], "condoned": r[4]} for r in cur.fetchall()}

            # 3. Load timetable for next-class projections
            timetable_sessions = []
            if self.session_broker and hasattr(self.session_broker, "service"):
                try:
                    timetable_sessions, _ = self.session_broker.service.load_timetable_sessions(user_id, rolling_two_weeks=False)
                except Exception:
                    pass

            now_dt = datetime.datetime.now()
            today_str = now_dt.strftime("%Y-%m-%d")
            now_time_str = now_dt.strftime("%H:%M:%S")

            subject_reports = []
            overall_conducted = 0
            overall_attended = 0
            overall_condoned = 0
            overall_safe_bunks = 0
            critical_count = 0

            for r in mod_rows:
                m_id, m_name, m_code, tot_s, tot_a, tot_c, att_pct, term_pct, last_sync = r
                conducted = tot_s or 0
                attended = tot_a or 0
                condoned = tot_c or 0
                pct = att_pct if att_pct is not None else compute_attendance_percentage(attended, conducted, condoned)

                # Safe bunks & recovery calculations
                safe_bunks = calculate_safe_bunks(attended + condoned, conducted, threshold)
                recovery_needed = calculate_recovery_classes(attended + condoned, conducted, threshold)

                # Check discrepancy between session records and official summary
                sess_stat = session_stats.get(m_id, {"total": 0, "present": 0, "absent": 0, "condoned": 0})
                discrepancy = (sess_stat["total"] > 0 and sess_stat["total"] != conducted)

                # Status pill
                if pct < 75.0:
                    status_badge = "critical"
                    critical_count += 1
                elif pct < 80.0:
                    status_badge = "warning"
                else:
                    status_badge = "safe"

                # Find next upcoming scheduled class from timetable
                next_class = None
                if timetable_sessions:
                    matching_sched = [
                        s for s in timetable_sessions
                        if (s.course_name.strip().lower() == m_name.strip().lower() or
                            (m_code and s.course_code.strip().lower() == m_code.strip().lower())) and
                        (s.date > today_str or (s.date == today_str and s.start_time > now_time_str))
                    ]
                    matching_sched.sort(key=lambda s: (s.date, s.start_time))
                    if matching_sched:
                        nxt = matching_sched[0]
                        # Compute projections
                        proj_attend = compute_attendance_percentage(attended + condoned + 1, conducted + 1)
                        proj_skip = compute_attendance_percentage(attended + condoned, conducted + 1)
                        next_class = {
                            "date": nxt.date,
                            "start_time": nxt.start_time,
                            "end_time": nxt.end_time,
                            "room": nxt.room,
                            "faculty": nxt.faculty,
                            "meeting_link": getattr(nxt, "meeting_link", ""),
                            "projected_pct_if_attended": proj_attend,
                            "projected_pct_if_skipped": proj_skip
                        }

                overall_conducted += conducted
                overall_attended += attended
                overall_condoned += condoned
                overall_safe_bunks += safe_bunks

                subject_reports.append({
                    "module_id": m_id,
                    "course_name": m_name,
                    "course_code": m_code or "",
                    "conducted_classes": conducted,
                    "attended_classes": attended,
                    "absent_classes": max(0, conducted - attended - condoned),
                    "condoned_classes": condoned,
                    "attendance_percentage": pct,
                    "term_attendance_percentage": term_pct,
                    "safe_bunks_remaining": safe_bunks,
                    "recovery_classes_required": recovery_needed,
                    "status": status_badge,
                    "has_discrepancy": discrepancy,
                    "session_counts": sess_stat,
                    "last_synced_at": last_sync,
                    "next_session": next_class
                })

            # 4. Today's sessions & live card punches
            cur.execute("""
                SELECT session_id, module_id, course_name, course_code,
                       session_date, start_time, end_time, faculty, room,
                       attendance_status, attendance_subtype, punch_in_time
                FROM academic_sessions
                WHERE user_id = ? AND session_date = ?
                ORDER BY start_time ASC
            """, (user_id, today_str))
            today_sessions = [
                {
                    "session_id": r[0],
                    "module_id": r[1],
                    "course_name": r[2],
                    "course_code": r[3],
                    "session_date": r[4],
                    "start_time": r[5],
                    "end_time": r[6],
                    "faculty": r[7],
                    "room": r[8],
                    "attendance_status": r[9],
                    "attendance_subtype": r[10],
                    "punch_in_time": r[11],
                    "is_punched": bool(r[11] and r[11].strip())
                }
                for r in cur.fetchall()
            ]

            # 5. Recent session history (latest 50)
            cur.execute("""
                SELECT session_id, module_id, course_name, course_code,
                       session_date, start_time, end_time, faculty, room,
                       attendance_status, attendance_subtype, punch_in_time, last_synced_at
                FROM academic_sessions
                WHERE user_id = ?
                ORDER BY session_date DESC, start_time DESC LIMIT 50
            """, (user_id,))
            recent_sessions = [
                {
                    "session_id": r[0],
                    "module_id": r[1],
                    "course_name": r[2],
                    "course_code": r[3],
                    "session_date": r[4],
                    "start_time": r[5],
                    "end_time": r[6],
                    "faculty": r[7],
                    "room": r[8],
                    "attendance_status": r[9],
                    "attendance_subtype": r[10],
                    "punch_in_time": r[11],
                    "subtype_desc": SUBTYPE_DESCRIPTIONS.get(r[10], r[10]),
                    "last_synced_at": r[12]
                }
                for r in cur.fetchall()
            ]

            overall_pct = compute_attendance_percentage(overall_attended, overall_conducted, overall_condoned)
            overall_missed = max(0, overall_conducted - overall_attended - overall_condoned)

            return {
                "user_id": user_id,
                "as_of_date": today_str,
                "as_of_time": now_time_str,
                "threshold": threshold,
                "overall": {
                    "conducted_classes": overall_conducted,
                    "attended_classes": overall_attended,
                    "condoned_classes": overall_condoned,
                    "missed_classes": overall_missed,
                    "attendance_percentage": overall_pct,
                    "total_safe_bunks": overall_safe_bunks,
                    "critical_subjects": critical_count,
                    "total_subjects": len(subject_reports)
                },
                "subjects": subject_reports,
                "today_classes": today_sessions,
                "recent_sessions": recent_sessions
            }
        finally:
            conn.close()

    def get_sessions(
        self,
        user_id: str,
        module_id: Optional[int] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        limit: int = 200
    ) -> List[Dict[str, Any]]:
        """Retrieves individual session ledger records with optional filters."""
        conn = self.conn_factory()
        try:
            cur = conn.cursor()
            query = """
                SELECT session_id, module_id, course_name, course_code,
                       session_date, start_time, end_time, faculty, room, virtual_room,
                       mode, session_type, session_status, attendance_status,
                       attendance_subtype, punch_in_time, reason_json, last_synced_at
                FROM academic_sessions
                WHERE user_id = ?
            """
            params = [user_id]
            if module_id is not None:
                query += " AND module_id = ?"
                params.append(module_id)
            if date_from:
                query += " AND session_date >= ?"
                params.append(date_from)
            if date_to:
                query += " AND session_date <= ?"
                params.append(date_to)
            query += " ORDER BY session_date DESC, start_time DESC LIMIT ?"
            params.append(limit)

            cur.execute(query, params)
            return [
                {
                    "session_id": r[0],
                    "module_id": r[1],
                    "course_name": r[2],
                    "course_code": r[3],
                    "session_date": r[4],
                    "start_time": r[5],
                    "end_time": r[6],
                    "faculty": r[7],
                    "room": r[8],
                    "virtual_room": r[9],
                    "mode": r[10],
                    "session_type": r[11],
                    "session_status": r[12],
                    "attendance_status": r[13],
                    "attendance_subtype": r[14],
                    "punch_in_time": r[15],
                    "reason_json": r[16],
                    "last_synced_at": r[17]
                }
                for r in cur.fetchall()
            ]
        finally:
            conn.close()

    def sync_all_active_users(self) -> Dict[str, Any]:
        """Synchronizes attendance for all active users having configured UPES sessions."""
        conn = self.conn_factory()
        user_ids = []
        try:
            cur = conn.cursor()
            cur.execute("SELECT DISTINCT user_id FROM upes_auth_sessions")
            user_ids = [r[0] for r in cur.fetchall()]
        finally:
            conn.close()

        results = {}
        for uid in user_ids:
            try:
                res = self.sync_user_attendance(uid)
                results[uid] = res
            except Exception as e:
                results[uid] = {"status": "ERROR", "error": str(e)}
        return results
