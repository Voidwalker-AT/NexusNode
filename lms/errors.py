"""
NexusNode — LMS Domain Errors & Fault Classifications
Self-contained LMS exception hierarchy to eliminate circular package dependencies.
"""

from typing import Optional, Dict, Any


class LMSError(Exception):
    """Base exception for all LMS operations."""
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


class LMSAuthRequiredError(LMSError):
    """Raised when LMS session has expired or requires interactive user login."""
    code = "LMS_AUTH_REQUIRED"

    def __init__(self, message: str = "LMS authentication required. Please log into the LMS browser profile.", details: Optional[Dict[str, Any]] = None):
        super().__init__(message=message, details=details)


class LMSPageChangedError(LMSError):
    """Raised when the LMS DOM structure or navigation flow has changed unexpectedly."""
    code = "LMS_PAGE_CHANGED"

    def __init__(self, message: str = "LMS layout changed or expected elements missing.", details: Optional[Dict[str, Any]] = None):
        super().__init__(message=message, details=details)


class LMSAmbiguousCourseError(LMSError):
    """Raised when a course search matches multiple distinct courses."""
    code = "LMS_AMBIGUOUS_COURSE"

    def __init__(self, message: str = "Course query is ambiguous.", candidates: Optional[list] = None):
        details = {"candidates": candidates or []}
        super().__init__(message=message, details=details)


class LMSResourceNotFoundError(LMSError):
    """Raised when a requested resource identifier does not exist in the course."""
    code = "LMS_RESOURCE_NOT_FOUND"

    def __init__(self, message: str = "LMS resource not found.", details: Optional[Dict[str, Any]] = None):
        super().__init__(message=message, details=details)


class LMSAssignmentNotFoundError(LMSError):
    """Raised when an assignment identifier does not exist."""
    code = "LMS_ASSIGNMENT_NOT_FOUND"

    def __init__(self, message: str = "LMS assignment not found.", details: Optional[Dict[str, Any]] = None):
        super().__init__(message=message, details=details)


class SubmissionConsequentialBlockedError(LMSError):
    """Raised when an assignment form cannot be prepared safely without triggering immediate submission."""
    code = "SUBMISSION_CONSEQUENTIAL_BLOCKED"

    def __init__(self, message: str = "Submission form triggers immediate submission without separate draft stage. Final submission is blocked.", details: Optional[Dict[str, Any]] = None):
        super().__init__(message=message, details=details)


class SubmissionPlanInvalidError(LMSError):
    """Raised when submission plan validation fails (e.g. file modified or expired)."""
    code = "SUBMISSION_PLAN_INVALID"

    def __init__(self, message: str = "Submission plan is invalid or file hash mismatch.", details: Optional[Dict[str, Any]] = None):
        super().__init__(message=message, details=details)
