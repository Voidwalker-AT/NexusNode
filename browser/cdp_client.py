"""
NexusNode — Lightweight Pure-Python Chrome DevTools Protocol (CDP) Client
Standard library RFC 6455 WebSocket transport and HTTP target management.
No external dependencies.
"""

import os
import sys
import time
import json
import socket
import struct
import urllib.request
import urllib.error
import base64
import logging
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger("NEXUS_CDP_CLIENT")


class CDPError(Exception):
    """Raised when a CDP command returns an error object."""
    def __init__(self, message: str, code: Optional[int] = None, data: Optional[Any] = None):
        super().__init__(message)
        self.code = code
        self.data = data


class CDPConnectionError(Exception):
    """Raised when socket connectivity or handshake fails."""
    pass


class CDPTimeoutError(Exception):
    """Raised when a command fails to complete within the allotted time."""
    pass


class SimpleWebSocket:
    """
    Minimal RFC 6455 compliant WebSocket client over standard library sockets.
    Supports client-to-server masked text frames and server unmasked text/close/ping frames.
    """

    def __init__(self, ws_url: str, timeout: float = 15.0):
        self.ws_url = ws_url
        self.timeout = timeout
        self.sock: Optional[socket.socket] = None
        self._msg_id = 0
        self._connect()

    def _connect(self):
        parts = self.ws_url.replace("ws://", "").split("/", 1)
        host_port = parts[0].split(":")
        host = host_port[0]
        port = int(host_port[1]) if len(host_port) > 1 else 80
        path = "/" + parts[1] if len(parts) > 1 else "/"

        try:
            self.sock = socket.create_connection((host, port), timeout=self.timeout)
            key = base64.b64encode(os.urandom(16)).decode("ascii")
            handshake = (
                f"GET {path} HTTP/1.1\r\n"
                f"Host: {host}:{port}\r\n"
                f"Upgrade: websocket\r\n"
                f"Connection: Upgrade\r\n"
                f"Sec-WebSocket-Key: {key}\r\n"
                f"Sec-WebSocket-Version: 13\r\n\r\n"
            )
            self.sock.sendall(handshake.encode("ascii"))
            resp = b""
            while b"\r\n\r\n" not in resp:
                chunk = self.sock.recv(4096)
                if not chunk:
                    raise CDPConnectionError("WebSocket connection closed during handshake.")
                resp += chunk

            status_line = resp.split(b"\r\n")[0].decode("latin1", errors="replace")
            if "101" not in status_line:
                raise CDPConnectionError(f"WebSocket handshake failed: {status_line}")
        except Exception as e:
            self.close()
            raise CDPConnectionError(f"Failed to connect to CDP target at {self.ws_url}: {e}") from e

    def send_frame(self, text: str):
        if not self.sock:
            raise CDPConnectionError("Socket not connected.")
        data = text.encode("utf-8")
        length = len(data)
        header = bytearray([0x81])  # Fin bit set, opcode 0x1 (Text)
        mask_key = os.urandom(4)

        if length <= 125:
            header.append(0x80 | length)
        elif length <= 65535:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", length))

        masked_data = bytearray(length)
        for i in range(length):
            masked_data[i] = data[i] ^ mask_key[i % 4]

        frame = bytes(header) + mask_key + bytes(masked_data)
        self.sock.sendall(frame)

    def recv_frame(self) -> Optional[str]:
        if not self.sock:
            raise CDPConnectionError("Socket not connected.")
        header = self._recv_exact(2)
        b1, b2 = header[0], header[1]
        opcode = b1 & 0x0F
        masked = (b2 & 0x80) != 0
        payload_len = b2 & 0x7F

        if payload_len == 126:
            payload_len = struct.unpack("!H", self._recv_exact(2))[0]
        elif payload_len == 127:
            payload_len = struct.unpack("!Q", self._recv_exact(8))[0]

        mask_key = self._recv_exact(4) if masked else None
        data = self._recv_exact(payload_len)

        if masked and mask_key:
            unmasked = bytearray(payload_len)
            for i in range(payload_len):
                unmasked[i] = data[i] ^ mask_key[i % 4]
            data = bytes(unmasked)

        if opcode == 0x8:  # Connection close
            return None
        elif opcode == 0x9:  # Ping -> reply with Pong (0xA)
            pong = bytearray([0x8A, 0x00])
            self.sock.sendall(pong)
            return self.recv_frame()
        elif opcode == 0x1:  # Text frame
            return data.decode("utf-8", errors="replace")
        return None

    def _recv_exact(self, n: int) -> bytes:
        buf = bytearray()
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise CDPConnectionError("Socket closed prematurely during read.")
            buf.extend(chunk)
        return bytes(buf)

    def close(self):
        if self.sock:
            try:
                # Send close frame
                close_frame = bytearray([0x88, 0x80]) + os.urandom(4)
                self.sock.sendall(close_frame)
            except Exception:
                pass
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None


