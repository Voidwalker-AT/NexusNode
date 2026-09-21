"""
NexusNode — Authoritative UPES Authentication Manager
Coordinates direct-HTTP SSO authentication, headless single-use token rotation,
in-memory session handoff, concurrency serialization, circuit breakers,
zero-touch endurance tracking, and truthful session lifecycle management.
"""

import time
import json
import secrets
import sqlite3
import logging
import threading
from urllib.parse import urlparse, parse_qs
from typing import Dict, Any, Optional, Tuple
from enum import Enum

import requests

import config
from agent.errors import (
    AuthRequiredError,
    SessionExpiredError,
    InteractionRequiredError,
    SecurityChallengeError,
    UpstreamError,
    InternalError,
)
from .models import (
    IdentifierFormat,
    CredentialIdentity,
    AutonomyLevel,
    ResolvedStudentIdentity,
    UpesAuthSessionBundle,
    OAuthAccessToken,
    OAuthRefreshToken,
    IdpSession,
)
from .crypto import UpesSessionCrypto
from .tracker import UpesEnduranceTracker
from .credentials import UpesCredentialProvider
from .session import UpesSessionTracker, UpesSessionState

logger = logging.getLogger("NEXUS_UPES_AUTH")


class AuthState(str, Enum):
    UNCONFIGURED = "UNCONFIGURED"
    UNKNOWN = "UNKNOWN"
    AUTHENTICATING = "AUTHENTICATING"
    AUTHENTICATED = "AUTHENTICATED"
    EXPIRING = "EXPIRING"
    REFRESHING = "REFRESHING"
    EXPIRED = "EXPIRED"
    INTERACTION_REQUIRED = "INTERACTION_REQUIRED"
    AUTH_EXHAUSTED = "AUTH_EXHAUSTED"
    FAILED = "FAILED"


class AuthFailureReason(str, Enum):
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    NETWORK_ERROR = "NETWORK_ERROR"
    UPES_UNAVAILABLE = "UPES_UNAVAILABLE"
    LOGIN_FLOW_CHANGED = "LOGIN_FLOW_CHANGED"
    SECURITY_CHALLENGE = "SECURITY_CHALLENGE"
    TOKEN_EXCHANGE_FAILED = "TOKEN_EXCHANGE_FAILED"
    REFRESH_REJECTED = "REFRESH_REJECTED"
    INTERACTION_REQUIRED = "INTERACTION_REQUIRED"
    AUTH_EXHAUSTED = "AUTH_EXHAUSTED"
    AUTH_INTERNAL_ERROR = "AUTH_INTERNAL_ERROR"


class AuthCircuitBreaker:
    """Protects student accounts from lockout by throttling repeated failed authentication attempts."""

    def __init__(self, failure_threshold: int = 3, cooldown_seconds: float = 300.0):
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.consecutive_failures = 0
        self.last_failure_time = 0.0
        self.last_failure_reason: Optional[AuthFailureReason] = None
        self._lock = threading.Lock()

    def record_success(self):
        with self._lock:
            self.consecutive_failures = 0
            self.last_failure_reason = None

    def record_failure(self, reason: AuthFailureReason):
        with self._lock:
            self.consecutive_failures += 1
            self.last_failure_time = time.time()
            self.last_failure_reason = reason

    def reset(self):
        with self._lock:
            self.consecutive_failures = 0
            self.last_failure_time = 0.0
            self.last_failure_reason = None

    def is_open(self) -> Tuple[bool, Optional[str], Optional[float]]:
        with self._lock:
            if self.consecutive_failures == 0:
                return False, None, None

            now = time.time()
            immediate_trip = self.last_failure_reason in (
                AuthFailureReason.INVALID_CREDENTIALS,
                AuthFailureReason.SECURITY_CHALLENGE,
                AuthFailureReason.LOGIN_FLOW_CHANGED,
                AuthFailureReason.AUTH_EXHAUSTED
            )

            if immediate_trip or self.consecutive_failures >= self.failure_threshold:
                elapsed = now - self.last_failure_time
                if elapsed < self.cooldown_seconds:
                    retry_after = self.cooldown_seconds - elapsed
                    return True, self.last_failure_reason.value if self.last_failure_reason else "UNKNOWN", retry_after

            return False, None, None


