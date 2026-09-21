"""
NexusNode — Camofox Browser Provider Stub (Phase 3.0/3.1 Placeholder)
Unregistered placeholder for future C++ anti-fingerprinting stealth browser node.
"""

from typing import Dict, Any, List, Optional
from .base import (
    BrowserProvider,
    BrowserSession,
    BrowserSnapshot,
    BrowserCapture,
    BrowserDownload,
)
from agent.errors import BrowserUnavailableError


class CamofoxProvider(BrowserProvider):
    """
    Placeholder client for future Camofox stealth node.
    Not registered in Phase 3.1 runtime.
    """

    def __init__(self, base_url: str = "http://127.0.0.1:9377", api_key: Optional[str] = None):
        self.base_url = base_url
        self._api_key = api_key

    @property
    def provider_name(self) -> str:
        return "camofox"

    def get_health(self) -> Dict[str, Any]:
        return {"provider": "camofox", "status": "unregistered", "error": "CamofoxProvider is not registered in Phase 3.1."}

    def create_session(self, session_id: str, profile_name: Optional[str] = None) -> BrowserSession:
        raise BrowserUnavailableError("CamofoxProvider is not registered in Phase 3.1.")

    def close_session(self, session_id: str) -> bool:
        return True

    def navigate(self, session_id: str, url: str, wait_until: str = "load") -> Dict[str, Any]:
        raise BrowserUnavailableError("CamofoxProvider is not registered in Phase 3.1.")

    def snapshot(self, session_id: str, include_screenshot: bool = False) -> BrowserSnapshot:
        raise BrowserUnavailableError("CamofoxProvider is not registered in Phase 3.1.")

    def capture(self, session_id: str, full_page: bool = False) -> BrowserCapture:
        raise BrowserUnavailableError("CamofoxProvider is not registered in Phase 3.1.")

    def click(self, session_id: str, element_ref: str) -> Dict[str, Any]:
        raise BrowserUnavailableError("CamofoxProvider is not registered in Phase 3.1.")

    def type_text(self, session_id: str, element_ref: str, text: str, submit: bool = False) -> Dict[str, Any]:
        raise BrowserUnavailableError("CamofoxProvider is not registered in Phase 3.1.")

    def press(self, session_id: str, key: str) -> Dict[str, Any]:
        raise BrowserUnavailableError("CamofoxProvider is not registered in Phase 3.1.")

    def upload_file(self, session_id: str, element_ref: str, file_path: str) -> Dict[str, Any]:
        raise BrowserUnavailableError("CamofoxProvider is not registered in Phase 3.1.")

    def download_file(self, session_id: str, element_ref: str, target_dir: str) -> BrowserDownload:
        raise BrowserUnavailableError("CamofoxProvider is not registered in Phase 3.1.")

    def get_cookies(self, session_id: str, domain: Optional[str] = None) -> List[Dict[str, Any]]:
        return []
