"""
NexusNode — Agent Execution Foundation Errors
Structured, typed exceptions and normalized error codes.
Never exposes raw stack traces, local paths, or credentials to clients/agents.
"""

from typing import Optional, Dict, Any


class NexusAgentError(Exception):
    """Base exception for all agent execution operations."""
    code = "INTERNAL_ERROR"

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "error": self.message,
            "error_code": self.code,
            "details": self.details
        }


# Authentication & Session Errors
class AuthRequiredError(NexusAgentError):
    code = "AUTH_REQUIRED"


class SessionExpiredError(NexusAgentError):
    code = "SESSION_EXPIRED"


class InteractionRequiredError(NexusAgentError):
    code = "INTERACTION_REQUIRED"


# Browser Provider Errors
class BrowserUnavailableError(NexusAgentError):
    code = "BROWSER_UNAVAILABLE"


class BrowserConnectionError(NexusAgentError):
    code = "BROWSER_CONNECTION_FAILED"


class BrowserSessionError(NexusAgentError):
    code = "BROWSER_SESSION_FAILED"


class NavigationFailedError(NexusAgentError):
    code = "NAVIGATION_FAILED"


class ElementStaleError(NexusAgentError):
    code = "ELEMENT_STALE"


class UploadFailedError(NexusAgentError):
    code = "UPLOAD_FAILED"


class DownloadFailedError(NexusAgentError):
    code = "DOWNLOAD_FAILED"


class SecurityChallengeError(NexusAgentError):
    code = "SECURITY_CHALLENGE"


# Resource Governor Errors
class ResourcePressureError(NexusAgentError):
    code = "RESOURCE_PRESSURE"


# Policy & Approval Errors
class ApprovalRequiredError(NexusAgentError):
    code = "APPROVAL_REQUIRED"

    def __init__(self, message: str, approval_id: str, details: Optional[Dict[str, Any]] = None):
        details = details or {}
        details["approval_id"] = approval_id
        super().__init__(message, details)
        self.approval_id = approval_id


class ApprovalDeniedError(NexusAgentError):
    code = "APPROVAL_DENIED"


class ApprovalExpiredError(NexusAgentError):
    code = "APPROVAL_EXPIRED"


# Upstream & Internal Errors
class UpstreamError(NexusAgentError):
    code = "UPSTREAM_ERROR"


class ConsequentialActionBlockedError(NexusAgentError):
    code = "CONSEQUENTIAL_ACTION_BLOCKED"


class InvalidParamsError(NexusAgentError):
    code = "INVALID_PARAMS"


class AccessDeniedError(NexusAgentError):
    code = "ACCESS_DENIED"


class InternalError(NexusAgentError):
    code = "INTERNAL_ERROR"