class CDPClient:
    """
    High-level CDP Client managing WebSocket connection, request/response tracking,
    and HTTP target enumeration.
    """

    def __init__(self, ws_url: str, timeout: float = 15.0):
        self.ws_url = ws_url
        self.timeout = timeout
        self.ws = SimpleWebSocket(ws_url, timeout=timeout)
        self._req_id = 0

    def call(self, method: str, params: Optional[Dict[str, Any]] = None, timeout: Optional[float] = None) -> Dict[str, Any]:
        """
        Sends a synchronous CDP request and awaits the matching response.
        Ignores asynchronous CDP events that arrive while waiting for the response ID.
        """
        self._req_id += 1
        mid = self._req_id
        req: Dict[str, Any] = {"id": mid, "method": method}
        if params is not None:
            req["params"] = params

        call_timeout = timeout or self.timeout
        self.ws.send_frame(json.dumps(req))

        start_t = time.time()
        while time.time() - start_t < call_timeout:
            raw = self.ws.recv_frame()
            if raw is None:
                raise CDPConnectionError(f"CDP connection closed while awaiting response for {method} (id={mid})")
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                continue

            if payload.get("id") == mid:
                if "error" in payload:
                    err = payload["error"]
                    raise CDPError(
                        f"CDP error in {method}: {err.get('message', 'Unknown error')}",
                        code=err.get("code"),
                        data=err.get("data")
                    )
                return payload.get("result", {})

        raise CDPTimeoutError(f"CDP call '{method}' (id={mid}) timed out after {call_timeout} seconds.")

    def close(self):
        if self.ws:
            self.ws.close()


# ==============================================================================
# HTTP Target Management & Target Filtering Helpers
# ==============================================================================

def get_browser_version(port: int = 9222, timeout: float = 2.0) -> Dict[str, Any]:
    """Retrieves browser version info from http://127.0.0.1:{port}/json/version."""
    url = f"http://127.0.0.1:{port}/json/version"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def list_browser_targets(port: int = 9222, timeout: float = 2.0) -> List[Dict[str, Any]]:
    """Retrieves target list from http://127.0.0.1:{port}/json/list."""
    url = f"http://127.0.0.1:{port}/json/list"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def create_new_target(port: int = 9222, url: str = "about:blank", timeout: float = 2.0) -> Dict[str, Any]:
    """Creates a new page target via http://127.0.0.1:{port}/json/new (using PUT verb)."""
    target_url = f"http://127.0.0.1:{port}/json/new?{urllib.parse.quote(url)}"
    try:
        req = urllib.request.Request(target_url, method="PUT")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as he:
        if he.code == 405:
            req = urllib.request.Request(target_url, method="GET")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        raise


def close_browser_target(port: int = 9222, target_id: str = "", timeout: float = 2.0) -> bool:
    """Closes target via http://127.0.0.1:{port}/json/close/{target_id} (using PUT/GET)."""
    url = f"http://127.0.0.1:{port}/json/close/{target_id}"
    try:
        req = urllib.request.Request(url, method="PUT")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except urllib.error.HTTPError as he:
        if he.code == 405:
            try:
                req = urllib.request.Request(url, method="GET")
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return resp.status == 200
            except Exception:
                return False
        return False
    except Exception:
        return False


def select_page_target(targets: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    CRITICAL REGRESSION FILTER (Phase 4.1A / 4.1B):
    Strictly selects the actual browser page target.
    Rejects:
      - background extension pages (e.g. chrome-extension://...)
      - devtools internal targets (devtools://...)
      - chrome internal targets (chrome://...)
      - non-page targets (type != "page")
    """
    for tgt in targets:
        t_type = tgt.get("type", "")
        t_url = tgt.get("url", "")

        # Must be type "page"
        if t_type != "page":
            continue

        # Reject extension and internal schemes
        if (
            t_url.startswith("chrome-extension://")
            or t_url.startswith("devtools://")
            or t_url.startswith("chrome://")
            or t_url.startswith("edge://")
        ):
            continue

        return tgt

    return None
