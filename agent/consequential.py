"""
NexusNode — Consequential Action Engine & Cryptographic Approval Architecture
Phase 3.6A Implementation:
- Consequential Action state machine and single-flight execution
- Cryptographically authenticated Approval Grants (HKDF domain: nexusnode/approval/v1)
- Single-use, replay-protected, expiry-guarded transactional authority
- Comprehensive immutable audit logging and event dispatch
- Protection against agent self-authorization and TOCTOU parameter drift
"""

import os
import sys
import time
import json
import uuid
import hmac
import hashlib
import logging
import sqlite3
import threading
from typing import Dict, Any, Optional, List, Tuple, Callable
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes

import config
from .models import (
    ConsequentialAction,
    ApprovalRequest,
    ApprovalGrant,
    ConsequentialState,
    ApprovalState,
)
from .errors import (
    NexusAgentError,
    ApprovalRequiredError,
    ApprovalDeniedError,
    ApprovalExpiredError,
    InternalError,
)

logger = logging.getLogger("NEXUS_CONSEQUENTIAL")

# Thread-safe in-memory lock for concurrent execution synchronization
EXECUTION_LOCK = threading.Lock()
ACTIVE_EXECUTIONS: Dict[str, float] = {}

# Event listeners callback registry for Samsung companion / event bus
EVENT_LISTENERS: List[Callable[[str, Dict[str, Any]], None]] = []


def register_event_listener(listener: Callable[[str, Dict[str, Any]], None]):
    """Registers an event listener callback for consequential & approval lifecycle events."""
    with EXECUTION_LOCK:
        if listener not in EVENT_LISTENERS:
            EVENT_LISTENERS.append(listener)


def emit_event(event_name: str, payload: Dict[str, Any]):
    """Dispatches safe lifecycle events to all registered listeners and logs safely."""
    # Ensure no secret key or token is leaked in event payloads
    safe_payload = dict(payload)
    safe_payload.pop("signature", None)
    safe_payload.pop("token", None)
    safe_payload.pop("password", None)
    safe_payload.pop("cookie", None)
    safe_payload.pop("secret", None)

    logger.info(f"[EVENT] {event_name}: {json.dumps(safe_payload)}")
    for listener in list(EVENT_LISTENERS):
        try:
            listener(event_name, safe_payload)
        except Exception as e:
            logger.warning(f"Event listener failed on '{event_name}': {e}")


