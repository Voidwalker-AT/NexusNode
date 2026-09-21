"""
NexusNode — Agent Execution Policy & Approvals
Enforces action risk classification, pending approval lifecycle, and prompt-injection safety boundaries.
"""

import time
import json
import uuid
import sqlite3
from typing import Dict, Any, Optional, List
from enum import Enum

from .models import PendingApproval, ExecutionResult
from .errors import (
    ApprovalRequiredError,
    ApprovalDeniedError,
    ApprovalExpiredError,
    InternalError
)


class RiskClass(str, Enum):
    READ_ONLY = "READ_ONLY"
    WRITE_LOW_RISK = "WRITE_LOW_RISK"
    CONSEQUENTIAL = "CONSEQUENTIAL"


class ApprovalStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"
    EXECUTED = "EXECUTED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


# Default operation risk mappings
DEFAULT_RISK_MAP: Dict[str, RiskClass] = {
    # Appliance Status
    "nexus.status": RiskClass.READ_ONLY,

    # UPES Semantic Tools
    "upes.auth_status": RiskClass.READ_ONLY,
    "upes.get_attendance": RiskClass.READ_ONLY,
    "upes.get_timetable": RiskClass.READ_ONLY,
    "upes.get_next_classes": RiskClass.READ_ONLY,
    "upes.get_courses": RiskClass.READ_ONLY,
    "upes.search_lms": RiskClass.READ_ONLY,
    "upes.download_resource": RiskClass.WRITE_LOW_RISK,
    "upes.calculate_attendance": RiskClass.READ_ONLY,
    "upes.get_punches": RiskClass.READ_ONLY,
    "upes.get_punch_status": RiskClass.READ_ONLY,
    "upes.export_timetable": RiskClass.WRITE_LOW_RISK,
    
    # LMS Semantic Tools (Phase 3.5)
    "lms.list_courses": RiskClass.READ_ONLY,
    "lms.get_course": RiskClass.READ_ONLY,
    "lms.list_resources": RiskClass.READ_ONLY,
    "lms.download_resource": RiskClass.WRITE_LOW_RISK,
    "lms.list_assignments": RiskClass.READ_ONLY,
    "lms.get_assignment": RiskClass.READ_ONLY,
    "lms.prepare_submission": RiskClass.WRITE_LOW_RISK,

    # Vault Tools (Read-Only & Local Write)
    "vault.list": RiskClass.READ_ONLY,
    "vault.search": RiskClass.READ_ONLY,
    "vault.read": RiskClass.READ_ONLY,
    "vault.mkdir": RiskClass.WRITE_LOW_RISK,
    "vault.create": RiskClass.WRITE_LOW_RISK,
    "vault.write": RiskClass.WRITE_LOW_RISK,
    "vault.rename": RiskClass.WRITE_LOW_RISK,
    "vault.move": RiskClass.WRITE_LOW_RISK,
    "vault.copy": RiskClass.WRITE_LOW_RISK,
    "vault.archive_list": RiskClass.READ_ONLY,
    "vault.archive_extract": RiskClass.WRITE_LOW_RISK,
    "document.extract": RiskClass.READ_ONLY,
    "document.create": RiskClass.WRITE_LOW_RISK,

    # Browser Tools (Read-Only & Preparatory / Remote Reversible)
    "browser.status": RiskClass.READ_ONLY,
    "browser.health": RiskClass.READ_ONLY,
    "browser.open": RiskClass.WRITE_LOW_RISK,
    "browser.close": RiskClass.WRITE_LOW_RISK,
    "browser.navigate": RiskClass.WRITE_LOW_RISK,
    "browser.snapshot": RiskClass.READ_ONLY,
    "browser.screenshot": RiskClass.READ_ONLY,
    "browser.capture": RiskClass.READ_ONLY,
    "browser.click": RiskClass.WRITE_LOW_RISK,
    "browser.type": RiskClass.WRITE_LOW_RISK,
    "browser.press": RiskClass.WRITE_LOW_RISK,
    "browser.upload": RiskClass.WRITE_LOW_RISK,
    "browser.download": RiskClass.WRITE_LOW_RISK,

    # Consequential Actions (Mandatory Human/Samsung Approval)
    "upes.submit_assignment": RiskClass.CONSEQUENTIAL,
    "lms.submit_assignment": RiskClass.CONSEQUENTIAL,
    "portal.delete": RiskClass.CONSEQUENTIAL,
    "portal.message_send": RiskClass.CONSEQUENTIAL,
    "portal.payment": RiskClass.CONSEQUENTIAL,
    "system.reboot": RiskClass.CONSEQUENTIAL,
}


