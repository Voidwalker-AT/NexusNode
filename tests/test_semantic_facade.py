"""
NexusNode — Phase 4.1C Semantic Facade Test Suite
Authoritative tests verifying the 11-tool semantic catalog (nexus-semantic-v1),
tenant derivation, RBAC capability enforcement, schema adapters, error normalization,
zero-browser invariants, and dual-mode catalog switching.
"""

import json
import copy
import logging
import unittest
from unittest.mock import MagicMock, patch

import config
from agent.semantic_facade import (
    SemanticMcpFacade,
    SEMANTIC_TOOL_DEFINITIONS,
    SEMANTIC_CATALOG_VERSION,
    SEMANTIC_OPERATION_MAP,
    INTERNAL_CAPABILITY_MAP,
    adapt_schema_for_gemini,
    adapt_schema_for_mistral,
)
from agent.models import ExecutionResult
from agent.execution_router import ExecutionRouter, ExecutionRoute, RouteDecisionReason
from agent.mcp_server import McpServerAdapter, MCP_TOOL_DEFINITIONS


class TestSemanticFacade(unittest.TestCase):

    def setUp(self):
        self.mock_registry = MagicMock()
        self.mock_token_manager = MagicMock()
        self.mock_router = ExecutionRouter()
        self.facade = SemanticMcpFacade(
            registry=self.mock_registry,
            execution_router=self.mock_router,
            token_manager=self.mock_token_manager
        )
        self.mock_token_manager.check_capability.return_value = True

    # --------------------------------------------------------------------------
    # 1. Tool Count and Version
    # --------------------------------------------------------------------------
    def test_01_catalog_tool_count_and_version(self):
        """Verify catalog contains exactly 11 semantic tools and version is nexus-semantic-v1."""
        tools = self.facade.get_tool_definitions(catalog_mode="semantic")
        self.assertEqual(len(tools), 11)
        self.assertEqual(len(SEMANTIC_TOOL_DEFINITIONS), 11)
        self.assertEqual(SEMANTIC_CATALOG_VERSION, "nexus-semantic-v1")
        tool_names = [t["name"] for t in tools]
        expected_names = [
            "nexus.status",
            "academic.query",
            "academic.sync",
            "academic.analyze",
            "lms.query",
            "lms.fetch",
            "lms.prepare",
            "vault.manage",
            "document.process",
            "browser.interact",
            "action.status",
        ]
        self.assertEqual(set(tool_names), set(expected_names))

    # --------------------------------------------------------------------------
    # 2. Schema Adaptation and Byte Budget
    # --------------------------------------------------------------------------
    def test_02_schema_adapters_and_byte_budget(self):
        """Verify Gemini and Mistral schema adaptations and measure byte footprint."""
        canonical = self.facade.get_tool_definitions(client_type="canonical")
        gemini = self.facade.get_tool_definitions(client_type="gemini")
        mistral = self.facade.get_tool_definitions(client_type="mistral")

        canon_bytes = len(json.dumps(canonical))
        gemini_bytes = len(json.dumps(gemini))
        mistral_bytes = len(json.dumps(mistral))

        # Ensure byte reduction or equivalence
        self.assertLessEqual(gemini_bytes, canon_bytes)
        self.assertLessEqual(mistral_bytes, canon_bytes)

        # Verify Gemini strips disallowed keywords
        for t in gemini:
            schema = t["inputSchema"]
            self.assertNotIn("$schema", schema)
            self.assertNotIn("$id", schema)
            self.assertNotIn("additionalProperties", schema)

    # --------------------------------------------------------------------------
    # 3. Semantic Dispatch for All 11 Tools
    # --------------------------------------------------------------------------
    def test_03_semantic_dispatch_all_11_tools(self):
        """Verify each of the 11 semantic tools maps to the correct internal operation."""
        test_calls = [
            ("nexus.status", {}, "nexus.status"),
            ("academic.query", {"operation": "timetable"}, "upes.get_timetable"),
            ("academic.sync", {"operation": "attendance"}, "upes.attendance.sync"),
            ("academic.analyze", {"operation": "safe_bunks"}, "upes.calculate_attendance"),
            ("lms.query", {"operation": "courses"}, "lms.list_courses"),
            ("lms.fetch", {"resource_id": "r1", "destination_path": "a/b.pdf"}, "lms.download_resource"),
            ("lms.prepare", {"operation": "inspect_assignment", "assignment_id": "a1"}, "lms.get_assignment"),
            ("vault.manage", {"operation": "list"}, "vault.list"),
            ("document.process", {"operation": "extract", "path": "test.pdf"}, "document.extract"),
            ("browser.interact", {"operation": "open", "url": "https://example.com"}, "browser.open"),
            ("action.status", {"plan_id": "p1"}, "action.status"),
        ]

        token_meta = {"principal": "test-agent", "user_id": "student1"}

        for tool_name, args, expected_internal in test_calls:
            self.mock_registry.execute.return_value = ExecutionResult(
                ok=True,
                operation=expected_internal,
                source="live",
                provider="direct_http",
                data={"result": "ok"}
            )
            res = self.facade.execute(tool_name, args, token_meta)
            self.assertFalse(res["isError"], f"Failed for {tool_name}: {res}")
            parsed = json.loads(res["content"][0]["text"])
            self.assertTrue(parsed["ok"])
            self.mock_registry.execute.assert_called_with(
                operation_name=expected_internal,
                user_id="student1",
                params=unittest.mock.ANY,
                description=unittest.mock.ANY
            )

    # --------------------------------------------------------------------------
    # 4. Strict Tenant Derivation (Client Cannot Override Principal)
    # --------------------------------------------------------------------------
    def test_04_tenant_derivation_rejects_client_override(self):
        """Verify client-supplied user_id, username, target_user are stripped."""
        token_meta = {"principal": "auth-student", "user_id": "auth-student"}
        malicious_args = {
            "operation": "timetable",
            "user_id": "victim-user",
            "username": "victim-admin",
            "target_user": "victim-target"
        }

        self.mock_registry.execute.return_value = ExecutionResult(
            ok=True,
            operation="upes.get_timetable",
            source="live",
            provider="direct_http",
            data=[]
        )

        res = self.facade.execute("academic.query", malicious_args, token_meta)
        self.assertFalse(res["isError"])
        # Ensure registry execute was called with auth-student and NOT victim-user
        call_kwargs = self.mock_registry.execute.call_args.kwargs
        self.assertEqual(call_kwargs["user_id"], "auth-student")
        passed_params = call_kwargs["params"]
        self.assertNotIn("user_id", passed_params)
        self.assertNotIn("username", passed_params)
        self.assertNotIn("target_user", passed_params)

    # --------------------------------------------------------------------------
    # 5. RBAC Capability Enforcement
    # --------------------------------------------------------------------------
    def test_05_capability_enforcement_blocks_unauthorized_principal(self):
        """Verify operations are rejected with PERMISSION_DENIED if required capability is absent."""
        self.mock_token_manager.check_capability.return_value = False
        token_meta = {"principal": "unprivileged-agent", "capabilities": []}

        res = self.facade.execute("academic.query", {"operation": "timetable"}, token_meta)
        self.assertTrue(res["isError"])
        parsed = json.loads(res["content"][0]["text"])
        self.assertFalse(parsed["ok"])
        self.assertEqual(parsed["error"]["code"], "PERMISSION_DENIED")
        self.assertIn("unprivileged-agent", parsed["error"]["message"])

    # --------------------------------------------------------------------------
    # 6. Provenance Envelope
    # --------------------------------------------------------------------------
    def test_06_provenance_envelope_structure(self):
        """Verify provenance structure includes source, route, stale, fetched_at, fallback_used."""
        self.mock_registry.execute.return_value = ExecutionResult(
            ok=True,
            operation="upes.get_attendance",
            source="live",
            provider="direct_http",
            data={"percentage": 88.5},
            stale=False,
            fetched_at=1700000000.0
        )
        token_meta = {"principal": "test-agent"}
        res = self.facade.execute("academic.query", {"operation": "attendance"}, token_meta)
        parsed = json.loads(res["content"][0]["text"])

        self.assertTrue(parsed["ok"])
        prov = parsed.get("provenance")
        self.assertIsNotNone(prov)
        self.assertEqual(prov["source"], "live")
        self.assertEqual(prov["route"], "direct_http")
        self.assertFalse(prov["stale"])
        self.assertFalse(prov["fallback_used"])
        self.assertIn("fetched_at", prov)

    # --------------------------------------------------------------------------
    # 7. Error Normalization (No Stack Traces)
    # --------------------------------------------------------------------------
    def test_07_error_normalization_without_stack_traces(self):
        """Verify errors are normalized to standard codes and do not leak exceptions/traces."""
        self.mock_registry.execute.return_value = ExecutionResult(
            ok=False,
            operation="upes.get_timetable",
            source="local",
            provider="direct_http",
            error="Connection refused to upstream at 10.0.0.1:8080: trace line 42",
            error_code="UPSTREAM_UNAVAILABLE"
        )
        token_meta = {"principal": "test-agent"}
        res = self.facade.execute("academic.query", {"operation": "timetable"}, token_meta)
        self.assertTrue(res["isError"])
        parsed = json.loads(res["content"][0]["text"])

        self.assertFalse(parsed["ok"])
        self.assertEqual(parsed["error"]["code"], "UPSTREAM_UNAVAILABLE")
        self.assertIn("message", parsed["error"])
        self.assertIn("retryable", parsed["error"])
        # Ensure no traceback keywords
        self.assertNotIn("Traceback", res["content"][0]["text"])

    # --------------------------------------------------------------------------
    # 8. Dual Audit Logging
    # --------------------------------------------------------------------------
    def test_08_audit_mapping_logs_external_and_internal_ops(self):
        """Verify [SEMANTIC_AUDIT] is emitted with external tool, semantic op, and internal op."""
        self.mock_registry.execute.return_value = ExecutionResult(
            ok=True,
            operation="upes.get_timetable",
            source="live",
            provider="direct_http",
            data=[]
        )
        token_meta = {"principal": "audited-agent", "user_id": "u1"}
        with self.assertLogs("NEXUS_SEMANTIC_FACADE", level="INFO") as log_ctx:
            self.facade.execute("academic.query", {"operation": "timetable"}, token_meta)
            audit_records = [r for r in log_ctx.output if "[SEMANTIC_AUDIT]" in r]
            self.assertTrue(len(audit_records) > 0)
            rec = audit_records[0]
            self.assertIn("external='academic.query'", rec)
            self.assertIn("op='timetable'", rec)
            self.assertIn("internal='upes.get_timetable'", rec)
            self.assertIn("principal='audited-agent'", rec)

    # --------------------------------------------------------------------------
    # 9. Self-Approval Impossibility
    # --------------------------------------------------------------------------
    def test_09_self_approval_impossibility(self):
        """Verify approval.approve cannot be invoked through the MCP interface."""
        adapter = McpServerAdapter(
            registry=self.mock_registry,
            token_manager=self.mock_token_manager,
            semantic_facade=self.facade
        )
        token_meta = {"principal": "rogue-agent", "capabilities": ["*"]}

        # Attempt to call approval.approve in semantic mode
        req = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "approval.approve",
                "arguments": {"approval_id": "appr_123"}
            }
        }
        res = adapter.handle_json_rpc(req, token_meta)
        self.assertIn("error", res)
        self.assertEqual(res["error"]["code"], -32601)

    # --------------------------------------------------------------------------
    # 10. Dual Catalog Mode Rollback
    # --------------------------------------------------------------------------
    def test_10_dual_catalog_mode_legacy_rollback(self):
        """Verify setting MCP_CATALOG_MODE='legacy' exposes the 43+ tool catalog."""
        adapter = McpServerAdapter(
            registry=self.mock_registry,
            token_manager=self.mock_token_manager,
            semantic_facade=self.facade
        )
        token_meta = {"principal": "test-agent", "capabilities": ["*"]}

        # 1. Semantic mode (default)
        with patch.object(config, "MCP_CATALOG_MODE", "semantic"):
            res_semantic = adapter.handle_json_rpc({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, token_meta)
            tools_semantic = res_semantic["result"]["tools"]
            self.assertEqual(len(tools_semantic), 11)

        # 2. Legacy mode (with filter unset to expose all catalog tools)
        with patch.object(config, "MCP_CATALOG_MODE", "legacy"), patch.object(config, "MCP_EXPOSED_TOOLS", None):
            res_legacy = adapter.handle_json_rpc({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, token_meta)
            tools_legacy = res_legacy["result"]["tools"]
            self.assertGreater(len(tools_legacy), 40)
            self.assertIn("upes.get_timetable", [t["name"] for t in tools_legacy])

    # --------------------------------------------------------------------------
    # 11. Zero-Browser Invariant for Academic Queries
    # --------------------------------------------------------------------------
    def test_11_zero_browser_invariant_for_academic_queries(self):
        """Verify normal academic queries route to direct_http or local, NEVER browser fallback."""
        router = ExecutionRouter()
        for op in ["timetable", "attendance", "punches", "courses", "next_classes"]:
            internal_op = SEMANTIC_OPERATION_MAP["academic.query"][op]
            route, reason, _ = router.determine_route(internal_op)
            self.assertNotEqual(route, ExecutionRoute.BROWSER_FALLBACK)
            self.assertIn(route, (ExecutionRoute.DIRECT_HTTP, ExecutionRoute.LOCAL_CACHE_OR_API))

    # --------------------------------------------------------------------------
    # 12. Calendar Browser Impossibility
    # --------------------------------------------------------------------------
    def test_12_calendar_browser_impossibility(self):
        """Verify calendar.reconcile enforces API-only and strictly rejects browser fallback."""
        router = ExecutionRouter()
        internal_op = SEMANTIC_OPERATION_MAP["academic.sync"]["calendar"]
        self.assertEqual(internal_op, "calendar.reconcile")

        route, reason, telemetry = router.determine_route(internal_op, params={"calendar_id": "cal_123"})
        self.assertEqual(route, ExecutionRoute.LOCAL_CACHE_OR_API)
        self.assertEqual(reason, RouteDecisionReason.API_ONLY_ENFORCED)
        self.assertFalse(telemetry["can_browser_fallback"])


if __name__ == "__main__":
    unittest.main()