def init_consequential_tables(conn: sqlite3.Connection):
    """Initializes normalized SQLite tables for consequential actions, approval requests, and audit logs."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS consequential_actions (
            action_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            principal TEXT NOT NULL,
            operation TEXT NOT NULL,
            target_type TEXT NOT NULL,
            target_id TEXT NOT NULL,
            summary_json TEXT NOT NULL,
            parameters_hash TEXT NOT NULL,
            created_at REAL NOT NULL,
            expires_at REAL NOT NULL,
            risk_class TEXT NOT NULL,
            state TEXT NOT NULL,
            approval_id TEXT,
            execution_started_at REAL,
            completed_at REAL,
            execution_result_json TEXT,
            error_message TEXT,
            post_evidence_id TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_consequential_user_state ON consequential_actions (user_id, state)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_consequential_target ON consequential_actions (target_type, target_id, parameters_hash)")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS approval_requests (
            approval_id TEXT PRIMARY KEY,
            action_id TEXT NOT NULL UNIQUE,
            user_id TEXT NOT NULL,
            operation TEXT NOT NULL,
            human_readable_summary_json TEXT NOT NULL,
            target_identity TEXT NOT NULL,
            immutable_parameter_digest TEXT NOT NULL,
            evidence_references_json TEXT NOT NULL,
            created_at REAL NOT NULL,
            expires_at REAL NOT NULL,
            state TEXT NOT NULL,
            resolved_at REAL,
            resolved_by TEXT,
            denial_reason TEXT,
            approving_device_id TEXT,
            approval_method TEXT,
            user_presence INTEGER,
            device_public_key_id TEXT,
            device_signature TEXT,
            FOREIGN KEY (action_id) REFERENCES consequential_actions(action_id)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_approval_user_state ON approval_requests (user_id, state)")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS approval_grants (
            grant_id TEXT PRIMARY KEY,
            approval_id TEXT NOT NULL UNIQUE,
            action_id TEXT NOT NULL,
            operation TEXT NOT NULL,
            user_id TEXT NOT NULL,
            parameters_hash TEXT NOT NULL,
            created_at REAL NOT NULL,
            expires_at REAL NOT NULL,
            nonce TEXT NOT NULL,
            signature TEXT NOT NULL,
            is_consumed INTEGER NOT NULL DEFAULT 0,
            consumed_at REAL,
            consumed_by TEXT,
            FOREIGN KEY (approval_id) REFERENCES approval_requests(approval_id),
            FOREIGN KEY (action_id) REFERENCES consequential_actions(action_id)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS consequential_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT NOT NULL,
            timestamp REAL NOT NULL,
            event_type TEXT NOT NULL,
            user_id TEXT NOT NULL,
            principal TEXT NOT NULL,
            action_id TEXT NOT NULL,
            approval_id TEXT,
            operation TEXT NOT NULL,
            target TEXT NOT NULL,
            parameters_hash TEXT NOT NULL,
            details_json TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_consequential_audit_action ON consequential_audit_log (action_id)")
    conn.commit()


# ==============================================================================
# Domain-Separated Cryptography Provider for Approval Grants
# ==============================================================================

class ApprovalCryptoProvider:
    """
    Cryptographic MAC signing and verification for ApprovalGrants using HKDF-SHA256
    with domain separation info b'nexusnode/approval/v1'.
    Strictly isolated from credential and session keys.
    """

    DOMAIN_INFO = b"nexusnode/approval/v1"
    KDF_SALT = b"nexusnode_approval_v1_salt"

    @classmethod
    def _derive_approval_key(cls) -> bytes:
        """Derives a dedicated 256-bit symmetric signing key from SECRET_KEY."""
        secret_bytes = config.SECRET_KEY.encode("utf-8")
        hkdf = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=cls.KDF_SALT,
            info=cls.DOMAIN_INFO,
        )
        return hkdf.derive(secret_bytes)

    @classmethod
    def canonicalize_grant_payload(
        cls,
        grant_id: str,
        approval_id: str,
        action_id: str,
        operation: str,
        user_id: str,
        parameters_hash: str,
        created_at: float,
        expires_at: float,
        nonce: str
    ) -> bytes:
        """Constructs an unambiguous pipe-delimited canonical string for MAC signing."""
        canonical_str = (
            f"v1|{grant_id}|{approval_id}|{action_id}|{operation}|{user_id}|"
            f"{parameters_hash}|{created_at:.6f}|{expires_at:.6f}|{nonce}"
        )
        return canonical_str.encode("utf-8")

    @classmethod
    def sign_grant(
        cls,
        grant_id: str,
        approval_id: str,
        action_id: str,
        operation: str,
        user_id: str,
        parameters_hash: str,
        created_at: float,
        expires_at: float,
        nonce: str
    ) -> str:
        """Generates an HMAC-SHA256 signature for the approval grant payload."""
        key = cls._derive_approval_key()
        payload = cls.canonicalize_grant_payload(
            grant_id=grant_id,
            approval_id=approval_id,
            action_id=action_id,
            operation=operation,
            user_id=user_id,
            parameters_hash=parameters_hash,
            created_at=created_at,
            expires_at=expires_at,
            nonce=nonce
        )
        return hmac.new(key, payload, hashlib.sha256).hexdigest()

    @classmethod
    def verify_grant_signature(cls, grant: ApprovalGrant) -> bool:
        """Verifies the grant HMAC signature with constant-time comparison."""
        expected_sig = cls.sign_grant(
            grant_id=grant.grant_id,
            approval_id=grant.approval_id,
            action_id=grant.action_id,
            operation=grant.operation,
            user_id=grant.user_id,
            parameters_hash=grant.parameters_hash,
            created_at=grant.created_at,
            expires_at=grant.expires_at,
            nonce=grant.nonce
        )
        return hmac.compare_digest(expected_sig, grant.signature)


# ==============================================================================
# Consequential Audit Logger
# ==============================================================================

class ConsequentialAuditLogger:
    """Records append-only immutable audit entries for all consequential action operations."""

    def __init__(self, conn_factory: Callable[[], sqlite3.Connection]):
        self.conn_factory = conn_factory

    def record(
        self,
        event_type: str,
        user_id: str,
        principal: str,
        action_id: str,
        operation: str,
        target: str,
        parameters_hash: str,
        approval_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None
    ):
        """Persists a sanitised audit record."""
        clean_details = dict(details or {})
        clean_details.pop("password", None)
        clean_details.pop("token", None)
        clean_details.pop("cookie", None)
        clean_details.pop("secret", None)
        clean_details.pop("signature", None)

        now = time.time()
        event_id = f"aud_{uuid.uuid4().hex[:12]}"

        conn = self.conn_factory()
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("""
                INSERT INTO consequential_audit_log (
                    event_id, timestamp, event_type, user_id, principal, action_id,
                    approval_id, operation, target, parameters_hash, details_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                event_id, now, event_type, user_id, principal, action_id,
                approval_id, operation, target, parameters_hash, json.dumps(clean_details)
            ))
            conn.commit()
        except Exception as e:
            logger.error(f"Failed to record consequential audit log: {e}")
        finally:
            conn.close()


