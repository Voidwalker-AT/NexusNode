"""
NexusNode — LMS Data Models & Normalization Schema
Defines semantic abstractions for courses, resources, assignments, and submission plans.
"""

from enum import Enum
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field


class ResourceType(str, Enum):
    PDF = "pdf"
    FILE = "file"
    ARCHIVE = "archive"
    LINK = "link"
    PAGE = "page"
    FOLDER = "folder"
    UNKNOWN = "unknown"


class SubmissionState(str, Enum):
    DRAFT = "DRAFT"
    FILES_PREPARED = "FILES_PREPARED"
    UPLOADED_DRAFT = "UPLOADED_DRAFT"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    INVALID = "INVALID"
    EXPIRED = "EXPIRED"


@dataclass
class LMSCourse:
    course_id: str             # Normalized reference e.g. "lmscourse_100891"
    name: str                  # Course title e.g. "Cryptography and Network Security_Sem5"
    short_name: str            # Normalized short identifier e.g. "CNS_Sem5"
    provider_id: str           # Provider native ID e.g. "100891"
    url: str                   # Canonical course outline URL
    semester: Optional[str] = "Sem5"
    provider: str = "moodle"
    is_active: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "course_id": self.course_id,
            "name": self.name,
            "short_name": self.short_name,
            "provider_id": self.provider_id,
            "url": self.url,
            "semester": self.semester,
            "provider": self.provider,
            "is_active": self.is_active,
            "metadata": self.metadata
        }


@dataclass
class LMSResource:
    resource_id: str           # Normalized reference e.g. "lmsres_103840"
    course_id: str             # Associated normalized course reference
    title: str                 # Resource title e.g. "Books for the course File"
    resource_type: ResourceType
    section: Optional[str] = None
    downloadable: bool = True
    external: bool = False
    url: str = ""
    provider_id: str = ""
    file_extension: Optional[str] = None
    size_bytes: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "resource_id": self.resource_id,
            "course_id": self.course_id,
            "title": self.title,
            "resource_type": self.resource_type.value if isinstance(self.resource_type, ResourceType) else str(self.resource_type),
            "section": self.section,
            "downloadable": self.downloadable,
            "external": self.external,
            "url": self.url,
            "provider_id": self.provider_id,
            "file_extension": self.file_extension,
            "size_bytes": self.size_bytes,
            "metadata": self.metadata
        }


@dataclass
class LMSAssignment:
    assignment_id: str         # Normalized reference e.g. "lmsassign_112233"
    course_id: str             # Associated normalized course reference
    title: str                 # Assignment title e.g. "Lab Assignment 1"
    instructions: str          # Untrusted external instructions
    due_at: Optional[str] = None
    status: str = "OPEN"       # "OPEN", "SUBMITTED", "OVERDUE", "CLOSED"
    submitted: bool = False
    submission_allowed: bool = True
    allowed_file_types: List[str] = field(default_factory=list)
    max_files: int = 1
    max_bytes: int = 20971520   # 20 MB default
    current_files: List[Dict[str, Any]] = field(default_factory=list)
    url: str = ""
    provider_id: str = ""
    final_submission_control_present: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "assignment_id": self.assignment_id,
            "course_id": self.course_id,
            "title": self.title,
            "instructions": {
                "content_type": "untrusted_lms_content",
                "text": self.instructions
            },
            "due_at": self.due_at,
            "status": self.status,
            "submitted": self.submitted,
            "submission_allowed": self.submission_allowed,
            "allowed_file_types": self.allowed_file_types,
            "max_files": self.max_files,
            "max_bytes": self.max_bytes,
            "current_files": self.current_files,
            "url": self.url,
            "provider_id": self.provider_id,
            "final_submission_control_present": self.final_submission_control_present,
            "metadata": self.metadata
        }


@dataclass
class SubmissionPlan:
    submission_plan_id: str    # Unique ID e.g. "subplan_a1b2c3d4"
    user_id: str
    course_id: str
    assignment_id: str
    assignment_title: str
    vault_files: List[Dict[str, Any]]  # List of {"vault_path": ..., "size": ..., "sha256": ...}
    created_at: float
    expires_at: float
    page_url: str
    capture_id: Optional[str] = None
    screenshot_artifact: Optional[str] = None
    page_verified: bool = False
    draft_upload_verified: bool = False
    state: SubmissionState = SubmissionState.DRAFT
    final_action_required: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "submission_plan_id": self.submission_plan_id,
            "user_id": self.user_id,
            "course_id": self.course_id,
            "assignment_id": self.assignment_id,
            "assignment_title": self.assignment_title,
            "vault_files": self.vault_files,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "page_url": self.page_url,
            "capture_id": self.capture_id,
            "screenshot_artifact": self.screenshot_artifact,
            "page_verified": self.page_verified,
            "draft_upload_verified": self.draft_upload_verified,
            "state": self.state.value if isinstance(self.state, SubmissionState) else str(self.state),
            "final_action_required": self.final_action_required
        }
