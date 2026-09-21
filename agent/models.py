"""
NexusNode — Agent Execution Foundation Models
Normalized data structures for execution results, web content envelopes, and approvals.
"""

import time
import json
import hashlib
from enum import Enum
from typing import Any, Dict, Optional, List
from dataclasses import dataclass, field, asdict



@dataclass
class ExecutionResult:
    """
    Authoritative normalized execution response model across all agent tools.
    Explicitly declares provenance (live vs lkg vs browser vs local).
    """
    ok: bool
    operation: str
    source: str                      # 'live' | 'lkg' | 'browser' | 'local'
    provider: str                    # 'direct_http' | 'pinchtab' | 'camofox' | 'lkg_cache' | 'local_vault'
    data: Any = None
    fetched_at: float = field(default_factory=time.time)
    stale: bool = False
    requires_approval: bool = False
    approval_id: Optional[str] = None
    error: Optional[str] = None
    error_code: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        res = {
            "ok": self.ok,
            "operation": self.operation,
            "provenance": {
                "source": self.source,
                "provider": self.provider,
                "fetched_at": self.fetched_at,
                "stale": self.stale,
            },
            "requires_approval": self.requires_approval,
            "data": self.data,
            "metadata": self.metadata
        }
        if self.approval_id:
            res["approval_id"] = self.approval_id
        if self.error:
            res["error"] = self.error
        if self.error_code:
            res["error_code"] = self.error_code
        return res

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ExecutionResult":
        prov = d.get("provenance", {})
        return cls(
            ok=d.get("ok", True),
            operation=d.get("operation", "unknown"),
            source=prov.get("source", d.get("source", "local")),
            provider=prov.get("provider", d.get("provider", "direct_http")),
            data=d.get("data"),
            fetched_at=prov.get("fetched_at", d.get("fetched_at", time.time())),
            stale=prov.get("stale", d.get("stale", False)),
            requires_approval=d.get("requires_approval", False),
            approval_id=d.get("approval_id"),
            error=d.get("error"),
            error_code=d.get("error_code"),
            metadata=d.get("metadata", {})
        )


@dataclass
class WebContent:
    """
    Encapsulated remote web page content.
    Prevents indirect prompt injection by wrapping remote text in strict untrusted data boundaries.
    """
    url: str
    title: str
    content: str                     # Structured accessibility tree or sanitized readability text
    element_map: Dict[str, str] = field(default_factory=dict)
    screenshot_base64: Optional[str] = None
    timestamp: float = field(default_factory=time.time)

    @property
    def url_hash(self) -> str:
        return hashlib.sha256(self.url.encode("utf-8")).hexdigest()[:12]

    def to_envelope(self) -> str:
        """Renders the untrusted web content envelope for LLM agent context."""
        return (
            f'<untrusted_web_content origin="{self.url}" url_hash="{self.url_hash}" timestamp="{self.timestamp:.0f}">\n'
            f'  <page_title>{self.title}</page_title>\n'
            f'  <accessibility_tree>\n'
            f'{self.content}\n'
            f'  </accessibility_tree>\n'
            f'</untrusted_web_content>'
        )


@dataclass
class PendingApproval:
    """
    Structured server-side approval request for consequential actions.
    Protects against agent self-authorization and parameter mutation.
    """
    id: str
    operation: str
    description: str
    risk_class: str                  # 'READ_ONLY' | 'WRITE_LOW_RISK' | 'CONSEQUENTIAL'
    status: str                      # 'PENDING' | 'APPROVED' | 'DENIED' | 'EXPIRED' | 'EXECUTED' | 'FAILED' | 'CANCELLED'
    requested_by: str
    safe_context: Dict[str, Any]
    created_at: float = field(default_factory=time.time)
    expires_at: float = field(default_factory=lambda: time.time() + 3600.0)
    approved_by: Optional[str] = None
    resolved_at: Optional[float] = None
    execution_result: Optional[Dict[str, Any]] = None

    def is_expired(self) -> bool:
        return time.time() > self.expires_at

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "operation": self.operation,
            "description": self.description,
            "risk_class": self.risk_class,
            "status": self.status,
            "requested_by": self.requested_by,
            "approved_by": self.approved_by,
            "safe_context": self.safe_context,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "resolved_at": self.resolved_at,
            "is_expired": self.is_expired()
        }


