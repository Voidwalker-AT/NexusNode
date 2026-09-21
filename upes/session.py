"""
NexusNode — UPES Session State Tracker & Security Model
Maintains authoritative session state without exposing tokens or cookie secrets.
"""

import time
import sqlite3
from typing import Dict, Any, Optional
from enum import Enum
from .models import AutonomyLevel


class UpesSessionState(str, Enum):
    AUTHENTICATED = "AUTHENTICATED"
    EXPIRING = "EXPIRING"
    EXPIRED = "EXPIRED"
    REFRESHING = "REFRESHING"
    INTERACTION_REQUIRED = "INTERACTION_REQUIRED"
    AUTH_EXHAUSTED = "AUTH_EXHAUSTED"
    UNKNOWN = "UNKNOWN"


class UpesSessionTracker:
    """Tracks and evaluates live UPES session longevity and freshness."""

    def __init__(self, conn_factory, session_broker=None):
        self.conn_factory = conn_factory
        self.session_broker = session_broker

    def get_session_state(self, user_id: str = "admin") -> UpesSessionState:
        """Determines the current lifecycle state of the user's UPES session."""
        status = self.get_safe_status(user_id)
        if not status.get("configured"):
            return UpesSessionState.UNKNOWN

        now = time.time()
        token_exp = status.get("token_expiry")
        cookie_exp = status.get("cookie_expiry")
        has_refresh = status.get("has_refresh_token", False)

        if token_exp and token_exp > now + 1800:
            return UpesSessionState.AUTHENTICATED
        elif token_exp and token_exp > now:
            return UpesSessionState.EXPIRING
        elif has_refresh and cookie_exp and cookie_exp > now + 60:
            return UpesSessionState.REFRESHING
        else:
            return UpesSessionState.EXPIRED

    def get_safe_status(self, user_id: str = "admin") -> Dict[str, Any]:
        """
        Returns sanitized session metadata.
        Guarantees that plaintext tokens, cookies, and secret keys are NEVER returned.
        """
        now = time.time()
        conn = self.conn_factory()
        try:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("""
                SELECT user_id, student_code, api_url, expires_at, cookie_expires_at,
                       credential_generation, last_refresh_at, last_refresh_status,
                       (encrypted_refresh_token IS NOT NULL) AS has_refresh,
                       (encrypted_cookies IS NOT NULL) AS has_cookies,
                       updated_at
                FROM upes_auth_sessions
                WHERE user_id = ?
            """, (user_id,))
            row = cur.fetchone()
            if not row:
                return {
                    "user_id": user_id,
                    "configured": False,
                    "state": UpesSessionState.UNKNOWN.value,
                    "is_live_ready": False
                }

            token_exp = row["expires_at"]
            cookie_exp = row["cookie_expires_at"]
            has_refresh = bool(row["has_refresh"])
            
            # Determine state
            if token_exp and token_exp > now + 1800:
                state = UpesSessionState.AUTHENTICATED
            elif token_exp and token_exp > now:
                state = UpesSessionState.EXPIRING
            elif has_refresh and cookie_exp and cookie_exp > now + 60:
                state = UpesSessionState.REFRESHING
            else:
                state = UpesSessionState.EXPIRED

            # Mask student code (UUID)
            sc = row["student_code"] or ""
            masked_code = sc[:4] + "***" + sc[-4:] if len(sc) > 8 else "***"

            # Compute autonomy level
            if not (token_exp and token_exp > now) and not has_refresh and not bool(row["has_cookies"]):
                autonomy_level = AutonomyLevel.LEVEL_0_INTERACTION_REQUIRED.value
            elif token_exp and token_exp > now and not has_refresh and not bool(row["has_cookies"]):
                autonomy_level = AutonomyLevel.LEVEL_1_ACCESS_TOKEN_ONLY.value
            elif has_refresh and not bool(row["has_cookies"]):
                autonomy_level = AutonomyLevel.LEVEL_2_OAUTH_REFRESHABLE.value
            elif bool(row["has_cookies"]):
                autonomy_level = AutonomyLevel.LEVEL_3_IDP_RENEWABLE.value
            else:
                autonomy_level = AutonomyLevel.LEVEL_1_ACCESS_TOKEN_ONLY.value

            return {
                "user_id": user_id,
                "configured": True,
                "state": state.value,
                "autonomy_level": autonomy_level,
                "student_code_masked": masked_code,
                "token_expiry": token_exp,
                "token_ttl_seconds": max(0, int(token_exp - now)) if token_exp else 0,
                "cookie_expiry": cookie_exp,
                "cookie_ttl_seconds": max(0, int(cookie_exp - now)) if cookie_exp else 0,
                "has_refresh_token": has_refresh,
                "has_sso_cookies": bool(row["has_cookies"]),
                "credential_generation": row["credential_generation"],
                "last_refresh_status": row["last_refresh_status"],
                "last_refresh_at": row["last_refresh_at"],
                "updated_at": row["updated_at"],
                "is_live_ready": state in (UpesSessionState.AUTHENTICATED, UpesSessionState.EXPIRING, UpesSessionState.REFRESHING)
            }
        finally:
            conn.close()
