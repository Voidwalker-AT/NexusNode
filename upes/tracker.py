"""
NexusNode — UPES Zero-Touch Endurance Tracker
Maintains non-sensitive telemetry on OAuth token longevity, generation progression,
recovery events, and empirical autonomy level calculation.
NEVER stores access tokens, refresh tokens, cookies, passwords, or codes.
"""

import time
import sqlite3
import logging
from typing import Dict, Any, Optional
from .models import AutonomyLevel

logger = logging.getLogger("NEXUS_UPES_ENDURANCE_TRACKER")


def init_tracker_tables(conn: sqlite3.Connection):
    """Initializes the endurance tracking table."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS upes_endurance_metrics (
            user_id TEXT PRIMARY KEY,
            test_started_at REAL NOT NULL,
            initial_generation INTEGER NOT NULL DEFAULT 1,
            current_generation INTEGER NOT NULL DEFAULT 1,
            generation_count INTEGER NOT NULL DEFAULT 1,
            access_expires_at REAL,
            refresh_count INTEGER NOT NULL DEFAULT 0,
            last_refresh_at REAL,
            last_live_api_success REAL,
            consecutive_refresh_failures INTEGER NOT NULL DEFAULT 0,
            idp_cookie_expires_at REAL,
            refresh_after_idp_expiry INTEGER NOT NULL DEFAULT 0,
            service_restart_recovery INTEGER NOT NULL DEFAULT 0,
            device_restart_recovery INTEGER NOT NULL DEFAULT 0,
            autonomy_level TEXT NOT NULL DEFAULT 'LEVEL_0_NONE',
            final_status TEXT NOT NULL DEFAULT 'INITIALIZED',
            updated_at REAL NOT NULL
        );
    """)


