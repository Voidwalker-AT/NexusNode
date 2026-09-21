"""
NexusNode — LMS Provider Abstract Base Class
Defines the uniform contract for LMS implementations (Moodle, Blackboard, Canvas, etc.).
"""

from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any, Tuple
from .models import LMSCourse, LMSResource, LMSAssignment, SubmissionPlan


class LMSProvider(ABC):
    """Abstract interface for LMS provider adapters."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Returns the identifier of the provider (e.g. 'moodle')."""
        pass

    @abstractmethod
    def check_auth(self) -> bool:
        """Checks if current LMS session is authenticated."""
        pass

    @abstractmethod
    def list_courses(self, query: Optional[str] = None, active_only: bool = True) -> Tuple[List[LMSCourse], str]:
        """
        Lists enrolled academic courses.
        Returns tuple of (courses, transport) where transport is 'direct_http' or 'browser'.
        """
        pass

    @abstractmethod
    def get_course(self, course_id: str) -> Tuple[Optional[LMSCourse], Dict[str, Any], str]:
        """
        Gets detailed course outline, sections, and summary statistics.
        Returns tuple of (course, outline_dict, transport).
        """
        pass

    @abstractmethod
    def list_resources(self, course_id: str, section: Optional[str] = None) -> Tuple[List[LMSResource], str]:
        """
        Lists all downloadable and viewable resources in a course.
        Returns tuple of (resources, transport).
        """
        pass

    @abstractmethod
    def download_resource(self, resource_id: str, dest_vault_abs_path: str, max_bytes: int = 52428800) -> Dict[str, Any]:
        """
        Downloads a resource file directly into a destination path in the user Vault.
        Enforces maximum download byte limits.
        """
        pass

    @abstractmethod
    def list_assignments(self, course_id: Optional[str] = None, upcoming_only: bool = False) -> Tuple[List[LMSAssignment], str]:
        """
        Lists assignments for a specific course or across all active enrolled courses.
        Returns tuple of (assignments, transport).
        """
        pass

    @abstractmethod
    def get_assignment(self, assignment_id: str) -> Tuple[Optional[LMSAssignment], str]:
        """
        Retrieves detailed assignment information, instructions, and submission parameters.
        Returns tuple of (assignment, transport).
        """
        pass

    @abstractmethod
    def prepare_submission(
        self,
        assignment_id: str,
        vault_file_records: List[Dict[str, Any]],
        browser_service=None
    ) -> Tuple[Dict[str, Any], str]:
        """
        Prepares a draft submission in the LMS browser workflow.
        Validates page identity, ensures safe draft semantics, attaches files,
        captures screenshot proof, and returns verification details.
        """
        pass

    def submit_final_assignment(
        self,
        assignment_id: str,
        vault_file_records: List[Dict[str, Any]],
        browser_service=None,
        session_id: Optional[str] = None
    ) -> Tuple[bool, Dict[str, Any], str]:
        """
        Executes the final assignment submission sequence under privileged server-side control.
        Returns: (success: bool, result_details: dict, transport: str)
        """
        raise NotImplementedError("submit_final_assignment must be implemented by LMSProvider subclass.")

    def inspect_submission_status(
        self,
        assignment_id: str,
        browser_service=None
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Inspects remote LMS assignment submission status for positive proof / crash recovery.
        Returns: (is_submitted: bool, status_details: dict)
        """
        return False, {}

