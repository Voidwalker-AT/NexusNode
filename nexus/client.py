"""
NexusNode CLI — Authoritative Remote HTTPS REST Client
Communicates exclusively over HTTPS using Python standard library (urllib.request).
Enforces TLS verification, session token injection, error handling, and streaming.
"""

import os
import sys
import ssl
import json
import socket
import urllib.request
import urllib.error
import urllib.parse
from pathlib import Path

from . import config
from . import output


class NexusError(Exception):
    """Base exception for NexusNode CLI client operations."""
    pass


class NexusConnectionError(NexusError):
    """Raised when unable to reach the NexusNode server (DNS, connection, timeout)."""
    pass


class NexusAuthError(NexusError):
    """Raised on authentication failures (401 Unauthorized, 429 Locked)."""
    pass


class NexusPermissionError(NexusError):
    """Raised on authorization failures (403 Forbidden)."""
    pass


class NexusClient:
    """
    Authoritative HTTP/HTTPS client for NexusNode backend API.
    Zero external dependencies; uses urllib.request with standard TLS verification.
    """

    def __init__(self, server_url: str = None, token: str = None):
        self.server_url = (server_url or config.resolve_server_url() or "").rstrip("/")
        self.token = token
        if not self.token:
            session = config.load_session()
            if session:
                self.token = session.get("token")

        # Standard secure TLS context
        self.ssl_context = ssl.create_default_context()

    def set_token(self, token: str):
        """Sets active session token."""
        self.token = token

    def build_url(self, path: str, params: dict = None) -> str:
        """Constructs full absolute URL with optional query parameters."""
        clean_path = "/" + path.lstrip("/")
        base = f"{self.server_url}{clean_path}"
        if params:
            clean_params = {k: v for k, v in params.items() if v is not None}
            if clean_params:
                base += "?" + urllib.parse.urlencode(clean_params)
        return base

    def probe_handshake(self, timeout: int = 5) -> dict:
        """
        Lightweight non-blocking handshake probe that verifies DNS resolution, TLS,
        measures round-trip latency, and retrieves basic server identity.
        """
        if not self.server_url:
            return {"ok": False, "error": "Server URL not configured."}

        import time
        t0 = time.perf_counter()

        # Step 1: Health probe
        try:
            status_code, resp = self.get("/api/health", timeout=timeout)
            latency_ms = int((time.perf_counter() - t0) * 1000)

            if isinstance(resp, dict) and resp.get("_is_html"):
                return {
                    "ok": False,
                    "is_html": True,
                    "error": resp.get("message", "Received HTML from endpoint."),
                    "latency_ms": latency_ms
                }

            if status_code == 200 and isinstance(resp, dict):
                # Retrieve additional system status metadata if quickly available
                srv_name = resp.get("service", resp.get("name", "NexusNode Mobile Appliance"))
                version = resp.get("version", "2.3.2")
                device = resp.get("device", "TECNO BG6")
                status = (resp.get("status") or "HEALTHY").upper()

                return {
                    "ok": True,
                    "name": srv_name,
                    "version": version,
                    "device": device,
                    "status": status,
                    "latency_ms": latency_ms
                }

            return {
                "ok": False,
                "error": f"Health check returned HTTP {status_code}",
                "latency_ms": latency_ms
            }

        except NexusConnectionError as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:
            return {"ok": False, "error": f"Handshake failed: {e}"}

    def request(self, method: str, path: str, data: dict = None, params: dict = None, timeout: int = 30) -> tuple[int, any]:
        """
        Executes an HTTP request against the NexusNode server and returns (status_code, response_data).
        """
        if not self.server_url:
            raise NexusConnectionError("Server URL is not set. Use 'nexus connect <url>' or --server.")

        url = self.build_url(path, params)
        headers = {
            "User-Agent": "NexusNode-CLI/2.3.2",
            "Accept": "application/json"
        }

        # Apply LocalToNet skip warning header only if targeting a LocalToNet endpoint
        if "localto.net" in self.server_url.lower() or "localtonet-skip-warning" in self.server_url.lower():
            headers["localtonet-skip-warning"] = "true"

        # Attach active session token if present
        if self.token:
            headers["X-Session-Token"] = self.token
            headers["Authorization"] = f"Bearer {self.token}"

        body_bytes = None
        if data is not None:
            headers["Content-Type"] = "application/json; charset=utf-8"
            body_bytes = json.dumps(data).encode("utf-8")

        req = urllib.request.Request(url, data=body_bytes, headers=headers, method=method.upper())

        try:
            with urllib.request.urlopen(req, timeout=timeout, context=self.ssl_context) as resp:
                status_code = resp.getcode()
                raw_data = resp.read()
                content_type = resp.headers.get("Content-Type", "").lower()

                # Detect HTML response body
                is_html = "text/html" in content_type or raw_data.lstrip().startswith(b"<!DOCTYPE") or raw_data.lstrip().startswith(b"<html")
                if is_html:
                    raw_text = raw_data.decode("utf-8", errors="replace")
                    is_waf = "localtonet" in raw_text.lower() or "waf" in raw_text.lower()
                    return status_code, {
                        "_is_html": True,
                        "_is_waf": is_waf,
                        "error": "html_response",
                        "message": "LocalToNet WAF/Tunnel returned HTML instead of NexusNode API JSON." if is_waf else "NexusNode API expected JSON but received HTML. This may indicate a tunnel/WAF/gateway or wrong URL.",
                        "preview": raw_text[:250]
                    }

                try:
                    parsed = json.loads(raw_data.decode("utf-8"))
                    return status_code, parsed
                except Exception:
                    raw_text = raw_data.decode("utf-8", errors="replace")
                    return status_code, {
                        "_is_html": "<html" in raw_text.lower(),
                        "error": "non_json_response",
                        "message": raw_text[:250]
                    }

        except urllib.error.HTTPError as e:
            status_code = e.code
            raw_err = e.read()
            content_type = e.headers.get("Content-Type", "").lower() if e.headers else ""
            is_html = "text/html" in content_type or raw_err.lstrip().startswith(b"<!DOCTYPE") or raw_err.lstrip().startswith(b"<html")

            if is_html:
                raw_text = raw_err.decode("utf-8", errors="replace")
                is_waf = "localtonet" in raw_text.lower() or "waf" in raw_text.lower()
                err_json = {
                    "_is_html": True,
                    "_is_waf": is_waf,
                    "error": "html_response",
                    "message": "LocalToNet WAF/Tunnel returned HTML error page." if is_waf else "NexusNode API expected JSON but received HTML error page.",
                    "preview": raw_text[:250]
                }
            else:
                try:
                    err_json = json.loads(raw_err.decode("utf-8"))
                except Exception:
                    err_json = {"error": raw_err.decode("utf-8", errors="replace") or e.reason}

            # 401 Unauthorized -> session expired / invalid
            if status_code == 401:
                if path != "/api/auth/login":
                    config.clear_session()
                return 401, err_json

            # 403 Forbidden -> permission denied
            if status_code == 403:
                return 403, err_json

            # 429 Too Many Requests -> lockout
            if status_code == 429:
                return 429, err_json

            return status_code, err_json

        except (urllib.error.URLError, socket.timeout, ConnectionError, ssl.SSLError) as e:
            err_msg = str(e)
            if isinstance(e, urllib.error.URLError) and hasattr(e, "reason"):
                err_msg = str(e.reason)
            raise NexusConnectionError(f"Unable to reach NexusNode server at '{self.server_url}': {err_msg}")

    def get(self, path: str, params: dict = None, timeout: int = 30) -> tuple[int, any]:
        return self.request("GET", path, params=params, timeout=timeout)

    def post(self, path: str, data: dict = None, timeout: int = 30) -> tuple[int, any]:
        return self.request("POST", path, data=data, timeout=timeout)

    def delete(self, path: str, params: dict = None, timeout: int = 30) -> tuple[int, any]:
        return self.request("DELETE", path, params=params, timeout=timeout)

    def stream_post(self, path: str, data: dict = None, on_chunk: callable = None, timeout: int = 120):
        """
        Executes a POST request and streams text chunks line by line (used for /chat/stream and /api/logs/stream).
        """
        if not self.server_url:
            raise NexusConnectionError("Server URL is not set. Use --server or run 'nexus login'.")

        url = self.build_url(path)
        headers = {
            "User-Agent": "NexusNode-CLI/1.0",
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "text/event-stream, text/plain, application/json"
        }
        if self.token:
            headers["X-Session-Token"] = self.token
            headers["Authorization"] = f"Bearer {self.token}"

        body_bytes = json.dumps(data or {}).encode("utf-8")
        req = urllib.request.Request(url, data=body_bytes, headers=headers, method="POST")

        try:
            with urllib.request.urlopen(req, timeout=timeout, context=self.ssl_context) as resp:
                for line in resp:
                    if line:
                        chunk_str = line.decode("utf-8", errors="replace")
                        if on_chunk:
                            on_chunk(chunk_str)
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", errors="replace")
            raise NexusError(f"HTTP {e.code}: {raw}")
        except Exception as e:
            raise NexusConnectionError(f"Streaming error: {e}")

    def download_file(self, path: str, dest_file: Path | str, timeout: int = 120) -> bool:
        """Downloads a remote file path to a local destination file path."""
        url = self.build_url(path)
        headers = {"User-Agent": "NexusNode-CLI/1.0"}
        if self.token:
            headers["X-Session-Token"] = self.token
            headers["Authorization"] = f"Bearer {self.token}"

        req = urllib.request.Request(url, headers=headers, method="GET")
        dest_p = Path(dest_file)
        dest_p.parent.mkdir(parents=True, exist_ok=True)

        try:
            with urllib.request.urlopen(req, timeout=timeout, context=self.ssl_context) as resp:
                with open(dest_p, "wb") as f:
                    while True:
                        chunk = resp.read(65536)
                        if not chunk:
                            break
                        f.write(chunk)
            return True
        except urllib.error.HTTPError as e:
            raise NexusError(f"HTTP {e.code}: Failed to download file.")
        except Exception as e:
            raise NexusConnectionError(f"Failed to download file: {e}")