def init_approval_tables(conn: sqlite3.Connection):
    """Initializes normalized SQLite tables for action approvals."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS action_approvals (
            id TEXT PRIMARY KEY,
            operation TEXT NOT NULL,
            description TEXT NOT NULL,
            risk_class TEXT NOT NULL,
            status TEXT NOT NULL,
            requested_by TEXT NOT NULL,
            approved_by TEXT,
            safe_context TEXT NOT NULL,
            created_at REAL NOT NULL,
            expires_at REAL NOT NULL,
            resolved_at REAL,
            execution_result TEXT
        );
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_approvals_user_status ON action_approvals (requested_by, status);")


class ApprovalManager:
    """Manages persistent lifecycle for pending consequential action approvals."""

    def __init__(self, conn_factory):
        self.conn_factory = conn_factory

    def create_approval(
        self,
        operation: str,
        description: str,
        requested_by: str,
        safe_context: Dict[str, Any],
        risk_class: RiskClass = RiskClass.CONSEQUENTIAL,
        ttl_seconds: float = 3600.0
    ) -> PendingApproval:
        """Creates and stores a new pending approval record."""
        now = time.time()
        appr_id = f"appr_{uuid.uuid4().hex[:12]}"
        expires_at = now + ttl_seconds
        
        # Ensure context is JSON serializable
        ctx_str = json.dumps(safe_context)

        conn = self.conn_factory()
        try:
            conn.execute("""
                INSERT INTO action_approvals (
                    id, operation, description, risk_class, status,
                    requested_by, safe_context, created_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                appr_id, operation, description, risk_class.value, ApprovalStatus.PENDING.value,
                requested_by, ctx_str, now, expires_at
            ))
            conn.commit()
        finally:
            conn.close()

        return PendingApproval(
            id=appr_id,
            operation=operation,
            description=description,
            risk_class=risk_class.value,
            status=ApprovalStatus.PENDING.value,
            requested_by=requested_by,
            safe_context=safe_context,
            created_at=now,
            expires_at=expires_at
        )

    def get_approval(self, approval_id: str) -> Optional[PendingApproval]:
        """Retrieves an approval record, checking for expiration."""
        conn = self.conn_factory()
        try:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("SELECT * FROM action_approvals WHERE id = ?", (approval_id,))
            row = cur.fetchone()
            if not row:
                return None

            now = time.time()
            status = row["status"]
            if status == ApprovalStatus.PENDING.value and now > row["expires_at"]:
                # Automatically mark expired
                conn.execute("UPDATE action_approvals SET status = ? WHERE id = ?", (ApprovalStatus.EXPIRED.value, approval_id))
                conn.commit()
                status = ApprovalStatus.EXPIRED.value

            return PendingApproval(
                id=row["id"],
                operation=row["operation"],
                description=row["description"],
                risk_class=row["risk_class"],
                status=status,
                requested_by=row["requested_by"],
                approved_by=row["approved_by"],
                safe_context=json.loads(row["safe_context"]),
                created_at=row["created_at"],
                expires_at=row["expires_at"],
                resolved_at=row["resolved_at"]
            )
        finally:
            conn.close()

    def list_approvals(self, user_id: Optional[str] = None, status: Optional[str] = None) -> List[PendingApproval]:
        """Lists approval records with optional user and status filters."""
        conn = self.conn_factory()
        try:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            query = "SELECT * FROM action_approvals WHERE 1=1"
            params = []
            if user_id:
                query += " AND requested_by = ?"
                params.append(user_id)
            if status:
                query += " AND status = ?"
                params.append(status)
            query += " ORDER BY created_at DESC LIMIT 100"
            
            cur.execute(query, tuple(params))
            results = []
            now = time.time()
            for row in cur.fetchall():
                st = row["status"]
                if st == ApprovalStatus.PENDING.value and now > row["expires_at"]:
                    st = ApprovalStatus.EXPIRED.value
                results.append(PendingApproval(
                    id=row["id"],
                    operation=row["operation"],
                    description=row["description"],
                    risk_class=row["risk_class"],
                    status=st,
                    requested_by=row["requested_by"],
                    approved_by=row["approved_by"],
                    safe_context=json.loads(row["safe_context"]),
                    created_at=row["created_at"],
                    expires_at=row["expires_at"],
                    resolved_at=row["resolved_at"]
                ))
            return results
        finally:
            conn.close()

    def approve(self, approval_id: str, approved_by: str) -> PendingApproval:
        """Grants human/privileged authorization for an approval request."""
        appr = self.get_approval(approval_id)
        if not appr:
            raise InternalError(f"Approval request '{approval_id}' not found.")
        if appr.status == ApprovalStatus.EXPIRED.value:
            raise ApprovalExpiredError(f"Approval request '{approval_id}' has expired.")
        if appr.status != ApprovalStatus.PENDING.value:
            raise InternalError(f"Cannot approve request '{approval_id}' with status '{appr.status}'.")

        now = time.time()
        conn = self.conn_factory()
        try:
            conn.execute("""
                UPDATE action_approvals
                SET status = ?, approved_by = ?, resolved_at = ?
                WHERE id = ? AND status = ?
            """, (ApprovalStatus.APPROVED.value, approved_by, now, approval_id, ApprovalStatus.PENDING.value))
            conn.commit()
        finally:
            conn.close()

        appr.status = ApprovalStatus.APPROVED.value
        appr.approved_by = approved_by
        appr.resolved_at = now
        return appr

    def deny(self, approval_id: str, denied_by: str) -> PendingApproval:
        """Denies an approval request."""
        appr = self.get_approval(approval_id)
        if not appr:
            raise InternalError(f"Approval request '{approval_id}' not found.")
        if appr.status != ApprovalStatus.PENDING.value:
            raise InternalError(f"Cannot deny request '{approval_id}' with status '{appr.status}'.")

        now = time.time()
        conn = self.conn_factory()
        try:
            conn.execute("""
                UPDATE action_approvals
                SET status = ?, approved_by = ?, resolved_at = ?
                WHERE id = ? AND status = ?
            """, (ApprovalStatus.DENIED.value, denied_by, now, approval_id, ApprovalStatus.PENDING.value))
            conn.commit()
        finally:
            conn.close()

        appr.status = ApprovalStatus.DENIED.value
        appr.approved_by = denied_by
        appr.resolved_at = now
        return appr

    def mark_executed(self, approval_id: str, execution_result: Optional[Dict[str, Any]] = None) -> bool:
        """
        Marks an approved request as EXECUTED.
        Strict single-use guarantee: only transitions from APPROVED -> EXECUTED.
        Prevents replay attacks or double execution.
        """
        res_str = json.dumps(execution_result) if execution_result else None
        conn = self.conn_factory()
        try:
            cur = conn.cursor()
            cur.execute("""
                UPDATE action_approvals
                SET status = ?, execution_result = ?
                WHERE id = ? AND status = ?
            """, (ApprovalStatus.EXECUTED.value, res_str, approval_id, ApprovalStatus.APPROVED.value))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()


