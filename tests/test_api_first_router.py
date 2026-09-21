"""
Unit tests for NexusNode API-First Execution Router (Phase 4.1B).
Validates routing decisions, policy invariants, and failure fallback handling.
"""

import unittest
from agent.execution_router import ExecutionRouter, ExecutionRoute, RouteDecisionReason


class TestApiFirstRouter(unittest.TestCase):

    def setUp(self):
        self.router = ExecutionRouter()

    # 1. Calendar Invariant
    def test_calendar_never_browser_fallback(self):
        calendar_ops = [
            "calendar.reconcile",
            "calendar.events.list",
            "calendar.events.insert",
            "calendar.sync",
            "google_calendar_reconciliation"
        ]
        for op in calendar_ops:
            route, reason, telemetry = self.router.determine_route(op)
            self.assertEqual(route, ExecutionRoute.LOCAL_CACHE_OR_API, f"Failed for {op}")
            self.assertEqual(reason, RouteDecisionReason.API_ONLY_ENFORCED, f"Failed for {op}")
            self.assertFalse(telemetry["can_browser_fallback"], f"Fallback allowed for {op}")

    def test_calendar_failure_never_falls_back(self):
        allowed, reason = self.router.handle_direct_failure("calendar.sync", 500, Exception("Server Error"))
        self.assertFalse(allowed)
        self.assertEqual(reason, RouteDecisionReason.API_ONLY_ENFORCED)

        allowed, reason = self.router.handle_direct_failure("calendar.events.list", 401, Exception("Unauthorized"))
        self.assertFalse(allowed)
        self.assertEqual(reason, RouteDecisionReason.API_ONLY_ENFORCED)

    # 2. Academic Operations (Direct HTTP)
    def test_academic_operations_route_direct_http(self):
        academic_ops = [
            "upes.attendance.get",
            "attendance.get",
            "timetable.get",
            "punches.get",
            "courses.get"
        ]
        for op in academic_ops:
            route, reason, telemetry = self.router.determine_route(op)
            self.assertEqual(route, ExecutionRoute.DIRECT_HTTP, f"Failed for {op}")
            self.assertEqual(reason, RouteDecisionReason.DIRECT_PROVIDER_AVAILABLE, f"Failed for {op}")
            self.assertFalse(telemetry["can_browser_fallback"], f"Fallback allowed for {op}")

    def test_academic_operation_interactive_auth_override(self):
        route, reason, telemetry = self.router.determine_route(
            "attendance.get",
            context={"interactive_auth_required": True}
        )
        self.assertEqual(route, ExecutionRoute.BROWSER_FALLBACK)
        self.assertEqual(reason, RouteDecisionReason.INTERACTIVE_AUTH_REQUIRED)
        self.assertTrue(telemetry["can_browser_fallback"])

    # 3. LMS Operations
    def test_lms_direct_operations_route_direct_http(self):
        lms_direct_ops = [
            "lms.list_courses",
            "lms.get_course",
            "lms.list_resources",
            "lms.download_resource",
            "lms.list_assignments",
            "lms.get_assignment"
        ]
        for op in lms_direct_ops:
            route, reason, telemetry = self.router.determine_route(op)
            self.assertEqual(route, ExecutionRoute.DIRECT_HTTP, f"Failed for {op}")
            self.assertEqual(reason, RouteDecisionReason.DIRECT_PROVIDER_AVAILABLE, f"Failed for {op}")
            self.assertFalse(telemetry["can_browser_fallback"], f"Fallback allowed for {op}")

    def test_lms_javascript_or_unsupported_routes_browser_fallback(self):
        # Unsupported direct LMS operation
        route, reason, telemetry = self.router.determine_route("lms.submit_assignment_wizard")
        self.assertEqual(route, ExecutionRoute.BROWSER_FALLBACK)
        self.assertEqual(reason, RouteDecisionReason.UNSUPPORTED_DIRECT_OPERATION)
        self.assertTrue(telemetry["can_browser_fallback"])

        # Operation requiring dynamic javascript execution
        route, reason, telemetry = self.router.determine_route(
            "lms.list_resources",
            context={"requires_javascript": True}
        )
        self.assertEqual(route, ExecutionRoute.BROWSER_FALLBACK)
        self.assertEqual(reason, RouteDecisionReason.JAVASCRIPT_REQUIRED)
        self.assertTrue(telemetry["can_browser_fallback"])

    # 4. Transient Error Handling
    def test_transient_http_errors_never_fallback_to_browser(self):
        transient_codes = [500, 502, 503, 504, 408, 429]
        for code in transient_codes:
            allowed, reason = self.router.handle_direct_failure("attendance.get", code, Exception("Gateway Error"))
            self.assertFalse(allowed, f"Should not fallback on {code}")
            self.assertEqual(reason, RouteDecisionReason.TRANSIENT_ERROR_NO_FALLBACK, f"Wrong reason for {code}")

    # 5. Challenge and Unsupported Status Handling
    def test_interactive_challenge_triggers_fallback(self):
        # 401 with captcha / challenge keyword
        allowed, reason = self.router.handle_direct_failure(
            "attendance.get", 401, Exception("Encountered CAPTCHA challenge during login")
        )
        self.assertTrue(allowed)
        self.assertEqual(reason, RouteDecisionReason.INTERACTIVE_AUTH_REQUIRED)

        # 403 with sso_redirect
        allowed, reason = self.router.handle_direct_failure(
            "attendance.get", 403, Exception("SSO_REDIRECT required for re-auth")
        )
        self.assertTrue(allowed)
        self.assertEqual(reason, RouteDecisionReason.INTERACTIVE_AUTH_REQUIRED)

    def test_unsupported_status_triggers_fallback(self):
        allowed, reason = self.router.handle_direct_failure("lms.complex_action", 404, Exception("Not Found"))
        self.assertTrue(allowed)
        self.assertEqual(reason, RouteDecisionReason.UNSUPPORTED_DIRECT_OPERATION)

        allowed, reason = self.router.handle_direct_failure("lms.complex_action", 405, Exception("Method Not Allowed"))
        self.assertTrue(allowed)
        self.assertEqual(reason, RouteDecisionReason.UNSUPPORTED_DIRECT_OPERATION)


if __name__ == "__main__":
    unittest.main()