class UpesEnduranceTracker:
    """Safe telemetry engine for evaluating long-duration zero-touch authentication."""

    def __init__(self, conn_factory):
        self.conn_factory = conn_factory
        conn = self.conn_factory()
        try:
            init_tracker_tables(conn)
            conn.commit()
        finally:
            conn.close()

    def record_import(
        self,
        user_id: str,
        generation: int = 1,
        access_expires_at: Optional[float] = None,
        idp_cookie_expires_at: Optional[float] = None
    ):
        """Records an initial or newly imported OAuth context."""
        now = time.time()
        conn = self.conn_factory()
        try:
            conn.execute("""
                INSERT INTO upes_endurance_metrics (
                    user_id, test_started_at, initial_generation, current_generation,
                    generation_count, access_expires_at, refresh_count, last_refresh_at,
                    last_live_api_success, consecutive_refresh_failures, idp_cookie_expires_at,
                    refresh_after_idp_expiry, service_restart_recovery, device_restart_recovery,
                    autonomy_level, final_status, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 0, NULL, NULL, 0, ?, 0, 0, 0, 'LEVEL_1_TOKEN_ONLY', 'ACTIVE_SESSION_IMPORTED', ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    current_generation = excluded.current_generation,
                    generation_count = excluded.generation_count,
                    access_expires_at = excluded.access_expires_at,
                    idp_cookie_expires_at = excluded.idp_cookie_expires_at,
                    consecutive_refresh_failures = 0,
                    autonomy_level = CASE
                        WHEN excluded.current_generation > 1 THEN autonomy_level
                        ELSE 'LEVEL_1_TOKEN_ONLY'
                    END,
                    final_status = 'ACTIVE_SESSION_IMPORTED',
                    updated_at = excluded.updated_at
            """, (user_id, now, generation, generation, 1, access_expires_at, idp_cookie_expires_at, now))
            conn.commit()
        finally:
            conn.close()

    def record_live_api_success(self, user_id: str):
        """Records successful direct-HTTP live academic read."""
        now = time.time()
        conn = self.conn_factory()
        try:
            conn.execute("""
                UPDATE upes_endurance_metrics
                SET last_live_api_success = ?,
                    updated_at = ?
                WHERE user_id = ?
            """, (now, now, user_id))
            conn.commit()
        finally:
            conn.close()

    def record_refresh_success(
        self,
        user_id: str,
        new_generation: int,
        new_access_expires_at: Optional[float],
        idp_expired_at_refresh: bool = False
    ):
        """Records successful token generation progression."""
        now = time.time()
        conn = self.conn_factory()
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT refresh_count, generation_count, refresh_after_idp_expiry,
                       service_restart_recovery, device_restart_recovery, test_started_at
                FROM upes_endurance_metrics WHERE user_id = ?
            """, (user_id,))
            row = cur.fetchone()
            
            ref_count = (row[0] if row else 0) + 1
            gen_count = (row[1] if row else 0) + 1
            after_idp = 1 if (idp_expired_at_refresh or (row and row[2])) else 0
            srv_restart = row[3] if row else 0
            dev_reboot = row[4] if row else 0
            test_start = row[5] if row else now

            # Compute autonomy level
            level = self._compute_level(
                gen_count=gen_count,
                ref_count=ref_count,
                after_idp=bool(after_idp),
                srv_restart=bool(srv_restart),
                dev_reboot=bool(dev_reboot),
                test_start=test_start
            )

            conn.execute("""
                UPDATE upes_endurance_metrics
                SET current_generation = ?,
                    generation_count = ?,
                    access_expires_at = ?,
                    refresh_count = ?,
                    last_refresh_at = ?,
                    consecutive_refresh_failures = 0,
                    refresh_after_idp_expiry = ?,
                    autonomy_level = ?,
                    final_status = 'REFRESH_SUCCESS',
                    updated_at = ?
                WHERE user_id = ?
            """, (new_generation, gen_count, new_access_expires_at, ref_count, now, after_idp, level.value, now, user_id))
            conn.commit()
        finally:
            conn.close()

    def record_idp_renewal_success(
        self,
        user_id: str,
        new_generation: int,
        new_access_expires_at: Optional[float],
        new_idp_cookie_expires_at: Optional[float]
    ):
        """Records successful silent IdP session SSO renewal."""
        now = time.time()
        conn = self.conn_factory()
        try:
            conn.execute("""
                INSERT INTO upes_endurance_metrics (
                    user_id, test_started_at, initial_generation, current_generation,
                    generation_count, access_expires_at, refresh_count, last_refresh_at,
                    last_live_api_success, consecutive_refresh_failures, idp_cookie_expires_at,
                    refresh_after_idp_expiry, service_restart_recovery, device_restart_recovery,
                    autonomy_level, final_status, updated_at
                ) VALUES (?, ?, 1, ?, 2, ?, 1, ?, NULL, 0, ?, 0, 0, 0, 'LEVEL_3_IDP_RENEWABLE', 'IDP_RENEWAL_SUCCESS', ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    current_generation = excluded.current_generation,
                    generation_count = generation_count + 1,
                    access_expires_at = excluded.access_expires_at,
                    idp_cookie_expires_at = COALESCE(excluded.idp_cookie_expires_at, upes_endurance_metrics.idp_cookie_expires_at),
                    last_refresh_at = excluded.last_refresh_at,
                    consecutive_refresh_failures = 0,
                    autonomy_level = 'LEVEL_3_IDP_RENEWABLE',
                    final_status = 'IDP_RENEWAL_SUCCESS',
                    updated_at = excluded.updated_at
            """, (user_id, now, new_generation, new_access_expires_at, now, new_idp_cookie_expires_at, now))
            conn.commit()
        finally:
            conn.close()

    def record_refresh_failure(self, user_id: str, reason: str):
        """Records a refresh attempt failure."""
        now = time.time()
        conn = self.conn_factory()
        try:
            conn.execute("""
                UPDATE upes_endurance_metrics
                SET consecutive_refresh_failures = consecutive_refresh_failures + 1,
                    final_status = ?,
                    updated_at = ?
                WHERE user_id = ?
            """, (f"REFRESH_FAILED: {reason[:50]}", now, user_id))
            conn.commit()
        finally:
            conn.close()

    def record_service_restart(self, user_id: str):
        """Records successful recovery after NexusNode process restart."""
        now = time.time()
        conn = self.conn_factory()
        try:
            conn.execute("""
                UPDATE upes_endurance_metrics
                SET service_restart_recovery = 1,
                    updated_at = ?
                WHERE user_id = ?
            """, (now, user_id))
            conn.commit()
        finally:
            conn.close()

    def record_device_reboot(self, user_id: str):
        """Records successful recovery after host appliance reboot."""
        now = time.time()
        conn = self.conn_factory()
        try:
            conn.execute("""
                UPDATE upes_endurance_metrics
                SET device_restart_recovery = 1,
                    updated_at = ?
                WHERE user_id = ?
            """, (now, user_id))
            conn.commit()
        finally:
            conn.close()

    def _compute_level(
        self,
        gen_count: int,
        ref_count: int,
        after_idp: bool,
        srv_restart: bool,
        dev_reboot: bool,
        test_start: float
    ) -> AutonomyLevel:
        """Conservatively calculates autonomy level based on empirical criteria."""
        if gen_count <= 0:
            return AutonomyLevel.LEVEL_0_NONE
        if gen_count == 1 and ref_count == 0:
            return AutonomyLevel.LEVEL_1_TOKEN_ONLY
        if ref_count >= 1 and not after_idp:
            return AutonomyLevel.LEVEL_2_IDP_REFRESH
        if after_idp and (not srv_restart or not dev_reboot):
            return AutonomyLevel.LEVEL_3_INDEPENDENT_REFRESH
        if after_idp and srv_restart and dev_reboot and gen_count >= 3:
            # Long duration empirical threshold: > 14 days
            if time.time() - test_start > (14 * 86400):
                return AutonomyLevel.LEVEL_5_LONG_DURATION
            return AutonomyLevel.LEVEL_4_RESTART_SURVIVED
        return AutonomyLevel.LEVEL_2_IDP_REFRESH

    def get_safe_metrics(self, user_id: str = "admin") -> Dict[str, Any]:
        """Returns non-sensitive endurance telemetry."""
        now = time.time()
        conn = self.conn_factory()
        try:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("SELECT * FROM upes_endurance_metrics WHERE user_id = ?", (user_id,))
            row = cur.fetchone()
            if not row:
                return {
                    "user_id": user_id,
                    "tracking_active": False,
                    "autonomy_level": AutonomyLevel.LEVEL_0_NONE.value,
                    "final_status": "UNTRACKED"
                }

            acc_exp = row["access_expires_at"]
            idp_exp = row["idp_cookie_expires_at"]

            return {
                "user_id": user_id,
                "tracking_active": True,
                "test_started_at": row["test_started_at"],
                "test_duration_seconds": int(now - row["test_started_at"]),
                "initial_generation": row["initial_generation"],
                "current_generation": row["current_generation"],
                "generation_count": row["generation_count"],
                "access_expires_at": acc_exp,
                "access_ttl_seconds": max(0, int(acc_exp - now)) if acc_exp else 0,
                "refresh_count": row["refresh_count"],
                "last_refresh_at": row["last_refresh_at"],
                "last_live_api_success": row["last_live_api_success"],
                "consecutive_refresh_failures": row["consecutive_refresh_failures"],
                "idp_cookie_expires_at": idp_exp,
                "idp_cookie_ttl_seconds": max(0, int(idp_exp - now)) if idp_exp else 0,
                "refresh_after_idp_expiry": bool(row["refresh_after_idp_expiry"]),
                "service_restart_recovery": bool(row["service_restart_recovery"]),
                "device_restart_recovery": bool(row["device_restart_recovery"]),
                "autonomy_level": row["autonomy_level"],
                "final_status": row["final_status"],
                "updated_at": row["updated_at"]
            }
        finally:
            conn.close()
