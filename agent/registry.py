"""
NexusNode — Agent Semantic Operation Registry
Central internal dispatch point for all semantic tools.
Enforces policy gates, normalized execution results, and structured error handling.
"""

import time
import logging
from typing import Callable, Dict, Any, Optional

from .models import ExecutionResult
from .policy import PolicyEngine, RiskClass
from .errors import (
    NexusAgentError,
    ApprovalRequiredError,
    ApprovalDeniedError,
    ApprovalExpiredError,
    ResourcePressureError,
    InternalError
)

logger = logging.getLogger("NEXUS_AGENT_REGISTRY")


class AgentOperationRegistry:
    """Internal registry and execution dispatcher for agent semantic operations."""

    def __init__(self, policy_engine: PolicyEngine, governor=None):
        self.policy_engine = policy_engine
        self.governor = governor
        self._handlers: Dict[str, Callable[..., ExecutionResult]] = {}

    def register(self, operation_name: str, handler: Callable[..., ExecutionResult], risk_class: Optional[RiskClass] = None):
        """Registers a semantic operation handler."""
        self._handlers[operation_name] = handler
        if risk_class:
            self.policy_engine.risk_map[operation_name] = risk_class

    def is_registered(self, operation_name: str) -> bool:
        return operation_name in self._handlers

    def execute(
        self,
        operation_name: str,
        user_id: str,
        params: Optional[Dict[str, Any]] = None,
        description: Optional[str] = None,
        approval_id: Optional[str] = None
    ) -> ExecutionResult:
        """
        Executes a registered semantic operation through policy and governor gates.
        Returns a normalized ExecutionResult under all conditions.
        """
        params = params or {}
        now = time.time()

        if operation_name not in self._handlers:
            return ExecutionResult(
                ok=False,
                operation=operation_name,
                source="local",
                provider="agent_registry",
                error=f"Semantic operation '{operation_name}' is not registered.",
                error_code="INTERNAL_ERROR",
                fetched_at=now
            )

        handler = self._handlers[operation_name]

        # 1. Evaluate Policy & Consequential Action Gates
        approved_grant = None
        try:
            approved_grant = self.policy_engine.evaluate_invocation(
                operation=operation_name,
                requested_by=user_id,
                description=description or f"Execute '{operation_name}'",
                params=params,
                approval_id=approval_id
            )
        except ApprovalRequiredError as are:
            return ExecutionResult(
                ok=False,
                operation=operation_name,
                source="local",
                provider="policy_engine",
                requires_approval=True,
                approval_id=are.approval_id,
                error=are.message,
                error_code=are.code,
                metadata=are.details,
                fetched_at=now
            )
        except NexusAgentError as nae:
            return ExecutionResult(
                ok=False,
                operation=operation_name,
                source="local",
                provider="policy_engine",
                error=nae.message,
                error_code=nae.code,
                metadata=nae.details,
                fetched_at=now
            )
        except Exception as ex:
            return ExecutionResult(
                ok=False,
                operation=operation_name,
                source="local",
                provider="policy_engine",
                error=f"Policy evaluation failed: {str(ex)}",
                error_code="INTERNAL_ERROR",
                fetched_at=now
            )

        # 2. Execute Handler
        try:
            result = handler(user_id=user_id, params=params, approval_grant=approved_grant)
            if not isinstance(result, ExecutionResult):
                result = ExecutionResult(
                    ok=True,
                    operation=operation_name,
                    source="local",
                    provider="agent_handler",
                    data=result,
                    fetched_at=now
                )

            # 3. If action was approved, consume/mark approval as executed (single-use guarantee)
            if approved_grant and self.policy_engine.approval_manager:
                self.policy_engine.approval_manager.mark_executed(
                    approval_id=approved_grant.id,
                    execution_result={"ok": result.ok, "fetched_at": result.fetched_at}
                )

            return result

        except NexusAgentError as nae:
            return ExecutionResult(
                ok=False,
                operation=operation_name,
                source="local",
                provider="agent_handler",
                error=nae.message,
                error_code=nae.code,
                metadata=nae.details,
                fetched_at=now
            )
        except Exception as ex:
            logger.exception(f"Unhandled error executing operation '{operation_name}': {ex}")
            return ExecutionResult(
                ok=False,
                operation=operation_name,
                source="local",
                provider="agent_handler",
                error=f"Operation failed with unexpected internal error: {str(ex)}",
                error_code="INTERNAL_ERROR",
                fetched_at=now
            )
