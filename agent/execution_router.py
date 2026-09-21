"""
NexusNode — API-First Execution Router
Decides between Direct HTTP, Local SQLite/Cache, Google API, and Browser Fallback.
Decoupled completely from browser implementation details.

Invariants:
1. Google Calendar operations NEVER fall back to browser.
2. Academic operations (attendance, timetable, punches) default strictly to direct HTTP.
3. Transient HTTP errors (500, 502, 503, timeouts) NEVER trigger browser fallback.
4. Browser fallback is reserved exclusively for UNKNOWN/UNSUPPORTED endpoints,
   mandatory JavaScript challenges, or interactive authentication recovery.
"""

import logging
from enum import Enum
from typing import Dict, Any, Optional, Tuple, Callable

logger = logging.getLogger("NEXUS_EXECUTION_ROUTER")


class ExecutionRoute(Enum):
    DIRECT_HTTP = "direct_http"
    LOCAL_CACHE_OR_API = "local"
    BROWSER_FALLBACK = "browser_fallback"


class RouteDecisionReason(Enum):
    DIRECT_PROVIDER_AVAILABLE = "direct_provider_available"
    API_ONLY_ENFORCED = "api_only_enforced"
    LOCAL_CACHE_HIT = "local_cache_hit"
    JAVASCRIPT_REQUIRED = "javascript_required"
    INTERACTIVE_AUTH_REQUIRED = "interactive_auth_required"
    UNSUPPORTED_DIRECT_OPERATION = "unsupported_direct_operation"
    TRANSIENT_ERROR_NO_FALLBACK = "transient_error_no_fallback"
    BROWSER_FALLBACK_AVAILABLE = "browser_fallback_available"


class ExecutionRouter:
    """
    Evaluates semantic operations and dispatches to the most efficient,
    resource-conscious execution route.
    """

    def __init__(self, browser_service=None):
        self.browser_service = browser_service

    def determine_route(
        self,
        operation: str,
        params: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> Tuple[ExecutionRoute, RouteDecisionReason, Dict[str, Any]]:
        """
        Determines the optimal execution route for a given semantic operation.
        Returns: (ExecutionRoute, RouteDecisionReason, TelemetryDict)
        """
        params = params or {}
        context = context or {}
        op = (operation or "").strip().lower()

        telemetry = {
            "operation": op,
            "can_browser_fallback": False,
            "policy": "api_first"
        }

        # 1. Invariant 1: Google Calendar is ALWAYS API-Only. NEVER Browser Fallback.
        if op.startswith("calendar.") or "calendar" in op:
            telemetry["can_browser_fallback"] = False
            telemetry["reason"] = "Google Calendar API-first contract strictly prohibits browser fallback."
            return ExecutionRoute.LOCAL_CACHE_OR_API, RouteDecisionReason.API_ONLY_ENFORCED, telemetry

        # 2. Invariant 2: Normal Academic Operations (Timetable, Attendance, Punches)
        if op.startswith("upes.") or op in ("attendance.get", "timetable.get", "punches.get", "courses.get"):
            # Check if this is an explicit interactive auth recovery request
            if context.get("interactive_auth_required") is True:
                telemetry["can_browser_fallback"] = True
                telemetry["reason"] = "Interactive institutional authentication challenge requires browser fallback."
                return ExecutionRoute.BROWSER_FALLBACK, RouteDecisionReason.INTERACTIVE_AUTH_REQUIRED, telemetry

            # Normal path is ALWAYS Direct HTTP
            telemetry["can_browser_fallback"] = False
            telemetry["reason"] = "Academic sync uses direct REST / JSON APIs (~1000x faster than browser)."
            return ExecutionRoute.DIRECT_HTTP, RouteDecisionReason.DIRECT_PROVIDER_AVAILABLE, telemetry

        # 3. LMS Operations
        if op.startswith("lms."):
            # Check if direct Moodle session supports the operation
            direct_supported_ops = {
                "lms.list_courses",
                "lms.get_course",
                "lms.list_resources",
                "lms.download_resource",
                "lms.list_assignments",
                "lms.get_assignment"
            }

            if context.get("requires_javascript") is True:
                telemetry["can_browser_fallback"] = True
                telemetry["reason"] = "LMS resource requires dynamic JavaScript client execution."
                return ExecutionRoute.BROWSER_FALLBACK, RouteDecisionReason.JAVASCRIPT_REQUIRED, telemetry

            if op in direct_supported_ops and not context.get("force_browser"):
                telemetry["can_browser_fallback"] = False
                telemetry["reason"] = "Moodle direct HTTP API supports read operation."
                return ExecutionRoute.DIRECT_HTTP, RouteDecisionReason.DIRECT_PROVIDER_AVAILABLE, telemetry

            # Unsupported direct operation or interactive submission wizard
            telemetry["can_browser_fallback"] = True
            telemetry["reason"] = f"LMS operation '{op}' requires browser automation fallback."
            return ExecutionRoute.BROWSER_FALLBACK, RouteDecisionReason.UNSUPPORTED_DIRECT_OPERATION, telemetry

        # 4. Generic External Operations
        if context.get("requires_browser") is True or context.get("requires_javascript") is True:
            telemetry["can_browser_fallback"] = True
            return ExecutionRoute.BROWSER_FALLBACK, RouteDecisionReason.JAVASCRIPT_REQUIRED, telemetry

        # Default fallback
        telemetry["can_browser_fallback"] = False
        return ExecutionRoute.DIRECT_HTTP, RouteDecisionReason.DIRECT_PROVIDER_AVAILABLE, telemetry

    def handle_direct_failure(
        self,
        operation: str,
        http_status: Optional[int],
        exception: Optional[Exception]
    ) -> Tuple[bool, RouteDecisionReason]:
        """
        Evaluates whether a failed direct HTTP operation may fall back to browser.
        CRITICAL: Never fall back on transient server errors (500, 502, 503, timeout).
        """
        op = (operation or "").strip().lower()

        # Invariant: Calendar NEVER falls back
        if "calendar" in op:
            return False, RouteDecisionReason.API_ONLY_ENFORCED

        # Transient server errors: DO NOT fall back
        if http_status in (500, 502, 503, 504, 408, 429):
            logger.info(f"Direct HTTP failed with transient status {http_status}. Refusing browser fallback.")
            return False, RouteDecisionReason.TRANSIENT_ERROR_NO_FALLBACK

        # 401/403: May trigger browser fallback IF interactive challenge detected
        if http_status in (401, 403):
            err_str = str(exception).lower() if exception else ""
            if "captcha" in err_str or "challenge" in err_str or "sso_redirect" in err_str:
                return True, RouteDecisionReason.INTERACTIVE_AUTH_REQUIRED
            return False, RouteDecisionReason.TRANSIENT_ERROR_NO_FALLBACK

        # Not supported
        if http_status == 404 or http_status == 405:
            return True, RouteDecisionReason.UNSUPPORTED_DIRECT_OPERATION

        return False, RouteDecisionReason.TRANSIENT_ERROR_NO_FALLBACK
