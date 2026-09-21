"""
NexusNode — High-Level Agent LMS Semantic Service
Coordinates course discovery, resource retrieval, assignment queries, and draft submission preparation.
Enforces short-lived caching with truthful provenance, disambiguation guards, and submission plan immutability.
"""

import os
import re
import time
import json
import uuid
import hashlib
import sqlite3
import logging
from typing import Dict, Any, List, Optional, Tuple

import config
from .models import ExecutionResult
from .errors import (
    NexusAgentError,
    InternalError,
    AuthRequiredError
)
from lms.models import (
    LMSCourse,
    LMSResource,
    LMSAssignment,
    SubmissionPlan,
    SubmissionState
)
from lms.errors import (
    LMSAuthRequiredError,
    LMSPageChangedError,
    LMSAmbiguousCourseError,
    LMSResourceNotFoundError,
    LMSAssignmentNotFoundError,
    SubmissionConsequentialBlockedError,
    SubmissionPlanInvalidError
)
from lms.moodle import MoodleProvider
from .consequential import (
    ConsequentialActionManager,
    ConsequentialExecutor,
    init_consequential_tables
)
from .models import (
    ConsequentialAction,
    ApprovalGrant,
    ConsequentialState,
    ApprovalState
)

logger = logging.getLogger("NEXUS_LMS_SERVICE")


