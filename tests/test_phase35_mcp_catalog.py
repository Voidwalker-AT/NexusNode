"""
Unit and Integration Tests for Phase 3.5 MCP Tool Catalog & Server Adapter
"""

import os
import unittest
from agent.mcp_server import MCP_TOOL_DEFINITIONS, McpServerAdapter
from agent.mcp_auth import DEFAULT_SPARK_CAPABILITIES, AgentTokenManager
from agent.registry import AgentOperationRegistry
from agent.policy import PolicyEngine


class TestMCPCatalogPhase35(unittest.TestCase):

    def test_mcp_exact_tool_count(self):
        # Baseline (27) + Phase 3.5 Tools (14) + Phase 3.6A Tools (2: lms.submit_assignment, action.status) = 43 Total Tools
        self.assertEqual(len(MCP_TOOL_DEFINITIONS), 43)


    def test_mcp_tools_schema_validity(self):
        tool_names = set()
        for tool in MCP_TOOL_DEFINITIONS:
            name = tool["name"]
            self.assertNotIn(name, tool_names, f"Duplicate tool name '{name}'")
            tool_names.add(name)

            self.assertIn("description", tool)
            self.assertIn("inputSchema", tool)
            self.assertIn("required_capability", tool)

            schema = tool["inputSchema"]
            self.assertEqual(schema.get("$schema"), "https://json-schema.org/draft/2020-12/schema")
            self.assertEqual(schema.get("type"), "object")
            self.assertFalse(schema.get("additionalProperties", True))

    def test_all_tools_covered_by_default_spark_capabilities(self):
        spark_caps = set(DEFAULT_SPARK_CAPABILITIES)
        for tool in MCP_TOOL_DEFINITIONS:
            req_cap = tool["required_capability"]
            self.assertIn(
                req_cap,
                spark_caps,
                f"Tool '{tool['name']}' required capability '{req_cap}' missing from DEFAULT_SPARK_CAPABILITIES"
            )


if __name__ == "__main__":
    unittest.main()
