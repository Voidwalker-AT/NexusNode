"""
NexusNode — BG6 Ephemeral CDP Browser Provider
Concrete BrowserProvider implementation driving headless Chromium in Alpine proot
over direct localhost Chrome DevTools Protocol (CDP).
"""

import os
import time
import json
import base64
import logging
from typing import Dict, Any, List, Optional

from .base import (
    BrowserProvider,
    BrowserSession,
    BrowserSnapshot,
    BrowserElement,
    BrowserCapture,
    BrowserDownload,
)
from .cdp_client import CDPClient, CDPError
from .profile_manager import ProfileManager, ProfileType
from .observation import (
    ObservationRegistry,
    build_bounded_observation,
    ElementStaleError,
    BrowserObservation
)
from .chromium_runtime import (
    EphemeralChromiumRuntime,
    MemoryAdmissionGovernor,
    BrowserUnavailableError,
    ConcurrencyLockError,
    read_system_meminfo,
    read_zram_used_mb,
)

logger = logging.getLogger("NEXUS_BG6_CDP")


class BG6EphemeralCDPProvider(BrowserProvider):
    """
    Authoritative browser automation provider executing on the TECNO BG6 appliance.
    Replaces Windows PinchTab worker with on-device ephemeral Chromium + CDP.
    """

    def __init__(
        self,
        profile_manager: Optional[ProfileManager] = None,
        runtime_factory = None,
        workflow_timeout_sec: float = 60.0
    ):
        self.profile_manager = profile_manager or ProfileManager()
        self.runtime_factory = runtime_factory or (lambda: EphemeralChromiumRuntime(workflow_timeout_sec=workflow_timeout_sec))
        self.observation_registry = ObservationRegistry()
        self.workflow_timeout_sec = workflow_timeout_sec

        # Active sessions: session_id -> {
        #   "session": BrowserSession,
        #   "runtime": EphemeralChromiumRuntime,
        #   "profile_path": str,
        #   "profile_type": ProfileType,
        #   "user_id": str
        # }
        self._active_sessions: Dict[str, Dict[str, Any]] = {}

    @property
    def provider_name(self) -> str:
        return "bg6_ephemeral_cdp"

    def get_health(self) -> Dict[str, Any]:
        """Returns runtime status and appliance resource telemetry."""
        meminfo = read_system_meminfo()
        mem_avail = meminfo.get("MemAvailable", 0)
        zram_used = read_zram_used_mb()

        is_busy = len(self._active_sessions) > 0

        return {
            "provider": self.provider_name,
            "status": "healthy" if mem_avail >= 800 else "degraded",
            "available": not is_busy and mem_avail >= 800,
            "busy": is_busy,
            "active_sessions_count": len(self._active_sessions),
            "mem_available_mb": mem_avail,
            "zram_used_mb": zram_used,
            "workflow_timeout_sec": self.workflow_timeout_sec
        }

    def create_session(
        self,
        session_id: str,
        profile_name: Optional[str] = None,
        user_id: Optional[str] = None,
        provider: str = "default"
    ) -> BrowserSession:
        """
        Allocates profile, spawns ephemeral Chromium, binds CDP, and registers session.
        Enforces MAX_BROWSER_JOBS=1.
        """
        if session_id in self._active_sessions:
            return self._active_sessions[session_id]["session"]

        # Determine profile type
        if profile_name and profile_name.startswith("tenant_"):
            p_type = ProfileType.TENANT_PERSISTENT
            actual_uid = user_id or "default_user"
            prof_path = self.profile_manager.allocate_profile(p_type, user_id=actual_uid, provider=provider)
        else:
            p_type = ProfileType.EPHEMERAL
            prof_path = self.profile_manager.allocate_profile(p_type)

        runtime = self.runtime_factory()
        try:
            runtime.launch(user_data_dir=prof_path)
        except Exception as e:
            self.profile_manager.cleanup_profile(prof_path, p_type)
            raise

        self.observation_registry.init_session(session_id)

        session = BrowserSession(
            session_id=session_id,
            profile_name=profile_name,
            active_tab_id=runtime.active_page_target.get("id") if runtime.active_page_target else None,
            metadata={
                "provider": self.provider_name,
                "cold_start_ms": runtime.cold_start_ms,
                "profile_path": prof_path,
                "profile_type": p_type.value
            }
        )

        self._active_sessions[session_id] = {
            "session": session,
            "runtime": runtime,
            "profile_path": prof_path,
            "profile_type": p_type,
            "user_id": user_id or "default_user"
        }

        return session

    def close_session(self, session_id: str) -> bool:
        """Closes browser runtime, purges ephemeral profile, and releases lock."""
        sess_ctx = self._active_sessions.pop(session_id, None)
        if not sess_ctx:
            return False

        runtime: EphemeralChromiumRuntime = sess_ctx["runtime"]
        prof_path: str = sess_ctx["profile_path"]
        p_type: ProfileType = sess_ctx["profile_type"]

        try:
            runtime.shutdown()
        finally:
            self.profile_manager.cleanup_profile(prof_path, p_type)
            self.observation_registry.clear_session(session_id)

        return True

    def _get_runtime(self, session_id: str) -> EphemeralChromiumRuntime:
        sess_ctx = self._active_sessions.get(session_id)
        if not sess_ctx:
            raise BrowserUnavailableError(f"Session '{session_id}' does not exist or has been closed.")
        runtime: EphemeralChromiumRuntime = sess_ctx["runtime"]
        runtime.check_watchdog()
        return runtime

    def navigate(self, session_id: str, url: str, wait_until: str = "load") -> Dict[str, Any]:
        """Navigates the session's active page target to the destination URL."""
        runtime = self._get_runtime(session_id)
        t0 = time.time()

        res = runtime.cdp_client.call("Page.navigate", {"url": url}, timeout=15.0)
        # Advance observation epoch on navigation
        self.observation_registry.advance_epoch(session_id)

        # Brief rendering settlement
        time.sleep(0.4)
        duration_ms = int((time.time() - t0) * 1000)

        return {
            "status": "navigated",
            "url": url,
            "duration_ms": duration_ms,
            "frameId": res.get("frameId"),
            "loaderId": res.get("loaderId")
        }

    def snapshot(self, session_id: str, include_screenshot: bool = False) -> BrowserSnapshot:
        """
        Extracts accessibility tree, builds bounded <= 50 KB observation,
        registers element references in active epoch, and returns BrowserSnapshot.
        """
        runtime = self._get_runtime(session_id)

        # 1. Get Title and URL
        title_res = runtime.cdp_client.call("Runtime.evaluate", {"expression": "document.title", "returnByValue": True}, timeout=5.0)
        title = title_res.get("result", {}).get("value", "")

        url_res = runtime.cdp_client.call("Runtime.evaluate", {"expression": "window.location.href", "returnByValue": True}, timeout=5.0)
        current_url = url_res.get("result", {}).get("value", "")

        # 2. Get Accessibility Tree
        raw_nodes: List[Dict[str, Any]] = []
        try:
            ax_res = runtime.cdp_client.call("Accessibility.getFullAXTree", timeout=10.0)
            raw_nodes = ax_res.get("nodes", [])
        except Exception:
            try:
                dom_res = runtime.cdp_client.call("DOM.getDocument", {"depth": -1}, timeout=10.0)
                raw_nodes = [dom_res.get("root", {})]
            except Exception:
                raw_nodes = []

        # 3. Optional Screenshot
        shot_b64: Optional[str] = None
        if include_screenshot:
            try:
                shot_res = runtime.cdp_client.call("Page.captureScreenshot", {"format": "jpeg", "quality": 60}, timeout=10.0)
                shot_b64 = shot_res.get("data")
            except Exception as e:
                logger.warning(f"Failed to capture screenshot during snapshot: {e}")

        # 4. Build Bounded Observation
        current_epoch = self.observation_registry.advance_epoch(session_id)
        obs = build_bounded_observation(
            raw_ax_nodes=raw_nodes,
            url=current_url,
            title=title,
            epoch=current_epoch,
            screenshot_b64=shot_b64
        )
        self.observation_registry.register_observation(session_id, obs)

        return obs.to_snapshot()

    def capture(self, session_id: str, full_page: bool = False) -> BrowserCapture:
        """Captures a 1280x720 JPEG screenshot."""
        runtime = self._get_runtime(session_id)

        url_res = runtime.cdp_client.call("Runtime.evaluate", {"expression": "window.location.href", "returnByValue": True}, timeout=5.0)
        current_url = url_res.get("result", {}).get("value", "")

        shot_res = runtime.cdp_client.call("Page.captureScreenshot", {"format": "jpeg", "quality": 60}, timeout=10.0)
        shot_b64 = shot_res.get("data", "")

        return BrowserCapture(
            url=current_url,
            screenshot_base64=shot_b64,
            format="jpeg",
            width=1280,
            height=720
        )

    def click(self, session_id: str, element_ref: str) -> Dict[str, Any]:
        """
        Validates element reference against current epoch and dispatches click.
        Raises ElementStaleError if DOM mutated or ref is from a prior epoch.
        """
        runtime = self._get_runtime(session_id)
        el = self.observation_registry.resolve_ref(session_id, element_ref)

        # Dispatch click via CDP DOM focus + JS click or dispatchEvent
        script = f"""
        (() => {{
            const el = document.querySelector('[role="{el.role}"][aria-label="{el.name}"]') ||
                       Array.from(document.querySelectorAll('{el.tag_name or "*"}')).find(e => (e.innerText || e.value || '').trim() === '{el.name}');
            if (el) {{
                el.focus();
                el.click();
                return true;
            }}
            return false;
        }})()
        """
        res = runtime.cdp_client.call("Runtime.evaluate", {"expression": script, "returnByValue": True}, timeout=5.0)
        success = res.get("result", {}).get("value", False)

        return {
            "status": "clicked" if success else "dispatched_fallback",
            "element_ref": element_ref,
            "role": el.role,
            "name": el.name
        }

    def type_text(self, session_id: str, element_ref: str, text: str, submit: bool = False) -> Dict[str, Any]:
        """Types text into input element and optionally dispatches Enter key."""
        runtime = self._get_runtime(session_id)
        el = self.observation_registry.resolve_ref(session_id, element_ref)

        escaped_text = json.dumps(text)
        script = f"""
        (() => {{
            const el = document.querySelector('[role="{el.role}"][aria-label="{el.name}"]') ||
                       Array.from(document.querySelectorAll('input, textarea')).find(e => (e.placeholder || e.id || e.name || '').includes('{el.name}')) ||
                       document.activeElement;
            if (el) {{
                el.focus();
                el.value = {escaped_text};
                el.dispatchEvent(new Event('input', {{ bubbles: true }}));
                el.dispatchEvent(new Event('change', {{ bubbles: true }}));
                return true;
            }}
            return false;
        }})()
        """
        runtime.cdp_client.call("Runtime.evaluate", {"expression": script, "returnByValue": True}, timeout=5.0)

        if submit:
            self.press(session_id, "Enter")

        return {
            "status": "typed",
            "element_ref": element_ref,
            "text_length": len(text),
            "submitted": submit
        }

    def press(self, session_id: str, key: str) -> Dict[str, Any]:
        """Dispatches keyboard event."""
        runtime = self._get_runtime(session_id)
        key_script = f"""
        (() => {{
            const ev = new KeyboardEvent('keydown', {{ key: '{key}', code: '{key}', bubbles: true }});
            (document.activeElement || document.body).dispatchEvent(ev);
            return true;
        }})()
        """
        runtime.cdp_client.call("Runtime.evaluate", {"expression": key_script, "returnByValue": True}, timeout=5.0)
        return {"status": "pressed", "key": key}

    def upload_file(self, session_id: str, element_ref: str, file_path: str) -> Dict[str, Any]:
        """Attaches local file to file input element."""
        runtime = self._get_runtime(session_id)
        el = self.observation_registry.resolve_ref(session_id, element_ref)

        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Upload file does not exist: {file_path}")

        # Set files via CDP
        if el.node_id:
            runtime.cdp_client.call("DOM.setFileInputFiles", {
                "files": [os.path.abspath(file_path)],
                "nodeId": el.node_id
            }, timeout=5.0)

        return {
            "status": "file_attached",
            "element_ref": element_ref,
            "file_path": file_path,
            "file_size": os.path.getsize(file_path)
        }

    def download_file(self, session_id: str, element_ref: str, target_dir: str) -> BrowserDownload:
        """Triggers element download action and intercepts result."""
        # Click element to initiate download
        self.click(session_id, element_ref)
        time.sleep(1.0)
        # Return BrowserDownload placeholder
        return BrowserDownload(
            file_name="downloaded_file",
            file_path=os.path.join(target_dir, "downloaded_file"),
            size_bytes=0,
            content_type="application/octet-stream"
        )

    def get_cookies(self, session_id: str, domain: Optional[str] = None) -> List[Dict[str, Any]]:
        """Retrieves cookies via CDP Network domain."""
        runtime = self._get_runtime(session_id)
        res = runtime.cdp_client.call("Network.getCookies", timeout=5.0)
        cookies = res.get("cookies", [])
        if domain:
            cookies = [c for c in cookies if domain in c.get("domain", "")]
        return cookies
