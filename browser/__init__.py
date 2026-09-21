"""
NexusNode — Browser Provider Package
"""

from .base import (
    BrowserProvider,
    BrowserSession,
    BrowserSnapshot,
    BrowserElement,
    BrowserCapture,
    BrowserDownload,
)
from .pinchtab import PinchTabProvider
from .camofox import CamofoxProvider
from .bg6_cdp import BG6EphemeralCDPProvider
from .cdp_client import CDPClient, select_page_target
from .profile_manager import ProfileManager, ProfileType
from .chromium_runtime import EphemeralChromiumRuntime, MemoryAdmissionGovernor
from .observation import BrowserObservation, build_bounded_observation, ElementStaleError

__all__ = [
    "BrowserProvider",
    "BrowserSession",
    "BrowserSnapshot",
    "BrowserElement",
    "BrowserCapture",
    "BrowserDownload",
    "BG6EphemeralCDPProvider",
    "PinchTabProvider",
    "CamofoxProvider",
    "CDPClient",
    "select_page_target",
    "ProfileManager",
    "ProfileType",
    "EphemeralChromiumRuntime",
    "MemoryAdmissionGovernor",
    "BrowserObservation",
    "build_bounded_observation",
    "ElementStaleError",
]