class PolicyEngine:
    """Authoritative policy decision point for agent operations."""

    def __init__(self, approval_manager: Optional[ApprovalManager] = None):
        self.approval_manager = approval_manager
        self.risk_map = dict(DEFAULT_RISK_MAP)

    def get_risk_class(self, operation: str) -> RiskClass:
        """Returns the risk class for a semantic operation."""
        return self.risk_map.get(operation, RiskClass.CONSEQUENTIAL)

    def is_consequential(self, operation: str) -> bool:
        return self.get_risk_class(operation) == RiskClass.CONSEQUENTIAL

    def evaluate_invocation(
        self,
        operation: str,
        requested_by: str,
        description: str,
        params: Dict[str, Any],
        approval_id: Optional[str] = None
    ) -> Optional[PendingApproval]:
        """
        Evaluates whether an operation can execute immediately or requires/satisfies an approval.
        Raises ApprovalRequiredError, ApprovalDeniedError, or ApprovalExpiredError.
        Returns the satisfied PendingApproval if authorized, or None for non-consequential actions.
        """
        risk = self.get_risk_class(operation)
        if risk != RiskClass.CONSEQUENTIAL:
            return None

        if not self.approval_manager:
            raise InternalError("Approval manager not configured on policy engine.")

        # If no approval ID was provided, create a pending approval request
        if not approval_id:
            pending = self.approval_manager.create_approval(
                operation=operation,
                description=description or f"Execute consequential operation '{operation}'",
                requested_by=requested_by,
                safe_context=params,
                risk_class=risk
            )
            raise ApprovalRequiredError(
                message=f"Operation '{operation}' is consequential and requires user approval.",
                approval_id=pending.id,
                details={"approval": pending.to_dict()}
            )

        # If approval ID was provided, verify state
        appr = self.approval_manager.get_approval(approval_id)
        if not appr:
            raise ApprovalDeniedError(f"Approval grant '{approval_id}' not found.")
        if appr.is_expired() or appr.status == ApprovalStatus.EXPIRED.value:
            raise ApprovalExpiredError(f"Approval grant '{approval_id}' has expired.")
        if appr.status == ApprovalStatus.DENIED.value:
            raise ApprovalDeniedError(f"Approval grant '{approval_id}' was denied by {appr.approved_by}.")
        if appr.status == ApprovalStatus.EXECUTED.value:
            raise ApprovalDeniedError(f"Approval grant '{approval_id}' has already been executed (replay rejected).")
        if appr.status != ApprovalStatus.APPROVED.value:
            raise ApprovalRequiredError(
                message=f"Approval grant '{approval_id}' is still in status '{appr.status}'.",
                approval_id=approval_id,
                details={"approval": appr.to_dict()}
            )

        # Verify operation matches approved operation (anti-parameter tampering)
        if appr.operation != operation:
            raise ApprovalDeniedError(
                f"Approval grant '{approval_id}' was authorized for '{appr.operation}', not '{operation}'."
            )

        return appr
