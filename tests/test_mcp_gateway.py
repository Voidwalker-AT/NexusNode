"""
NexusNode — Unit & Integration Test Suite for MCP Gateway (Phase 3.3B — MCP 2026-07-28)
Tests official MCP 2026-07-28 Stateless Protocol, Streamable HTTP headers, server/discover,
tool discovery, capability enforcement, Vault allowlist containment, rate limiting, and output sanitization.
"""

import os
import sys
import json
import time
import shutil
import sqlite3
import unittest
from unittest.mock import MagicMock, patch

import config
import agent
import upes
from agent.mcp_auth import AgentTokenManager, init_agent_auth_tables
from agent.vault_service import VaultService, VaultPathError, VaultAccessError
from agent.status_service import StatusService
from agent.rate_limiter import AgentRateLimiter
from agent.sanitizer import sanitize_data
from agent.mcp_server import McpServerAdapter, MCP_TOOL_DEFINITIONS
from agent.mcp_client import McpClient


class TestMcpGatewayModern(unittest.TestCase):

    def setUp(self):
        self.test_dir = os.path.join(config.BASE_DIR, "tests", "scratch", f"test_mcp_mod_{int(time.time()*1000)}")
        os.makedirs(self.test_dir, exist_ok=True)
        self.db_path = os.path.join(self.test_dir, "test_mcp.db")
        self.agent_vault_dir = os.path.join(self.test_dir, "user_files")
        os.makedirs(self.agent_vault_dir, exist_ok=True)

        self.conn_factory = lambda: sqlite3.connect(self.db_path)

        # Initialize DB tables
        conn = self.conn_factory()
        init_agent_auth_tables(conn)
        conn.close()

        self.token_manager = AgentTokenManager(conn_factory=self.conn_factory)
        self.rate_limiter = AgentRateLimiter(default_principal_rpm=60, default_tool_rpm=30, tool_rpm_overrides={})
        self.policy_engine = agent.PolicyEngine()
        self.registry = agent.AgentOperationRegistry(policy_engine=self.policy_engine)
        self.vault_service = VaultService(agent_vault_root=self.agent_vault_dir)

        # Setup mock services for UPES & Status
        self.mock_upes_router = MagicMock()
        self.mock_upes_router.session_tracker.get_safe_status.return_value = {"state": "AUTHENTICATED"}
        self.mock_browser_provider = MagicMock()
        self.mock_browser_provider.provider_name = "pinchtab"
        self.mock_browser_provider.get_health.return_value = {"status": "HEALTHY", "daemon_running": True}

        self.status_service = StatusService(
            conn_factory=self.conn_factory,
            upes_router=self.mock_upes_router,
            browser_provider=self.mock_browser_provider
        )

        # Register tools
        self.registry.register("nexus.status", lambda user_id, params, **kw: self.status_service.get_status(user_id, params), risk_class=agent.RiskClass.READ_ONLY)
        self.registry.register("upes.auth_status", lambda user_id, params, **kw: self.mock_upes_router.execute("upes.auth_status", user_id, params, **kw), risk_class=agent.RiskClass.READ_ONLY)
        self.registry.register("upes.get_attendance", lambda user_id, params, **kw: self.mock_upes_router.execute("upes.get_attendance", user_id, params, **kw), risk_class=agent.RiskClass.READ_ONLY)
        self.registry.register("upes.get_timetable", lambda user_id, params, **kw: self.mock_upes_router.execute("upes.get_timetable", user_id, params, **kw), risk_class=agent.RiskClass.READ_ONLY)
        self.registry.register("upes.get_next_classes", lambda user_id, params, **kw: self.mock_upes_router.execute("upes.get_next_classes", user_id, params, **kw), risk_class=agent.RiskClass.READ_ONLY)
        self.registry.register("upes.get_courses", lambda user_id, params, **kw: self.mock_upes_router.execute("upes.get_courses", user_id, params, **kw), risk_class=agent.RiskClass.READ_ONLY)
        self.registry.register("vault.list", lambda user_id, params, **kw: self.vault_service.list_files(user_id, params), risk_class=agent.RiskClass.READ_ONLY)
        self.registry.register("vault.search", lambda user_id, params, **kw: self.vault_service.search_vault(user_id, params), risk_class=agent.RiskClass.READ_ONLY)
        self.registry.register("vault.read", lambda user_id, params, **kw: self.vault_service.read_file(user_id, params), risk_class=agent.RiskClass.READ_ONLY)
        self.registry.register("browser.status", lambda user_id, params, **kw: agent.ExecutionResult(ok=True, operation="browser.status", source="browser", provider=self.mock_browser_provider.provider_name, data=self.mock_browser_provider.get_health()), risk_class=agent.RiskClass.READ_ONLY)

        self.mcp_adapter = McpServerAdapter(
            registry=self.registry,
            token_manager=self.token_manager,
            rate_limiter=self.rate_limiter
        )

        # Generate default test agent token
        self.raw_token, self.token_meta = self.token_manager.generate_token(
            principal="spark-agent",
            capabilities=agent.DEFAULT_SPARK_CAPABILITIES
        )
        self.orig_exposed = getattr(config, "MCP_EXPOSED_TOOLS", None)
        self.orig_variant = getattr(config, "MCP_SCHEMA_VARIANT", "variant_a")
        self.orig_catalog = getattr(config, "MCP_CATALOG_MODE", "semantic")
        config.MCP_EXPOSED_TOOLS = None
        config.MCP_SCHEMA_VARIANT = "variant_a"
        config.MCP_CATALOG_MODE = "legacy"

    def tearDown(self):
        config.MCP_EXPOSED_TOOLS = self.orig_exposed
        config.MCP_SCHEMA_VARIANT = self.orig_variant
        config.MCP_CATALOG_MODE = self.orig_catalog
        try:
            if os.path.exists(self.test_dir):
                shutil.rmtree(self.test_dir, ignore_errors=True)
        except Exception:
            pass

    # --------------------------------------------------------------------------
    # 1. MCP 2026-07-28 Modern Discovery & Header Validation Tests
    # --------------------------------------------------------------------------

    def test_01_mcp_server_discover(self):
        req = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "server/discover",
            "params": {
                "_meta": {
                    "io.modelcontextprotocol/protocolVersion": "2026-07-28"
                }
            }
        }
        resp = self.mcp_adapter.handle_json_rpc(req, self.token_meta)
        self.assertEqual(resp["jsonrpc"], "2.0")
        self.assertEqual(resp["id"], 1)
        res = resp["result"]
        self.assertEqual(res["defaultProtocolVersion"], "2026-07-28")
        self.assertIn("2026-07-28", res["protocolVersions"])
        self.assertEqual(res["serverInfo"]["name"], "nexusnode-mcp")

    def test_02_mcp_modern_header_validation_success(self):
        req = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "nexus.status",
                "arguments": {},
                "_meta": {"io.modelcontextprotocol/protocolVersion": "2026-07-28"}
            }
        }
        headers = {
            "MCP-Protocol-Version": "2026-07-28",
            "Mcp-Method": "tools/call",
            "Mcp-Name": "nexus.status"
        }
        resp = self.mcp_adapter.handle_json_rpc(req, self.token_meta, headers=headers)
        self.assertFalse(resp["result"]["isError"])

    def test_03_mcp_mismatched_method_header_rejected(self):
        req = {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/list",
            "params": {}
        }
        headers = {
            "MCP-Protocol-Version": "2026-07-28",
            "Mcp-Method": "tools/call"  # Mismatched!
        }
        resp = self.mcp_adapter.handle_json_rpc(req, self.token_meta, headers=headers)
        self.assertIn("error", resp)
        self.assertEqual(resp["error"]["code"], -32600)
        self.assertIn("Mcp-Method", resp["error"]["message"])

    def test_04_mcp_mismatched_tool_name_header_rejected(self):
        req = {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "nexus.status", "arguments": {}}
        }
        headers = {
            "MCP-Protocol-Version": "2026-07-28",
            "Mcp-Method": "tools/call",
            "Mcp-Name": "upes.get_attendance"  # Mismatched!
        }
        resp = self.mcp_adapter.handle_json_rpc(req, self.token_meta, headers=headers)
        self.assertIn("error", resp)
        self.assertEqual(resp["error"]["code"], -32600)
        self.assertIn("Mcp-Name", resp["error"]["message"])

    def test_05_mcp_unsupported_protocol_version_rejected(self):
        req = {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "server/discover"
        }
        headers = {
            "MCP-Protocol-Version": "2019-01-01"  # Unsupported!
        }
        resp = self.mcp_adapter.handle_json_rpc(req, self.token_meta, headers=headers)
        self.assertIn("error", resp)
        self.assertEqual(resp["error"]["code"], -32600)
        self.assertIn("Unsupported MCP-Protocol-Version", resp["error"]["message"])

    # --------------------------------------------------------------------------
    # 2. Modern Stateless Tool Discovery & Capability Tests
    # --------------------------------------------------------------------------

    def test_06_modern_stateless_tools_list(self):
        # Directly invoke tools/list without initialize handshake
        req = {
            "jsonrpc": "2.0",
            "id": 6,
            "method": "tools/list",
            "params": {
                "_meta": {"io.modelcontextprotocol/protocolVersion": "2026-07-28"}
            }
        }
        resp = self.mcp_adapter.handle_json_rpc(req, self.token_meta)
        tools = resp["result"]["tools"]
        tool_names = [t["name"] for t in tools]
        
        expected_tools = [
            "nexus.status", "upes.auth_status", "upes.get_attendance",
            "upes.get_timetable", "upes.get_next_classes", "upes.get_courses",
            "vault.list", "vault.search", "vault.read", "browser.status"
        ]
        for et in expected_tools:
            self.assertIn(et, tool_names)

        # Verify JSON Schema 2020-12 in tool schemas
        for t in tools:
            self.assertEqual(t["inputSchema"].get("$schema"), "https://json-schema.org/draft/2020-12/schema")

    def test_07_capability_authorization_rejection(self):
        raw_restricted, meta_restricted = self.token_manager.generate_token(
            principal="restricted-agent",
            capabilities=["nexus.status.read"]
        )
        req = {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {"name": "upes.get_attendance", "arguments": {}}
        }
        resp = self.mcp_adapter.handle_json_rpc(req, meta_restricted)
        self.assertIn("error", resp)
        self.assertEqual(resp["error"]["code"], -32000)
        self.assertIn("lacks capability", resp["error"]["message"])

    # --------------------------------------------------------------------------
    # 3. Semantic Tools & Provenance Tests
    # --------------------------------------------------------------------------

    def test_08_nexus_status_tool(self):
        req = {
            "jsonrpc": "2.0",
            "id": 8,
            "method": "tools/call",
            "params": {"name": "nexus.status", "arguments": {}}
        }
        resp = self.mcp_adapter.handle_json_rpc(req, self.token_meta)
        self.assertFalse(resp["result"]["isError"])
        data = json.loads(resp["result"]["content"][0]["text"])
        self.assertTrue(data["ok"])
        self.assertEqual(data["operation"], "nexus.status")
        self.assertEqual(data["data"]["appliance"]["device"], "TECNO BG6")

    def test_09_upes_attendance_tool_provenance(self):
        self.mock_upes_router.execute.return_value = agent.ExecutionResult(
            ok=True,
            operation="upes.get_attendance",
            source="live",
            provider="direct_http",
            data={"overall_percentage": 85.0, "total_sessions": 50, "total_attended": 42},
            stale=False
        )
        req = {
            "jsonrpc": "2.0",
            "id": 9,
            "method": "tools/call",
            "params": {"name": "upes.get_attendance", "arguments": {"threshold": 0.75}}
        }
        resp = self.mcp_adapter.handle_json_rpc(req, self.token_meta)
        data = json.loads(resp["result"]["content"][0]["text"])
        self.assertTrue(data["ok"])
        self.assertEqual(data["provenance"]["source"], "live")
        self.assertFalse(data["provenance"]["stale"])

    def test_10_browser_status_tool(self):
        req = {
            "jsonrpc": "2.0",
            "id": 10,
            "method": "tools/call",
            "params": {"name": "browser.status", "arguments": {}}
        }
        resp = self.mcp_adapter.handle_json_rpc(req, self.token_meta)
        data = json.loads(resp["result"]["content"][0]["text"])
        self.assertTrue(data["ok"])
        self.assertEqual(data["provenance"]["provider"], "pinchtab")

    # --------------------------------------------------------------------------
    # 4. Vault Allowlist & Security Boundary Tests
    # --------------------------------------------------------------------------

    def test_11_vault_list_allowlist(self):
        sample = os.path.join(self.agent_vault_dir, "notes.txt")
        with open(sample, "w", encoding="utf-8") as f:
            f.write("Syllabus notes")
        res = self.vault_service.list_files("spark-agent")
        self.assertTrue(res.ok)
        self.assertEqual(len(res.data["items"]), 1)

    def test_12_vault_read_path_traversal_blocked(self):
        res = self.vault_service.read_file("spark-agent", {"path": "../../etc/shadow"})
        self.assertFalse(res.ok)
        self.assertEqual(res.error_code, "INVALID_PATH")

    def test_13_vault_read_untrusted_envelope(self):
        test_file = os.path.join(self.agent_vault_dir, "doc.txt")
        with open(test_file, "w", encoding="utf-8") as f:
            f.write("Untrusted student text.")
        res = self.vault_service.read_file("spark-agent", {"path": "doc.txt"})
        self.assertTrue(res.ok)
        self.assertEqual(res.data["content_type"], "untrusted_document")
        self.assertIn("<untrusted_document_content", res.data["envelope"])

    def test_14_vault_read_binary_file(self):
        bin_file = os.path.join(self.agent_vault_dir, "app.bin")
        with open(bin_file, "wb") as f:
            f.write(b"\x00\x01\x02\xFF\xFE")
        res = self.vault_service.read_file("spark-agent", {"path": "app.bin"})
        self.assertTrue(res.ok)
        self.assertTrue(res.data["is_binary"])

    def test_15_vault_search_allowlist_scoping(self):
        doc = os.path.join(self.agent_vault_dir, "search_target.txt")
        with open(doc, "w", encoding="utf-8") as f:
            f.write("Special agent search keyword: quantum_teleportation")
        res = self.vault_service.search_vault("spark-agent", {"query": "quantum_teleportation"})
        self.assertTrue(res.ok)
        self.assertEqual(res.data["total_matches"], 1)

    # --------------------------------------------------------------------------
    # 5. Rate Limiter, Sanitizer & Legacy Handshake Compatibility
    # --------------------------------------------------------------------------

    def test_16_rate_limiter(self):
        limiter = AgentRateLimiter(default_principal_rpm=2, default_tool_rpm=2, tool_rpm_overrides={})
        ok1, _, _ = limiter.check_rate_limit("spark-agent", "custom.tool")
        ok2, _, _ = limiter.check_rate_limit("spark-agent", "custom.tool")
        ok3, reason, retry = limiter.check_rate_limit("spark-agent", "custom.tool")
        self.assertTrue(ok1)
        self.assertTrue(ok2)
        self.assertFalse(ok3)
        self.assertGreater(retry, 0)

    def test_17_output_sanitizer(self):
        payload = {
            "password": "SecretPassword123!",
            "access_token": "eyJhbGciOi.eyJzdWIi.signature",
            "data": "safe content"
        }
        cleaned = sanitize_data(payload)
        self.assertEqual(cleaned["password"], "[REDACTED_SECRET]")
        self.assertEqual(cleaned["access_token"], "[REDACTED_SECRET]")
        self.assertEqual(cleaned["data"], "safe content")

    def test_18_legacy_initialize_compatibility(self):
        req = {"jsonrpc": "2.0", "id": 18, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}}
        resp = self.mcp_adapter.handle_json_rpc(req, self.token_meta)
        self.assertEqual(resp["result"]["protocolVersion"], "2024-11-05")

    def test_19_legacy_ping_compatibility(self):
        req = {"jsonrpc": "2.0", "id": 19, "method": "ping"}
        resp = self.mcp_adapter.handle_json_rpc(req, self.token_meta)
        self.assertEqual(resp["result"], {})

    def test_19a_malformed_jsonrpc_missing_version_or_method(self):
        req = {"id": 99}  # Missing jsonrpc='2.0' and method
        resp = self.mcp_adapter.handle_json_rpc(req, self.token_meta)
        self.assertIn("error", resp)
        self.assertEqual(resp["error"]["code"], -32600)

    def test_19b_unknown_mcp_method_rejected(self):
        req = {"jsonrpc": "2.0", "id": 100, "method": "unknown/nonexistent_rpc"}
        resp = self.mcp_adapter.handle_json_rpc(req, self.token_meta)
        self.assertIn("error", resp)
        self.assertEqual(resp["error"]["code"], -32601)

    def test_19c_gemini_schema_adapter(self):
        """Tests that legacy Gemini clients receive schemas stripped of $schema and additionalProperties."""
        from agent.mcp_server import adapt_schema_for_gemini
        
        # Test parameterless tool
        raw_status = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {},
            "additionalProperties": False
        }
        adapted_status = adapt_schema_for_gemini(raw_status)
        self.assertEqual(adapted_status, {"type": "object"})
        self.assertNotIn("$schema", adapted_status)
        self.assertNotIn("additionalProperties", adapted_status)

        # Test parameterized tool
        raw_param = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Max count"}
            },
            "additionalProperties": False
        }
        adapted_param = adapt_schema_for_gemini(raw_param)
        self.assertNotIn("$schema", adapted_param)
        self.assertNotIn("additionalProperties", adapted_param)
        self.assertEqual(adapted_param["type"], "object")
        self.assertIn("limit", adapted_param["properties"])