# ==============================================================================
# Phase 3.6A Consequential Action & Cryptographic Approval Models
# ==============================================================================

class ConsequentialState(str, Enum):
    PREPARED = "PREPARED"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    APPROVED = "APPROVED"
    EXECUTING = "EXECUTING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"
    INVALIDATED = "INVALIDATED"
    UNCERTAIN = "UNCERTAIN"


class ApprovalState(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"
    INVALIDATED = "INVALIDATED"


@dataclass
class ConsequentialAction:
    action_id: str
    user_id: str
    principal: str
    operation: str
    target_type: str
    target_id: str
    summary: Dict[str, Any]
    parameters_hash: str
    created_at: float
    expires_at: float
    risk_class: str = "CONSEQUENTIAL"
    state: ConsequentialState = ConsequentialState.APPROVAL_REQUIRED
    approval_id: Optional[str] = None
    execution_started_at: Optional[float] = None
    completed_at: Optional[float] = None
    execution_result: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    post_evidence_id: Optional[str] = None

    def is_expired(self) -> bool:
        return time.time() > self.expires_at

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_id": self.action_id,
            "user_id": self.user_id,
            "principal": self.principal,
            "operation": self.operation,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "summary": self.summary,
            "parameters_hash": self.parameters_hash,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "risk_class": self.risk_class,
            "state": self.state.value if isinstance(self.state, ConsequentialState) else str(self.state),
            "approval_id": self.approval_id,
            "execution_started_at": self.execution_started_at,
            "completed_at": self.completed_at,
            "execution_result": self.execution_result,
            "error_message": self.error_message,
            "post_evidence_id": self.post_evidence_id,
            "is_expired": self.is_expired()
        }


@dataclass
class ApprovalRequest:
    approval_id: str
    action_id: str
    user_id: str
    operation: str
    human_readable_summary: Dict[str, Any]
    target_identity: str
    immutable_parameter_digest: str
    evidence_references: Dict[str, Any]
    created_at: float
    expires_at: float
    state: ApprovalState = ApprovalState.PENDING
    resolved_at: Optional[float] = None
    resolved_by: Optional[str] = None
    denial_reason: Optional[str] = None
    # Future Samsung Device Identity fields (Nullable in Phase 3.6A)
    approving_device_id: Optional[str] = None
    approval_method: Optional[str] = None
    user_presence: Optional[bool] = None
    device_public_key_id: Optional[str] = None
    device_signature: Optional[str] = None

    def is_expired(self) -> bool:
        return time.time() > self.expires_at

    def to_dict(self) -> Dict[str, Any]:
        return {
            "approval_id": self.approval_id,
            "action_id": self.action_id,
            "user_id": self.user_id,
            "operation": self.operation,
            "human_readable_summary": self.human_readable_summary,
            "target_identity": self.target_identity,
            "immutable_parameter_digest": self.immutable_parameter_digest,
            "evidence_references": self.evidence_references,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "state": self.state.value if isinstance(self.state, ApprovalState) else str(self.state),
            "resolved_at": self.resolved_at,
            "resolved_by": self.resolved_by,
            "denial_reason": self.denial_reason,
            "approving_device_id": self.approving_device_id,
            "approval_method": self.approval_method,
            "user_presence": self.user_presence,
            "device_public_key_id": self.device_public_key_id,
            "device_signature": self.device_signature,
            "is_expired": self.is_expired()
        }


@dataclass
class ApprovalGrant:
    grant_id: str
    approval_id: str
    action_id: str
    operation: str
    user_id: str
    parameters_hash: str
    created_at: float
    expires_at: float
    nonce: str
    signature: str
    is_consumed: bool = False
    consumed_at: Optional[float] = None
    consumed_by: Optional[str] = None

    def is_expired(self) -> bool:
        return time.time() > self.expires_at

    def to_dict(self) -> Dict[str, Any]:
        return {
            "grant_id": self.grant_id,
            "approval_id": self.approval_id,
            "action_id": self.action_id,
            "operation": self.operation,
            "user_id": self.user_id,
            "parameters_hash": self.parameters_hash,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "nonce": self.nonce,
            "is_consumed": self.is_consumed,
            "consumed_at": self.consumed_at,
            "consumed_by": self.consumed_by,
            "is_expired": self.is_expired()
        }