def init_lms_tables(conn: sqlite3.Connection):
    """Initializes SQLite persistence for submission plans and consequential tables."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS submission_plans (
            submission_plan_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            course_id TEXT NOT NULL,
            assignment_id TEXT NOT NULL,
            assignment_title TEXT NOT NULL,
            vault_files_json TEXT NOT NULL,
            created_at REAL NOT NULL,
            expires_at REAL NOT NULL,
            page_url TEXT NOT NULL,
            capture_id TEXT,
            screenshot_artifact TEXT,
            page_verified INTEGER NOT NULL DEFAULT 0,
            draft_upload_verified INTEGER NOT NULL DEFAULT 0,
            state TEXT NOT NULL DEFAULT 'DRAFT',
            final_action_required INTEGER NOT NULL DEFAULT 1
        );
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_subplans_user ON submission_plans (user_id);")
    init_consequential_tables(conn)


class LMSService:
    """High-level semantic LMS service wrapping provider adapters."""

    def __init__(
        self,
        conn_factory,
        provider=None,
        browser_service=None,
        consequential_mgr=None,
        cache_ttl_sec: int = 600
    ):
        self.conn_factory = conn_factory
        self.provider = provider or MoodleProvider(browser_service=browser_service)
        self.browser_service = browser_service
        self.cache_ttl_sec = cache_ttl_sec
        self.consequential_mgr = consequential_mgr or ConsequentialActionManager(conn_factory)
        self.consequential_executor = ConsequentialExecutor(self.consequential_mgr, conn_factory)
        self._course_cache: Dict[str, Tuple[List[LMSCourse], float, str]] = {}  # key -> (courses, fetched_at, transport)

        conn = self.conn_factory()
        try:
            init_lms_tables(conn)
            conn.commit()
        finally:
            conn.close()


    def list_courses(self, user_id: str, params: Dict[str, Any]) -> ExecutionResult:
        """
        Lists enrolled academic courses with disambiguation and provenance tracking.
        Params:
          query (str, optional): Search filter (e.g. 'Deep Learning', 'CNS', '100891').
          active_only (bool, default True): Filter to active semester courses.
        """
        now = time.time()
        query = params.get("query")
        active_only = params.get("active_only", True)

        try:
            cache_key = f"{user_id}:courses"
            courses = []
            transport = "direct_http"
            src = "live"
            fetched_ts = now

            if cache_key in self._course_cache:
                c_list, c_ts, c_trans = self._course_cache[cache_key]
                if (now - c_ts) < self.cache_ttl_sec:
                    courses = c_list
                    transport = c_trans
                    src = "local"
                    fetched_ts = c_ts

            if not courses:
                courses, transport = self.provider.list_courses(active_only=active_only)
                self._course_cache[cache_key] = (courses, now, transport)
                src = "live"
                fetched_ts = now

            # If query is provided, perform strict disambiguation
            if query:
                q_clean = query.strip().lower()
                matched = []
                for c in courses:
                    name_lower = c.name.lower()
                    short_lower = c.short_name.lower()
                    cid_lower = c.course_id.lower()
                    
                    # Exact ID match
                    if q_clean == cid_lower or q_clean == c.provider_id:
                        matched = [c]
                        break
                    # Exact or word token match
                    if q_clean in name_lower or q_clean in short_lower:
                        matched.append(c)
                        continue

                    # Acronym match (e.g. "cns" -> "Cryptography and Network Security")
                    words = [w for w in re.findall(r'[A-Za-z]+', c.name) if w.lower() not in ('and', 'of', 'in', 'the', 'for', 'sem', 'sem5')]
                    acronym = "".join(w[0] for w in words).lower()
                    if q_clean == acronym or q_clean in acronym:
                        matched.append(c)

                if len(matched) > 1:
                    # Check if one is an exact match for query
                    exact = [m for m in matched if q_clean == m.name.lower() or q_clean == m.short_name.lower()]
                    if len(exact) == 1:
                        matched = exact
                    else:
                        candidates = [{"course_id": m.course_id, "name": m.name, "short_name": m.short_name} for m in matched]
                        return ExecutionResult(
                            ok=False,
                            operation="lms.list_courses",
                            source=src,
                            provider=self.provider.provider_name,
                            error=f"Course query '{query}' is ambiguous. Matched {len(matched)} courses.",
                            error_code="LMS_AMBIGUOUS_COURSE",
                            metadata={"candidates": candidates},
                            fetched_at=fetched_ts
                        )
                courses = matched

            return ExecutionResult(
                ok=True,
                operation="lms.list_courses",
                source=src,
                provider=self.provider.provider_name,
                data={
                    "total_courses": len(courses),
                    "courses": [c.to_dict() for c in courses]
                },
                fetched_at=fetched_ts,
                metadata={"transport": transport, "cache_age_seconds": round(now - fetched_ts, 1)}
            )
        except LMSAuthRequiredError as are:
            return ExecutionResult(
                ok=False,
                operation="lms.list_courses",
                source="live",
                provider=self.provider.provider_name,
                error=are.message,
                error_code=are.code,
                fetched_at=now
            )
        except Exception as e:
            logger.exception("Failed to list LMS courses")
            return ExecutionResult(
                ok=False,
                operation="lms.list_courses",
                source="local",
                provider=self.provider.provider_name,
                error=str(e),
                error_code="INTERNAL_ERROR",
                fetched_at=now
            )

    def get_course(self, user_id: str, params: Dict[str, Any]) -> ExecutionResult:
        """
        Gets detailed course outline, sections, and activity counts.
        Params:
          course_id (str): Normalized reference (e.g. 'lmscourse_100891') or course query.
        """
        now = time.time()
        course_target = params.get("course_id") or params.get("query")
        if not course_target:
            return ExecutionResult(
                ok=False,
                operation="lms.get_course",
                source="local",
                provider=self.provider.provider_name,
                error="Parameter 'course_id' or 'query' is required.",
                error_code="INVALID_PARAMETER",
                fetched_at=now
            )

        # Disambiguate if target is a course title or partial code
        if not course_target.startswith("lmscourse_") and not course_target.isdigit():
            c_res = self.list_courses(user_id, {"query": course_target})
            if not c_res.ok or not c_res.data.get("courses"):
                return ExecutionResult(
                    ok=False,
                    operation="lms.get_course",
                    source="local",
                    provider=self.provider.provider_name,
                    error=c_res.error or f"Course '{course_target}' not found.",
                    error_code=c_res.error_code or "LMS_COURSE_NOT_FOUND",
                    metadata=c_res.metadata,
                    fetched_at=now
                )
            course_target = c_res.data["courses"][0]["course_id"]

        try:
            course, outline, transport = self.provider.get_course(course_target)
            if not course:
                return ExecutionResult(
                    ok=False,
                    operation="lms.get_course",
                    source="live",
                    provider=self.provider.provider_name,
                    error=f"Course '{course_target}' outline not found.",
                    error_code="LMS_COURSE_NOT_FOUND",
                    fetched_at=now
                )

            return ExecutionResult(
                ok=True,
                operation="lms.get_course",
                source="live",
                provider=self.provider.provider_name,
                data=outline,
                fetched_at=now,
                metadata={"transport": transport}
            )
        except LMSAuthRequiredError as are:
            return ExecutionResult(
                ok=False,
                operation="lms.get_course",
                source="live",
                provider=self.provider.provider_name,
                error=are.message,
                error_code=are.code,
                fetched_at=now
            )
        except Exception as e:
            return ExecutionResult(
                ok=False,
                operation="lms.get_course",
                source="local",
                provider=self.provider.provider_name,
                error=str(e),
                error_code="INTERNAL_ERROR",
                fetched_at=now
            )

    def list_resources(self, user_id: str, params: Dict[str, Any]) -> ExecutionResult:
        """
        Lists downloadable and viewable materials in a course.
        Params:
          course_id (str): Course reference or query.
          section (str, optional): Section filter.
        """
        now = time.time()
        course_target = params.get("course_id") or params.get("query")
        if not course_target:
            return ExecutionResult(
                ok=False,
                operation="lms.list_resources",
                source="local",
                provider=self.provider.provider_name,
                error="Parameter 'course_id' is required.",
                error_code="INVALID_PARAMETER",
                fetched_at=now
            )

        if not course_target.startswith("lmscourse_") and not course_target.isdigit():
            c_res = self.list_courses(user_id, {"query": course_target})
            if not c_res.ok or not c_res.data.get("courses"):
                return c_res
            course_target = c_res.data["courses"][0]["course_id"]

        try:
            resources, transport = self.provider.list_resources(course_target, section=params.get("section"))
            return ExecutionResult(
                ok=True,
                operation="lms.list_resources",
                source="live",
                provider=self.provider.provider_name,
                data={
                    "course_id": course_target,
                    "total_resources": len(resources),
                    "resources": [r.to_dict() for r in resources]
                },
                fetched_at=now,
                metadata={"transport": transport}
            )
        except LMSAuthRequiredError as are:
            return ExecutionResult(
                ok=False,
                operation="lms.list_resources",
                source="live",
                provider=self.provider.provider_name,
                error=are.message,
                error_code=are.code,
                fetched_at=now
            )
        except Exception as e:
            return ExecutionResult(
                ok=False,
                operation="lms.list_resources",
                source="local",
                provider=self.provider.provider_name,
                error=str(e),
                error_code="INTERNAL_ERROR",
                fetched_at=now
            )

    def download_resource(self, user_id: str, params: Dict[str, Any]) -> ExecutionResult:
        """
        Downloads a course resource file into the user's Vault.
        Params:
          resource_id (str): Resource identifier (e.g. 'lmsres_103840').
          destination_path (str): Target directory or file path in Vault (e.g. 'Cryptography/Books.zip').
        """
        now = time.time()
        resource_id = params.get("resource_id")
        destination_path = params.get("destination_path") or params.get("vault_destination")

        if not resource_id or not destination_path:
            return ExecutionResult(
                ok=False,
                operation="lms.download_resource",
                source="local",
                provider=self.provider.provider_name,
                error="Parameters 'resource_id' and 'destination_path' are required.",
                error_code="INVALID_PARAMETER",
                fetched_at=now
            )

        vault_root = getattr(config, "AGENT_VAULT_ROOT", r"E:\Workspace\Active\server\storage_vault\user_files")
        clean_rel = os.path.normpath(destination_path.strip().lstrip("/\\"))
        if clean_rel.startswith(".."):
            return ExecutionResult(
                ok=False,
                operation="lms.download_resource",
                source="local",
                provider=self.provider.provider_name,
                error="Path traversal outside Vault boundary is prohibited.",
                error_code="PATH_TRAVERSAL_DETECTED",
                fetched_at=now
            )

        target_abs = os.path.join(vault_root, clean_rel)

        try:
            res_meta = self.provider.download_resource(resource_id, target_abs, max_bytes=getattr(config, "MAX_LMS_DOWNLOAD_BYTES", 52428800))
            
            # Compute relative vault path
            rel_vault = os.path.relpath(res_meta["vault_dest_path"], vault_root).replace("\\", "/")
            return ExecutionResult(
                ok=True,
                operation="lms.download_resource",
                source="live",
                provider=self.provider.provider_name,
                data={
                    "vault_path": rel_vault,
                    "filename": res_meta["filename"],
                    "mime_type": res_meta["mime_type"],
                    "size_bytes": res_meta["size_bytes"],
                    "sha256": res_meta["sha256"],
                    "source_url": res_meta["source_url"],
                    "downloaded_at": res_meta["downloaded_at"]
                },
                fetched_at=now,
                metadata={"transport": "direct_http"}
            )
        except LMSAuthRequiredError as are:
            return ExecutionResult(
                ok=False,
                operation="lms.download_resource",
                source="live",
                provider=self.provider.provider_name,
                error=are.message,
                error_code=are.code,
                fetched_at=now
            )
        except Exception as e:
            return ExecutionResult(
                ok=False,
                operation="lms.download_resource",
                source="local",
                provider=self.provider.provider_name,
                error=str(e),
                error_code="DOWNLOAD_FAILED",
                fetched_at=now
            )

    def list_assignments(self, user_id: str, params: Dict[str, Any]) -> ExecutionResult:
        """
        Lists assignments for a specific course or across all enrolled courses.
        Params:
          course_id (str, optional): Course identifier or query.
          upcoming_only (bool, default False): Filter to open/upcoming assignments.
        """
        now = time.time()
        course_target = params.get("course_id")
        if course_target and not course_target.startswith("lmscourse_") and not course_target.isdigit():
            c_res = self.list_courses(user_id, {"query": course_target})
            if c_res.ok and c_res.data.get("courses"):
                course_target = c_res.data["courses"][0]["course_id"]

        try:
            assignments, transport = self.provider.list_assignments(course_target, upcoming_only=params.get("upcoming_only", False))
            return ExecutionResult(
                ok=True,
                operation="lms.list_assignments",
                source="live",
                provider=self.provider.provider_name,
                data={
                    "total_assignments": len(assignments),
                    "assignments": [a.to_dict() for a in assignments]
                },
                fetched_at=now,
                metadata={"transport": transport}
            )
        except LMSAuthRequiredError as are:
            return ExecutionResult(
                ok=False,
                operation="lms.list_assignments",
                source="live",
                provider=self.provider.provider_name,
                error=are.message,
                error_code=are.code,
                fetched_at=now
            )
        except Exception as e:
            return ExecutionResult(
                ok=False,
                operation="lms.list_assignments",
                source="local",
                provider=self.provider.provider_name,
                error=str(e),
                error_code="INTERNAL_ERROR",
                fetched_at=now
            )

    def get_assignment(self, user_id: str, params: Dict[str, Any]) -> ExecutionResult:
        """
        Retrieves detailed assignment information and instructions.
        Params:
          assignment_id (str): Assignment reference (e.g. 'lmsassign_112233').
        """
        now = time.time()
        assignment_id = params.get("assignment_id")
        if not assignment_id:
            return ExecutionResult(
                ok=False,
                operation="lms.get_assignment",
                source="local",
                provider=self.provider.provider_name,
                error="Parameter 'assignment_id' is required.",
                error_code="INVALID_PARAMETER",
                fetched_at=now
            )

        try:
            assignment, transport = self.provider.get_assignment(assignment_id)
            if not assignment:
                return ExecutionResult(
                    ok=False,
                    operation="lms.get_assignment",
                    source="live",
                    provider=self.provider.provider_name,
                    error=f"Assignment '{assignment_id}' not found.",
                    error_code="LMS_ASSIGNMENT_NOT_FOUND",
                    fetched_at=now
                )

            return ExecutionResult(
                ok=True,
                operation="lms.get_assignment",
                source="live",
                provider=self.provider.provider_name,
                data=assignment.to_dict(),
                fetched_at=now,
                metadata={"transport": transport}
            )
        except LMSAuthRequiredError as are:
            return ExecutionResult(
                ok=False,
                operation="lms.get_assignment",
                source="live",
                provider=self.provider.provider_name,
                error=are.message,
                error_code=are.code,
                fetched_at=now
            )
        except Exception as e:
            return ExecutionResult(
                ok=False,
                operation="lms.get_assignment",
                source="local",
                provider=self.provider.provider_name,
                error=str(e),
                error_code="INTERNAL_ERROR",
                fetched_at=now
            )

    def prepare_submission(self, user_id: str, params: Dict[str, Any]) -> ExecutionResult:
        """
        Prepares a draft submission plan and attaches verified files.
        STRICTLY PREPARATORY: Does NOT execute final submission.
        Params:
          assignment_id (str): Target assignment reference.
          vault_paths (list[str]): List of relative file paths in Vault.
        """
        now = time.time()
        assignment_id = params.get("assignment_id")
        vault_paths = params.get("vault_paths") or []

        if not assignment_id or not vault_paths:
            return ExecutionResult(
                ok=False,
                operation="lms.prepare_submission",
                source="local",
                provider=self.provider.provider_name,
                error="Parameters 'assignment_id' and 'vault_paths' are required.",
                error_code="INVALID_PARAMETER",
                fetched_at=now
            )

        vault_root = getattr(config, "AGENT_VAULT_ROOT", r"E:\Workspace\Active\server\storage_vault\user_files")
        
        # 1. Validate and Hash all Vault files
        file_records = []
        for vp in vault_paths:
            clean_rel = os.path.normpath(vp.strip().lstrip("/\\"))
            if clean_rel.startswith(".."):
                return ExecutionResult(
                    ok=False,
                    operation="lms.prepare_submission",
                    source="local",
                    provider=self.provider.provider_name,
                    error=f"Invalid vault path: '{vp}'",
                    error_code="PATH_TRAVERSAL_DETECTED",
                    fetched_at=now
                )
            abs_p = os.path.join(vault_root, clean_rel)
            if not os.path.isfile(abs_p):
                return ExecutionResult(
                    ok=False,
                    operation="lms.prepare_submission",
                    source="local",
                    provider=self.provider.provider_name,
                    error=f"File '{vp}' not found in user Vault.",
                    error_code="FILE_NOT_FOUND",
                    fetched_at=now
                )
            with open(abs_p, "rb") as f:
                data = f.read()
                file_records.append({
                    "vault_path": clean_rel.replace("\\", "/"),
                    "size": len(data),
                    "sha256": hashlib.sha256(data).hexdigest()
                })

        try:
            # 2. Execute interactive preparation via provider
            prep_data, transport = self.provider.prepare_submission(
                assignment_id=assignment_id,
                vault_file_records=file_records,
                browser_service=self.browser_service
            )

            # 3. Create persistent SubmissionPlan
            plan_id = f"subplan_{uuid.uuid4().hex[:12]}"
            expires_at = now + 3600.0  # 1 hour validity

            plan = SubmissionPlan(
                submission_plan_id=plan_id,
                user_id=user_id,
                course_id=params.get("course_id", ""),
                assignment_id=assignment_id,
                assignment_title=params.get("assignment_title", f"Assignment {assignment_id}"),
                vault_files=file_records,
                created_at=now,
                expires_at=expires_at,
                page_url=prep_data.get("current_url", ""),
                capture_id=prep_data.get("capture_id"),
                screenshot_artifact=prep_data.get("screenshot_artifact"),
                page_verified=prep_data.get("page_verified", False),
                draft_upload_verified=prep_data.get("draft_upload_verified", False),
                state=SubmissionState.READY_FOR_REVIEW if prep_data.get("page_verified") else SubmissionState.DRAFT,
                final_action_required=True
            )

            # 4. Save plan to SQLite
            conn = self.conn_factory()
            try:
                conn.execute("""
                    INSERT INTO submission_plans (
                        submission_plan_id, user_id, course_id, assignment_id, assignment_title,
                        vault_files_json, created_at, expires_at, page_url, capture_id,
                        screenshot_artifact, page_verified, draft_upload_verified, state,
                        final_action_required
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    plan.submission_plan_id, plan.user_id, plan.course_id, plan.assignment_id,
                    plan.assignment_title, json.dumps(plan.vault_files), plan.created_at,
                    plan.expires_at, plan.page_url, plan.capture_id, plan.screenshot_artifact,
                    1 if plan.page_verified else 0, 1 if plan.draft_upload_verified else 0,
                    plan.state.value if isinstance(plan.state, SubmissionState) else str(plan.state),
                    1 if plan.final_action_required else 0
                ))
                conn.commit()
            finally:
                conn.close()

            return ExecutionResult(
                ok=True,
                operation="lms.prepare_submission",
                source="live",
                provider=self.provider.provider_name,
                data=plan.to_dict(),
                fetched_at=now,
                metadata={"transport": transport}
            )
        except Exception as e:
            logger.exception("Submission preparation failed")
            return ExecutionResult(
                ok=False,
                operation="lms.prepare_submission",
                source="local",
                provider=self.provider.provider_name,
                error=str(e),
                error_code="SUBMISSION_PREPARATION_FAILED",
                fetched_at=now
            )

    def _get_submission_plan(self, plan_id: str) -> Optional[SubmissionPlan]:
        """Fetches a SubmissionPlan from SQLite by plan_id."""
        conn = self.conn_factory()
        conn.row_factory = sqlite3.Row
        try:
            cur = conn.cursor()

            cur.execute("SELECT * FROM submission_plans WHERE submission_plan_id = ?", (plan_id,))
            row = cur.fetchone()
            if not row:
                return None
            return SubmissionPlan(
                submission_plan_id=row["submission_plan_id"],
                user_id=row["user_id"],
                course_id=row["course_id"],
                assignment_id=row["assignment_id"],
                assignment_title=row["assignment_title"],
                vault_files=json.loads(row["vault_files_json"]),
                created_at=float(row["created_at"]),
                expires_at=float(row["expires_at"]),
                page_url=row["page_url"],
                capture_id=row["capture_id"],
                screenshot_artifact=row["screenshot_artifact"],
                page_verified=bool(row["page_verified"]),
                draft_upload_verified=bool(row["draft_upload_verified"]),
                state=SubmissionState(row["state"]),
                final_action_required=bool(row["final_action_required"])
            )
        finally:
            conn.close()

    def _verify_vault_files_unmodified(self, plan: SubmissionPlan) -> Tuple[bool, Optional[str]]:
        """
        Revalidates every Vault file on disk to protect against TOCTOU parameter drift.
        Verifies existence, accessibility, size, and SHA-256 hash.
        """
        vault_root = os.path.realpath(config.AGENT_VAULT_ROOT)
        for vf in plan.vault_files:
            rel_path = vf.get("vault_path", "").replace("\\", "/").lstrip("/")
            full_path = os.path.realpath(os.path.join(vault_root, rel_path))
            if not full_path.startswith(vault_root) or not os.path.exists(full_path):
                return False, f"Vault file '{rel_path}' no longer exists at approved path."
            try:
                with open(full_path, "rb") as f:
                    data = f.read()
                current_hash = hashlib.sha256(data).hexdigest()
                if current_hash != vf.get("sha256"):
                    return False, f"Vault file '{rel_path}' content was modified after preparation (TOCTOU violation)."
            except Exception as e:
                return False, f"Failed to verify Vault file '{rel_path}': {e}"
        return True, None

    def submit_assignment(self, user_id: str, params: Dict[str, Any], principal: str = "spark-agent") -> ExecutionResult:
        """
        Requests final assignment submission for a prepared SubmissionPlan.
        Enforces consequential action boundaries: calling without user approval produces
        APPROVAL_REQUIRED, creates ConsequentialAction & ApprovalRequest, and returns safe metadata.
        """
        now = time.time()
        plan_id = str(params.get("submission_plan_id") or "").strip()
        if not plan_id:
            return ExecutionResult(
                ok=False,
                operation="lms.submit_assignment",
                source="local",
                provider=self.provider.provider_name,
                error="Parameter 'submission_plan_id' is required.",
                error_code="INVALID_ARGUMENTS",
                fetched_at=now
            )

        plan = self._get_submission_plan(plan_id)
        if not plan:
            return ExecutionResult(
                ok=False,
                operation="lms.submit_assignment",
                source="local",
                provider=self.provider.provider_name,
                error=f"SubmissionPlan '{plan_id}' not found.",
                error_code="SUBMISSION_PLAN_NOT_FOUND",
                fetched_at=now
            )

        if plan.user_id != user_id:
            return ExecutionResult(
                ok=False,
                operation="lms.submit_assignment",
                source="local",
                provider=self.provider.provider_name,
                error="Unauthorized: SubmissionPlan belongs to a different user.",
                error_code="UNAUTHORIZED",
                fetched_at=now
            )

        if plan.expires_at < now:
            return ExecutionResult(
                ok=False,
                operation="lms.submit_assignment",
                source="local",
                provider=self.provider.provider_name,
                error=f"SubmissionPlan '{plan_id}' has expired.",
                error_code="SUBMISSION_PLAN_EXPIRED",
                fetched_at=now
            )


        if plan.state not in (SubmissionState.READY_FOR_REVIEW, SubmissionState.DRAFT):
            return ExecutionResult(
                ok=False,
                operation="lms.submit_assignment",
                source="local",
                provider=self.provider.provider_name,
                error=f"SubmissionPlan is in state '{plan.state}', cannot request submission.",
                error_code="INVALID_PLAN_STATE",
                fetched_at=now
            )

        # TOCTOU check on disk
        files_valid, err_msg = self._verify_vault_files_unmodified(plan)
        if not files_valid:
            # Invalidate plan in SQLite
            conn = self.conn_factory()
            try:
                conn.execute("UPDATE submission_plans SET state = 'INVALIDATED' WHERE submission_plan_id = ?", (plan_id,))
                conn.commit()
            finally:
                conn.close()
            return ExecutionResult(
                ok=False,
                operation="lms.submit_assignment",
                source="local",
                provider=self.provider.provider_name,
                error=f"Plan invalidated: {err_msg}",
                error_code="TOCTOU_VIOLATION",
                fetched_at=now
            )

        # Build authoritative structured summary and evidence references
        summary = {
            "submission_plan_id": plan.submission_plan_id,
            "course_id": plan.course_id,
            "assignment_id": plan.assignment_id,
            "assignment_title": plan.assignment_title,
            "files": [
                {
                    "vault_path": f["vault_path"],
                    "size": f["size"],
                    "sha256": f["sha256"]
                }
                for f in plan.vault_files
            ],
            "page_verified": plan.page_verified,
            "target_url": plan.page_url,
            "pre_submit_capture_id": plan.capture_id,
            "pre_submit_screenshot": plan.screenshot_artifact,
            "plan_expires_at": plan.expires_at
        }

        evidence_references = {
            "submission_plan_id": plan.submission_plan_id,
            "capture_id": plan.capture_id,
            "screenshot_artifact": plan.screenshot_artifact,
            "vault_files": plan.vault_files,
            "page_url": plan.page_url
        }

        # Request consequential action & approval from manager
        action, approval, is_deduped = self.consequential_mgr.request_consequential_action(
            user_id=user_id,
            principal=principal,
            operation="lms.submit_assignment",
            target_type="moodle_assignment",
            target_id=plan.assignment_id,
            parameters={"submission_plan_id": plan.submission_plan_id, "files": plan.vault_files},
            summary=summary,
            evidence_references=evidence_references,
            ttl_seconds=900.0  # 15 minutes
        )

        return ExecutionResult(
            ok=False,
            operation="lms.submit_assignment",
            source="local",
            provider=self.provider.provider_name,
            data={
                "status": "approval_required",
                "action_id": action.action_id,
                "approval_id": approval.approval_id,
                "operation": "lms.submit_assignment",
                "target": f"moodle_assignment:{plan.assignment_id}",
                "expires_at": approval.expires_at,
                "summary": summary,
                "is_existing_approval": is_deduped
            },
            error="Operation 'lms.submit_assignment' is consequential and requires user approval.",
            error_code="APPROVAL_REQUIRED",
            fetched_at=now
        )

    def get_action_status(self, user_id: str, params: Dict[str, Any]) -> ExecutionResult:
        """
        Queries the current lifecycle state of a consequential action (READ_ONLY).
        Spark-safe: Returns public state and execution results without exposing secret tokens.
        """
        now = time.time()
        action_id = str(params.get("action_id") or "").strip()
        if not action_id:
            return ExecutionResult(
                ok=False,
                operation="action.status",
                source="local",
                provider="nexusnode",
                error="Parameter 'action_id' is required.",
                error_code="INVALID_ARGUMENTS",
                fetched_at=now
            )

        action = self.consequential_mgr.get_action(action_id)
        if not action:
            return ExecutionResult(
                ok=False,
                operation="action.status",
                source="local",
                provider="nexusnode",
                error=f"Consequential action '{action_id}' not found.",
                error_code="ACTION_NOT_FOUND",
                fetched_at=now
            )

        if action.user_id != user_id:
            return ExecutionResult(
                ok=False,
                operation="action.status",
                source="local",
                provider="nexusnode",
                error="Unauthorized: Action belongs to a different user.",
                error_code="UNAUTHORIZED",
                fetched_at=now
            )

        return ExecutionResult(
            ok=True,
            operation="action.status",
            source="local",
            provider="nexusnode",
            data=action.to_dict(),
            fetched_at=now
        )

    def execute_approved_submission(
        self,
        action: ConsequentialAction,
        grant: ApprovalGrant
    ) -> Tuple[bool, Dict[str, Any], Optional[str]]:
        """
        Internal privileged submission execution pipeline called ONLY by ConsequentialExecutor.
        Enforces TOCTOU file checks, target re-verification, executes final submit,
        and records positive proof.
        """
        params = action.summary
        plan_id = params.get("submission_plan_id")
        plan = self._get_submission_plan(plan_id) if plan_id else None

        if not plan:
            return False, {}, f"SubmissionPlan '{plan_id}' not found during execution."

        # 1. TOCTOU Re-verification immediately before submit
        files_valid, err_msg = self._verify_vault_files_unmodified(plan)
        if not files_valid:
            self.consequential_mgr.invalidate_action(action.action_id, f"TOCTOU violation: {err_msg}")
            return False, {}, f"Execution rejected due to file modification: {err_msg}"

        # 2. Re-verify assignment identity
        if plan.assignment_id != action.target_id:
            self.consequential_mgr.invalidate_action(action.action_id, "Target assignment ID mismatch.")
            return False, {}, f"Assignment ID mismatch: expected {action.target_id}, found {plan.assignment_id}"

        # 3. Execute final submission via provider
        success, result_details, transport = self.provider.submit_final_assignment(
            assignment_id=plan.assignment_id,
            vault_file_records=plan.vault_files,
            browser_service=self.browser_service
        )

        # 4. Update SubmissionPlan state on positive proof
        if success and result_details.get("verified"):
            conn = self.conn_factory()
            try:
                conn.execute("UPDATE submission_plans SET state = 'SUBMITTED' WHERE submission_plan_id = ?", (plan_id,))
                conn.commit()
            finally:
                conn.close()

        result_details["submission_plan_id"] = plan_id
        result_details["action_id"] = action.action_id
        result_details["transport"] = transport
        return success, result_details, result_details.get("error")

    def inspect_remote_submission_state(self, action: ConsequentialAction) -> Tuple[bool, Dict[str, Any]]:
        """Remote inspection for crash recovery before dispatching new clicks."""
        return self.provider.inspect_submission_status(action.target_id, browser_service=self.browser_service)

