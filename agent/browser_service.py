"""
NexusNode — Agent Browser Semantic Service
Coordinates browser session lifecycles, domain allowlisting, SSRF prevention,
consequential action guards, paired snapshot+screenshot artifacts, and safe transfer pipelines.
"""

import os
import re
import time
import uuid
import base64
import hashlib
import ipaddress
import urllib.parse
import logging
from typing import Dict, Any, List, Optional, Tuple, Set

import config
from browser.base import BrowserProvider, BrowserSession, BrowserSnapshot, BrowserCapture, BrowserDownload
from .errors import (
    NexusAgentError,
    BrowserUnavailableError,
    BrowserConnectionError,
    BrowserSessionError,
    NavigationFailedError,
    ElementStaleError,
    SecurityChallengeError,
    ConsequentialActionBlockedError,
    InvalidParamsError,
    AccessDeniedError,
)
from .models import ExecutionResult
from .policy import RiskClass

logger = logging.getLogger("NEXUS_AGENT_BROWSER")

# Explicitly Trusted Domain Patterns
TRUSTED_DOMAIN_PATTERNS = [
    r"^([a-zA-Z0-9-]+\.)*upes\.ac\.in$",
    r"^([a-zA-Z0-9-]+\.)*blackboard\.com$",
    r"^([a-zA-Z0-9-]+\.)*microsoftonline\.com$",
    r"^([a-zA-Z0-9-]+\.)*microsoft\.com$",
    r"^([a-zA-Z0-9-]+\.)*live\.com$",
    r"^([a-zA-Z0-9-]+\.)*office\.com$",
    r"^([a-zA-Z0-9-]+\.)*sharepoint\.com$",
]

# Consequential Button / Action Keywords (Blocked from autonomous generic click)
CONSEQUENTIAL_KEYWORDS = {
    "submit", "turn in", "turnin", "finalize", "confirm submission",
    "delete", "remove account", "drop course", "purchase", "pay now",
    "enroll", "unenroll", "withdraw", "send email", "send message"
}


