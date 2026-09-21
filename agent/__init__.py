"""
NexusNode — Agent Execution Foundation Package
"""

from .models import (
    ExecutionResult,
    WebContent,
    PendingApproval,
    ConsequentialAction,
    ApprovalRequest,
    ApprovalGrant,
    ConsequentialState,
    ApprovalState
)
from .errors import (
    NexusAgentError,
    AuthRequiredError,
    SessionExpiredError,
    InteractionRequiredError,
    BrowserUnavailableError,
    BrowserConnectionError,
    BrowserSessionError,
    NavigationFailedError,
    ElementStaleError,
    UploadFailedError,
    DownloadFailedError,
    SecurityChallengeError,
    ResourcePressureError,
    ApprovalRequiredError,
    ApprovalDeniedError,
    ApprovalExpiredError,
    UpstreamError,
    InternalError,
)
from .consequential import (
    ConsequentialActionManager,
    ConsequentialExecutor,
    ApprovalCryptoProvider,
    ConsequentialAuditLogger,
    init_consequential_tables,
    register_event_listener,
    emit_event
)
from .policy import (
    RiskClass,
    ApprovalStatus,
    ApprovalManager,
    PolicyEngine,
    init_approval_tables,
)
from .registry import AgentOperationRegistry
from .mcp_auth import (
    AgentTokenManager,
    AgentAuthError,
    AgentForbiddenError,
    init_agent_auth_tables,
    DEFAULT_SPARK_CAPABILITIES,
)
from .vault_service import VaultService, VaultPathError, VaultAccessError
from .browser_service import BrowserService
from .status_service import StatusService
from .lms_service import LMSService, init_lms_tables
from .oauth_provider import OAuthProvider, init_oauth_tables, OAuthError
from .rate_limiter import AgentRateLimiter
from .sanitizer import sanitize_data, sanitize_text
from .mcp_server import McpServerAdapter, MCP_TOOL_DEFINITIONS
from .execution_router import ExecutionRouter, ExecutionRoute, RouteDecisionReason
from .semantic_facade import SemanticMcpFacade, SEMANTIC_TOOL_DEFINITIONS, SEMANTIC_CATALOG_VERSION


__all__ = [
    "SemanticMcpFacade",
    "SEMANTIC_TOOL_DEFINITIONS",
    "SEMANTIC_CATALOG_VERSION",
    "ExecutionRouter",
    "ExecutionRoute",
    "RouteDecisionReason",
    "OAuthProvider",
    "init_oauth_tables",
    "OAuthError",

    "ExecutionResult",
    "WebContent",
    "PendingApproval",
    "ConsequentialAction",
    "ApprovalRequest",
    "ApprovalGrant",
    "ConsequentialState",
    "ApprovalState",
    "ConsequentialActionManager",
    "ConsequentialExecutor",
    "ApprovalCryptoProvider",
    "ConsequentialAuditLogger",
    "init_consequential_tables",
    "register_event_listener",
    "emit_event",
    "NexusAgentError",
    "AuthRequiredError",
    "SessionExpiredError",
    "InteractionRequiredError",
    "BrowserUnavailableError",
    "BrowserConnectionError",
    "BrowserSessionError",
    "NavigationFailedError",
    "ElementStaleError",
    "UploadFailedError",
    "DownloadFailedError",
    "SecurityChallengeError",
    "ResourcePressureError",
    "ApprovalRequiredError",
    "ApprovalDeniedError",
    "ApprovalExpiredError",
    "UpstreamError",
    "InternalError",
    "RiskClass",
    "ApprovalStatus",
    "ApprovalManager",
    "PolicyEngine",
    "init_approval_tables",
    "AgentOperationRegistry",
    "AgentTokenManager",
    "AgentAuthError",
    "AgentForbiddenError",
    "init_agent_auth_tables",
    "DEFAULT_SPARK_CAPABILITIES",
    "VaultService",
    "VaultPathError",
    "VaultAccessError",
    "BrowserService",
    "StatusService",
    "LMSService",
    "AgentRateLimiter",
    "sanitize_data",
    "sanitize_text",
    "McpServerAdapter",
    "MCP_TOOL_DEFINITIONS",
]

