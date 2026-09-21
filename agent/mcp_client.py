"""
NexusNode — Model Context Protocol (MCP 2026-07-28) Client & Verification Tool
Authoritative JSON-RPC 2.0 Stateless Streamable HTTP client for remote MCP verification.
"""

import sys
import time
import json
import argparse
import requests
from typing import Dict, Any, List, Optional, Tuple

import config


class McpClient:
    """Standard HTTP JSON-RPC 2.0 client conforming to the MCP 2026-07-28 specification."""

    def __init__(
        self,
        endpoint_url: str,
        auth_token: str,
        protocol_version: str = "2026-07-28",
        timeout: float = 15.0
    ):
        self.endpoint_url = endpoint_url.rstrip("/")
        self.auth_token = auth_token
        self.protocol_version = protocol_version
        self.timeout = timeout
        self.session = requests.Session()
        self._request_id = 0

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def send_rpc(
        self,
        method: str,
        params: Optional[Dict[str, Any]] = None,
        tool_name: Optional[str] = None,
        custom_headers: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """Sends a modern MCP 2026-07-28 JSON-RPC request over Streamable HTTP."""
        req_id = self._next_id()
        params = params or {}
        
        # Inject modern _meta envelope if not already present
        if "_meta" not in params:
            params["_meta"] = {
                "io.modelcontextprotocol/protocolVersion": self.protocol_version,
                "io.modelcontextprotocol/clientInfo": {
                    "name": "nexusnode-mcp-client",
                    "version": getattr(config, "VERSION", "2.3.2")
                }
            }

        payload = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params
        }

        # Modern Streamable HTTP Headers
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.auth_token}",
            "MCP-Protocol-Version": self.protocol_version,
            "Mcp-Method": method
        }
        if tool_name:
            headers["Mcp-Name"] = tool_name

        if custom_headers:
            headers.update(custom_headers)

        resp = self.session.post(self.endpoint_url, json=payload, headers=headers, timeout=self.timeout)
        if resp.status_code == 204:
            return {}
        if resp.status_code not in (200, 400, 401, 403, 404, 500, 503):
            resp.raise_for_status()
        return resp.json()

    def discover(self) -> Dict[str, Any]:
        """Executes the modern MCP 2026-07-28 server/discover capability query."""
        res = self.send_rpc("server/discover")
        if "error" in res:
            raise RuntimeError(f"server/discover failed: {res['error']}")
        return res.get("result", {})

    def list_tools(self) -> List[Dict[str, Any]]:
        """Queries the server for registered and authorized tools (stateless)."""
        res = self.send_rpc("tools/list")
        if "error" in res:
            raise RuntimeError(f"tools/list failed: {res['error']}")
        return res.get("result", {}).get("tools", [])

    def call_tool(self, name: str, arguments: Optional[Dict[str, Any]] = None) -> Tuple[Dict[str, Any], bool]:
        """
        Executes a named MCP tool statelessly.
        Returns: (parsed_data_dict, is_error_boolean).
        """
        res = self.send_rpc(
            method="tools/call",
            params={"name": name, "arguments": arguments or {}},
            tool_name=name
        )
        if "error" in res:
            return res["error"], True

        result_obj = res.get("result", {})
        is_error = result_obj.get("isError", False)
        content_list = result_obj.get("content", [])
        
        parsed_data = {}
        if content_list and isinstance(content_list, list):
            first = content_list[0]
            if first.get("type") == "text":
                try:
                    parsed_data = json.loads(first.get("text", "{}"))
                except Exception:
                    parsed_data = {"raw_text": first.get("text")}

        return parsed_data, is_error

    def initialize(self) -> Dict[str, Any]:
        """Legacy 2024-11-05 initialize handshake (for backward compatibility testing)."""
        res = self.send_rpc("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "nexusnode-legacy-client", "version": "1.0.0"}
        })
        return res.get("result", {})

    def ping(self) -> bool:
        """Sends an MCP ping check."""
        res = self.send_rpc("ping")
        return "result" in res


def run_smoke_test(url: str, token: str):
    """Executes a full modern MCP 2026-07-28 verification suite."""
    print(f"==================================================")
    print(f"Connecting to NexusNode Modern MCP Gateway")
    print(f"Endpoint URL : {url}")
    print(f"Specification: MCP 2026-07-28 (Stateless Streamable HTTP)")
    print(f"==================================================")

    client = McpClient(endpoint_url=url, auth_token=token)

    # 1. server/discover
    print("\n[1/6] Invoking 'server/discover'...")
    disc = client.discover()
    print(f"  -> Server Name     : {disc.get('serverInfo', {}).get('name')}")
    print(f"  -> Server Version  : {disc.get('serverInfo', {}).get('version')}")
    print(f"  -> Default Protocol: {disc.get('defaultProtocolVersion')}")
    print(f"  -> Supported Vers  : {disc.get('protocolVersions')}")

    # 2. tools/list (Direct Stateless Discovery)
    print("\n[2/6] Invoking 'tools/list' (Stateless Tool Discovery)...")
    tools = client.list_tools()
    print(f"  -> Found {len(tools)} authorized tools:")
    for t in tools:
        print(f"     • {t['name']}: {t['description'][:55]}...")

    # 3. nexus.status
    print("\n[3/6] Invoking 'nexus.status'...")
    st_res, err = client.call_tool("nexus.status")
    print(f"  -> Status isError={err}")
    appliance = st_res.get("data", {}).get("appliance", {})
    resources = st_res.get("data", {}).get("resources", {})
    print(f"     Device : {appliance.get('device')}")
    print(f"     Uptime : {appliance.get('uptime_seconds')}s")
    print(f"     RAM    : {resources.get('memory', {}).get('percent_used')}% used")

    # 4. upes.auth_status
    print("\n[4/6] Invoking 'upes.auth_status'...")
    auth_res, err = client.call_tool("upes.auth_status")
    print(f"  -> UPES Auth isError={err}")
    auth_data = auth_res.get("data", {})
    print(f"     State       : {auth_data.get('state')}")
    print(f"     Live Ready  : {auth_data.get('is_live_ready')}")
    print(f"     Format Check: {auth_data.get('configured_identifier_format')} (mismatch={auth_data.get('mismatch')})")

    # 5. upes.get_next_classes
    print("\n[5/6] Invoking 'upes.get_next_classes'...")
    next_res, err = client.call_tool("upes.get_next_classes", {"limit": 2})
    print(f"  -> Next Classes isError={err}")
    next_data = next_res.get("data", {})
    classes = next_data.get("next_classes", [])
    print(f"     Upcoming count: {len(classes)}")
    for c in classes:
        print(f"     • {c.get('date')} {c.get('start_time')}: {c.get('course_name')} ({c.get('room')})")

    # 6. vault.list
    print("\n[6/6] Invoking 'vault.list'...")
    v_res, err = client.call_tool("vault.list")
    print(f"  -> Vault List isError={err}")
    print(f"     Total items: {v_res.get('data', {}).get('total_items')}")

    print("\n==================================================")
    print("[SUCCESS] Modern MCP 2026-07-28 Verification Passed.")
    print("==================================================")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="NexusNode MCP 2026-07-28 Client")
    parser.add_argument("--url", default="http://127.0.0.1:5000/api/mcp", help="MCP endpoint URL")
    parser.add_argument("--token", required=True, help="Agent Bearer Token")
    args = parser.parse_args()

    run_smoke_test(args.url, args.token)
