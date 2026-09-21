"""
NexusNode — Browser Provider Abstraction Layer
Defines the generic interface and normalized models for agent browser providers.
Decouples agent planners and semantic routers from specific browser implementations.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
import time


@dataclass
class BrowserSession:
    session_id: str
    profile_name: Optional[str] = None
    active_tab_id: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class BrowserElement:
    ref_id: str                     # Stable reference identifier (e.g. 'e0', 'e1')
    tag_name: str
    role: str                       # e.g. 'button', 'link', 'input', 'combobox'
    name: str                       # Visible element text or accessibility label
    is_clickable: bool = True
    is_editable: bool = False
    attributes: Dict[str, Any] = field(default_factory=dict)


@dataclass
class BrowserSnapshot:
    url: str
    title: str
    tree_text: str                  # Structured Accessibility Tree representation
    element_map: Dict[str, str] = field(default_factory=dict)   # Maps ref_id -> description
    screenshot_base64: Optional[str] = None
    token_estimate: int = 0
    timestamp: float = field(default_factory=time.time)

    def to_envelope(self) -> str:
        """Wraps snapshot in untrusted data boundary for LLM agent."""
        return (
            f'<untrusted_web_content origin="{self.url}" timestamp="{self.timestamp:.0f}">\n'
            f'  <page_title>{self.title}</page_title>\n'
            f'  <accessibility_tree>\n'
            f'{self.tree_text}\n'
            f'  </accessibility_tree>\n'
            f'</untrusted_web_content>'
        )


@dataclass
class BrowserCapture:
    url: str
    screenshot_base64: str
    format: str = "png"
    width: int = 1280
    height: int = 800
    timestamp: float = field(default_factory=time.time)


@dataclass
class BrowserDownload:
    file_name: str
    file_path: str
    size_bytes: int
    content_type: str
    downloaded_at: float = field(default_factory=time.time)


class BrowserProvider(ABC):
    """Authoritative abstract base class for all browser automation providers."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Returns the identifier for this browser provider (e.g. 'pinchtab', 'camofox')."""
        pass

    @abstractmethod
    def get_health(self) -> Dict[str, Any]:
        """Checks connectivity and returns provider runtime status."""
        pass

    @abstractmethod
    def create_session(self, session_id: str, profile_name: Optional[str] = None, user_id: Optional[str] = None) -> BrowserSession:
        """Allocates an isolated browser context."""
        pass

    @abstractmethod
    def close_session(self, session_id: str) -> bool:
        """Closes browser context and releases memory."""
        pass

    @abstractmethod
    def navigate(self, session_id: str, url: str, wait_until: str = "load") -> Dict[str, Any]:
        """Navigates session to destination URL."""
        pass

    @abstractmethod
    def snapshot(self, session_id: str, include_screenshot: bool = False) -> BrowserSnapshot:
        """Extracts token-efficient accessibility snapshot with stable element references."""
        pass

    @abstractmethod
    def capture(self, session_id: str, full_page: bool = False) -> BrowserCapture:
        """Captures a screenshot of the current page viewport."""
        pass

    @abstractmethod
    def click(self, session_id: str, element_ref: str) -> Dict[str, Any]:
        """Clicks an element by stable reference (e.g. 'e1')."""
        pass

    @abstractmethod
    def type_text(self, session_id: str, element_ref: str, text: str, submit: bool = False) -> Dict[str, Any]:
        """Types text into an input element."""
        pass

    @abstractmethod
    def press(self, session_id: str, key: str) -> Dict[str, Any]:
        """Sends keyboard key event (e.g. 'Enter', 'Tab', 'Escape')."""
        pass

    @abstractmethod
    def upload_file(self, session_id: str, element_ref: str, file_path: str) -> Dict[str, Any]:
        """Attaches local file from vault to file input element."""
        pass

    @abstractmethod
    def download_file(self, session_id: str, element_ref: str, target_dir: str) -> BrowserDownload:
        """Triggers element download action and intercepts result."""
        pass

    @abstractmethod
    def get_cookies(self, session_id: str, domain: Optional[str] = None) -> List[Dict[str, Any]]:
        """Retrieves active cookies for session."""
        pass