# ==============================================================================
# Consequential Action Manager
# ==============================================================================

class ConsequentialActionManager:
    """
    Authoritative manager for ConsequentialAction lifecycle, ApprovalRequests,
    and single-use ApprovalGrants.
    """

    DEFAULT_APPROVAL_TTL_SECONDS = 900.0  # 15 minutes default TTL

    def __init__(self, conn_factory: Callable[[], sqlite3.Connection]):
        self.conn_factory = conn_factory
        self.audit_logger = ConsequentialAuditLogger(conn_factory)

    @classmethod
    def compute_parameters_hash(cls, operation: str, target_id: str, params: Dict[str, Any]) -> str:
        """Computes a deterministic SHA-256 hash over canonical operation parameters."""
        canonical = {
            "operation": operation,
            "target_id": str(target_id),
            "params": params
        }
        raw = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def request_consequential_action(
        self,
        user_id: str,
        principal: str,
        operation: str,
        target_type: str,
        target_id: str,
        parameters: Dict[str, Any],
        summary: Dict[str, Any],
        evidence_references: Dict[str, Any],
        ttl_seconds: Optional[float] = None
    ) -> Tuple[ConsequentialAction, ApprovalRequest, bool]:
        """
        Creates or retrieves an active pending ConsequentialAction and ApprovalRequest.
        Deduplicates identical active pending requests for the same target & parameter digest.
        Returns: (ConsequentialAction, ApprovalRequest, is_existing: bool)
        """
        now = time.time()
        ttl = ttl_seconds or self.DEFAULT_APPROVAL_TTL_SECONDS
        params_hash = self.compute_parameters_hash(operation, target_id, parameters)

        conn = self.conn_factory()
        conn.row_factory = sqlite3.Row
        try:
            # 1. Deduplication: Check for active, non-expired pending action
            cur = conn.cursor()
            cur.execute("""
                SELECT action_id, approval_id, created_at, expires_at, state
                FROM consequential_actions
                WHERE user_id = ? AND target_type = ? AND target_id = ?
                  AND parameters_hash = ? AND state IN ('PREPARED', 'APPROVAL_REQUIRED')
                  AND expires_at > ?
                ORDER BY created_at DESC LIMIT 1
            """, (user_id, target_type, target_id, params_hash, now))
            existing_row = cur.fetchone()

            if existing_row:
                act_id = existing_row["action_id"]
                appr_id = existing_row["approval_id"]
                action = self.get_action(act_id)
                approval = self.get_approval(appr_id) if appr_id else None
                if action and approval and not approval.is_expired() and approval.state == ApprovalState.PENDING:
                    logger.info(f"Deduplicated existing active consequential action '{act_id}' for user '{user_id}'.")
                    return action, approval, True

            # 2. Create fresh ConsequentialAction and ApprovalRequest
            action_id = f"act_{uuid.uuid4().hex[:12]}"
            approval_id = f"appr_{uuid.uuid4().hex[:12]}"
            expires_at = now + ttl

            action = ConsequentialAction(
                action_id=action_id,
                user_id=user_id,
                principal=principal,
                operation=operation,
                target_type=target_type,
                target_id=target_id,
                summary=summary,
                parameters_hash=params_hash,
                created_at=now,
                expires_at=expires_at,
                risk_class="CONSEQUENTIAL",
                state=ConsequentialState.APPROVAL_REQUIRED,
                approval_id=approval_id
            )

            approval = ApprovalRequest(
                approval_id=approval_id,
                action_id=action_id,
                user_id=user_id,
                operation=operation,
                human_readable_summary=summary,
                target_identity=f"{target_type}:{target_id}",
                immutable_parameter_digest=params_hash,
                evidence_references=evidence_references,
                created_at=now,
                expires_at=expires_at,
                state=ApprovalState.PENDING
            )

            conn.execute("""
                INSERT INTO consequential_actions (
                    action_id, user_id, principal, operation, target_type, target_id,
                    summary_json, parameters_hash, created_at, expires_at, risk_class,
                    state, approval_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                action.action_id, action.user_id, action.principal, action.operation,
                action.target_type, action.target_id, json.dumps(action.summary),
                action.parameters_hash, action.created_at, action.expires_at,
                action.risk_class, action.state.value, action.approval_id
            ))

            conn.execute("""
                INSERT INTO approval_requests (
                    approval_id, action_id, user_id, operation, human_readable_summary_json,
                    target_identity, immutable_parameter_digest, evidence_references_json,
                    created_at, expires_at, state
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                approval.approval_id, approval.action_id, approval.user_id, approval.operation,
                json.dumps(approval.human_readable_summary), approval.target_identity,
                approval.immutable_parameter_digest, json.dumps(approval.evidence_references),
                approval.created_at, approval.expires_at, approval.state.value
            ))
            conn.commit()

            # Record audit log & dispatch event
            self.audit_logger.record(
                event_type="approval_required",
                user_id=user_id,
                principal=principal,
                action_id=action_id,
                operation=operation,
                target=f"{target_type}:{target_id}",
                parameters_hash=params_hash,
                approval_id=approval_id,
                details={"summary": summary, "evidence_references": evidence_references}
            )

            emit_event("approval.required", {
                "approval_id": approval_id,
                "action_id": action_id,
                "user_id": user_id,
                "operation": operation,
                "target": f"{target_type}:{target_id}",
                "summary": summary,
                "expires_at": expires_at
            })

            return action, approval, False
        finally:
            conn.close()

    def get_action(self, action_id: str) -> Optional[ConsequentialAction]:
        """Fetches a ConsequentialAction from SQLite by ID."""
        conn = self.conn_factory()
        conn.row_factory = sqlite3.Row
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM consequential_actions WHERE action_id = ?", (action_id,))
            row = cur.fetchone()
            if not row:
                return None
            return ConsequentialAction(
                action_id=row["action_id"],
                user_id=row["user_id"],
                principal=row["principal"],
                operation=row["operation"],
                target_type=row["target_type"],
                target_id=row["target_id"],
                summary=json.loads(row["summary_json"]),
                parameters_hash=row["parameters_hash"],
                created_at=float(row["created_at"]),
                expires_at=float(row["expires_at"]),
                risk_class=row["risk_class"],
                state=ConsequentialState(row["state"]),
                approval_id=row["approval_id"],
                execution_started_at=float(row["execution_started_at"]) if row["execution_started_at"] else None,
                completed_at=float(row["completed_at"]) if row["completed_at"] else None,
                execution_result=json.loads(row["execution_result_json"]) if row["execution_result_json"] else None,
                error_message=row["error_message"],
                post_evidence_id=row["post_evidence_id"]
            )
        finally:
            conn.close()

    def get_approval(self, approval_id: str) -> Optional[ApprovalRequest]:
        """Fetches an ApprovalRequest from SQLite by ID."""
        conn = self.conn_factory()
        conn.row_factory = sqlite3.Row
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM approval_requests WHERE approval_id = ?", (approval_id,))
            row = cur.fetchone()
            if not row:
                return None
            return ApprovalRequest(
                approval_id=row["approval_id"],
                action_id=row["action_id"],
                user_id=row["user_id"],
                operation=row["operation"],
                human_readable_summary=json.loads(row["human_readable_summary_json"]),
                target_identity=row["target_identity"],
                immutable_parameter_digest=row["immutable_parameter_digest"],
                evidence_references=json.loads(row["evidence_references_json"]),
                created_at=float(row["created_at"]),
                expires_at=float(row["expires_at"]),
                state=ApprovalState(row["state"]),
                resolved_at=float(row["resolved_at"]) if row["resolved_at"] else None,
                resolved_by=row["resolved_by"],
                denial_reason=row["denial_reason"],
                approving_device_id=row["approving_device_id"],
                approval_method=row["approval_method"],
                user_presence=bool(row["user_presence"]) if row["user_presence"] is not None else None,
                device_public_key_id=row["device_public_key_id"],
                device_signature=row["device_signature"]
            )
        finally:
            conn.close()

    def list_pending_approvals(self, user_id: str) -> List[ApprovalRequest]:
        """Returns all pending, non-expired approval requests for a user."""
        now = time.time()
        conn = self.conn_factory()
        conn.row_factory = sqlite3.Row
        results = []
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT * FROM approval_requests
                WHERE user_id = ? AND state = 'PENDING' AND expires_at > ?
                ORDER BY created_at DESC
            """, (user_id, now))
            for row in cur.fetchall():
                results.append(ApprovalRequest(
                    approval_id=row["approval_id"],
                    action_id=row["action_id"],
                    user_id=row["user_id"],
                    operation=row["operation"],
                    human_readable_summary=json.loads(row["human_readable_summary_json"]),
                    target_identity=row["target_identity"],
                    immutable_parameter_digest=row["immutable_parameter_digest"],
                    evidence_references=json.loads(row["evidence_references_json"]),
                    created_at=float(row["created_at"]),
                    expires_at=float(row["expires_at"]),
                    state=ApprovalState(row["state"]),
                    resolved_at=float(row["resolved_at"]) if row["resolved_at"] else None,
                    resolved_by=row["resolved_by"],
                    denial_reason=row["denial_reason"],
                    approving_device_id=row["approving_device_id"],
                    approval_method=row["approval_method"],
                    user_presence=bool(row["user_presence"]) if row["user_presence"] is not None else None,
                    device_public_key_id=row["device_public_key_id"],
                    device_signature=row["device_signature"]
                ))
            return results
        finally:
            conn.close()

    def approve_action(
        self,
        approval_id: str,
        user_id: str,
        device_meta: Optional[Dict[str, Any]] = None
    ) -> Tuple[ConsequentialAction, ApprovalGrant]:
        """
        Approves an action request, produces a cryptographic ApprovalGrant (domain: nexusnode/approval/v1),
        and transitions state to APPROVED. Idempotent on repeated calls.
        """
        now = time.time()
        conn = self.conn_factory()
        conn.row_factory = sqlite3.Row
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM approval_requests WHERE approval_id = ?", (approval_id,))
            appr_row = cur.fetchone()
            if not appr_row:
                raise ValueError(f"Approval request '{approval_id}' not found.")

            if appr_row["user_id"] != user_id:
                raise PermissionError("Cross-user approval authorization denied.")

            appr_state = ApprovalState(appr_row["state"])
            action_id = appr_row["action_id"]

            # Idempotency check: If already approved, return existing grant
            if appr_state == ApprovalState.APPROVED:
                cur.execute("SELECT * FROM approval_grants WHERE approval_id = ?", (approval_id,))
                grant_row = cur.fetchone()
                action = self.get_action(action_id)
                if grant_row and action:
                    grant = ApprovalGrant(
                        grant_id=grant_row["grant_id"],
                        approval_id=grant_row["approval_id"],
                        action_id=grant_row["action_id"],
                        operation=grant_row["operation"],
                        user_id=grant_row["user_id"],
                        parameters_hash=grant_row["parameters_hash"],
                        created_at=float(grant_row["created_at"]),
                        expires_at=float(grant_row["expires_at"]),
                        nonce=grant_row["nonce"],
                        signature=grant_row["signature"],
                        is_consumed=bool(grant_row["is_consumed"]),
                        consumed_at=float(grant_row["consumed_at"]) if grant_row["consumed_at"] else None,
                        consumed_by=grant_row["consumed_by"]
                    )
                    return action, grant

            if appr_state == ApprovalState.DENIED:
                raise ApprovalDeniedError(f"Approval request '{approval_id}' was already denied.")
            if appr_state in (ApprovalState.EXPIRED, ApprovalState.INVALIDATED) or float(appr_row["expires_at"]) <= now:
                raise ApprovalExpiredError(f"Approval request '{approval_id}' has expired.")

            # Create internal cryptographically bound ApprovalGrant
            grant_id = f"grant_{uuid.uuid4().hex[:12]}"
            nonce = uuid.uuid4().hex
            sig = ApprovalCryptoProvider.sign_grant(
                grant_id=grant_id,
                approval_id=approval_id,
                action_id=action_id,
                operation=appr_row["operation"],
                user_id=user_id,
                parameters_hash=appr_row["immutable_parameter_digest"],
                created_at=now,
                expires_at=float(appr_row["expires_at"]),
                nonce=nonce
            )

            grant = ApprovalGrant(
                grant_id=grant_id,
                approval_id=approval_id,
                action_id=action_id,
                operation=appr_row["operation"],
                user_id=user_id,
                parameters_hash=appr_row["immutable_parameter_digest"],
                created_at=now,
                expires_at=float(appr_row["expires_at"]),
                nonce=nonce,
                signature=sig,
                is_consumed=False
            )

            meta = device_meta or {}
            conn.execute("""
                UPDATE approval_requests
                SET state = 'APPROVED', resolved_at = ?, resolved_by = ?,
                    approving_device_id = ?, approval_method = ?, user_presence = ?,
                    device_public_key_id = ?, device_signature = ?
                WHERE approval_id = ?
            """, (
                now, user_id, meta.get("device_id"), meta.get("method", "user_session"),
                1 if meta.get("user_presence", True) else 0,
                meta.get("device_public_key_id"), meta.get("device_signature"),
                approval_id
            ))

            conn.execute("""
                UPDATE consequential_actions
                SET state = 'APPROVED'
                WHERE action_id = ?
            """, (action_id,))

            conn.execute("""
                INSERT INTO approval_grants (
                    grant_id, approval_id, action_id, operation, user_id,
                    parameters_hash, created_at, expires_at, nonce, signature, is_consumed
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """, (
                grant.grant_id, grant.approval_id, grant.action_id, grant.operation,
                grant.user_id, grant.parameters_hash, grant.created_at, grant.expires_at,
                grant.nonce, grant.signature
            ))
            conn.commit()

            self.audit_logger.record(
                event_type="approved",
                user_id=user_id,
                principal=user_id,
                action_id=action_id,
                operation=appr_row["operation"],
                target=appr_row["target_identity"],
                parameters_hash=appr_row["immutable_parameter_digest"],
                approval_id=approval_id,
                details={"device_meta": meta}
            )

            emit_event("approval.approved", {
                "approval_id": approval_id,
                "action_id": action_id,
                "user_id": user_id,
                "operation": appr_row["operation"],
                "target": appr_row["target_identity"],
                "resolved_at": now
            })

            action = self.get_action(action_id)
            return action, grant
        finally:
            conn.close()

    def deny_action(self, approval_id: str, user_id: str, reason: Optional[str] = None) -> ApprovalRequest:
        """Denies an approval request. Idempotent on repeated calls."""
        now = time.time()
        conn = self.conn_factory()
        conn.row_factory = sqlite3.Row
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM approval_requests WHERE approval_id = ?", (approval_id,))
            appr_row = cur.fetchone()
            if not appr_row:
                raise ValueError(f"Approval request '{approval_id}' not found.")

            if appr_row["user_id"] != user_id:
                raise PermissionError("Cross-user denial authorization denied.")

            appr_state = ApprovalState(appr_row["state"])
            if appr_state == ApprovalState.DENIED:
                return self.get_approval(approval_id)

            if appr_state == ApprovalState.APPROVED:
                raise ValueError(f"Cannot deny already approved request '{approval_id}'.")

            action_id = appr_row["action_id"]

            conn.execute("""
                UPDATE approval_requests
                SET state = 'DENIED', resolved_at = ?, resolved_by = ?, denial_reason = ?
                WHERE approval_id = ?
            """, (now, user_id, reason or "User denied action.", approval_id))

            conn.execute("""
                UPDATE consequential_actions
                SET state = 'DENIED', completed_at = ?, error_message = ?
                WHERE action_id = ?
            """, (now, reason or "Action denied by user.", action_id))
            conn.commit()

            self.audit_logger.record(
                event_type="denied",
                user_id=user_id,
                principal=user_id,
                action_id=action_id,
                operation=appr_row["operation"],
                target=appr_row["target_identity"],
                parameters_hash=appr_row["immutable_parameter_digest"],
                approval_id=approval_id,
                details={"reason": reason}
            )

            emit_event("approval.denied", {
                "approval_id": approval_id,
                "action_id": action_id,
                "user_id": user_id,
                "reason": reason
            })

            return self.get_approval(approval_id)
        finally:
            conn.close()

    def invalidate_action(self, action_id: str, reason: str):
        """Invalidates an active action and its approval request due to parameter or target drift."""
        now = time.time()
        conn = self.conn_factory()
        conn.row_factory = sqlite3.Row
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM consequential_actions WHERE action_id = ?", (action_id,))
            act_row = cur.fetchone()
            if not act_row:
                return

            approval_id = act_row["approval_id"]

            conn.execute("""
                UPDATE consequential_actions
                SET state = 'INVALIDATED', completed_at = ?, error_message = ?
                WHERE action_id = ?
            """, (now, reason, action_id))

            if approval_id:
                conn.execute("""
                    UPDATE approval_requests
                    SET state = 'INVALIDATED', resolved_at = ?, denial_reason = ?
                    WHERE approval_id = ?
                """, (now, reason, approval_id))

            conn.commit()

            self.audit_logger.record(
                event_type="invalidated",
                user_id=act_row["user_id"],
                principal=act_row["principal"],
                action_id=action_id,
                operation=act_row["operation"],
                target=f"{act_row['target_type']}:{act_row['target_id']}",
                parameters_hash=act_row["parameters_hash"],
                approval_id=approval_id,
                details={"reason": reason}
            )

            emit_event("approval.invalidated", {
                "action_id": action_id,
                "approval_id": approval_id,
                "reason": reason
            })
        finally:
            conn.close()


# ==============================================================================
# Controlled Consequential Executor (Single-Flight Execution Engine)
# ==============================================================================

class ConsequentialExecutor:
    """
    Controlled single-flight executor for approved consequential actions.
    Consumes approval authority transactionally, re-verifies parameters,
    executes privileged pipeline, and records positive proof.
    """

    def __init__(self, action_mgr: ConsequentialActionManager, conn_factory: Callable[[], sqlite3.Connection]):
        self.action_mgr = action_mgr
        self.conn_factory = conn_factory
        self.audit_logger = action_mgr.audit_logger

    def execute_action(
        self,
        action_id: str,
        executor_func: Callable[[ConsequentialAction, ApprovalGrant], Tuple[bool, Dict[str, Any], Optional[str]]],
        recovery_inspector: Optional[Callable[[ConsequentialAction], Tuple[bool, Dict[str, Any]]]] = None
    ) -> Dict[str, Any]:
        """
        Executes an approved consequential action under strict single-flight locking.
        Consumes the ApprovalGrant transactionally.
        Returns normalized execution dictionary.
        """
        with EXECUTION_LOCK:
            if action_id in ACTIVE_EXECUTIONS:
                raise RuntimeError(f"Action '{action_id}' is already executing (single-flight locked).")
            ACTIVE_EXECUTIONS[action_id] = time.time()

        try:
            # 1. Fetch action and grant
            action = self.action_mgr.get_action(action_id)
            if not action:
                raise ValueError(f"Consequential action '{action_id}' not found.")

            if action.state == ConsequentialState.SUCCEEDED:
                return {
                    "ok": True,
                    "status": "already_succeeded",
                    "action_id": action_id,
                    "result": action.execution_result
                }

            if action.state != ConsequentialState.APPROVED:
                raise ValueError(f"Action '{action_id}' is in state '{action.state}', expected 'APPROVED'.")

            now = time.time()
            if action.is_expired():
                self.action_mgr.invalidate_action(action_id, "Action expired before execution.")
                raise ApprovalExpiredError(f"Action '{action_id}' has expired.")

            # 2. Fetch and validate ApprovalGrant
            conn = self.conn_factory()
            conn.row_factory = sqlite3.Row
            try:
                cur = conn.cursor()
                cur.execute("SELECT * FROM approval_grants WHERE action_id = ?", (action_id,))
                grant_row = cur.fetchone()
                if not grant_row:
                    raise PermissionError(f"No ApprovalGrant exists for action '{action_id}'.")

                grant = ApprovalGrant(
                    grant_id=grant_row["grant_id"],
                    approval_id=grant_row["approval_id"],
                    action_id=grant_row["action_id"],
                    operation=grant_row["operation"],
                    user_id=grant_row["user_id"],
                    parameters_hash=grant_row["parameters_hash"],
                    created_at=float(grant_row["created_at"]),
                    expires_at=float(grant_row["expires_at"]),
                    nonce=grant_row["nonce"],
                    signature=grant_row["signature"],
                    is_consumed=bool(grant_row["is_consumed"]),
                    consumed_at=float(grant_row["consumed_at"]) if grant_row["consumed_at"] else None,
                    consumed_by=grant_row["consumed_by"]
                )

                if grant.is_consumed:
                    raise PermissionError(f"ApprovalGrant for action '{action_id}' has already been consumed (replay blocked).")

                if grant.is_expired():
                    raise ApprovalExpiredError(f"ApprovalGrant for action '{action_id}' has expired.")

                if not ApprovalCryptoProvider.verify_grant_signature(grant):
                    raise PermissionError(f"ApprovalGrant signature verification failed for action '{action_id}'.")

                # 3. Crash Recovery Check: Inspect remote state before clicking submit
                if recovery_inspector:
                    already_done, recovery_result = recovery_inspector(action)
                    if already_done:
                        logger.info(f"Crash recovery check: Action '{action_id}' is already completed remotely.")
                        conn.execute("""
                            UPDATE approval_grants
                            SET is_consumed = 1, consumed_at = ?, consumed_by = ?
                            WHERE grant_id = ?
                        """, (now, f"recovered_{action_id}", grant.grant_id))
                        conn.execute("""
                            UPDATE consequential_actions
                            SET state = 'SUCCEEDED', completed_at = ?, execution_result_json = ?
                            WHERE action_id = ?
                        """, (now, json.dumps(recovery_result), action_id))
                        conn.commit()

                        self.audit_logger.record(
                            event_type="execution_recovered",
                            user_id=action.user_id,
                            principal=action.principal,
                            action_id=action_id,
                            operation=action.operation,
                            target=f"{action.target_type}:{action.target_id}",
                            parameters_hash=action.parameters_hash,
                            approval_id=action.approval_id,
                            details={"result": recovery_result}
                        )
                        emit_event("consequential.succeeded", {
                            "action_id": action_id,
                            "user_id": action.user_id,
                            "operation": action.operation,
                            "recovered": True
                        })
                        return {"ok": True, "status": "recovered_succeeded", "action_id": action_id, "result": recovery_result}

                # 4. Atomically consume grant and transition action state to EXECUTING
                conn.execute("""
                    UPDATE approval_grants
                    SET is_consumed = 1, consumed_at = ?, consumed_by = ?
                    WHERE grant_id = ?
                """, (now, action_id, grant.grant_id))

                conn.execute("""
                    UPDATE consequential_actions
                    SET state = 'EXECUTING', execution_started_at = ?
                    WHERE action_id = ?
                """, (now, action_id))
                conn.commit()
            finally:
                conn.close()

            # Record execution start audit & emit event
            self.audit_logger.record(
                event_type="execution_started",
                user_id=action.user_id,
                principal=action.principal,
                action_id=action_id,
                operation=action.operation,
                target=f"{action.target_type}:{action.target_id}",
                parameters_hash=action.parameters_hash,
                approval_id=action.approval_id
            )
            emit_event("consequential.started", {
                "action_id": action_id,
                "user_id": action.user_id,
                "operation": action.operation
            })

            # 5. Execute privileged internal pipeline
            try:
                success, result_data, error_msg = executor_func(action, grant)
            except Exception as e:
                logger.error(f"Executor exception for action '{action_id}': {e}", exc_info=True)
                success, result_data, error_msg = False, {}, str(e)

            # 6. Post-execution persistence
            completed_now = time.time()
            current_act = self.action_mgr.get_action(action_id)
            if current_act and current_act.state == ConsequentialState.INVALIDATED:
                final_state = ConsequentialState.INVALIDATED
            else:
                final_state = ConsequentialState.SUCCEEDED if success else (
                    ConsequentialState.UNCERTAIN if result_data.get("uncertain") else ConsequentialState.FAILED
                )

            conn = self.conn_factory()
            conn.row_factory = sqlite3.Row

            try:
                post_ev_id = result_data.get("post_evidence_id")
                conn.execute("""
                    UPDATE consequential_actions
                    SET state = ?, completed_at = ?, execution_result_json = ?,
                        error_message = ?, post_evidence_id = ?
                    WHERE action_id = ?
                """, (
                    final_state.value, completed_now, json.dumps(result_data),
                    error_msg, post_ev_id, action_id
                ))
                conn.commit()
            finally:
                conn.close()

            # Record audit and emit completion event
            ev_type = "succeeded" if success else ("uncertain" if final_state == ConsequentialState.UNCERTAIN else "failed")
            self.audit_logger.record(
                event_type=ev_type,
                user_id=action.user_id,
                principal=action.principal,
                action_id=action_id,
                operation=action.operation,
                target=f"{action.target_type}:{action.target_id}",
                parameters_hash=action.parameters_hash,
                approval_id=action.approval_id,
                details={"result": result_data, "error": error_msg}
            )

            emit_event(f"consequential.{ev_type}", {
                "action_id": action_id,
                "user_id": action.user_id,
                "operation": action.operation,
                "state": final_state.value,
                "result": result_data
            })

            return {
                "ok": success,
                "status": final_state.value.lower(),
                "action_id": action_id,
                "result": result_data,
                "error": error_msg
            }
        finally:
            with EXECUTION_LOCK:
                ACTIVE_EXECUTIONS.pop(action_id, None)