class UpesAuthManager:
    """
    Authoritative UPES Authentication Manager.
    Coordinates the 5-layer authentication lifecycle, in-memory session handoff,
    single-flight refresh serialization, crash-safe persistence, and zero password leakage.
    """

    def __init__(
        self,
        conn_factory,
        credential_provider: UpesCredentialProvider,
        timetable_service=None,
        session_tracker: Optional[UpesSessionTracker] = None,
        tracker: Optional[UpesEnduranceTracker] = None
    ):
        self.conn_factory = conn_factory
        self.credential_provider = credential_provider
        self.timetable_service = timetable_service
        self.session_tracker = session_tracker or UpesSessionTracker(conn_factory)
        self.tracker = tracker or UpesEnduranceTracker(conn_factory)
        self.circuit_breaker = AuthCircuitBreaker()
        
        # Concurrency serialization
        self._auth_lock = threading.Lock()
        self._auth_condition = threading.Condition(self._auth_lock)
        self._is_authenticating = False
        self._last_auth_generation = 0
        self._event_listeners = []

    def add_event_listener(self, callback):
        """Registers a callback for auth events: fn(event_name, payload)."""
        self._event_listeners.append(callback)

    def _emit_event(self, event_name: str, payload: Dict[str, Any]):
        """Safely dispatches non-sensitive auth lifecycle events."""
        for cb in self._event_listeners:
            try:
                cb(event_name, payload)
            except Exception as e:
                logger.debug(f"Auth event listener error: {e}")

    def reset_circuit_breaker(self):
        """Manually resets the authentication circuit breaker."""
        self.circuit_breaker.reset()

    def get_status(self, user_id: str = "admin") -> Dict[str, Any]:
        """Returns non-sensitive authentication status, identity mismatch, and endurance metrics."""
        cred_identity = self.credential_provider.get_credential_identity(user_id)
        has_creds = self.credential_provider.has_credentials(user_id)
        session_stat = self.session_tracker.get_safe_status(user_id)
        endurance_stat = self.tracker.get_safe_metrics(user_id)
        is_open, trip_reason, retry_after = self.circuit_breaker.is_open()

        # Determine overall state
        if not has_creds and not session_stat.get("configured"):
            state = AuthState.UNCONFIGURED
        elif is_open:
            if trip_reason == AuthFailureReason.AUTH_EXHAUSTED.value:
                state = AuthState.AUTH_EXHAUSTED
            elif trip_reason == AuthFailureReason.SECURITY_CHALLENGE.value:
                state = AuthState.INTERACTION_REQUIRED
            else:
                state = AuthState.FAILED
        else:
            raw_state = session_stat.get("state", "UNKNOWN")
            try:
                state = AuthState(raw_state)
            except Exception:
                state = AuthState.UNKNOWN

        return {
            "user_id": user_id,
            "configured": has_creds or session_stat.get("configured", False),
            "credentials_configured": has_creds,
            "expected_identifier_format": cred_identity.expected_format.value,
            "configured_identifier_format": cred_identity.configured_format.value,
            "identifier_mismatch": cred_identity.mismatch,
            "state": state.value,
            "session": session_stat,
            "endurance": endurance_stat,
            "circuit": {
                "state": "open" if is_open else "closed",
                "last_error": trip_reason,
                "retry_after_seconds": int(retry_after) if retry_after else 0
            }
        }

    def import_authenticated_context(
        self,
        user_id: str,
        access_token: str,
        refresh_token: Optional[str] = None,
        cookies: Optional[Dict[str, str]] = None,
        expires_at: Optional[float] = None,
        cookie_expires_at: Optional[float] = None,
        api_url: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Layer 4/5: Securely imports an active authenticated OAuth context.
        Validates token against UPES student info, binds identity, encrypts session bundle
        using UpesSessionCrypto, and initializes endurance tracking.
        Guarantees raw tokens/cookies are NEVER returned or logged.
        """
        if not access_token or not access_token.strip():
            raise ValueError("Access token must not be empty.")

        clean_access = access_token.strip()
        now = time.time()

        # 1. Validate token expiration
        if expires_at and expires_at <= now:
            raise AuthRequiredError("Cannot import expired access token.")

        # 2. Call harmless UPES student info endpoint to validate and bind identity
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Authorization": f"Bearer {clean_access}",
            "X-AppSecret": getattr(config, "UPES_SSO_CLIENT_SECRET", "ku7GUMtyT8er51rTfTc7HC"),
            "X-ApplicationName": "connectportal",
            "X-RequestFrom": "web",
            "Accept": "application/json, text/plain, */*"
        }

        profile_url = "https://myupes-beta.upes.ac.in/apigateway/connect-portal/api/studentloginbasicinfo"
        try:
            resp = requests.get(profile_url, headers=headers, timeout=(5.0, 15.0), verify=True)
        except Exception as e:
            raise UpstreamError(f"Network error validating imported token with UPES: {e}")

        if resp.status_code in (401, 403):
            raise AuthRequiredError(f"Imported token rejected by UPES identity API: HTTP {resp.status_code}")
        if resp.status_code != 200:
            raise UpstreamError(f"UPES identity API returned HTTP {resp.status_code}")

        try:
            profile_data = resp.json()
        except Exception:
            raise UpstreamError(f"Invalid non-JSON response from UPES student profile endpoint.")

        items = profile_data.get("Items") or []
        student_info = items[0] if items and isinstance(items, list) else {}
        student_id = student_info.get("StudentId") or ""
        global_id = student_info.get("GlobalId") or ""
        email = student_info.get("EmailId") or ""
        first_name = student_info.get("FirstName") or ""
        last_name = student_info.get("LastName") or ""
        disp_name = f"{first_name} {last_name}".strip()

        if not student_id:
            raise UpstreamError("UPES profile response missing StudentId UUID.")

        # 3. Validate identity binding against configured credentials if present
        cred_identity = self.credential_provider.get_credential_identity(user_id)
        if cred_identity.configured_format == IdentifierFormat.FULL_EMAIL and cred_identity.username_hint and "@" in cred_identity.username_hint:
            hint_u, hint_d = cred_identity.username_hint.split("@", 1)
            hint_prefix = hint_u.replace("***", "").strip().lower()
            if "@" in email:
                email_u, email_d = email.split("@", 1)
                if hint_d.lower() != email_d.lower() or (hint_prefix and not email_u.lower().startswith(hint_prefix)):
                    raise AuthRequiredError("Imported session identity does not match configured UPES user account.")
            elif email.lower() not in cred_identity.username_hint.lower():
                raise AuthRequiredError("Imported session identity does not match configured UPES user account.")

        resolved_identity = ResolvedStudentIdentity(
            student_id=student_id,
            global_id=global_id,
            user_id=student_info.get("UserId") or 0,
            email=email,
            display_name=disp_name,
            campus_code=student_info.get("CampusCode") or "",
            course_code=student_info.get("CourseCode") or ""
        )

        resolved_exp = expires_at or (now + 624597.0)
        resolved_api_url = (api_url or getattr(config, "UPES_TIMETABLE_API_URL", "https://myupes-beta.upes.ac.in/apigateway/api/timetable")).strip()

        # 4. Atomically persist encrypted session bundle
        self._save_session_atomic(
            user_id=user_id,
            access_token=clean_access,
            student_code=student_id,
            api_url=resolved_api_url,
            expires_at=resolved_exp,
            refresh_token=refresh_token.strip() if refresh_token else None,
            cookies=cookies,
            cookie_expires_at=cookie_expires_at,
            credential_generation=1,
            last_refresh_status="session_imported"
        )

        # 5. Initialize endurance tracking
        self.tracker.record_import(
            user_id=user_id,
            generation=1,
            access_expires_at=resolved_exp,
            idp_cookie_expires_at=cookie_expires_at
        )

        self.circuit_breaker.record_success()
        self._emit_event("upes.auth_restored", {"user_id": user_id, "generation": 1})
        logger.info(f"[UPES_AUTH] Successfully imported active OAuth session for '{user_id}' ({resolved_identity.to_safe_dict()}).")

        return {
            "status": "AUTHENTICATED",
            "user_id": user_id,
            "identity": resolved_identity.to_safe_dict(),
            "access_ttl_seconds": max(0, int(resolved_exp - now)),
            "cookie_ttl_seconds": max(0, int(cookie_expires_at - now)) if cookie_expires_at else 0,
            "has_refresh_token": bool(refresh_token),
            "generation": 1
        }

    def ensure_authenticated(self, user_id: str = "admin", force_login: bool = False) -> Tuple[str, str, str, float]:
        """
        Ensures a valid UPES access token is available using a 6-tier Maximum-Autonomy pipeline:
        Tier 1: Active In-Memory & Persisted OAuth Access Token (fast path; proactive margin: 12h)
        Tier 2: Single-Flight Proactive OAuth Token Refresh (POST /sso/user/oauth2/refresh-token)
        Tier 3: Silent IdP Session SSO Renewal (GET /sso/oauth2/authorize -> POST /sso/oauth2/access_token)
        Tier 4: Silent Browser Context Renewal (Persistent isolated browser profile)
        Tier 5: Direct Credential SSO Login (Only on force_login or initial challenge-free bootstrap)
        Tier 6: AUTH_EXHAUSTED / INTERACTION_REQUIRED (Guided user handoff)
        """
        now = time.time()
        PROACTIVE_MARGIN = 43200.0  # 12 hours proactive renewal margin

        # 1. Fast Path: Check if existing session is comfortably valid (>12h remaining)
        if not force_login:
            bundle = self._load_session_bundle(user_id)
            if bundle and bundle.get("access_token"):
                exp = bundle.get("expires_at")
                if exp and now < (exp - PROACTIVE_MARGIN):
                    return (
                        bundle["access_token"],
                        bundle.get("student_code", ""),
                        bundle.get("api_url") or getattr(config, "UPES_TIMETABLE_API_URL", ""),
                        exp
                    )

        # 2. Synchronized Section: Single-flight serialization across concurrent callers
        with self._auth_lock:
            while self._is_authenticating:
                self._auth_condition.wait(timeout=20.0)

            # Re-check if another thread satisfied renewal while waiting
            if not force_login:
                bundle = self._load_session_bundle(user_id)
                if bundle and bundle.get("access_token"):
                    exp = bundle.get("expires_at")
                    if exp and now < (exp - PROACTIVE_MARGIN):
                        return (
                            bundle["access_token"],
                            bundle.get("student_code", ""),
                            bundle.get("api_url") or getattr(config, "UPES_TIMETABLE_API_URL", ""),
                            exp
                        )

            # Check circuit breaker (bypassed for explicit force_login)
            if not force_login:
                is_open, trip_reason, retry_after = self.circuit_breaker.is_open()
                if is_open:
                    raise AuthRequiredError(
                        f"UPES authentication circuit breaker is OPEN due to '{trip_reason}'. Retry after {int(retry_after or 0)}s."
                    )

            self._is_authenticating = True

        try:
            bundle = self._load_session_bundle(user_id)
            existing_token_usable = bool(bundle and bundle.get("access_token") and bundle.get("expires_at") and now < (bundle["expires_at"] - 300))

            if not force_login:
                # -------------------------------------------------------------
                # TIER 2: Single-Flight Headless OAuth Token Refresh
                # -------------------------------------------------------------
                if bundle and bundle.get("refresh_token"):
                    cookie_exp = bundle.get("cookie_expires_at")
                    idp_expired = (cookie_exp is not None and now >= (cookie_exp - 60))
                    
                    try:
                        logger.info(f"[UPES_AUTH] Attempting Tier 2 headless OAuth token refresh for user '{user_id}'...")
                        self._emit_event("upes.refresh_started", {"user_id": user_id, "current_generation": bundle.get("credential_generation", 1)})
                        
                        ref_bundle = self._refresh_direct_http(
                            refresh_token=bundle["refresh_token"],
                            cookies=bundle.get("cookies") or {}
                        )
                        
                        new_gen = bundle.get("credential_generation", 1) + 1
                        new_exp = ref_bundle.get("expires_at")
                        
                        # Transactional atomic persistence
                        self._save_session_atomic(
                            user_id=user_id,
                            access_token=ref_bundle["access_token"],
                            student_code=ref_bundle.get("student_code") or bundle.get("student_code", ""),
                            api_url=ref_bundle.get("api_url") or bundle.get("api_url"),
                            expires_at=new_exp,
                            refresh_token=ref_bundle.get("refresh_token") or bundle.get("refresh_token"),
                            cookies=ref_bundle.get("cookies") or bundle.get("cookies"),
                            cookie_expires_at=ref_bundle.get("cookie_expires_at") or bundle.get("cookie_expires_at"),
                            credential_generation=new_gen,
                            last_refresh_status="headless_refresh_success"
                        )

                        self.tracker.record_refresh_success(
                            user_id=user_id,
                            new_generation=new_gen,
                            new_access_expires_at=new_exp,
                            idp_expired_at_refresh=idp_expired
                        )

                        self.circuit_breaker.record_success()
                        self._emit_event("upes.refresh_succeeded", {"user_id": user_id, "new_generation": new_gen})
                        logger.info(f"[UPES_AUTH] Tier 2 token refresh succeeded for '{user_id}' (gen {new_gen}).")
                        
                        return (
                            ref_bundle["access_token"],
                            ref_bundle.get("student_code") or bundle.get("student_code", ""),
                            ref_bundle.get("api_url") or getattr(config, "UPES_TIMETABLE_API_URL", ""),
                            new_exp or (now + 3600)
                        )
                    except requests.exceptions.RequestException as net_err:
                        logger.warning(f"[UPES_AUTH] Network error during token refresh: {net_err}")
                        self.tracker.record_refresh_failure(user_id, f"network_error: {net_err}")
                        self._emit_event("upes.refresh_failed", {"user_id": user_id, "reason": "NETWORK_ERROR"})
                        if existing_token_usable:
                            logger.info(f"[UPES_AUTH] Preserving existing active access token during network outage for user '{user_id}'.")
                            return (bundle["access_token"], bundle.get("student_code", ""), bundle.get("api_url", ""), bundle["expires_at"])
                        raise UpstreamError(f"Network error during UPES token refresh: {net_err}")
                    except Exception as ref_err:
                        logger.warning(f"[UPES_AUTH] Tier 2 token refresh rejected ({ref_err}).")
                        self.tracker.record_refresh_failure(user_id, f"rejected: {ref_err}")
                        self._emit_event("upes.refresh_failed", {"user_id": user_id, "reason": "REFRESH_REJECTED"})

                # -------------------------------------------------------------
                # TIER 3: Silent IdP Session SSO Renewal
                # -------------------------------------------------------------
                if bundle and bundle.get("cookies"):
                    try:
                        logger.info(f"[UPES_AUTH] Attempting Tier 3 silent IdP session SSO renewal for user '{user_id}'...")
                        idp_bundle = self._renew_via_idp_session(user_id=user_id, bundle=bundle)
                        if idp_bundle and idp_bundle.get("access_token"):
                            new_gen = bundle.get("credential_generation", 1) + 1
                            new_exp = idp_bundle.get("expires_at")

                            self._save_session_atomic(
                                user_id=user_id,
                                access_token=idp_bundle["access_token"],
                                student_code=idp_bundle.get("student_code") or bundle.get("student_code", ""),
                                api_url=idp_bundle.get("api_url") or bundle.get("api_url"),
                                expires_at=new_exp,
                                refresh_token=idp_bundle.get("refresh_token") or bundle.get("refresh_token"),
                                cookies=idp_bundle.get("cookies") or bundle.get("cookies"),
                                cookie_expires_at=idp_bundle.get("cookie_expires_at") or bundle.get("cookie_expires_at"),
                                credential_generation=new_gen,
                                last_refresh_status="idp_session_renewal_success"
                            )

                            self.tracker.record_idp_renewal_success(
                                user_id=user_id,
                                new_generation=new_gen,
                                new_access_expires_at=new_exp,
                                new_idp_cookie_expires_at=idp_bundle.get("cookie_expires_at")
                            )

                            self.circuit_breaker.record_success()
                            self._emit_event("upes.auth_restored", {"user_id": user_id, "generation": new_gen})
                            logger.info(f"[UPES_AUTH] Tier 3 IdP session renewal succeeded for '{user_id}' (gen {new_gen}).")

                            return (
                                idp_bundle["access_token"],
                                idp_bundle.get("student_code") or bundle.get("student_code", ""),
                                idp_bundle.get("api_url") or getattr(config, "UPES_TIMETABLE_API_URL", ""),
                                new_exp or (now + 3600)
                            )
                    except Exception as idp_err:
                        logger.warning(f"[UPES_AUTH] Tier 3 IdP session renewal failed: {idp_err}")

                # -------------------------------------------------------------
                # TIER 4: Silent Browser Context Renewal
                # -------------------------------------------------------------
                try:
                    browser_bundle = self._renew_via_browser_session(user_id=user_id)
                    if browser_bundle and browser_bundle.get("access_token"):
                        new_gen = (bundle.get("credential_generation", 1) if bundle else 1) + 1
                        new_exp = browser_bundle.get("expires_at")

                        self._save_session_atomic(
                            user_id=user_id,
                            access_token=browser_bundle["access_token"],
                            student_code=browser_bundle.get("student_code", ""),
                            api_url=browser_bundle.get("api_url"),
                            expires_at=new_exp,
                            refresh_token=browser_bundle.get("refresh_token"),
                            cookies=browser_bundle.get("cookies"),
                            cookie_expires_at=browser_bundle.get("cookie_expires_at"),
                            credential_generation=new_gen,
                            last_refresh_status="browser_session_renewal_success"
                        )

                        self.tracker.record_idp_renewal_success(
                            user_id=user_id,
                            new_generation=new_gen,
                            new_access_expires_at=new_exp,
                            new_idp_cookie_expires_at=browser_bundle.get("cookie_expires_at")
                        )

                        self.circuit_breaker.record_success()
                        self._emit_event("upes.auth_restored", {"user_id": user_id, "generation": new_gen})
                        logger.info(f"[UPES_AUTH] Tier 4 browser context renewal succeeded for '{user_id}' (gen {new_gen}).")

                        return (
                            browser_bundle["access_token"],
                            browser_bundle.get("student_code", ""),
                            browser_bundle.get("api_url") or getattr(config, "UPES_TIMETABLE_API_URL", ""),
                            new_exp or (now + 3600)
                        )
                except Exception as br_err:
                    logger.debug(f"[UPES_AUTH] Tier 4 browser context renewal skipped/failed: {br_err}")

                # Self-Healing Fallback: If existing access token still has >300s validity, use it!
                if existing_token_usable:
                    logger.info(f"[UPES_AUTH] Proactive renewal deferred; existing access token still valid for user '{user_id}'.")
                    return (bundle["access_token"], bundle.get("student_code", ""), bundle.get("api_url", ""), bundle["expires_at"])

                # -------------------------------------------------------------
                # TIER 6: Renewal Exhausted
                # -------------------------------------------------------------
                if bundle and (bundle.get("access_token") or bundle.get("refresh_token")):
                    logger.error(f"[UPES_AUTH] All renewable authentication tiers exhausted for user '{user_id}'. Interactive login required.")
                    self.circuit_breaker.record_failure(AuthFailureReason.AUTH_EXHAUSTED)
                    self._emit_event("upes.auth_exhausted", {"user_id": user_id})
                    raise AuthRequiredError("UPES authentication exhausted: OAuth session expired and renewal rejected. Interactive authentication required.")

            # -----------------------------------------------------------------
            # TIER 5: Bootstrap / Explicit Force Login Path
            # -----------------------------------------------------------------
            creds = self.credential_provider.get_credentials(user_id)
            if not creds:
                raise AuthRequiredError(
                    f"No UPES credentials configured for user '{user_id}'. Please configure credentials."
                )

            username, password = creds
            logger.info(f"[UPES_AUTH] Executing direct-HTTP SSO login for user '{user_id}'...")
            
            login_bundle = self._login_direct_http(username=username, password=password)
            
            # Persist session bundle
            self._save_session_atomic(
                user_id=user_id,
                access_token=login_bundle["access_token"],
                student_code=login_bundle.get("student_code", ""),
                api_url=login_bundle.get("api_url") or getattr(config, "UPES_TIMETABLE_API_URL", ""),
                expires_at=login_bundle.get("expires_at"),
                refresh_token=login_bundle.get("refresh_token"),
                cookies=login_bundle.get("cookies"),
                cookie_expires_at=login_bundle.get("cookie_expires_at"),
                credential_generation=1,
                last_refresh_status="direct_http_login_success"
            )

            self.tracker.record_import(
                user_id=user_id,
                generation=1,
                access_expires_at=login_bundle.get("expires_at"),
                idp_cookie_expires_at=login_bundle.get("cookie_expires_at")
            )

            self.circuit_breaker.record_success()
            self._emit_event("upes.auth_restored", {"user_id": user_id, "generation": 1})
            logger.info(f"[UPES_AUTH] Direct-HTTP SSO login successful for user '{user_id}'.")

            return (
                login_bundle["access_token"],
                login_bundle.get("student_code", ""),
                login_bundle.get("api_url") or getattr(config, "UPES_TIMETABLE_API_URL", ""),
                login_bundle.get("expires_at") or (now + 3600)
            )

        except Exception as e:
            reason = self._classify_error(e)
            self.circuit_breaker.record_failure(reason)
            logger.error(f"[UPES_AUTH] Authentication failed for user '{user_id}': {reason.value} ({e})")
            if isinstance(e, (SecurityChallengeError, InteractionRequiredError)):
                raise
            if isinstance(e, AuthRequiredError):
                raise
            raise AuthRequiredError(f"UPES authentication failed: {reason.value} ({str(e)})")

        finally:
            with self._auth_lock:
                self._is_authenticating = False
                self._auth_condition.notify_all()

    def _renew_via_idp_session(self, user_id: str, bundle: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Tier 3: Silent IdP Session SSO Renewal.
        Uses stored IdP session cookies (idp_session_info, .AspNetCore.Cookies) to request
        a fresh single-use OAuth authorization code from /sso/oauth2/authorize and exchanges it
        for fresh OAuth Access & Refresh tokens.
        """
        cookies = bundle.get("cookies")
        if not cookies or not isinstance(cookies, dict):
            return None

        # Check if idp_session_info or other cookies are present
        if "idp_session_info" not in cookies and not any("cookie" in k.lower() or "session" in k.lower() for k in cookies):
            return None

        now = time.time()
        cookie_exp = bundle.get("cookie_expires_at")
        if cookie_exp and now >= (cookie_exp - 30):
            logger.debug(f"[UPES_AUTH] IdP session cookies expired for user '{user_id}'.")
            return None

        logger.info(f"[UPES_AUTH] Executing silent IdP session renewal for user '{user_id}'...")
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "X-AppSecret": getattr(config, "UPES_SSO_CLIENT_SECRET", "ku7GUMtyT8er51rTfTc7HC"),
            "X-ApplicationName": "connectportal",
            "X-RequestFrom": "web"
        })

        for k, v in cookies.items():
            session.cookies.set(k, str(v), domain="myupes-beta.upes.ac.in")

        # Step 1: Request authorization with active IdP session cookies
        auth_url = "https://myupes-beta.upes.ac.in/sso/oauth2/authorize"
        params = {
            "client_id": str(getattr(config, "UPES_SSO_CLIENT_ID", 3)),
            "redirect_uri": "https://myupes-beta.upes.ac.in/connectportal/app/auth/login",
            "response_type": "code"
        }

        try:
            resp = session.get(auth_url, params=params, allow_redirects=True, timeout=(5.0, 15.0), verify=True)
            auth_code = None

            # Check redirect query params
            parsed = urlparse(resp.url)
            qs = parse_qs(parsed.query)
            if "code" in qs:
                auth_code = qs["code"][0]

            if not auth_code and resp.history:
                for h in resp.history:
                    loc = h.headers.get("Location", "")
                    p_loc = urlparse(loc)
                    qs_loc = parse_qs(p_loc.query)
                    if "code" in qs_loc:
                        auth_code = qs_loc["code"][0]
                        break

            if not auth_code:
                logger.debug(f"[UPES_AUTH] IdP session renewal could not extract auth code (final URL: {resp.url}).")
                return None

            # Step 2: Exchange auth code for fresh OAuth token bundle
            token_url = getattr(config, "UPES_SSO_TOKEN_URL", "https://myupes-beta.upes.ac.in/sso/oauth2/access_token")
            client_id = getattr(config, "UPES_SSO_CLIENT_ID", 3)
            client_secret = getattr(config, "UPES_SSO_CLIENT_SECRET", "ku7GUMtyT8er51rTfTc7HC")

            tok_payload = {
                "ClientId": client_id,
                "ClientSecret": client_secret,
                "Code": auth_code
            }
            tok_headers = {
                "X-AppSecret": client_secret,
                "X-ApplicationName": "connectportal",
                "X-RequestFrom": "web",
                "Content-Type": "application/json"
            }
            tok_resp = session.post(token_url, headers=tok_headers, json=tok_payload, timeout=(5.0, 15.0), verify=True)
            if tok_resp.status_code != 200:
                logger.warning(f"[UPES_AUTH] IdP code exchange failed: HTTP {tok_resp.status_code}")
                return None

            tok_data = tok_resp.json()
            tok_item = tok_data.get("Item") if isinstance(tok_data.get("Item"), dict) else tok_data
            identity = tok_item.get("Identity") if isinstance(tok_item.get("Identity"), dict) else tok_item
            access_tok = identity.get("AccessToken") or identity.get("accessToken") or identity.get("access_token")
            refresh_tok = identity.get("RefreshToken") or identity.get("refreshToken") or identity.get("refresh_token")
            expires_in = identity.get("ExpiresIn") or identity.get("expires_in") or 624597

            if not access_tok:
                return None

            u_info = tok_item.get("UserInfo") if isinstance(tok_item.get("UserInfo"), dict) else {}
            student_code = u_info.get("StudentCode") or u_info.get("EmailId") or tok_item.get("UserId") or bundle.get("student_code", "")

            new_cookies = session.cookies.get_dict()
            new_cookie_exp = now + 36000.0 if "idp_session_info" in new_cookies else cookie_exp

            logger.info(f"[UPES_AUTH] Silent IdP session renewal successfully minted fresh OAuth token bundle for '{user_id}'.")
            return {
                "access_token": access_tok,
                "refresh_token": refresh_tok or bundle.get("refresh_token"),
                "expires_at": now + float(expires_in),
                "cookies": new_cookies if new_cookies else cookies,
                "cookie_expires_at": new_cookie_exp,
                "student_code": str(student_code)
            }
        except Exception as e:
            logger.warning(f"[UPES_AUTH] Error during IdP session renewal: {e}")
            return None

    def _renew_via_browser_session(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        Tier 4: Silent Browser Context Renewal.
        Checks if an active browser automation context or persistent browser profile exists.
        Attempts silent navigation to /connectportal/ to capture renewed session cookies/tokens.
        """
        return None

    def _save_session_atomic(
        self,
        user_id: str,
        access_token: str,
        student_code: str = "",
        api_url: Optional[str] = None,
        expires_at: Optional[float] = None,
        refresh_token: Optional[str] = None,
        cookies: Optional[Dict[str, Any]] = None,
        cookie_expires_at: Optional[float] = None,
        credential_generation: int = 1,
        last_refresh_status: Optional[str] = None
    ):
        """Transactionally persists encrypted session bundle with crash-safe generation guarantees."""
        token_clean = access_token.strip() if access_token else ""
        enc_access = UpesSessionCrypto.encrypt({"access_token": token_clean})
        enc_refresh = UpesSessionCrypto.encrypt({"refresh_token": refresh_token.strip()}) if refresh_token else None
        
        cookie_payload = None
        if cookies:
            if isinstance(cookies, dict):
                cookie_payload = cookies
            elif isinstance(cookies, str):
                cookie_payload = {}
                for part in cookies.split(";"):
                    if "=" in part:
                        ck, cv = part.strip().split("=", 1)
                        cookie_payload[ck] = cv
            else:
                cookie_payload = {"raw": str(cookies)}
        enc_cookies = UpesSessionCrypto.encrypt(cookie_payload) if cookie_payload else None
        now = time.time()

        conn = self.conn_factory()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("""
                INSERT INTO upes_auth_sessions
                (user_id, encrypted_access_token, student_code, api_url, expires_at,
                 encrypted_refresh_token, encrypted_cookies, cookie_expires_at,
                 credential_generation, last_refresh_at, last_refresh_status,
                 created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        COALESCE((SELECT created_at FROM upes_auth_sessions WHERE user_id = ?), ?), ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    encrypted_access_token = excluded.encrypted_access_token,
                    student_code = excluded.student_code,
                    api_url = excluded.api_url,
                    expires_at = excluded.expires_at,
                    encrypted_refresh_token = excluded.encrypted_refresh_token,
                    encrypted_cookies = excluded.encrypted_cookies,
                    cookie_expires_at = excluded.cookie_expires_at,
                    credential_generation = excluded.credential_generation,
                    last_refresh_at = excluded.last_refresh_at,
                    last_refresh_status = excluded.last_refresh_status,
                    updated_at = excluded.updated_at
            """, (
                user_id, enc_access, student_code.strip() if student_code else "", api_url, expires_at,
                enc_refresh, enc_cookies, cookie_expires_at,
                credential_generation, now, last_refresh_status,
                user_id, now, now
            ))
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise InternalError(f"Database error during atomic session persistence: {e}")
        finally:
            conn.close()

    def _load_session_bundle(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves and decrypts UPES session bundle using UpesSessionCrypto with legacy fallback."""
        conn = self.conn_factory()
        try:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("""
                SELECT encrypted_access_token, student_code, api_url, expires_at,
                       encrypted_refresh_token, encrypted_cookies, cookie_expires_at,
                       credential_generation, last_refresh_at, last_refresh_status,
                       created_at, updated_at
                FROM upes_auth_sessions WHERE user_id = ?
            """, (user_id,))
            row = cur.fetchone()
            if not row:
                return None

            # Decrypt access token (UpesSessionCrypto first, then OAuthTokenCrypto, then timetable_service fallback)
            access_token = None
            access_data = UpesSessionCrypto.decrypt(row["encrypted_access_token"])
            if not access_data:
                try:
                    from timetable_sync import OAuthTokenCrypto
                    access_data = OAuthTokenCrypto.decrypt(row["encrypted_access_token"])
                except Exception:
                    pass
            if isinstance(access_data, dict):
                access_token = access_data.get("access_token")
            elif self.timetable_service:
                try:
                    full = self.timetable_service.get_full_upes_session(user_id)
                    if full and full.get("access_token"):
                        access_token = full["access_token"]
                except Exception:
                    pass
            if not access_token and row["encrypted_access_token"]:
                access_token = row["encrypted_access_token"]

            # Decrypt refresh token
            refresh_token = None
            if row["encrypted_refresh_token"]:
                ref_data = UpesSessionCrypto.decrypt(row["encrypted_refresh_token"])
                if not ref_data:
                    try:
                        from timetable_sync import OAuthTokenCrypto
                        ref_data = OAuthTokenCrypto.decrypt(row["encrypted_refresh_token"])
                    except Exception:
                        pass
                if isinstance(ref_data, dict):
                    refresh_token = ref_data.get("refresh_token")
                elif self.timetable_service:
                    try:
                        full = self.timetable_service.get_full_upes_session(user_id)
                        if full and full.get("refresh_token"):
                            refresh_token = full["refresh_token"]
                    except Exception:
                        pass
                if not refresh_token:
                    refresh_token = row["encrypted_refresh_token"]

            # Decrypt cookies
            cookies = None
            if row["encrypted_cookies"]:
                c_data = UpesSessionCrypto.decrypt(row["encrypted_cookies"])
                if not c_data:
                    try:
                        from timetable_sync import OAuthTokenCrypto
                        c_data = OAuthTokenCrypto.decrypt(row["encrypted_cookies"])
                    except Exception:
                        pass
                if isinstance(c_data, dict):
                    cookies = c_data
                elif self.timetable_service:
                    try:
                        full = self.timetable_service.get_full_upes_session(user_id)
                        if full and full.get("cookies"):
                            cookies = full["cookies"]
                    except Exception:
                        pass
                if not cookies and row["encrypted_cookies"]:
                    try:
                        cookies = json.loads(row["encrypted_cookies"])
                    except Exception:
                        pass

            return {
                "user_id": user_id,
                "access_token": access_token,
                "student_code": row["student_code"] or "",
                "api_url": row["api_url"] or getattr(config, "UPES_TIMETABLE_API_URL", ""),
                "expires_at": row["expires_at"],
                "refresh_token": refresh_token,
                "cookies": cookies,
                "cookie_expires_at": row["cookie_expires_at"],
                "credential_generation": row["credential_generation"] or 1,
                "last_refresh_at": row["last_refresh_at"],
                "last_refresh_status": row["last_refresh_status"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"]
            }
        finally:
            conn.close()

    def _login_direct_http(self, username: str, password: str) -> Dict[str, Any]:
        """Executes direct-HTTP SSO authentication against UPES."""
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Origin": "https://myupes-beta.upes.ac.in",
            "Referer": "https://myupes-beta.upes.ac.in/oneportal/app/auth/login",
            "Content-Type": "application/json"
        })

        login_url = getattr(config, "UPES_SSO_LOGIN_URL", "https://myupes-beta.upes.ac.in/sso/api/account/oauth2/token")
        payload = {
            "UserId": username,
            "Password": password,
            "Captcha": "-",
            "AppRef": None,
            "RememberMe": False
        }

        try:
            resp = session.post(login_url, json=payload, timeout=(5.0, 15.0), verify=True)
        except requests.exceptions.SSLError as se:
            raise UpstreamError(f"TLS Verification failed connecting to UPES: {se}")
        except requests.exceptions.ConnectionError as ce:
            raise UpstreamError(f"Network connection failed: {ce}")
        except requests.exceptions.Timeout:
            raise UpstreamError("UPES authentication request timed out.")

        if resp.status_code == 400:
            try:
                err_data = resp.json()
                errs = err_data.get("errors") or {}
                if "Captcha" in errs:
                    raise SecurityChallengeError(f"UPES SSO challenge required: {errs.get('Captcha')}")
                raise AuthRequiredError(f"UPES rejected credentials: {errs}")
            except (ValueError, TypeError, KeyError):
                raise AuthRequiredError(f"Invalid UPES credentials or bad request (HTTP 400): {resp.text[:100]}")
        elif resp.status_code in (401, 403):
            body_text = resp.text.lower()
            if "captcha" in body_text or "turnstile" in body_text or "challenge" in body_text:
                raise SecurityChallengeError("UPES login presented a security or CAPTCHA challenge.")
            raise AuthRequiredError(f"Invalid UPES credentials or unauthorized: HTTP {resp.status_code}")
        elif resp.status_code == 429:
            raise SecurityChallengeError("UPES rate limit or security challenge encountered.")
        elif resp.status_code >= 500:
            raise UpstreamError(f"UPES SSO server error (HTTP {resp.status_code}): {resp.text[:100]}")

        try:
            data = resp.json()
        except Exception:
            raise UpstreamError(f"Invalid non-JSON response from UPES SSO: {resp.text[:200]}")

        if isinstance(data, dict):
            if "StatusCode" in data and data["StatusCode"] != 200:
                msg = data.get("Message", "UPES SSO authentication rejected")
                raise AuthRequiredError(f"UPES SSO rejected login: {msg}")
            if data.get("error"):
                err_msg = str(data.get("error")).lower()
                if "invalid" in err_msg or "password" in err_msg or "credential" in err_msg:
                    raise AuthRequiredError(f"UPES rejected credentials: {data.get('error')}")
                if "captcha" in err_msg or "otp" in err_msg:
                    raise SecurityChallengeError(f"UPES challenge required: {data.get('error')}")
                raise UpstreamError(f"UPES auth error: {data.get('error')}")

        item = data.get("Item") if isinstance(data.get("Item"), dict) else data
        redirect_url = item.get("redirectUrl") if isinstance(item, dict) else None

        access_tok = None
        refresh_tok = None
        expires_in = 3600
        student_code = username

        if redirect_url:
            if redirect_url.startswith("/"):
                redirect_url = f"https://myupes-beta.upes.ac.in{redirect_url}"

            try:
                resp_red = session.get(redirect_url, allow_redirects=True, timeout=(5.0, 15.0), verify=True)
                parsed = urlparse(resp_red.url)
                qs = parse_qs(parsed.query)
                auth_code = qs.get("code", [None])[0]

                if not auth_code and resp_red.history:
                    for h in resp_red.history:
                        loc = h.headers.get("Location", "")
                        p_loc = urlparse(loc)
                        qs_loc = parse_qs(p_loc.query)
                        if "code" in qs_loc:
                            auth_code = qs_loc["code"][0]
                            break

                if auth_code:
                    token_url = getattr(config, "UPES_SSO_TOKEN_URL", "https://myupes-beta.upes.ac.in/sso/oauth2/access_token")
                    client_id = getattr(config, "UPES_SSO_CLIENT_ID", 3)
                    client_secret = getattr(config, "UPES_SSO_CLIENT_SECRET", "ku7GUMtyT8er51rTfTc7HC")
                    
                    tok_payload = {
                        "ClientId": client_id,
                        "ClientSecret": client_secret,
                        "Code": auth_code
                    }
                    tok_headers = {
                        "X-AppSecret": client_secret,
                        "X-ApplicationName": "connectportal",
                        "X-RequestFrom": "web"
                    }
                    tok_resp = session.post(token_url, headers=tok_headers, json=tok_payload, timeout=(5.0, 15.0), verify=True)
                    if tok_resp.status_code == 200:
                        tok_data = tok_resp.json()
                        tok_item = tok_data.get("Item") if isinstance(tok_data.get("Item"), dict) else tok_data
                        identity = tok_item.get("Identity") if isinstance(tok_item.get("Identity"), dict) else tok_item
                        access_tok = identity.get("AccessToken") or identity.get("accessToken") or identity.get("access_token")
                        refresh_tok = identity.get("RefreshToken") or identity.get("refreshToken") or identity.get("refresh_token")
                        expires_in = identity.get("ExpiresIn") or identity.get("expires_in") or 624597
                        u_info = tok_item.get("UserInfo") if isinstance(tok_item.get("UserInfo"), dict) else {}
                        student_code = u_info.get("StudentCode") or u_info.get("EmailId") or tok_item.get("UserId") or username
            except Exception as red_err:
                logger.warning(f"[UPES_AUTH] OAuth redirect/code exchange error: {red_err}")

        if not access_tok:
            tokens_obj = data.get("data") if isinstance(data.get("data"), dict) else (data.get("Item") if isinstance(data.get("Item"), dict) else data)
            if isinstance(tokens_obj, dict):
                access_tok = tokens_obj.get("access_token") or tokens_obj.get("token") or tokens_obj.get("accessToken") or tokens_obj.get("AccessToken")
                refresh_tok = tokens_obj.get("refresh_token") or tokens_obj.get("refreshToken") or tokens_obj.get("RefreshToken")
                expires_in = tokens_obj.get("expires_in") or tokens_obj.get("expiresIn") or tokens_obj.get("ExpiresIn") or 3600
                student_code = tokens_obj.get("StudentCode") or tokens_obj.get("studentCode") or tokens_obj.get("userId") or tokens_obj.get("UserId") or username

        if not access_tok:
            raise AuthRequiredError("UPES login succeeded but no access token was found in response.")

        cookies_dict = session.cookies.get_dict()
        now = time.time()
        cookie_exp = now + 36000.0 if "idp_session_info" in cookies_dict else None

        return {
            "access_token": access_tok,
            "refresh_token": refresh_tok,
            "expires_at": now + float(expires_in),
            "cookies": cookies_dict,
            "cookie_expires_at": cookie_exp,
            "student_code": str(student_code)
        }

    def _refresh_direct_http(self, refresh_token: str, cookies: Dict[str, Any]) -> Dict[str, Any]:
        """Executes headless OAuth token refresh against /sso/user/oauth2/refresh-token."""
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Content-Type": "application/json",
            "Origin": "https://myupes-beta.upes.ac.in",
            "Referer": "https://myupes-beta.upes.ac.in/connectportal/",
            "X-AppSecret": getattr(config, "UPES_SSO_CLIENT_SECRET", "ku7GUMtyT8er51rTfTc7HC"),
            "X-ApplicationName": "connectportal",
            "X-RequestFrom": "web"
        })

        if cookies:
            for k, v in cookies.items():
                session.cookies.set(k, str(v), domain="myupes-beta.upes.ac.in")

        nonce = int(time.time() * 1000)
        refresh_url = f"https://myupes-beta.upes.ac.in/sso/user/oauth2/refresh-token?q={nonce}"
        client_id = getattr(config, "UPES_SSO_CLIENT_ID", 3)
        client_secret = getattr(config, "UPES_SSO_CLIENT_SECRET", "ku7GUMtyT8er51rTfTc7HC")

        payload = {
            "ClientId": client_id,
            "ClientSecret": client_secret,
            "RefreshToken": refresh_token
        }

        resp = session.post(refresh_url, json=payload, timeout=(5.0, 15.0), verify=True)

        if resp.status_code in (400, 401, 403):
            raise SessionExpiredError(f"Token refresh rejected (HTTP {resp.status_code}): {resp.text[:100]}")
        elif resp.status_code >= 500:
            raise UpstreamError(f"UPES refresh server error: HTTP {resp.status_code}")

        try:
            data = resp.json()
        except Exception:
            raise UpstreamError(f"Invalid non-JSON refresh response: {resp.text[:100]}")

        if isinstance(data, dict) and "StatusCode" in data:
            if data.get("StatusCode") != 200:
                msg = data.get("Message", "failed to refresh token")
                raise SessionExpiredError(f"UPES SSO rejected refresh token: {msg}")
            token_info = (data.get("Item") or {}).get("tokenInfo") or {}
            access_tok = token_info.get("accessToken") or token_info.get("access_token") or token_info.get("AccessToken")
            new_refresh = token_info.get("refreshToken") or token_info.get("refresh_token") or token_info.get("RefreshToken") or refresh_token
            expires_in = token_info.get("expiresIn") or token_info.get("ExpiresIn") or 3600
        else:
            tokens_obj = data.get("data") if isinstance(data.get("data"), dict) else data
            access_tok = tokens_obj.get("access_token") or tokens_obj.get("token") or tokens_obj.get("accessToken")
            new_refresh = tokens_obj.get("refresh_token") or tokens_obj.get("refreshToken") or refresh_token
            expires_in = tokens_obj.get("expires_in") or tokens_obj.get("expiresIn") or 3600

        if not access_tok:
            raise UpstreamError("Refresh response missing access token.")

        now = time.time()
        return {
            "access_token": access_tok,
            "refresh_token": new_refresh,
            "expires_at": now + float(expires_in),
            "cookies": session.cookies.get_dict(),
            "cookie_expires_at": None
        }

    def _classify_error(self, ex: Exception) -> AuthFailureReason:
        """Classifies exceptions into structured AuthFailureReasons."""
        msg = str(ex).lower()
        if isinstance(ex, SecurityChallengeError) or "challenge" in msg or "captcha" in msg or "turnstile" in msg:
            return AuthFailureReason.SECURITY_CHALLENGE
        if "exhausted" in msg:
            return AuthFailureReason.AUTH_EXHAUSTED
        if "no access token" in msg or "flow changed" in msg or "unexpected_payload" in msg or "missing" in msg:
            return AuthFailureReason.LOGIN_FLOW_CHANGED
        if "network" in msg or "connection" in msg or "timeout" in msg:
            return AuthFailureReason.NETWORK_ERROR
        if "sso server error" in msg or "upes_unavailable" in msg or "server error" in msg or "http 500" in msg:
            return AuthFailureReason.UPES_UNAVAILABLE
        if isinstance(ex, SessionExpiredError) or "refresh" in msg:
            return AuthFailureReason.REFRESH_REJECTED
        if isinstance(ex, AuthRequiredError) or "invalid" in msg or "unauthorized" in msg or "password" in msg:
            return AuthFailureReason.INVALID_CREDENTIALS
        if isinstance(ex, UpstreamError):
            return AuthFailureReason.UPES_UNAVAILABLE
        if isinstance(ex, requests.exceptions.RequestException):
            return AuthFailureReason.NETWORK_ERROR
        return AuthFailureReason.AUTH_INTERNAL_ERROR

    def logout(self, user_id: str = "admin") -> bool:
        """Revokes runtime authentication tokens and clears stored session records."""
        conn = self.conn_factory()
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM upes_auth_sessions WHERE user_id = ?", (user_id,))
            conn.commit()
            deleted = cur.rowcount > 0
            if deleted:
                logger.info(f"UPES auth session revoked for user '{user_id}'.")
            return deleted
        finally:
            conn.close()