class BrowserService:
    """Provides safe, policy-governed browser operations for AI agents."""

    def __init__(
        self,
        provider: Optional[BrowserProvider] = None,
        vault_service = None,
        max_sessions_per_principal: int = 2,
        idle_session_ttl_sec: float = 900.0,
        artifact_dir: Optional[str] = None
    ):
        if provider is None:
            try:
                from browser.bg6_cdp import BG6EphemeralCDPProvider
                provider = BG6EphemeralCDPProvider()
            except Exception as e:
                logger.warning(f"Could not initialize BG6EphemeralCDPProvider, falling back to legacy PinchTabProvider: {e}")
                from browser.pinchtab import PinchTabProvider
                provider = PinchTabProvider()
        self.provider = provider
        self.vault_service = vault_service
        self.max_sessions_per_principal = max_sessions_per_principal
        self.idle_session_ttl_sec = idle_session_ttl_sec
        self.artifact_dir = os.path.realpath(artifact_dir or os.path.join(config.STORAGE_DIR, "artifacts", "screenshots"))
        os.makedirs(self.artifact_dir, exist_ok=True)

        # Internal session registry: session_id -> metadata dict
        self._sessions: Dict[str, Dict[str, Any]] = {}
        # Element cache for stale ref & consequence detection: session_id -> {ref_id: node_dict}
        self._element_cache: Dict[str, Dict[str, Any]] = {}

    @property
    def provider_name(self) -> str:
        if self.provider and hasattr(self.provider, "provider_name"):
            return self.provider.provider_name
        return "unknown"

    def get_health(self) -> Dict[str, Any]:
        """Returns health and status telemetry of the browser service."""
        from browser.chromium_runtime import read_system_meminfo, read_zram_used_mb, find_system_chromium_pids
        mem = read_system_meminfo()
        zram = read_zram_used_mb()
        pids = find_system_chromium_pids()
        return {
            "status": "healthy",
            "provider": self.provider_name,
            "active_sessions": len(self._sessions),
            "mem_available_mb": mem.get("MemAvailable", 0),
            "zram_used_mb": zram,
            "active_chromium_pids": pids,
            "artifact_dir": self.artifact_dir
        }

    def _cleanup_idle_sessions(self):
        """Releases abandoned sessions exceeding idle TTL."""
        now = time.time()
        expired = []
        for sid, sdata in self._sessions.items():
            if now - sdata.get("last_activity", now) > self.idle_session_ttl_sec:
                expired.append(sid)
        for sid in expired:
            logger.info(f"Cleaning up idle browser session: {sid}")
            try:
                self.provider.close_session(sid)
            except Exception:
                pass
    def cleanup_artifacts(
        self,
        max_count: int = 100,
        max_bytes: int = 100 * 1024 * 1024,
        max_age_sec: float = 7 * 86400
    ) -> Dict[str, int]:
        """
        Enforces bounded screenshot retention.
        Removes oldest artifacts when max_count, max_bytes, or max_age_sec are exceeded.
        """
        if not os.path.exists(self.artifact_dir):
            return {"deleted_count": 0, "freed_bytes": 0}

        now = time.time()
        files = []
        for fname in os.listdir(self.artifact_dir):
            fpath = os.path.join(self.artifact_dir, fname)
            if os.path.isfile(fpath):
                try:
                    stat = os.stat(fpath)
                    files.append({"path": fpath, "size": stat.st_size, "mtime": stat.st_mtime})
                except Exception:
                    continue

        files.sort(key=lambda x: x["mtime"])

        deleted_count = 0
        freed_bytes = 0
        total_bytes = sum(f["size"] for f in files)
        total_count = len(files)

        for f in files:
            is_expired = (now - f["mtime"]) > max_age_sec
            is_over_count = (total_count - deleted_count) > max_count
            is_over_bytes = (total_bytes - freed_bytes) > max_bytes

            if is_expired or is_over_count or is_over_bytes:
                try:
                    os.remove(f["path"])
                    deleted_count += 1
                    freed_bytes += f["size"]
                except Exception:
                    pass

        return {"deleted_count": deleted_count, "freed_bytes": freed_bytes}

    def _validate_session_ownership(self, session_id: str, user_id: str) -> Dict[str, Any]:
        """Validates that session exists and belongs to the calling principal."""
        self._cleanup_idle_sessions()
        session_info = self._sessions.get(session_id)
        if not session_info:
            raise BrowserSessionError(f"Browser session '{session_id}' not found or has expired.")
        if session_info.get("owner") != user_id:
            raise AccessDeniedError(f"Principal '{user_id}' does not own browser session '{session_id}'.")
        session_info["last_activity"] = time.time()
        return session_info

    def validate_url_safety(self, target_url: str, allow_internal_diagnostics: bool = False) -> Tuple[bool, str, str]:
        """
        Validates target URL against SSRF, dangerous schemes, and domain policy.
        Returns: (is_safe, category, reason_or_hostname)
        """
        if not target_url or not isinstance(target_url, str):
            return False, "invalid", "Empty or non-string URL."

        try:
            parsed = urllib.parse.urlparse(target_url.strip())
        except Exception as e:
            return False, "invalid", f"Malformed URL: {e}"

        scheme = (parsed.scheme or "").lower()
        if scheme not in ("http", "https"):
            return False, "dangerous_scheme", f"Scheme '{scheme}' is strictly prohibited. Only HTTP/HTTPS allowed."

        hostname = (parsed.hostname or "").lower()
        if not hostname:
            return False, "invalid", "Missing hostname in URL."

        # Dedicated test/diagnostic fixture: only permitted if explicitly enabled by internal test code
        if allow_internal_diagnostics and hostname in ("localhost", "127.0.0.1") and parsed.port == 5000:
            return True, "internal_diagnostic", hostname

        # Block loopback, localhost, and special addresses for ALL standard/external calls
        if hostname in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
            return False, "ssrf_blocked", "Access to loopback/localhost targets is strictly prohibited."

        # Check if hostname is an IP address
        try:
            ip_obj = ipaddress.ip_address(hostname)
            if ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local or ip_obj.is_reserved or ip_obj.is_multicast:
                return False, "ssrf_blocked", f"Access to private/reserved IP target '{hostname}' is prohibited."
        except ValueError:
            # It's a domain name
            pass

        # Check Category A: Explicitly Trusted UPES / LMS / Identity Domains
        for pat in TRUSTED_DOMAIN_PATTERNS:
            if re.match(pat, hostname):
                return True, "trusted_academic", hostname

        # Category B: Safe Public Web Domain
        # Verify it has valid TLD and does not resolve to private address tokens
        if "." in hostname and not hostname.endswith(".local") and not hostname.endswith(".internal"):
            return True, "safe_public_web", hostname

        return False, "policy_rejected", f"Hostname '{hostname}' does not match policy allowlist."

    def get_status(self, user_id: str, operation: str = "browser.status") -> ExecutionResult:
        """Returns browser provider health and active session metrics."""
        now = time.time()
        self._cleanup_idle_sessions()
        try:
            health = self.provider.get_health()
            user_sessions = [
                {
                    "session_id": sid,
                    "created_at": sdata.get("created_at"),
                    "last_activity": sdata.get("last_activity"),
                    "current_url": sdata.get("current_url"),
                    "profile": sdata.get("profile")
                }
                for sid, sdata in self._sessions.items()
                if sdata.get("owner") == user_id
            ]
            return ExecutionResult(
                ok=True,
                operation=operation,
                source="browser",
                provider=self.provider.provider_name,
                data={
                    "status": health.get("status", "unknown"),
                    "provider": self.provider.provider_name,
                    "active_sessions": len(user_sessions),
                    "sessions": user_sessions,
                    "worker_health": health
                },
                fetched_at=now
            )
        except Exception as e:
            return ExecutionResult(
                ok=False,
                operation=operation,
                source="browser",
                provider=self.provider.provider_name,
                error=f"Browser provider check failed: {str(e)}",
                error_code="BROWSER_UNAVAILABLE",
                fetched_at=now
            )

    def open_session(self, user_id: str, params: Optional[Dict[str, Any]] = None) -> ExecutionResult:
        """
        Allocates a new browser session context.
        Params:
          url (str, optional): Initial URL to open (default 'about:blank' or UPES LMS).
          profile (str, optional): Profile name (default 'nexusnode-browser-profile').
        """
        params = params or {}
        init_url = params.get("url") or "about:blank"
        profile = params.get("profile") or "nexusnode-browser-profile"
        now = time.time()

        self._cleanup_idle_sessions()

        # Concurrency limit check
        active_count = sum(1 for s in self._sessions.values() if s.get("owner") == user_id)
        if active_count >= self.max_sessions_per_principal:
            return ExecutionResult(
                ok=False,
                operation="browser.open",
                source="browser",
                provider=self.provider.provider_name,
                error=f"Maximum concurrent browser session limit ({self.max_sessions_per_principal}) reached.",
                error_code="SESSION_LIMIT_EXCEEDED",
                fetched_at=now
            )

        if init_url != "about:blank":
            allow_diag = bool(params.get("allow_internal_diagnostics", False))
            is_safe, cat, reason = self.validate_url_safety(init_url, allow_internal_diagnostics=allow_diag)
            if not is_safe:
                return ExecutionResult(
                    ok=False,
                    operation="browser.open",
                    source="browser",
                    provider=self.provider.provider_name,
                    error=f"Cannot open destination '{init_url}': {reason}",
                    error_code="URL_SAFETY_VIOLATION",
                    fetched_at=now
                )

        session_id = f"brs_{uuid.uuid4().hex[:12]}"
        try:
            bsession = self.provider.create_session(session_id=session_id, profile_name=profile, user_id=user_id)
            if init_url != "about:blank":
                self.provider.navigate(session_id, init_url)

            self._sessions[session_id] = {
                "session_id": session_id,
                "owner": user_id,
                "profile": profile,
                "created_at": now,
                "last_activity": now,
                "current_url": init_url,
                "instance_id": bsession.metadata.get("instance_id", ""),
                "active_tab": bsession.active_tab_id
            }

            return ExecutionResult(
                ok=True,
                operation="browser.open",
                source="browser",
                provider=self.provider.provider_name,
                data={
                    "session_id": session_id,
                    "profile": profile,
                    "current_url": init_url,
                    "created_at": now
                },
                fetched_at=now
            )
        except Exception as e:
            return ExecutionResult(
                ok=False,
                operation="browser.open",
                source="browser",
                provider=self.provider.provider_name,
                error=f"Failed to open browser session: {str(e)}",
                error_code="BROWSER_SESSION_FAILED",
                fetched_at=now
            )

    def close_session(self, user_id: str, params: Optional[Dict[str, Any]] = None) -> ExecutionResult:
        """Closes browser session and releases resources."""
        params = params or {}
        session_id = (params.get("session_id") or "").strip()
        now = time.time()

        if not session_id:
            return ExecutionResult(
                ok=False,
                operation="browser.close",
                source="browser",
                provider=self.provider.provider_name,
                error="Parameter 'session_id' is required.",
                error_code="INVALID_PARAMS",
                fetched_at=now
            )

        try:
            self._validate_session_ownership(session_id, user_id)
        except NexusAgentError as ne:
            return ExecutionResult(
                ok=False,
                operation="browser.close",
                source="browser",
                provider=self.provider.provider_name,
                error=ne.message,
                error_code=ne.code,
                fetched_at=now
            )

        try:
            self.provider.close_session(session_id)
        except Exception:
            pass

        self._sessions.pop(session_id, None)
        self._element_cache.pop(session_id, None)

        return ExecutionResult(
            ok=True,
            operation="browser.close",
            source="browser",
            provider=self.provider.provider_name,
            data={"session_id": session_id, "closed": True},
            fetched_at=now
        )

    def navigate(self, user_id: str, params: Optional[Dict[str, Any]] = None) -> ExecutionResult:
        """Navigates active session to a validated URL."""
        params = params or {}
        session_id = (params.get("session_id") or "").strip()
        target_url = (params.get("url") or "").strip()
        discovered_from = params.get("discovered_from")
        now = time.time()

        if not session_id or not target_url:
            return ExecutionResult(
                ok=False,
                operation="browser.navigate",
                source="browser",
                provider=self.provider.provider_name,
                error="Parameters 'session_id' and 'url' are required.",
                error_code="INVALID_PARAMS",
                fetched_at=now
            )

        try:
            sdata = self._validate_session_ownership(session_id, user_id)
        except NexusAgentError as ne:
            return ExecutionResult(
                ok=False,
                operation="browser.navigate",
                source="browser",
                provider=self.provider.provider_name,
                error=ne.message,
                error_code=ne.code,
                fetched_at=now
            )

        allow_diag = bool(params.get("allow_internal_diagnostics", False))
        is_safe, category, reason = self.validate_url_safety(target_url, allow_internal_diagnostics=allow_diag)
        if not is_safe:
            return ExecutionResult(
                ok=False,
                operation="browser.navigate",
                source="browser",
                provider=self.provider.provider_name,
                error=f"Navigation rejected: {reason}",
                error_code="URL_SAFETY_VIOLATION",
                fetched_at=now
            )

        try:
            res = self.provider.navigate(session_id, target_url)
            sdata["current_url"] = target_url
            sdata["last_activity"] = now
            # Clear element cache on navigation
            self._element_cache[session_id] = {}

            return ExecutionResult(
                ok=True,
                operation="browser.navigate",
                source="browser",
                provider=self.provider.provider_name,
                data={
                    "session_id": session_id,
                    "url": target_url,
                    "category": category,
                    "discovered_from": discovered_from,
                    "details": res
                },
                fetched_at=now
            )
        except Exception as e:
            return ExecutionResult(
                ok=False,
                operation="browser.navigate",
                source="browser",
                provider=self.provider.provider_name,
                error=f"Navigation failed: {str(e)}",
                error_code="NAVIGATION_FAILED",
                fetched_at=now
            )

    def snapshot(self, user_id: str, params: Optional[Dict[str, Any]] = None) -> ExecutionResult:
        """Extracts structured accessibility snapshot with untrusted content wrapper."""
        params = params or {}
        session_id = (params.get("session_id") or "").strip()
        now = time.time()

        if not session_id:
            return ExecutionResult(
                ok=False,
                operation="browser.snapshot",
                source="browser",
                provider=self.provider.provider_name,
                error="Parameter 'session_id' is required.",
                error_code="INVALID_PARAMS",
                fetched_at=now
            )

        try:
            sdata = self._validate_session_ownership(session_id, user_id)
        except NexusAgentError as ne:
            return ExecutionResult(
                ok=False,
                operation="browser.snapshot",
                source="browser",
                provider=self.provider.provider_name,
                error=ne.message,
                error_code=ne.code,
                fetched_at=now
            )

        try:
            bsnap = self.provider.snapshot(session_id)
            sdata["current_url"] = bsnap.url or sdata.get("current_url")
            sdata["last_activity"] = now

            # Cache elements
            if hasattr(bsnap, "element_map") and bsnap.element_map:
                self._element_cache[session_id] = bsnap.element_map

            return ExecutionResult(
                ok=True,
                operation="browser.snapshot",
                source="browser",
                provider=self.provider.provider_name,
                data={
                    "session_id": session_id,
                    "url": bsnap.url,
                    "title": bsnap.title,
                    "token_estimate": bsnap.token_estimate,
                    "element_count": len(bsnap.element_map) if bsnap.element_map else 0,
                    "envelope": bsnap.to_envelope(),
                    "tree_text": bsnap.tree_text
                },
                fetched_at=now
            )
        except Exception as e:
            return ExecutionResult(
                ok=False,
                operation="browser.snapshot",
                source="browser",
                provider=self.provider.provider_name,
                error=f"Failed to capture snapshot: {str(e)}",
                error_code="BROWSER_SESSION_FAILED",
                fetched_at=now
            )

    def screenshot(self, user_id: str, params: Optional[Dict[str, Any]] = None) -> ExecutionResult:
        """Captures page screenshot, stores as artifact, and returns bounded metadata."""
        params = params or {}
        session_id = (params.get("session_id") or "").strip()
        full_page = bool(params.get("full_page", False))
        include_preview = bool(params.get("include_preview", True))
        now = time.time()

        if not session_id:
            return ExecutionResult(
                ok=False,
                operation="browser.screenshot",
                source="browser",
                provider=self.provider.provider_name,
                error="Parameter 'session_id' is required.",
                error_code="INVALID_PARAMS",
                fetched_at=now
            )

        try:
            sdata = self._validate_session_ownership(session_id, user_id)
        except NexusAgentError as ne:
            return ExecutionResult(
                ok=False,
                operation="browser.screenshot",
                source="browser",
                provider=self.provider.provider_name,
                error=ne.message,
                error_code=ne.code,
                fetched_at=now
            )

        try:
            bcap = self.provider.capture(session_id, full_page=full_page)
            screenshot_id = f"scr_{uuid.uuid4().hex[:12]}"
            filename = f"{screenshot_id}.png"
            file_path = os.path.join(self.artifact_dir, filename)

            # Decode and write artifact
            img_b64 = bcap.screenshot_base64
            if img_b64.startswith("data:image"):
                img_b64 = img_b64.split(",", 1)[-1]

            img_bytes = base64.b64decode(img_b64)
            with open(file_path, "wb") as f:
                f.write(img_bytes)

            size_bytes = len(img_bytes)
            sha256_val = hashlib.sha256(img_bytes).hexdigest()
            artifact_uri = f"/api/artifacts/screenshots/{filename}"

            sdata["last_activity"] = now

            res_data = {
                "screenshot_id": screenshot_id,
                "session_id": session_id,
                "url": bcap.url or sdata.get("current_url"),
                "captured_at": now,
                "format": bcap.format,
                "width": bcap.width,
                "height": bcap.height,
                "size_bytes": size_bytes,
                "sha256": sha256_val,
                "artifact_uri": artifact_uri,
                "storage_path": file_path
            }
            # Provide bounded base64 preview if requested (and under 1MB)
            if include_preview and size_bytes <= 1024 * 1024:
                res_data["preview_base64"] = img_b64

            return ExecutionResult(
                ok=True,
                operation="browser.screenshot",
                source="browser",
                provider=self.provider.provider_name,
                data=res_data,
                fetched_at=now
            )
        except Exception as e:
            return ExecutionResult(
                ok=False,
                operation="browser.screenshot",
                source="browser",
                provider=self.provider.provider_name,
                error=f"Failed to capture screenshot: {str(e)}",
                error_code="BROWSER_SESSION_FAILED",
                fetched_at=now
            )

    def capture(self, user_id: str, params: Optional[Dict[str, Any]] = None) -> ExecutionResult:
        """
        Paired operation: captures accessibility snapshot + screenshot from the exact same page state.
        Associates them with a unique capture_id for multi-modal reasoning.
        """
        params = params or {}
        session_id = (params.get("session_id") or "").strip()
        now = time.time()

        if not session_id:
            return ExecutionResult(
                ok=False,
                operation="browser.capture",
                source="browser",
                provider=self.provider.provider_name,
                error="Parameter 'session_id' is required.",
                error_code="INVALID_PARAMS",
                fetched_at=now
            )

        try:
            sdata = self._validate_session_ownership(session_id, user_id)
        except NexusAgentError as ne:
            return ExecutionResult(
                ok=False,
                operation="browser.capture",
                source="browser",
                provider=self.provider.provider_name,
                error=ne.message,
                error_code=ne.code,
                fetched_at=now
            )

        capture_id = f"cap_{uuid.uuid4().hex[:12]}"
        try:
            # 1. Snapshot
            bsnap = self.provider.snapshot(session_id)
            # 2. Screenshot
            bcap = self.provider.capture(session_id)

            filename = f"{capture_id}.png"
            file_path = os.path.join(self.artifact_dir, filename)

            img_b64 = bcap.screenshot_base64
            if img_b64.startswith("data:image"):
                img_b64 = img_b64.split(",", 1)[-1]
            img_bytes = base64.b64decode(img_b64)
            with open(file_path, "wb") as f:
                f.write(img_bytes)

            size_bytes = len(img_bytes)
            sha256_val = hashlib.sha256(img_bytes).hexdigest()
            artifact_uri = f"/api/artifacts/screenshots/{filename}"

            sdata["current_url"] = bsnap.url or sdata.get("current_url")
            sdata["last_activity"] = now
            if bsnap.element_map:
                self._element_cache[session_id] = bsnap.element_map

            return ExecutionResult(
                ok=True,
                operation="browser.capture",
                source="browser",
                provider=self.provider.provider_name,
                data={
                    "capture_id": capture_id,
                    "session_id": session_id,
                    "url": bsnap.url,
                    "title": bsnap.title,
                    "captured_at": now,
                    "token_estimate": bsnap.token_estimate,
                    "envelope": bsnap.to_envelope(),
                    "tree_text": bsnap.tree_text,
                    "screenshot": {
                        "artifact_uri": artifact_uri,
                        "storage_path": file_path,
                        "size_bytes": size_bytes,
                        "sha256": sha256_val,
                        "width": bcap.width,
                        "height": bcap.height
                    }
                },
                fetched_at=now
            )
        except Exception as e:
            return ExecutionResult(
                ok=False,
                operation="browser.capture",
                source="browser",
                provider=self.provider.provider_name,
                error=f"Failed to execute paired capture: {str(e)}",
                error_code="BROWSER_SESSION_FAILED",
                fetched_at=now
            )

    def _is_consequential_element(self, session_id: str, element_ref: str) -> Tuple[bool, str]:
        """Inspects element cache for consequential keywords (Submit, Turn In, Confirm, etc.)."""
        cache = self._element_cache.get(session_id, {})
        elem_info = cache.get(element_ref)
        if not elem_info:
            return False, ""

        text_val = ""
        if isinstance(elem_info, dict):
            text_val = f"{elem_info.get('name', '')} {elem_info.get('text', '')} {elem_info.get('role', '')}".lower()
        elif isinstance(elem_info, str):
            text_val = elem_info.lower()

        for kw in CONSEQUENTIAL_KEYWORDS:
            if kw in text_val:
                return True, kw

        return False, ""

    def click(self, user_id: str, params: Optional[Dict[str, Any]] = None) -> ExecutionResult:
        """
        Clicks an interactive element by reference (e.g. 'e1').
        Strictly blocks consequential actions (Submit, Turn In, Delete, etc.).
        """
        params = params or {}
        session_id = (params.get("session_id") or "").strip()
        element_ref = (params.get("element") or params.get("ref") or "").strip()
        now = time.time()

        if not session_id or not element_ref:
            return ExecutionResult(
                ok=False,
                operation="browser.click",
                source="browser",
                provider=self.provider.provider_name,
                error="Parameters 'session_id' and 'element' are required.",
                error_code="INVALID_PARAMS",
                fetched_at=now
            )

        try:
            sdata = self._validate_session_ownership(session_id, user_id)
        except NexusAgentError as ne:
            return ExecutionResult(
                ok=False,
                operation="browser.click",
                source="browser",
                provider=self.provider.provider_name,
                error=ne.message,
                error_code=ne.code,
                fetched_at=now
            )

        # Consequential Action Guard Check
        is_consequential, matched_kw = self._is_consequential_element(session_id, element_ref)
        if is_consequential:
            logger.warning(f"Blocked consequential click attempt on '{element_ref}' (keyword: '{matched_kw}')")
            return ExecutionResult(
                ok=False,
                operation="browser.click",
                source="browser",
                provider=self.provider.provider_name,
                error=f"Consequential action blocked: Target element '{element_ref}' matches irreversible action keyword '{matched_kw}'. Final submission/deletion is not permitted in Phase 3.4.",
                error_code="CONSEQUENTIAL_ACTION_BLOCKED",
                fetched_at=now
            )

        try:
            res = self.provider.click(session_id, element_ref)
            sdata["last_activity"] = now
            sdata["last_focused_element"] = element_ref
            return ExecutionResult(
                ok=True,
                operation="browser.click",
                source="browser",
                provider=self.provider.provider_name,
                data={"session_id": session_id, "element": element_ref, "details": res},
                fetched_at=now
            )
        except ElementStaleError as ese:
            return ExecutionResult(
                ok=False,
                operation="browser.click",
                source="browser",
                provider=self.provider.provider_name,
                error=ese.message,
                error_code="ELEMENT_STALE",
                fetched_at=now
            )
        except Exception as e:
            return ExecutionResult(
                ok=False,
                operation="browser.click",
                source="browser",
                provider=self.provider.provider_name,
                error=f"Click failed: {str(e)}",
                error_code="BROWSER_ACTION_FAILED",
                fetched_at=now
            )

    def type_text(self, user_id: str, params: Optional[Dict[str, Any]] = None) -> ExecutionResult:
        """Types text into an input element."""
        params = params or {}
        session_id = (params.get("session_id") or "").strip()
        element_ref = (params.get("element") or params.get("ref") or "").strip()
        text = params.get("text", "")
        submit = bool(params.get("submit", False))
        now = time.time()

        if not session_id or not element_ref:
            return ExecutionResult(
                ok=False,
                operation="browser.type",
                source="browser",
                provider=self.provider.provider_name,
                error="Parameters 'session_id' and 'element' are required.",
                error_code="INVALID_PARAMS",
                fetched_at=now
            )

        # Block submit flag if true (consequential guard)
        if submit:
            return ExecutionResult(
                ok=False,
                operation="browser.type",
                source="browser",
                provider=self.provider.provider_name,
                error="Implicit form submission via submit=True is blocked. Submit actions require explicit evaluation.",
                error_code="CONSEQUENTIAL_ACTION_BLOCKED",
                fetched_at=now
            )

        try:
            sdata = self._validate_session_ownership(session_id, user_id)
        except NexusAgentError as ne:
            return ExecutionResult(
                ok=False,
                operation="browser.type",
                source="browser",
                provider=self.provider.provider_name,
                error=ne.message,
                error_code=ne.code,
                fetched_at=now
            )

        try:
            res = self.provider.type_text(session_id, element_ref, text, submit=False)
            sdata["last_activity"] = now
            sdata["last_focused_element"] = element_ref
            return ExecutionResult(
                ok=True,
                operation="browser.type",
                source="browser",
                provider=self.provider.provider_name,
                data={"session_id": session_id, "element": element_ref, "details": res},
                fetched_at=now
            )
        except ElementStaleError as ese:
            return ExecutionResult(
                ok=False,
                operation="browser.type",
                source="browser",
                provider=self.provider.provider_name,
                error=ese.message,
                error_code="ELEMENT_STALE",
                fetched_at=now
            )
        except Exception as e:
            return ExecutionResult(
                ok=False,
                operation="browser.type",
                source="browser",
                provider=self.provider.provider_name,
                error=f"Type failed: {str(e)}",
                error_code="BROWSER_ACTION_FAILED",
                fetched_at=now
            )

    def press(self, user_id: str, params: Optional[Dict[str, Any]] = None) -> ExecutionResult:
        """Sends keyboard key event (e.g. 'Tab', 'ArrowDown', 'Escape')."""
        params = params or {}
        session_id = (params.get("session_id") or "").strip()
        key = (params.get("key") or "").strip()
        now = time.time()

        if not session_id or not key:
            return ExecutionResult(
                ok=False,
                operation="browser.press",
                source="browser",
                provider=self.provider.provider_name,
                error="Parameters 'session_id' and 'key' are required.",
                error_code="INVALID_PARAMS",
                fetched_at=now
            )

        try:
            sdata = self._validate_session_ownership(session_id, user_id)
        except NexusAgentError as ne:
            return ExecutionResult(
                ok=False,
                operation="browser.press",
                source="browser",
                provider=self.provider.provider_name,
                error=ne.message,
                error_code=ne.code,
                fetched_at=now
            )

        # Consequential Key Guard Check for Enter and Space
        if key.lower() in ("enter", "return", "space", " "):
            target_elem = (params.get("element") or params.get("ref") or sdata.get("last_focused_element") or "").strip()
            if target_elem:
                is_consequential, matched_kw = self._is_consequential_element(session_id, target_elem)
                if is_consequential:
                    logger.warning(f"Blocked consequential key press '{key}' on element '{target_elem}' (keyword: '{matched_kw}')")
                    return ExecutionResult(
                        ok=False,
                        operation="browser.press",
                        source="browser",
                        provider=self.provider.provider_name,
                        error=f"Consequential action blocked: Pressing '{key}' on target '{target_elem}' matches irreversible action keyword '{matched_kw}'. Final submission is not permitted.",
                        error_code="CONSEQUENTIAL_ACTION_BLOCKED",
                        fetched_at=now
                    )

            # Check if page has a consequential submit button and Enter is pressed from a form input
            cache = self._element_cache.get(session_id, {})
            has_submit_btn = any(
                any(kw in f"{e.get('name', '')} {e.get('text', '')} {e.get('role', '')}".lower() for kw in ("submit", "turn in", "turnin", "finalize", "confirm submission"))
                for e in cache.values() if isinstance(e, dict)
            )
            if has_submit_btn and target_elem:
                elem_info = cache.get(target_elem, {})
                if isinstance(elem_info, dict) and elem_info.get("role") in ("textbox", "input", "edit", "combobox", "searchbox"):
                    return ExecutionResult(
                        ok=False,
                        operation="browser.press",
                        source="browser",
                        provider=self.provider.provider_name,
                        error="Consequential action blocked: Pressing Enter inside a form containing a Submit button may trigger implicit submission.",
                        error_code="CONSEQUENTIAL_ACTION_BLOCKED",
                        fetched_at=now
                    )

        try:
            res = self.provider.press(session_id, key)
            sdata["last_activity"] = now
            return ExecutionResult(
                ok=True,
                operation="browser.press",
                source="browser",
                provider=self.provider.provider_name,
                data={"session_id": session_id, "key": key, "details": res},
                fetched_at=now
            )
        except Exception as e:
            return ExecutionResult(
                ok=False,
                operation="browser.press",
                source="browser",
                provider=self.provider.provider_name,
                error=f"Press failed: {str(e)}",
                error_code="BROWSER_ACTION_FAILED",
                fetched_at=now
            )

    def upload(self, user_id: str, params: Optional[Dict[str, Any]] = None) -> ExecutionResult:
        """
        Attaches a file from AGENT_VAULT_ROOT to a browser file input element.
        Strictly limits to draft form attachment; does NOT submit.
        Params:
          session_id (str, required): Active browser session ID.
          element (str, required): Target file input element reference (e.g. 'e4').
          vault_path (str, required): Relative path within Vault.
        """
        params = params or {}
        session_id = (params.get("session_id") or "").strip()
        element_ref = (params.get("element") or params.get("ref") or "").strip()
        vault_path = (params.get("vault_path") or "").strip()
        now = time.time()

        if not session_id or not element_ref or not vault_path:
            return ExecutionResult(
                ok=False,
                operation="browser.upload",
                source="browser",
                provider=self.provider.provider_name,
                error="Parameters 'session_id', 'element', and 'vault_path' are required.",
                error_code="INVALID_PARAMS",
                fetched_at=now
            )

        try:
            sdata = self._validate_session_ownership(session_id, user_id)
        except NexusAgentError as ne:
            return ExecutionResult(
                ok=False,
                operation="browser.upload",
                source="browser",
                provider=self.provider.provider_name,
                error=ne.message,
                error_code=ne.code,
                fetched_at=now
            )

        if not self.vault_service:
            return ExecutionResult(
                ok=False,
                operation="browser.upload",
                source="browser",
                provider=self.provider.provider_name,
                error="Vault service unavailable for upload resolution.",
                error_code="SERVICE_UNAVAILABLE",
                fetched_at=now
            )

        try:
            resolved_vault_file = self.vault_service._resolve_safe_path(vault_path)
        except NexusAgentError as ne:
            return ExecutionResult(
                ok=False,
                operation="browser.upload",
                source="browser",
                provider=self.provider.provider_name,
                error=ne.message,
                error_code=ne.code,
                fetched_at=now
            )

        if not os.path.exists(resolved_vault_file) or not os.path.isfile(resolved_vault_file):
            return ExecutionResult(
                ok=False,
                operation="browser.upload",
                source="browser",
                provider=self.provider.provider_name,
                error=f"Vault file '{vault_path}' not found.",
                error_code="NOT_FOUND",
                fetched_at=now
            )

        # File size check (max 10MB)
        if os.path.getsize(resolved_vault_file) > 10 * 1024 * 1024:
            return ExecutionResult(
                ok=False,
                operation="browser.upload",
                source="browser",
                provider=self.provider.provider_name,
                error="File exceeds maximum upload size limit (10 MB).",
                error_code="FILE_TOO_LARGE",
                fetched_at=now
            )

        try:
            res = self.provider.upload_file(session_id, element_ref, resolved_vault_file)
            sdata["last_activity"] = now
            return ExecutionResult(
                ok=True,
                operation="browser.upload",
                source="browser",
                provider=self.provider.provider_name,
                data={
                    "session_id": session_id,
                    "element": element_ref,
                    "vault_path": vault_path,
                    "uploaded_draft": True,
                    "is_final_submission": False,
                    "note": "File attached to draft form. Final submission not triggered.",
                    "details": res
                },
                fetched_at=now
            )
        except Exception as e:
            return ExecutionResult(
                ok=False,
                operation="browser.upload",
                source="browser",
                provider=self.provider.provider_name,
                error=f"Upload failed: {str(e)}",
                error_code="UPLOAD_FAILED",
                fetched_at=now
            )

    def download(self, user_id: str, params: Optional[Dict[str, Any]] = None) -> ExecutionResult:
        """
        Triggers controlled browser download and transfers result into AGENT_VAULT_ROOT destination.
        Params:
          session_id (str, required): Active browser session ID.
          element (str, optional): Target download link/button element reference.
          destination_path (str, required): Relative Vault path or directory.
        """
        params = params or {}
        session_id = (params.get("session_id") or "").strip()
        element_ref = (params.get("element") or params.get("ref") or "").strip()
        dst_rel = (params.get("destination_path") or params.get("destination") or "").strip()
        now = time.time()

        if not session_id or not dst_rel:
            return ExecutionResult(
                ok=False,
                operation="browser.download",
                source="browser",
                provider=self.provider.provider_name,
                error="Parameters 'session_id' and 'destination_path' are required.",
                error_code="INVALID_PARAMS",
                fetched_at=now
            )

        try:
            sdata = self._validate_session_ownership(session_id, user_id)
        except NexusAgentError as ne:
            return ExecutionResult(
                ok=False,
                operation="browser.download",
                source="browser",
                provider=self.provider.provider_name,
                error=ne.message,
                error_code=ne.code,
                fetched_at=now
            )

        if not self.vault_service:
            return ExecutionResult(
                ok=False,
                operation="browser.download",
                source="browser",
                provider=self.provider.provider_name,
                error="Vault service unavailable for download destination resolution.",
                error_code="SERVICE_UNAVAILABLE",
                fetched_at=now
            )

        try:
            dst_abs = self.vault_service._resolve_safe_path(dst_rel)
        except NexusAgentError as ne:
            return ExecutionResult(
                ok=False,
                operation="browser.download",
                source="browser",
                provider=self.provider.provider_name,
                error=ne.message,
                error_code=ne.code,
                fetched_at=now
            )

        # Stage in temporary download folder
        temp_dl_dir = os.path.join(config.STORAGE_DIR, "tmp_downloads", session_id)
        os.makedirs(temp_dl_dir, exist_ok=True)

        try:
            b_dl = self.provider.download_file(session_id, element_ref, temp_dl_dir)
            source_file = b_dl.file_path

            if not os.path.exists(source_file):
                # Fallback check inside temp_dl_dir
                found = [os.path.join(temp_dl_dir, f) for f in os.listdir(temp_dl_dir) if not f.startswith(".")]
                if found:
                    source_file = found[0]

            if not os.path.exists(source_file):
                return ExecutionResult(
                    ok=False,
                    operation="browser.download",
                    source="browser",
                    provider=self.provider.provider_name,
                    error="Download completed but output file not found on worker.",
                    error_code="DOWNLOAD_FAILED",
                    fetched_at=now
                )

            # Check size limit (25 MB)
            file_size = os.path.getsize(source_file)
            if file_size > 25 * 1024 * 1024:
                os.remove(source_file)
                return ExecutionResult(
                    ok=False,
                    operation="browser.download",
                    source="browser",
                    provider=self.provider.provider_name,
                    error=f"Downloaded file exceeds size limit (25 MB): {file_size} bytes",
                    error_code="FILE_TOO_LARGE",
                    fetched_at=now
                )

            # Compute SHA-256
            with open(source_file, "rb") as f:
                sha256_val = hashlib.sha256(f.read()).hexdigest()

            # Determine final destination file path
            if os.path.isdir(dst_abs):
                final_file = os.path.join(dst_abs, b_dl.file_name or os.path.basename(source_file))
            else:
                final_file = dst_abs

            parent_dir = os.path.dirname(final_file)
            if parent_dir:
                os.makedirs(parent_dir, exist_ok=True)

            # Atomic copy/move into Vault
            temp_vault_dest = f"{final_file}.tmp_{int(now * 1000)}"
            import shutil
            shutil.copy2(source_file, temp_vault_dest)
            os.replace(temp_vault_dest, final_file)

            # Clean up worker temp file
            try:
                os.remove(source_file)
            except Exception:
                pass

            rel_vault_path = self.vault_service._get_relative_path(final_file)
            sdata["last_activity"] = now

            return ExecutionResult(
                ok=True,
                operation="browser.download",
                source="browser_download",
                provider=self.provider.provider_name,
                data={
                    "vault_path": rel_vault_path,
                    "filename": os.path.basename(final_file),
                    "size_bytes": file_size,
                    "sha256": sha256_val,
                    "source_url": sdata.get("current_url"),
                    "downloaded_at": now,
                    "content_type": b_dl.content_type
                },
                fetched_at=now
            )
        except Exception as e:
            return ExecutionResult(
                ok=False,
                operation="browser.download",
                source="browser",
                provider=self.provider.provider_name,
                error=f"Download pipeline failed: {str(e)}",
                error_code="DOWNLOAD_FAILED",
                fetched_at=now
            )