class TestMcpFlaskEndpointsModern(unittest.TestCase):
    """Integration tests against Flask HTTP endpoint with modern headers."""

    def setUp(self):
        import app as nexus_app
        self.app = nexus_app
        self.app.app.config['TESTING'] = True
        self.client = self.app.app.test_client()

        # Admin session for token management
        self.admin_session = self.app.create_user_session({
            "user_id": "admin",
            "role": "admin",
            "privileges": config.ADMIN_DEFAULT_PRIVILEGES
        })

        # Generate live agent token
        self.raw_token, self.token_meta = self.app.agent_token_manager.generate_token(
            principal="spark-agent-modern-test",
            capabilities=agent.DEFAULT_SPARK_CAPABILITIES,
            description="Modern MCP Test Agent"
        )
        self.orig_exposed = getattr(config, "MCP_EXPOSED_TOOLS", None)
        self.orig_variant = getattr(config, "MCP_SCHEMA_VARIANT", "variant_a")
        config.MCP_EXPOSED_TOOLS = None
        config.MCP_SCHEMA_VARIANT = "variant_a"

    def tearDown(self):
        config.MCP_EXPOSED_TOOLS = self.orig_exposed
        config.MCP_SCHEMA_VARIANT = self.orig_variant
        try:
            self.app.agent_token_manager.revoke_token(self.token_meta["token_id"])
        except Exception:
            pass

    def test_20_mcp_health_endpoint(self):
        resp = self.client.get("/api/mcp/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("MCP-Protocol-Version"), "2026-07-28")
        data = resp.get_json()
        self.assertEqual(data["protocol_version"], "2026-07-28")
        self.assertEqual(data["tools_count"], 43)

    def test_21_mcp_server_discover_via_http(self):
        payload = {
            "jsonrpc": "2.0",
            "id": 21,
            "method": "server/discover",
            "params": {"_meta": {"io.modelcontextprotocol/protocolVersion": "2026-07-28"}}
        }
        headers = {
            "Authorization": f"Bearer {self.raw_token}",
            "MCP-Protocol-Version": "2026-07-28",
            "Mcp-Method": "server/discover"
        }
        resp = self.client.post("/api/mcp", json=payload, headers=headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("MCP-Protocol-Version"), "2026-07-28")
        data = resp.get_json()
        self.assertEqual(data["result"]["defaultProtocolVersion"], "2026-07-28")

    def test_22_mcp_tools_list_via_http(self):
        payload = {
            "jsonrpc": "2.0",
            "id": 22,
            "method": "tools/list",
            "params": {"_meta": {"io.modelcontextprotocol/protocolVersion": "2026-07-28"}}
        }
        headers = {
            "Authorization": f"Bearer {self.raw_token}",
            "MCP-Protocol-Version": "2026-07-28",
            "Mcp-Method": "tools/list"
        }
        resp = self.client.post("/api/mcp", json=payload, headers=headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        tools = data["result"]["tools"]
        tool_names = set(t["name"] for t in tools)
        expected_tools = {
            "nexus.status", "academic.query", "academic.sync", "academic.analyze",
            "lms.query", "lms.fetch", "lms.prepare", "vault.manage",
            "document.process", "browser.interact", "action.status"
        }
        self.assertEqual(tool_names, expected_tools)


    def test_23_mcp_tools_call_nexus_status_via_http(self):
        payload = {
            "jsonrpc": "2.0",
            "id": 23,
            "method": "tools/call",
            "params": {
                "name": "nexus.status",
                "arguments": {},
                "_meta": {"io.modelcontextprotocol/protocolVersion": "2026-07-28"}
            }
        }
        headers = {
            "Authorization": f"Bearer {self.raw_token}",
            "MCP-Protocol-Version": "2026-07-28",
            "Mcp-Method": "tools/call",
            "Mcp-Name": "nexus.status"
        }
        resp = self.client.post("/api/mcp", json=payload, headers=headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertFalse(data["result"]["isError"])
        content_text = data["result"]["content"][0]["text"]
        parsed = json.loads(content_text)
        self.assertTrue(parsed["ok"])
        self.assertEqual(parsed["data"]["appliance"]["device"], "TECNO BG6")

    def test_24_mcp_header_mismatch_rejection_via_http(self):
        payload = {
            "jsonrpc": "2.0",
            "id": 24,
            "method": "tools/list",
            "params": {}
        }
        headers = {
            "Authorization": f"Bearer {self.raw_token}",
            "MCP-Protocol-Version": "2026-07-28",
            "Mcp-Method": "tools/call"  # Mismatched
        }
        resp = self.client.post("/api/mcp", json=payload, headers=headers)
        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertEqual(data["error"]["code"], -32600)

    def test_25_admin_token_provisioning_and_revocation(self):
        admin_headers = {"Authorization": f"Bearer {self.admin_session}"}
        
        # 1. Provision
        create_res = self.client.post("/api/admin/agent-tokens", json={
            "principal": "spark-ci-agent",
            "capabilities": ["nexus.status.read"],
            "description": "CI Agent"
        }, headers=admin_headers)
        self.assertEqual(create_res.status_code, 201)
        token_str = create_res.get_json()["token"]
        tok_id = create_res.get_json()["metadata"]["token_id"]

        # 2. Call with token
        call_res = self.client.post("/api/mcp", json={
            "jsonrpc": "2.0", "id": 25, "method": "tools/call",
            "params": {"name": "nexus.status", "arguments": {}}
        }, headers={
            "Authorization": f"Bearer {token_str}",
            "MCP-Protocol-Version": "2026-07-28",
            "Mcp-Method": "tools/call",
            "Mcp-Name": "nexus.status"
        })
        self.assertEqual(call_res.status_code, 200)

        # 3. Revoke
        del_res = self.client.delete("/api/admin/agent-tokens", json={"token_id": tok_id}, headers=admin_headers)
        self.assertEqual(del_res.status_code, 200)

        # 4. Verify rejected
        call_revoked = self.client.post("/api/mcp", json={
            "jsonrpc": "2.0", "id": 26, "method": "tools/call",
            "params": {"name": "nexus.status", "arguments": {}}
        }, headers={"Authorization": f"Bearer {token_str}"})
        self.assertEqual(call_revoked.status_code, 401)


if __name__ == "__main__":
    unittest.main()
