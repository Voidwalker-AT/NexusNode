#!/usr/bin/env python3
"""
NexusNode — Phase 4.4B Black-Box Production MCP Acceptance Suite
Executes end-to-end black-box MCP testing over the public internet tunnel:
https://k09oezeyib.localto.net/api/mcp
"""

import os
import sys
import time
import json
import base64
import hashlib
import secrets
import threading
import concurrent.futures
from typing import Dict, Any, List, Optional, Tuple
import requests
import paramiko

BASE_PUBLIC = "https://k09oezeyib.localto.net"
HEADERS_SKIP = {"localtonet-skip-warning": "true"}
BG6_HOST = "192.168.29.21"
BG6_PORT = 8022
BG6_USER = "u0_a208"
BG6_PASS = "anmol2005"

def get_bg6_ssh() -> paramiko.SSHClient:
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(BG6_HOST, port=BG6_PORT, username=BG6_USER, password=BG6_PASS, timeout=10)
    return ssh

def get_bg6_chromium_count() -> int:
    ssh = get_bg6_ssh()
    stdin, stdout, stderr = ssh.exec_command("pgrep -c chromium || echo 0")
    out = stdout.read().decode().strip()
    ssh.close()
    try:
        lines = [l for l in out.splitlines() if l.strip().isdigit()]
        return int(lines[-1]) if lines else 0
    except Exception:
        return 0

def get_bg6_memory() -> Dict[str, float]:
    ssh = get_bg6_ssh()
    stdin, stdout, stderr = ssh.exec_command("cat /proc/meminfo | grep -E 'MemAvailable|MemTotal'")
    out = stdout.read().decode().strip()
    stdin2, stdout2, stderr2 = ssh.exec_command("ps -o rss,cmd -C python3 | grep server | awk '{print $1}' || echo 0")
    rss_out = stdout2.read().decode().strip()
    ssh.close()
    mem = {}
    for line in out.splitlines():
        parts = line.split(":")
        if len(parts) == 2:
            key = parts[0].strip()
            val_kb = float(parts[1].replace("kB", "").strip())
            mem[key] = round(val_kb / 1024.0, 1)
    try:
        rss_kb = float(rss_out.splitlines()[0]) if rss_out else 0.0
        mem["NexusNodeRSS"] = round(rss_kb / 1024.0, 1)
    except Exception:
        mem["NexusNodeRSS"] = 0.0
    return mem

class McpPublicClient:
    """External black-box MCP client communicating solely over public HTTPS."""

    def __init__(self, base_url: str = BASE_PUBLIC, bearer_token: Optional[str] = None):
        self.base_url = base_url.rstrip('/')
        self.endpoint = f"{self.base_url}/api/mcp"
        self.token = bearer_token
        self.protocol_version = "2024-11-05"
        self.session = requests.Session()
        self.session.headers.update(HEADERS_SKIP)

    def set_token(self, token: str):
        self.token = token

    def _headers(self, extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        h = dict(HEADERS_SKIP)
        h["Content-Type"] = "application/json"
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        if extra:
            h.update(extra)
        return h

    def call_raw(self, payload: Dict[str, Any], extra_headers: Optional[Dict[str, str]] = None, timeout: int = 15) -> Tuple[requests.Response, float]:
        t0 = time.time()
        resp = self.session.post(self.endpoint, headers=self._headers(extra_headers), json=payload, timeout=timeout)
        lat_ms = round((time.time() - t0) * 1000, 2)
        return resp, lat_ms

    def initialize(self, protocol_version: str = "2024-11-05", client_name: str = "ExternalMcpAcceptanceClient") -> Tuple[Dict[str, Any], float]:
        req = {
            "jsonrpc": "2.0",
            "id": f"init-{int(time.time()*1000)}",
            "method": "initialize",
            "params": {
                "protocolVersion": protocol_version,
                "clientInfo": {"name": client_name, "version": "1.0"},
                "capabilities": {}
            }
        }
        resp, lat = self.call_raw(req)
        assert resp.status_code == 200, f"initialize failed: HTTP {resp.status_code} - {resp.text}"
        data = resp.json()
        self.protocol_version = data.get("result", {}).get("protocolVersion", protocol_version)
        return data, lat

    def initialized_notification(self) -> int:
        req = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
            "params": {}
        }
        resp, _ = self.call_raw(req)
        return resp.status_code

    def list_tools(self, extra_headers: Optional[Dict[str, str]] = None) -> Tuple[List[Dict[str, Any]], float]:
        req = {
            "jsonrpc": "2.0",
            "id": f"list-{int(time.time()*1000)}",
            "method": "tools/list",
            "params": {}
        }
        resp, lat = self.call_raw(req, extra_headers=extra_headers)
        assert resp.status_code == 200, f"tools/list failed: HTTP {resp.status_code} - {resp.text}"
        data = resp.json()
        return data.get("result", {}).get("tools", []), lat

    def call_tool(self, name: str, arguments: Optional[Dict[str, Any]] = None, timeout: int = 30) -> Tuple[Dict[str, Any], float]:
        req = {
            "jsonrpc": "2.0",
            "id": f"call-{name}-{int(time.time()*1000)}",
            "method": "tools/call",
            "params": {
                "name": name,
                "arguments": arguments or {}
            }
        }
        resp, lat = self.call_raw(req, timeout=timeout)
        assert resp.status_code == 200, f"tools/call {name} failed: HTTP {resp.status_code} - {resp.text}"
        res = resp.json()
        result_obj = res.get("result", {})
        content = result_obj.get("content", [])
        text_str = content[0].get("text", "") if content else ""
        try:
            parsed = json.loads(text_str) if text_str.startswith("{") else text_str
        except Exception:
            parsed = text_str
        return {
            "raw_result": result_obj,
            "parsed": parsed,
            "isError": result_obj.get("isError", False)
        }, lat

if __name__ == "__main__":
    print("McpPublicClient module defined.")
