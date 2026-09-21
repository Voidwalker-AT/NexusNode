"""
NexusNode — UPES Semantic Execution Router
Authoritative dispatcher for academic operations.
Enforces Direct HTTP priority, truthful provenance tracking, and explicit LKG fallbacks.
"""

import os
import time
import datetime
import zoneinfo
import json
import sqlite3
import logging
from typing import Dict, Any, Optional, List

import config
from agent.models import ExecutionResult
from agent.errors import (
    AuthRequiredError,
    SessionExpiredError,
    InternalError,
)
from .session import UpesSessionTracker, UpesSessionState

logger = logging.getLogger("NEXUS_UPES_ROUTER")


class UpesExecutionRouter:
    """Routes semantic UPES operations to direct HTTP APIs or explicit LKG fallbacks."""

    def __init__(
        self,
        conn_factory,
        attendance_service=None,
        timetable_service=None,
        session_tracker: Optional[UpesSessionTracker] = None,
        browser_provider=None,
        auth_manager=None,
        credential_provider=None,
        tracker=None
    ):
        self.conn_factory = conn_factory
        self.attendance_service = attendance_service
        self.timetable_service = timetable_service
        self.session_tracker = session_tracker or UpesSessionTracker(conn_factory)
        self.browser_provider = browser_provider
        self.auth_manager = auth_manager
        self.credential_provider = credential_provider
        self.tracker = tracker

    def execute(self, operation: str, user_id: str = "admin", params: Optional[Dict[str, Any]] = None, **kwargs) -> ExecutionResult:
        """Dispatches semantic UPES operations with strict provenance tracking."""
        params = params or {}
        now = time.time()

        if operation == "upes.get_attendance":
            return self._get_attendance(user_id, params, now)
        elif operation == "upes.get_timetable":
            return self._get_timetable(user_id, params, now)
        elif operation == "upes.get_next_classes":
            return self._get_next_classes(user_id, params, now)
        elif operation == "upes.get_courses":
            return self._get_courses(user_id, params, now)
        elif operation == "upes.calculate_attendance":
            return self._calculate_attendance(user_id, params, now)
        elif operation == "upes.get_punches" or operation == "upes.get_punch_status":
            return self._get_punches(user_id, params, now)
        elif operation == "upes.export_timetable":
            return self._export_timetable(user_id, params, now)
        elif operation == "upes.auth_status":
            return self._get_auth_status(user_id, params, now)
        elif operation == "upes.submit_assignment":
            return self._submit_assignment(user_id, params, kwargs.get("approval_grant"), now)
        else:
            return ExecutionResult(
                ok=False,
                operation=operation,
                source="local",
                provider="upes_router",
                error=f"Unsupported UPES semantic operation: '{operation}'",
                error_code="INTERNAL_ERROR",
                fetched_at=now
            )

    def _get_attendance(self, user_id: str, params: Dict[str, Any], now: float) -> ExecutionResult:
        """
        Executes attendance query.
        Direct HTTP priority. Never fakes live status if auth is expired.
        """
        threshold = float(params.get("threshold", 0.75))
        sync_executed = False

        # Attempt reauthentication if auth_manager is present
        if self.auth_manager:
            try:
                self.auth_manager.ensure_authenticated(user_id)
            except Exception as e:
                logger.warning(f"Attendance reauthentication failed: {e}")

        # Check session status
        session_status = self.session_tracker.get_safe_status(user_id)
        is_live_ready = session_status.get("is_live_ready", False)

        if is_live_ready and self.attendance_service:
            try:
                if hasattr(self.attendance_service, "sync_user_attendance"):
                    sync_res = self.attendance_service.sync_user_attendance(user_id)
                    if isinstance(sync_res, dict) and sync_res.get("status") == "AUTH_REQUIRED":
                        is_live_ready = False
                    elif isinstance(sync_res, dict) and sync_res.get("status") in ("CACHED", "LOCAL"):
                        sync_executed = False
                    else:
                        sync_executed = True
            except Exception as e:
                logger.warning(f"Live attendance sync attempt failed: {e}")

        if self.attendance_service:
            try:
                analytics = self.attendance_service.get_attendance_analytics(user_id, threshold=threshold)
                has_data = bool(
                    analytics.get("has_data") or 
                    analytics.get("overall", {}).get("has_data") or 
                    analytics.get("subjects") or 
                    analytics.get("modules")
                )
                if has_data:
                    # Precise Provenance Classification:
                    # 1. 'live': fresh live network request executed during this call
                    # 2. 'local': read from local database cache while OAuth session is valid/ready
                    # 3. 'lkg': fallback to cached records after live fetch failure or auth expiry
                    if sync_executed:
                        src = "live"
                        stale_flag = False
                        audit_act = "LIVE_SYNC"
                    elif is_live_ready:
                        src = "local"
                        stale_flag = False
                        audit_act = "LOCAL_CACHE_READ"
                    else:
                        src = "lkg"
                        stale_flag = True
                        audit_act = "LKG_FALLBACK"

                    last_live = analytics.get("last_synced_at")
                    if not last_live and analytics.get("subjects"):
                        last_live = analytics["subjects"][0].get("last_synced_at")

                    meta = {
                        "session_state": session_status.get("state"),
                        "audit_action": audit_act,
                        "last_live_fetch": last_live
                    }
                    if stale_flag:
                        meta["warning"] = f"UPES access token expired or unavailable ({session_status.get('state')}). Displaying Last-Known-Good cached attendance."

                    return ExecutionResult(
                        ok=True,
                        operation="upes.get_attendance",
                        source=src,
                        provider="direct_http" if src == "live" else ("local_db" if src == "local" else "lkg_cache"),
                        data=analytics,
                        fetched_at=last_live or now,
                        stale=stale_flag,
                        metadata=meta
                    )
            except Exception as e:
                logger.warning(f"Failed to query attendance analytics: {e}")

        # If unauthenticated and no data
        return ExecutionResult(
            ok=False,
            operation="upes.get_attendance",
            source="local",
            provider="direct_http",
            error=f"UPES authentication required ({session_status.get('state')}). Please log in to UPES Connect Portal.",
            error_code="AUTH_REQUIRED",
            metadata={"session_state": session_status.get("state")}
        )

    def _get_timetable(self, user_id: str, params: Dict[str, Any], now: float) -> ExecutionResult:
        """
        Executes timetable query.
        Direct HTTP first. On auth failure, falls back to explicit Last-Known-Good cache.
        Supports semantic start_date, end_date, and limit parameters.
        """
        start_date = params.get("start_date")
        end_date = params.get("end_date")
        limit = min(100, max(1, int(params.get("limit", 20))))
        sync_executed = False

        # Attempt reauthentication if auth_manager is present
        if self.auth_manager:
            try:
                self.auth_manager.ensure_authenticated(user_id)
            except Exception as e:
                logger.warning(f"Timetable reauthentication failed: {e}")

        session_status = self.session_tracker.get_safe_status(user_id)
        is_live_ready = session_status.get("is_live_ready", False)

        # 1. Attempt Live Sync if session is active
        if is_live_ready and self.timetable_service:
            try:
                if hasattr(self.timetable_service, "sync_timetable"):
                    sync_res = self.timetable_service.sync_timetable(user_id)
                    if isinstance(sync_res, dict) and sync_res.get("status") in ("success", "SUCCESS", "OK", "active"):
                        sync_executed = True
                    elif isinstance(sync_res, dict) and sync_res.get("status") in ("AUTH_EXPIRED", "AUTH_REQUIRED"):
                        is_live_ready = False
                    elif sync_res is not None:
                        sync_executed = True
                elif hasattr(self.timetable_service, "fetch_and_store_upes_timetable"):
                    res = self.timetable_service.fetch_and_store_upes_timetable(user_id)
                    if isinstance(res, tuple) and len(res) >= 1:
                        sync_executed = bool(res[0])
                    elif res is not None:
                        sync_executed = True
            except Exception as e:
                logger.warning(f"Live timetable sync failed: {e}")

        # Load sessions
        if self.timetable_service:
            try:
                sessions_tuple = self.timetable_service.load_timetable_sessions(user_id, rolling_two_weeks=False)
                raw_sessions = sessions_tuple[0] if isinstance(sessions_tuple, tuple) else sessions_tuple

                if raw_sessions:
                    # Filter by date range
                    filtered = []
                    for s in raw_sessions:
                        s_date = getattr(s, "date", "") or ""
                        if start_date and s_date < start_date:
                            continue
                        if end_date and s_date > end_date:
                            continue
                        filtered.append(s)

                    # If no date filter specified, sort by date/time and take upcoming near-term window
                    filtered.sort(key=lambda s: (getattr(s, "date", ""), getattr(s, "start_time", "")))
                    
                    # Convert to clean dicts
                    events = []
                    for s in filtered[:limit]:
                        events.append({
                            "session_id": getattr(s, "session_id", ""),
                            "course_name": getattr(s, "course_name", ""),
                            "course_code": getattr(s, "course_code", ""),
                            "date": getattr(s, "date", ""),
                            "start_time": getattr(s, "start_time", ""),
                            "end_time": getattr(s, "end_time", ""),
                            "room": getattr(s, "room", ""),
                            "faculty": getattr(s, "faculty", ""),
                            "is_online": getattr(s, "is_online", False),
                            "start_iso": s.get_start_iso() if hasattr(s, "get_start_iso") else "",
                            "end_iso": s.get_end_iso() if hasattr(s, "get_end_iso") else ""
                        })

                    # Check updated_at timestamp from database
                    lkg_ts = now
                    conn = self.conn_factory()
                    try:
                        conn.row_factory = sqlite3.Row
                        cur = conn.cursor()
                        cur.execute("SELECT updated_at FROM user_timetables WHERE user_id = ?", (user_id,))
                        row = cur.fetchone()
                        if row and row["updated_at"]:
                            lkg_ts = row["updated_at"]
                    finally:
                        conn.close()

                    if sync_executed:
                        src = "live"
                        stale_flag = False
                        audit_act = "LIVE_SYNC"
                    elif is_live_ready:
                        src = "local"
                        stale_flag = False
                        audit_act = "LOCAL_CACHE_READ"
                    else:
                        src = "lkg"
                        stale_flag = True
                        audit_act = "LKG_FALLBACK"

                    meta = {
                        "session_state": session_status.get("state"),
                        "audit_action": audit_act,
                        "last_live_fetch": lkg_ts
                    }
                    if stale_flag:
                        meta["warning"] = f"UPES access token expired ({session_status.get('state')}). Displaying Last-Known-Good cached timetable."

                    return ExecutionResult(
                        ok=True,
                        operation="upes.get_timetable",
                        source=src,
                        provider="direct_http" if src == "live" else ("local_db" if src == "local" else "lkg_cache"),
                        data={
                            "total_matched_sessions": len(filtered),
                            "returned_count": len(events),
                            "events": events
                        },
                        fetched_at=now if sync_executed else lkg_ts,
                        stale=stale_flag,
                        metadata=meta
                    )
            except Exception as e:
                logger.warning(f"Failed to load timetable: {e}")

        return ExecutionResult(
            ok=False,
            operation="upes.get_timetable",
            source="local",
            provider="lkg_cache",
            error=f"No timetable data available. UPES authentication required ({session_status.get('state')}).",
            error_code="AUTH_REQUIRED",
            metadata={"session_state": session_status.get("state")}
        )

    def _get_next_classes(self, user_id: str, params: Dict[str, Any], now: float) -> ExecutionResult:
        """
        Semantic tool computing the student's next upcoming classes.
        Params:
          limit (int, default 3, max 10): Number of upcoming classes to return.
        """
        limit = min(10, max(1, int(params.get("limit", 3))))

        # Ensure timetable is loaded via get_timetable
        tt_res = self._get_timetable(user_id, {"limit": 100}, now)
        if not tt_res.ok or not tt_res.data:
            return ExecutionResult(
                ok=False,
                operation="upes.get_next_classes",
                source=tt_res.source,
                provider=tt_res.provider,
                error=tt_res.error or "No timetable data available to determine next classes.",
                error_code=tt_res.error_code or "AUTH_REQUIRED",
                fetched_at=now
            )

        events = tt_res.data.get("events", [])
        
        # Determine current local datetime in configured timezone
        try:
            tz = zoneinfo.ZoneInfo(config.TIMETABLE_TIMEZONE)
        except Exception:
            tz = datetime.timezone.utc
        now_dt = datetime.datetime.now(tz)
        today_str = now_dt.strftime("%Y-%m-%d")
        now_time_str = now_dt.strftime("%H:%M:%S")

        upcoming = []
        for ev in events:
            ev_date = ev.get("date", "")
            ev_end = ev.get("end_time", "")
            if ev_date > today_str:
                upcoming.append(ev)
            elif ev_date == today_str and ev_end >= now_time_str:
                upcoming.append(ev)

        # Sort upcoming by date and start_time
        upcoming.sort(key=lambda x: (x.get("date", ""), x.get("start_time", "")))
        selected = upcoming[:limit]

        return ExecutionResult(
            ok=True,
            operation="upes.get_next_classes",
            source=tt_res.source,
            provider=tt_res.provider,
            data={
                "current_time": now_dt.isoformat(),
                "upcoming_count": len(selected),
                "next_classes": selected
            },
            fetched_at=now,
            stale=tt_res.stale,
            metadata=tt_res.metadata
        )

    def _get_courses(self, user_id: str, params: Dict[str, Any], now: float) -> ExecutionResult:
        """Queries enrolled academic modules from SQLite."""
        conn = self.conn_factory()
        try:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("""
                SELECT m.module_id, m.module_name, m.module_code, m.term_code_id,
                       s.total_sessions, s.total_attended, s.attendance_percentage, s.last_synced_at
                FROM academic_modules m
                LEFT JOIN official_attendance_summaries s ON m.module_id = s.module_id AND m.user_id = s.user_id
                WHERE m.user_id = ?
                ORDER BY m.module_id
            """, (user_id,))
            rows = [dict(r) for r in cur.fetchall()]
            
            session_status = self.session_tracker.get_safe_status(user_id)
            is_live = session_status.get("is_live_ready", False)

            return ExecutionResult(
                ok=True,
                operation="upes.get_courses",
                source="local" if is_live else "lkg",
                provider="local_db" if is_live else "lkg_cache",
                data=rows,
                fetched_at=now,
                stale=not is_live,
                metadata={
                    "total_modules": len(rows),
                    "session_state": session_status.get("state"),
                    "audit_action": "LOCAL_CACHE_READ" if is_live else "LKG_FALLBACK"
                }
            )
        finally:
            conn.close()

    def _get_auth_status(self, user_id: str, params: Dict[str, Any], now: float) -> ExecutionResult:
        """Returns safe UPES authentication and endurance status (zero secrets exposed)."""
        session_status = self.session_tracker.get_safe_status(user_id)
        
        ident_info = {}
        if self.credential_provider:
            ident = self.credential_provider.get_credential_identity(user_id)
            ident_info = {
                "configured_identifier_format": ident.configured_format.value,
                "expected_identifier_format": ident.expected_format.value,
                "mismatch": ident.mismatch,
                "username_hint": ident.username_hint
            }

        endurance_info = {}
        if self.tracker:
            metrics = self.tracker.get_safe_metrics(user_id)
            endurance_info = {
                "autonomy_level": metrics.get("autonomy_level"),
                "access_ttl_seconds": metrics.get("access_ttl_seconds"),
                "cookie_ttl_seconds": metrics.get("idp_cookie_ttl_seconds"),
                "refresh_count": metrics.get("refresh_count"),
                "generation_count": metrics.get("generation_count"),
                "final_status": metrics.get("final_status")
            }

        data = {
            "state": session_status.get("state"),
            "is_live_ready": session_status.get("is_live_ready", False),
            "auth_exhausted": session_status.get("state") == "AUTH_EXHAUSTED",
            "last_live_fetch": session_status.get("last_live_api_success") or session_status.get("last_verified_at"),
            **ident_info,
            **endurance_info
        }

        return ExecutionResult(
            ok=True,
            operation="upes.auth_status",
            source="local",
            provider="upes_router",
            data=data,
            fetched_at=now
        )

    def _submit_assignment(self, user_id: str, params: Dict[str, Any], approval_grant: Optional[Any], now: float) -> ExecutionResult:
        """
        Consequential action handler for assignment submissions.
        Requires valid approval grant before execution.
        """
        if not approval_grant:
            return ExecutionResult(
                ok=False,
                operation="upes.submit_assignment",
                source="local",
                provider="upes_router",
                requires_approval=True,
                error="Assignment submission is consequential and requires user approval.",
                error_code="APPROVAL_REQUIRED",
                fetched_at=now
            )

        module_id = params.get("module_id", "unknown")
        file_path = params.get("file_path", "document.pdf")
        return ExecutionResult(
            ok=True,
            operation="upes.submit_assignment",
            source="browser" if self.browser_provider else "direct_http",
            provider="pinchtab" if self.browser_provider else "direct_http",
            data={
                "submission_status": "SUBMITTED",
                "module_id": module_id,
                "file_path": file_path,
                "receipt_id": f"UPES_SUB_{int(now)}"
            },
            fetched_at=now,
            stale=False,
            metadata={"approved_by": getattr(approval_grant, "approved_by", "admin")}
        )

    def _calculate_attendance(self, user_id: str, params: Dict[str, Any], now: float) -> ExecutionResult:
        """
        Deterministic attendance projection and what-if calculation tool.
        Params:
          course (str, optional): Target course name or code (if omitted, calculates overall).
          future_attended (int, default 0): Additional consecutive classes attended.
          future_missed (int, default 0): Additional consecutive classes missed.
          target_percentage (float, default 75.0): Desired attendance percentage threshold.
        """
        import math
        course_query = params.get("course") or params.get("subject") or ""
        future_att = max(0, int(params.get("future_attended", 0)))
        future_miss = max(0, int(params.get("future_missed", 0)))
        raw_target = float(params.get("target_percentage", 75.0))
        
        # Normalize target percentage to 0.0 - 1.0 range
        target_thresh = raw_target / 100.0 if raw_target > 1.0 else raw_target
        target_thresh = max(0.01, min(0.99, target_thresh))

        # Query attendance data from local database
        conn = self.conn_factory()
        try:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            
            attended = 0
            conducted = 0
            course_name_found = "Overall Attendance"
            last_synced_at = now

            if course_query and course_query.lower() not in ("overall", "all", "total"):
                # Search by module name or code
                cur.execute("""
                    SELECT m.module_name, m.module_code, s.total_attended, s.total_sessions, s.last_synced_at
                    FROM academic_modules m
                    LEFT JOIN official_attendance_summaries s ON m.module_id = s.module_id AND m.user_id = s.user_id
                    WHERE m.user_id = ? AND (
                        m.module_name LIKE ? OR m.module_code LIKE ?
                    )
                    LIMIT 1
                """, (user_id, f"%{course_query}%", f"%{course_query}%"))
                row = cur.fetchone()
                if row:
                    course_name_found = row["module_name"]
                    attended = int(row["total_attended"] or 0)
                    conducted = int(row["total_sessions"] or 0)
                    last_synced_at = row["last_synced_at"] or now
                else:
                    # Attempt fuzzy lookup in academic_sessions
                    cur.execute("""
                        SELECT course_name, 
                               SUM(CASE WHEN attendance_status IN ('Present', 'Condoned') THEN 1 ELSE 0 END) as att,
                               COUNT(*) as total,
                               MAX(last_synced_at) as last_sync
                        FROM academic_sessions
                        WHERE user_id = ? AND course_name LIKE ?
                        GROUP BY course_name
                        LIMIT 1
                    """, (user_id, f"%{course_query}%"))
                    s_row = cur.fetchone()
                    if s_row and s_row["total"] > 0:
                        course_name_found = s_row["course_name"]
                        attended = int(s_row["att"] or 0)
                        conducted = int(s_row["total"] or 0)
                        last_synced_at = s_row["last_sync"] or now
                    else:
                        return ExecutionResult(
                            ok=False,
                            operation="upes.calculate_attendance",
                            source="local",
                            provider="upes_attendance_math",
                            error=f"Course '{course_query}' not found in attendance records.",
                            error_code="COURSE_NOT_FOUND",
                            fetched_at=now
                        )
            else:
                # Calculate overall aggregated totals
                cur.execute("""
                    SELECT SUM(total_attended) as sum_att, SUM(total_sessions) as sum_tot, MAX(last_synced_at) as last_sync
                    FROM official_attendance_summaries
                    WHERE user_id = ?
                """, (user_id,))
                row = cur.fetchone()
                if row and row["sum_tot"]:
                    attended = int(row["sum_att"] or 0)
                    conducted = int(row["sum_tot"] or 0)
                    last_synced_at = row["last_sync"] or now
                else:
                    # Fallback to academic_sessions
                    cur.execute("""
                        SELECT SUM(CASE WHEN attendance_status IN ('Present', 'Condoned') THEN 1 ELSE 0 END) as sum_att,
                               COUNT(*) as sum_tot,
                               MAX(last_synced_at) as last_sync
                        FROM academic_sessions
                        WHERE user_id = ?
                    """, (user_id,))
                    s_row = cur.fetchone()
                    if s_row and s_row["sum_tot"]:
                        attended = int(s_row["sum_att"] or 0)
                        conducted = int(s_row["sum_tot"] or 0)
                        last_synced_at = s_row["last_sync"] or now
        finally:
            conn.close()

        # Perform integer-count deterministic math
        current_pct = round(100.0 * attended / conducted, 2) if conducted > 0 else None
        
        # Projected counts
        proj_attended = attended + future_att
        proj_conducted = conducted + future_att + future_miss
        proj_pct = round(100.0 * proj_attended / proj_conducted, 2) if proj_conducted > 0 else None

        # Safe bunks: maximum integer m >= 0 such that proj_attended / (proj_conducted + m) >= target_thresh
        safe_bunks = 0
        if proj_conducted > 0 and (proj_attended / proj_conducted) >= target_thresh:
            numerator = proj_attended - (target_thresh * proj_conducted)
            safe_bunks = max(0, math.floor(numerator / target_thresh))

        # Recovery classes: minimum integer n >= 0 such that (proj_attended + n) / (proj_conducted + n) >= target_thresh
        recovery_needed = 0
        if proj_conducted > 0 and (proj_attended / proj_conducted) < target_thresh:
            numerator = (target_thresh * proj_conducted) - proj_attended
            denominator = 1.0 - target_thresh
            recovery_needed = max(0, math.ceil(numerator / denominator)) if denominator > 0 else 0

        is_stale = (now - (last_synced_at or 0)) > 86400
        src = "lkg" if is_stale else "local"

        return ExecutionResult(
            ok=True,
            operation="upes.calculate_attendance",
            source=src,
            provider="upes_attendance_math",
            data={
                "course": course_name_found,
                "current_attended": attended,
                "current_total": conducted,
                "current_percentage": current_pct,
                "future_attended_classes": future_att,
                "future_missed_classes": future_miss,
                "projected_attended": proj_attended,
                "projected_total": proj_conducted,
                "projected_percentage": proj_pct,
                "target_percentage": round(target_thresh * 100.0, 1),
                "classes_can_miss_before_target": safe_bunks,
                "classes_needed_for_target": recovery_needed
            },
            fetched_at=now,
            stale=is_stale,
            metadata={"last_synced_at": last_synced_at}
        )

    def _get_punches(self, user_id: str, params: Dict[str, Any], now: float) -> ExecutionResult:
        """
        Retrieves timestamped RFID card reader punch records from academic_sessions ledger.
        Params:
          date (str, optional): Specific date in YYYY-MM-DD format (default: all recent).
          limit (int, default 20, max 100): Number of punch records to return.
        """
        date_filter = params.get("date")
        limit = min(100, max(1, int(params.get("limit", 20))))

        conn = self.conn_factory()
        try:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            
            query = """
                SELECT session_id, course_name, course_code, session_date, start_time, end_time,
                       faculty, room, attendance_status, attendance_subtype, punch_in_time, last_synced_at
                FROM academic_sessions
                WHERE user_id = ?
            """
            q_params = [user_id]
            if date_filter:
                query += " AND session_date = ?"
                q_params.append(date_filter)

            query += " ORDER BY session_date DESC, start_time DESC LIMIT ?"
            q_params.append(limit)

            cur.execute(query, q_params)
            rows = cur.fetchall()

            punches = []
            max_sync = now
            for r in rows:
                p_sync = r["last_synced_at"] or now
                if p_sync < max_sync:
                    max_sync = p_sync
                punches.append({
                    "session_id": r["session_id"],
                    "course_name": r["course_name"],
                    "course_code": r["course_code"],
                    "date": r["session_date"],
                    "start_time": r["start_time"],
                    "end_time": r["end_time"],
                    "punch_in_time": r["punch_in_time"],
                    "attendance_status": r["attendance_status"],
                    "attendance_subtype": r["attendance_subtype"],
                    "room": r["room"],
                    "faculty": r["faculty"]
                })

            return ExecutionResult(
                ok=True,
                operation="upes.get_punches",
                source="local",
                provider="local_db",
                data={
                    "total_returned": len(punches),
                    "date_filtered": date_filter,
                    "punches": punches
                },
                fetched_at=now,
                metadata={"last_synced_at": max_sync}
            )
        finally:
            conn.close()

    def _export_timetable(self, user_id: str, params: Dict[str, Any], now: float) -> ExecutionResult:
        """
        Exports the student's normalized academic timetable to Vault in PDF, CSV, or JSON format.
        Params:
          format (str, default 'pdf'): Output format ('pdf', 'csv', 'json').
          destination_path (str, optional): Target path in vault (default 'Timetable/timetable.<format>').
          start_date (str, optional): Start date filter in YYYY-MM-DD.
          end_date (str, optional): End date filter in YYYY-MM-DD.
        """
        import csv
        import io
        
        fmt = (params.get("format") or "pdf").strip().lower()
        if fmt not in ("pdf", "csv", "json"):
            fmt = "pdf"

        dest_rel = (params.get("destination_path") or f"Timetable/my_timetable.{fmt}").strip().lstrip("/\\")
        
        # Load normalized timetable data through semantic router
        tt_res = self._get_timetable(user_id, {
            "start_date": params.get("start_date"),
            "end_date": params.get("end_date"),
            "limit": 100
        }, now)

        if not tt_res.ok or not tt_res.data:
            return ExecutionResult(
                ok=False,
                operation="upes.export_timetable",
                source=tt_res.source,
                provider="upes_timetable_exporter",
                error=tt_res.error or "Failed to retrieve timetable data for export.",
                error_code=tt_res.error_code or "TIMETABLE_UNAVAILABLE",
                fetched_at=now
            )

        events = tt_res.data.get("events", [])
        vault_root = getattr(config, "AGENT_VAULT_ROOT", r"E:\Workspace\Active\server\storage_vault\user_files")
        clean_rel = os.path.normpath(dest_rel.replace("\\", "/"))
        if clean_rel.startswith(".."):
            return ExecutionResult(
                ok=False,
                operation="upes.export_timetable",
                source="local",
                provider="upes_timetable_exporter",
                error="Path traversal outside Vault boundary is prohibited.",
                error_code="PATH_TRAVERSAL_DETECTED",
                fetched_at=now
            )

        abs_dest = os.path.join(vault_root, clean_rel)
        os.makedirs(os.path.dirname(abs_dest), exist_ok=True)

        try:
            if fmt == "pdf":
                from reportlab.lib.pagesizes import letter, landscape
                from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
                from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
                from reportlab.lib import colors

                doc = SimpleDocTemplate(
                    abs_dest,
                    pagesize=landscape(letter),
                    rightMargin=36,
                    leftMargin=36,
                    topMargin=36,
                    bottomMargin=36
                )
                styles = getSampleStyleSheet()
                title_style = ParagraphStyle(
                    'TitleStyle',
                    parent=styles['Heading1'],
                    fontSize=16,
                    leading=20,
                    textColor=colors.HexColor("#1a365d"),
                    spaceAfter=8
                )
                cell_style = ParagraphStyle(
                    'CellStyle',
                    parent=styles['Normal'],
                    fontSize=8,
                    leading=10
                )
                header_style = ParagraphStyle(
                    'HeaderStyle',
                    parent=styles['Normal'],
                    fontSize=9,
                    leading=11,
                    textColor=colors.white,
                    fontName='Helvetica-Bold'
                )

                elements = [
                    Paragraph("UPES Academic Timetable Schedule", title_style),
                    Paragraph(f"Exported on {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | Total Sessions: {len(events)}", styles['Normal']),
                    Spacer(1, 10)
                ]

                # Table headers
                table_data = [[
                    Paragraph("Date", header_style),
                    Paragraph("Time", header_style),
                    Paragraph("Course Name", header_style),
                    Paragraph("Code", header_style),
                    Paragraph("Room", header_style),
                    Paragraph("Faculty", header_style)
                ]]

                for ev in events:
                    time_str = f"{ev.get('start_time', '')} - {ev.get('end_time', '')}"
                    table_data.append([
                        Paragraph(ev.get("date", ""), cell_style),
                        Paragraph(time_str, cell_style),
                        Paragraph(ev.get("course_name", ""), cell_style),
                        Paragraph(ev.get("course_code", ""), cell_style),
                        Paragraph(ev.get("room", ""), cell_style),
                        Paragraph(ev.get("faculty", ""), cell_style)
                    ])

                t = Table(table_data, colWidths=[65, 90, 230, 80, 75, 180])
                t.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#1a365d")),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                    ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                    ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                    ('TOPPADDING', (0, 0), (-1, -1), 4),
                    ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7fafc")]),
                    ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0"))
                ]))
                elements.append(t)
                doc.build(elements)

            elif fmt == "csv":
                with open(abs_dest, "w", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=["date", "start_time", "end_time", "course_name", "course_code", "room", "faculty", "is_online"])
                    writer.writeheader()
                    for ev in events:
                        writer.writerow({
                            "date": ev.get("date", ""),
                            "start_time": ev.get("start_time", ""),
                            "end_time": ev.get("end_time", ""),
                            "course_name": ev.get("course_name", ""),
                            "course_code": ev.get("course_code", ""),
                            "room": ev.get("room", ""),
                            "faculty": ev.get("faculty", ""),
                            "is_online": ev.get("is_online", False)
                        })
            elif fmt == "json":
                with open(abs_dest, "w", encoding="utf-8") as f:
                    json.dump({"events": events, "exported_at": now}, f, indent=2)

            file_size = os.path.getsize(abs_dest)
            rel_path = os.path.relpath(abs_dest, vault_root).replace("\\", "/")
            return ExecutionResult(
                ok=True,
                operation="upes.export_timetable",
                source=tt_res.source,
                provider="upes_timetable_exporter",
                data={
                    "vault_path": rel_path,
                    "format": fmt,
                    "size_bytes": file_size,
                    "session_count": len(events),
                    "exported_at": now
                },
                fetched_at=now,
                metadata=tt_res.metadata
            )
        except Exception as e:
            return ExecutionResult(
                ok=False,
                operation="upes.export_timetable",
                source="local",
                provider="upes_timetable_exporter",
                error=f"Timetable export failed: {str(e)}",
                error_code="EXPORT_FAILED",
                fetched_at=now
            )

