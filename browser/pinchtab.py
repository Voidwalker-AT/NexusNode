"""
NexusNode — PinchTab Browser Provider Implementation
Lightweight HTTP client communicating with an external or remote PinchTab server (v0.15.2+).
Preserves TECNO BG6 RAM stability by delegating heavy Chromium rendering to a remote browser worker.
"""

import time
import json
import logging
import urllib.request
import urllib.error
from typing import Dict, Any, List, Optional

import config
from .base import (
    BrowserProvider,
    BrowserSession,
    BrowserSnapshot,
    BrowserCapture,
    BrowserDownload,
    BrowserElement,
)
from agent.errors import (
    BrowserUnavailableError,
    BrowserConnectionError,
    BrowserSessionError,
    NavigationFailedError,
    ElementStaleError,
    UploadFailedError,
    DownloadFailedError,
    SecurityChallengeError,
    InternalError,
)

logger = logging.getLogger("NEXUS_PINCHTAB")


class PinchTabProvider(BrowserProvider):
    """
    Client adapter for PinchTab AI agent browser daemon.
    Communicates via PinchTab's REST API on configured base URL (default http://127.0.0.1:9867).
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        auth_token: Optional[str] = None,
        timeout: float = 20.0,
        enabled: bool = True
    ):
        self.base_url = (base_url or getattr(config, "PINCHTAB_BASE_URL", "http://127.0.0.1:9867")).rstrip("/")
        # Load token from config or pinchtab config file if not directly provided
        self._auth_token = auth_token or getattr(config, "PINCHTAB_TOKEN", None)
        if not self._auth_token:
            import os
            try:
                cfg_path = os.path.expandvars(r"%APPDATA%\pinchtab\config.json")
                if os.path.exists(cfg_path):
                    with open(cfg_path, "r") as f:
                        pt_cfg = json.load(f)
                        self._auth_token = pt_cfg.get("server", {}).get("token")
            except Exception:
                pass

        self.timeout = timeout
        self.enabled = enabled
        self._sessions: Dict[str, BrowserSession] = {}
        # Mapping session_id -> tab_id
        self._tab_map: Dict[str, str] = {}

    @property
    def provider_name(self) -> str:
        return "pinchtab"

    def _request(
        self,
        endpoint: str,
        method: str = "GET",
        payload: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Executes an authenticated HTTP request to the PinchTab server.
        Never logs or leaks the auth token or request secrets.
        """
        if not self.enabled:
            raise BrowserUnavailableError("PinchTab provider is currently disabled in configuration.")

        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self._auth_token:
            headers["Authorization"] = f"Bearer {self._auth_token}"

        req_timeout = timeout or self.timeout
        data_bytes = json.dumps(payload).encode("utf-8") if payload is not None else None

        try:
            req = urllib.request.Request(url, data=data_bytes, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=req_timeout) as resp:
                status = resp.status
                raw = resp.read().decode("utf-8", errors="replace")
                if not raw:
                    return {"status": status}
                try:
                    return json.loads(raw)
                except Exception:
                    return {"raw_text": raw, "status": status}

        except urllib.error.HTTPError as he:
            status_code = he.code
            err_text = ""
            try:
                err_text = he.read().decode("utf-8", errors="ignore")
            except Exception:
                pass

            if status_code in (401, 403):
                raise BrowserConnectionError("PinchTab server rejected authentication credentials.")
            elif status_code == 404:
                if "element" in err_text.lower() or "stale" in err_text.lower() or "not found" in err_text.lower():
                    raise ElementStaleError(f"PinchTab element or tab reference is stale: {err_text}")
                raise BrowserSessionError(f"PinchTab resource not found: {err_text}")
            elif status_code == 429 or "challenge" in err_text.lower() or "turnstile" in err_text.lower():
                raise SecurityChallengeError(f"PinchTab encountered a bot-detection or CAPTCHA challenge: {err_text}")
            else:
                raise BrowserSessionError(f"PinchTab HTTP {status_code} error: {err_text[:200]}")

        except urllib.error.URLError as ue:
            raise BrowserUnavailableError(f"Cannot connect to PinchTab server at {self.base_url}: {ue.reason}")
        except TimeoutError:
            raise BrowserConnectionError(f"PinchTab request timed out after {req_timeout}s.")
        except Exception as ex:
            if isinstance(ex, (BrowserUnavailableError, BrowserConnectionError, BrowserSessionError, ElementStaleError, SecurityChallengeError)):
                raise
            raise BrowserConnectionError(f"Unexpected error communicating with PinchTab: {str(ex)}")

    def get_health(self) -> Dict[str, Any]:
        """Checks connectivity and returns PinchTab health status."""
        try:
            res = self._request("health", method="GET", timeout=4.0)
            return {
                "provider": "pinchtab",
                "status": "healthy",
                "base_url": self.base_url,
                "version": res.get("version", "unknown"),
                "active_sessions": len(self._sessions),
                "instances": res.get("instances", 0),
                "details": res
            }
        except Exception as e:
            return {
                "provider": "pinchtab",
                "status": "unavailable",
                "base_url": self.base_url,
                "error": str(e)
            }

    def _get_or_create_instance(self, profile_name: Optional[str] = None) -> str:
        """Retrieves an active instance ID or launches a new instance for the profile."""
        insts = self._request("instances", method="GET")
        if isinstance(insts, list) and len(insts) > 0:
            return insts[0]["id"]
        # Fallback to start instance
        res = self._request("instances/start", method="POST", payload={"profile": profile_name or "default", "mode": "headless"})
        return res.get("id") or res.get("instanceId") or "inst_default"

    def create_session(self, session_id: str, profile_name: Optional[str] = None, user_id: Optional[str] = None) -> BrowserSession:
        """Allocates an isolated browser session context and tab."""
        try:
            inst_id = self._get_or_create_instance(profile_name=profile_name)
            # Open a new tab in the instance
            open_res = self._request(f"instances/{inst_id}/tabs/open", method="POST", payload={"url": "about:blank"})
            tab_id = open_res.get("tabId") or open_res.get("id")
            if not tab_id:
                raise BrowserSessionError(f"Failed to open tab in PinchTab instance {inst_id}: {open_res}")

            self._tab_map[session_id] = tab_id
            session = BrowserSession(
                session_id=session_id,
                profile_name=profile_name or "default",
                active_tab_id=tab_id,
                metadata={"instance_id": inst_id, "tab_id": tab_id}
            )
            self._sessions[session_id] = session
            return session
        except Exception as e:
            if isinstance(e, (BrowserUnavailableError, BrowserConnectionError, BrowserSessionError)):
                raise
            raise BrowserSessionError(f"Failed to allocate PinchTab session: {str(e)}")

    def close_session(self, session_id: str) -> bool:
        """Terminates tab session and frees worker memory."""
        tab_id = self._tab_map.pop(session_id, None)
        self._sessions.pop(session_id, None)
        if tab_id:
            try:
                self._request(f"tabs/{tab_id}/close", method="POST")
            except Exception:
                pass
        return True

    def _get_tab_id(self, session_id: str) -> str:
        tab_id = self._tab_map.get(session_id)
        if not tab_id:
            session = self._sessions.get(session_id)
            if session and session.active_tab_id:
                return session.active_tab_id
            return session_id
        return tab_id

    def navigate(self, session_id: str, url: str, wait_until: str = "load") -> Dict[str, Any]:
        """Navigates to URL and waits for page readiness."""
        tab_id = self._get_tab_id(session_id)
        try:
            res = self._request(f"tabs/{tab_id}/navigate", method="POST", payload={"url": url})
            return {"status": "ok", "url": url, "details": res}
        except SecurityChallengeError:
            raise
        except Exception as e:
            if isinstance(e, (BrowserUnavailableError, BrowserConnectionError, SecurityChallengeError, ElementStaleError)):
                raise
            raise NavigationFailedError(f"Failed to navigate to '{url}': {str(e)}")

    def snapshot(self, session_id: str, include_screenshot: bool = False) -> BrowserSnapshot:
        """Extracts structured accessibility tree snapshot with stable numeric element refs."""
        tab_id = self._get_tab_id(session_id)
        try:
            res = self._request(f"tabs/{tab_id}/snapshot?filter=interactive", method="GET")
            nodes = res.get("nodes", [])
            title = res.get("title", "")
            url = res.get("url", "")

            # Build readable tree text & element map
            tree_lines = []
            element_map = {}
            for n in nodes:
                ref = n.get("ref") or f"e{n.get('nodeId', 0)}"
                role = n.get("role", "element")
                tag = n.get("tag", "")
                text = n.get("text") or n.get("name") or ""
                desc = f"[{ref}] <{tag or role}> {text}".strip()
                tree_lines.append(desc)
                element_map[ref] = {
                    "ref": ref,
                    "role": role,
                    "tag": tag,
                    "text": text,
                    "name": n.get("name", "")
                }

            tree_text = "\n".join(tree_lines) if tree_lines else f"Title: {title}\nURL: {url}\n(No interactive nodes found)"
            token_est = max(10, len(tree_text) // 4)

            screenshot_b64 = None
            if include_screenshot:
                try:
                    cap = self.capture(session_id)
                    screenshot_b64 = cap.screenshot_base64
                except Exception:
                    pass

            return BrowserSnapshot(
                url=url,
                title=title,
                tree_text=tree_text,
                element_map=element_map,
                screenshot_base64=screenshot_b64,
                token_estimate=token_est
            )
        except Exception as e:
            if isinstance(e, (BrowserUnavailableError, BrowserConnectionError, SecurityChallengeError, ElementStaleError)):
                raise
            raise BrowserSessionError(f"Failed to capture accessibility snapshot: {str(e)}")

    def capture(self, session_id: str, full_page: bool = False) -> BrowserCapture:
        """Captures page screenshot."""
        tab_id = self._get_tab_id(session_id)
        try:
            res = self._request(f"tabs/{tab_id}/capture", method="GET")
            img_b64 = res.get("image") or res.get("data") or res.get("screenshot", "")
            if isinstance(img_b64, dict):
                img_b64 = img_b64.get("data", "")
            captured_at_val = res.get("capturedAt")
            ts = time.time()
            if isinstance(captured_at_val, (int, float)):
                ts = float(captured_at_val)
            elif isinstance(captured_at_val, str):
                try:
                    from datetime import datetime
                    ts = datetime.fromisoformat(captured_at_val.replace("Z", "+00:00")).timestamp()
                except Exception:
                    ts = time.time()

            return BrowserCapture(
                url=res.get("url", ""),
                screenshot_base64=str(img_b64),
                format="png",
                width=res.get("width", 1280),
                height=res.get("height", 800),
                timestamp=ts
            )
        except Exception as e:
            if isinstance(e, (BrowserUnavailableError, BrowserConnectionError, ElementStaleError)):
                raise
            raise BrowserSessionError(f"Failed to capture screenshot: {str(e)}")

    def click(self, session_id: str, element_ref: str) -> Dict[str, Any]:
        """Clicks an element referenced by stable ID (e.g. 'e1')."""
        tab_id = self._get_tab_id(session_id)
        payload = {"kind": "click", "ref": element_ref}
        try:
            res = self._request(f"tabs/{tab_id}/action", method="POST", payload=payload)
            return {"status": "ok", "element": element_ref, "details": res}
        except Exception as e:
            if isinstance(e, (BrowserUnavailableError, BrowserConnectionError, ElementStaleError, SecurityChallengeError)):
                raise
            raise ElementStaleError(f"Failed to click element '{element_ref}': {str(e)}")

    def type_text(self, session_id: str, element_ref: str, text: str, submit: bool = False) -> Dict[str, Any]:
        """Types text into an input element."""
        tab_id = self._get_tab_id(session_id)
        payload = {"kind": "fill", "ref": element_ref, "text": text}
        try:
            res = self._request(f"tabs/{tab_id}/action", method="POST", payload=payload)
            return {"status": "ok", "element": element_ref, "details": res}
        except Exception as e:
            if isinstance(e, (BrowserUnavailableError, BrowserConnectionError, ElementStaleError)):
                raise
            raise ElementStaleError(f"Failed to type into element '{element_ref}': {str(e)}")

    def press(self, session_id: str, key: str) -> Dict[str, Any]:
        """Sends keyboard key event."""
        tab_id = self._get_tab_id(session_id)
        payload = {"kind": "press", "key": key}
        try:
            res = self._request(f"tabs/{tab_id}/action", method="POST", payload=payload)
            return {"status": "ok", "key": key, "details": res}
        except Exception as e:
            if isinstance(e, (BrowserUnavailableError, BrowserConnectionError)):
                raise
            raise BrowserSessionError(f"Failed to press key '{key}': {str(e)}")

    def upload_file(self, session_id: str, element_ref: str, file_path: str) -> Dict[str, Any]:
        """Attaches file to file input element."""
        tab_id = self._get_tab_id(session_id)
        payload = {
            "kind": "upload",
            "ref": element_ref,
            "files": [file_path]
        }
        try:
            res = self._request(f"tabs/{tab_id}/action", method="POST", payload=payload)
            return {"status": "ok", "element": element_ref, "file_path": file_path, "details": res}
        except Exception as e:
            if isinstance(e, (BrowserUnavailableError, BrowserConnectionError, ElementStaleError)):
                raise
            raise UploadFailedError(f"Failed to upload file to element '{element_ref}': {str(e)}")

    def download_file(self, session_id: str, element_ref: str, target_dir: str) -> BrowserDownload:
        """Triggers element download action."""
        tab_id = self._get_tab_id(session_id)
        payload = {
            "kind": "download",
            "ref": element_ref
        }
        try:
            res = self._request(f"tabs/{tab_id}/action", method="POST", payload=payload)
            return BrowserDownload(
                file_name=res.get("fileName", "downloaded_document.pdf"),
                file_path=res.get("filePath", ""),
                size_bytes=res.get("sizeBytes", 0),
                content_type=res.get("contentType", "application/pdf")
            )
        except Exception as e:
            if isinstance(e, (BrowserUnavailableError, BrowserConnectionError, ElementStaleError)):
                raise
            raise DownloadFailedError(f"Failed to trigger download from element '{element_ref}': {str(e)}")

    def get_cookies(self, session_id: str, domain: Optional[str] = None) -> List[Dict[str, Any]]:
        """Retrieves session cookies."""
        tab_id = self._get_tab_id(session_id)
        try:
            res = self._request(f"tabs/{tab_id}/cookies", method="GET")
            return res.get("cookies", []) if isinstance(res, dict) else []
        except Exception:
            return []
