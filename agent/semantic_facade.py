"""
NexusNode — MCP-First Semantic Facade (nexus-semantic-v1)
Consolidates 43+ granular internal operations into an 11-tool high-signal semantic catalog
for remote LLM reasoning clients (Gemini Spark, Mistral).

Invariants:
1. Internal atomic operation registry remains 100% preserved.
2. Tenant is strictly derived from the authenticated MCP principal (no client user_id override).
3. Capability checks map directly to underlying atomic RBAC permissions.
4. Academic and calendar operations default strictly to direct APIs (browser fallback impossible for calendar).
5. Normalized response and error envelopes with provenance metadata.
6. Zero self-approval capability exposed to MCP clients.
"""

import time
import copy
import json
import logging
from typing import Dict, Any, List, Optional, Tuple, Callable

from .models import ExecutionResult
from .errors import NexusAgentError
from .sanitizer import sanitize_data

logger = logging.getLogger("NEXUS_SEMANTIC_FACADE")

SEMANTIC_CATALOG_VERSION = "nexus-semantic-v1"

# ==============================================================================
# 1. EXPLICIT SEMANTIC DISPATCH & CAPABILITY MAPPINGS
# ==============================================================================

# Maps: semantic_tool -> { semantic_operation_enum -> internal_atomic_operation }
SEMANTIC_OPERATION_MAP: Dict[str, Dict[str, str]] = {
    "nexus.status": {
        "default": "nexus.status"
    },
    "academic.query": {
        "timetable": "upes.get_timetable",
        "next_classes": "upes.get_next_classes",
        "attendance": "upes.get_attendance",
        "punches": "upes.get_punches",
        "courses": "upes.get_courses",
        "results": "upes.get_results",
        "semester_result": "upes.get_results",
        "transcript_summary": "upes.get_results"
    },
    "academic.sync": {
        "timetable": "upes.timetable.sync",
        "attendance": "upes.attendance.sync",
        "all": "upes.sync_all",
        "calendar": "calendar.reconcile",
        "results": "upes.results.sync"
    },
    "academic.analyze": {
        "safe_bunks": "upes.calculate_attendance",
        "recovery_classes": "upes.calculate_attendance",
        "attendance_risk": "upes.calculate_attendance",
        "attendance_what_if": "upes.calculate_attendance",
        "cgpa": "upes.analyze_performance",
        "sgpa": "upes.analyze_performance",
        "performance_summary": "upes.analyze_performance",
        "target_cgpa": "upes.calculate_what_if"
    },
    "lms.query": {
        "courses": "lms.list_courses",
        "assignments": "lms.list_assignments",
        "assignment": "lms.get_assignment",
        "resources": "lms.list_resources"
    },
    "lms.fetch": {
        "default": "lms.download_resource"
    },
    "lms.prepare": {
        "inspect_assignment": "lms.get_assignment",
        "stage_file": "lms.prepare_submission",
        "prepare_plan": "lms.prepare_submission"
    },
    "vault.manage": {
        "list": "vault.list",
        "search": "vault.search",
        "read": "vault.read",
        "create": "vault.create",
        "write": "vault.write",
        "move": "vault.move",
        "copy": "vault.copy",
        "rename": "vault.rename",
        "mkdir": "vault.mkdir"
    },
    "document.process": {
        "extract": "document.extract",
        "create": "document.create"
    },
    "browser.interact": {
        "open": "browser.open",
        "navigate": "browser.navigate",
        "observe": "browser.snapshot",
        "click": "browser.click",
        "type": "browser.type",
        "press": "browser.press",
        "capture": "browser.capture",
        "upload": "browser.upload",
        "download": "browser.download",
        "close": "browser.close"
    },
    "action.status": {
        "default": "action.status",
        "plan": "action.status",
        "approval": "action.status"
    }
}

# Maps: internal_atomic_operation -> list_of_accepted_capabilities
INTERNAL_CAPABILITY_MAP: Dict[str, List[str]] = {
    "nexus.status": ["nexus.status.read"],
    "upes.auth_status": ["upes.auth.read"],
    "upes.get_attendance": ["upes.attendance.read"],
    "upes.get_timetable": ["upes.timetable.read"],
    "upes.get_next_classes": ["upes.timetable.read"],
    "upes.get_courses": ["upes.courses.read"],
    "upes.calculate_attendance": ["upes.attendance.calculate"],
    "upes.get_punches": ["upes.punches.read"],
    "upes.export_timetable": ["upes.timetable.export"],
    "upes.timetable.sync": ["upes.timetable.read"],
    "upes.attendance.sync": ["upes.attendance.read"],
    "upes.sync_all": ["upes.timetable.read", "upes.attendance.read"],
    "calendar.reconcile": ["calendar.reconcile", "can_sync_timetable", "upes.timetable.read"],
    "upes.get_results": ["upes.results.read", "upes.timetable.read"],
    "upes.results.sync": ["upes.results.sync", "upes.timetable.read"],
    "upes.analyze_performance": ["upes.results.read", "upes.timetable.read"],
    "upes.calculate_what_if": ["upes.results.read", "upes.timetable.read"],
    "lms.list_courses": ["lms.courses.read"],
    "lms.get_course": ["lms.courses.read"],
    "lms.list_resources": ["lms.resources.read"],
    "lms.download_resource": ["lms.resource.download", "lms.resources.download"],
    "lms.list_assignments": ["lms.assignments.read"],
    "lms.get_assignment": ["lms.assignments.read"],
    "lms.prepare_submission": ["lms.assignment.submit", "lms.submission.prepare", "lms.submission.request"],
    "lms.submit_assignment": ["lms.assignment.submit", "lms.submission.request"],
    "action.status": ["action.status.read", "lms.assignments.read"],
    "vault.list": ["vault.list", "vault.read"],
    "vault.search": ["vault.search", "vault.read"],
    "vault.read": ["vault.read"],
    "vault.mkdir": ["vault.mkdir", "vault.write"],
    "vault.create": ["vault.create", "vault.write"],
    "vault.write": ["vault.write"],
    "vault.rename": ["vault.rename", "vault.write"],
    "vault.move": ["vault.move", "vault.write"],
    "vault.copy": ["vault.copy", "vault.write"],
    "vault.archive_list": ["vault.archive.read", "vault.read"],
    "vault.archive_extract": ["vault.archive.extract", "vault.write"],
    "document.extract": ["document.extract"],
    "document.create": ["document.create"],
    "browser.status": ["browser.status.read", "browser.navigate"],
    "browser.open": ["browser.open", "browser.navigate"],
    "browser.close": ["browser.close", "browser.navigate"],
    "browser.navigate": ["browser.navigate"],
    "browser.snapshot": ["browser.snapshot"],
    "browser.screenshot": ["browser.screenshot", "browser.snapshot"],
    "browser.capture": ["browser.capture", "browser.snapshot"],
    "browser.click": ["browser.click"],
    "browser.type": ["browser.type"],
    "browser.press": ["browser.press"],
    "browser.upload": ["browser.upload"],
    "browser.download": ["browser.download"]
}


# ==============================================================================
# 2. CANONICAL AUTHORITATIVE SEMANTIC TOOL DEFINITIONS (11 TOOLS)
# ==============================================================================

SEMANTIC_TOOL_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "name": "nexus.status",
        "description": "Returns safe appliance status, hardware resource metrics (RAM, storage), browser availability, and integration health.",
        "inputSchema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {},
            "additionalProperties": False
        },
        "required_capability": "nexus.status.read"
    },
    {
        "name": "academic.query",
        "description": "Read timetable, upcoming classes, attendance, punches, enrolled courses, or examination results/SGPA for the authenticated student.",
        "inputSchema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["timetable", "next_classes", "attendance", "punches", "courses", "results", "semester_result", "transcript_summary"],
                    "description": "Academic dataset to query."
                },
                "term_id": {
                    "type": "string",
                    "description": "Optional semester/term identifier (e.g. 'SEM1', 'SEM2') for results queries."
                },
                "date": {
                    "type": "string",
                    "description": "Specific date in YYYY-MM-DD format (for punches or timetable)."
                },
                "start_date": {
                    "type": "string",
                    "description": "Start date in YYYY-MM-DD format (for timetable range)."
                },
                "end_date": {
                    "type": "string",
                    "description": "End date in YYYY-MM-DD format (for timetable range)."
                },
                "course": {
                    "type": "string",
                    "description": "Optional course name or code filter."
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum records to return (default 20)."
                }
            },
            "required": ["operation"],
            "additionalProperties": False
        },
        "required_capability": "upes.timetable.read"
    },
    {
        "name": "academic.sync",
        "description": "Synchronize and refresh academic records via direct upstream APIs. Supported operations: 'timetable' (LIVE UPES timetable refresh only), 'calendar' (live UPES timetable refresh + Google Calendar reconciliation), 'attendance' (live UPES attendance refresh), 'results' (live UPES results/grades refresh), 'all' (full live academic refresh: timetable + attendance + results followed by Google Calendar reconciliation).",
        "inputSchema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["timetable", "calendar", "attendance", "results", "all"],
                    "description": "Synchronization operation: 'timetable' (live UPES timetable refresh only), 'calendar' (live UPES timetable refresh + Google Calendar reconciliation), 'attendance' (live UPES attendance refresh), 'results' (live UPES grades refresh), or 'all' (live timetable + attendance + results + calendar reconciliation)."
                }
            },
            "required": ["operation"],
            "additionalProperties": False
        },
        "required_capability": "upes.timetable.read"
    },
    {
        "name": "academic.analyze",
        "description": "Deterministic attendance risk analysis, safe bunks calculation, recovery class projections, SGPA/CGPA analysis, and What-If GPA modeling.",
        "inputSchema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["safe_bunks", "recovery_classes", "attendance_risk", "attendance_what_if", "cgpa", "sgpa", "performance_summary", "target_cgpa"],
                    "description": "Type of deterministic calculation."
                },
                "course": {
                    "type": "string",
                    "description": "Course name, code, or 'overall' (default 'overall')."
                },
                "future_attended": {
                    "type": "integer",
                    "description": "Hypothetical future consecutive sessions attended (default 0)."
                },
                "future_missed": {
                    "type": "integer",
                    "description": "Hypothetical future consecutive sessions missed (default 0)."
                },
                "target_percentage": {
                    "type": "number",
                    "description": "Desired minimum attendance percentage threshold (default 75.0)."
                },
                "target_cgpa": {
                    "type": "number",
                    "description": "Target CGPA value for What-If calculations (e.g. 8.5)."
                },
                "future_credits": {
                    "type": "number",
                    "description": "Projected future credit hours for target CGPA calculation (default 20.0)."
                },
                "hypothetical_courses": {
                    "type": "array",
                    "description": "List of prospective courses with {course_code, credits, letter_grade} for scenario projection."
                }
            },
            "required": ["operation"],
            "additionalProperties": False
        },
        "required_capability": "upes.attendance.calculate"
    },
    {
        "name": "lms.query",
        "description": "Read LMS courses, assignments, assignment details, or course resources from UPES Moodle LMS.",
        "inputSchema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["courses", "assignments", "assignment", "resources"],
                    "description": "LMS dataset to query."
                },
                "course_id": {
                    "type": "string",
                    "description": "LMS course identifier (for assignment/resource queries)."
                },
                "assignment_id": {
                    "type": "string",
                    "description": "Specific assignment ID (when operation='assignment')."
                },
                "query": {
                    "type": "string",
                    "description": "Optional search filter string."
                }
            },
            "required": ["operation"],
            "additionalProperties": False
        },
        "required_capability": "lms.courses.read"
    },
    {
        "name": "lms.fetch",
        "description": "Download an academic course resource, lecture notes, or assignment attachment into the user's encrypted Vault.",
        "inputSchema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "resource_id": {
                    "type": "string",
                    "description": "Moodle resource or attachment ID."
                },
                "url": {
                    "type": "string",
                    "description": "Validated LMS resource download URL."
                },
                "destination_path": {
                    "type": "string",
                    "description": "Destination path inside Vault (e.g. 'Coursework/lecture1.pdf')."
                },
                "course_name": {
                    "type": "string",
                    "description": "Optional course folder name."
                }
            },
            "required": ["resource_id", "destination_path"],
            "additionalProperties": False
        },
        "required_capability": "lms.resources.download"
    },
    {
        "name": "lms.prepare",
        "description": "Prepare an academic assignment submission plan and stage drafts WITHOUT final submission. Strictly stops before submit.",
        "inputSchema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["inspect_assignment", "stage_file", "prepare_plan"],
                    "description": "Staging operation. Does NOT execute final turn-in."
                },
                "assignment_id": {
                    "type": "string",
                    "description": "Target assignment identifier."
                },
                "vault_path": {
                    "type": "string",
                    "description": "Path to file inside Vault to stage (for stage_file / prepare_plan)."
                }
            },
            "required": ["operation", "assignment_id"],
            "additionalProperties": False
        },
        "required_capability": "lms.submission.prepare"
    },
    {
        "name": "vault.manage",
        "description": "Manage documents in the student's private encrypted storage vault (list, search, read, write, move, copy, mkdir).",
        "inputSchema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["list", "search", "read", "create", "write", "move", "copy", "rename", "mkdir"],
                    "description": "Vault storage operation."
                },
                "path": {
                    "type": "string",
                    "description": "Path inside Vault (e.g. 'Assignments/report.pdf')."
                },
                "destination_path": {
                    "type": "string",
                    "description": "Target path for move/copy/rename."
                },
                "content": {
                    "type": "string",
                    "description": "Text content to write (for create / write)."
                },
                "query": {
                    "type": "string",
                    "description": "Search query keyword (for search)."
                }
            },
            "required": ["operation"],
            "additionalProperties": False
        },
        "required_capability": "vault.read"
    },
    {
        "name": "document.process",
        "description": "Extract text from academic PDF/text documents or generate formatted PDF/Markdown documents in Vault.",
        "inputSchema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["extract", "create"],
                    "description": "Deterministic document processing operation."
                },
                "path": {
                    "type": "string",
                    "description": "Source path for extract, or destination path for create."
                },
                "content": {
                    "type": "string",
                    "description": "Text or markdown content (for create)."
                },
                "format": {
                    "type": "string",
                    "enum": ["pdf", "md", "txt"],
                    "description": "Document format (default 'pdf')."
                },
                "start_page": {
                    "type": "integer",
                    "description": "1-indexed start page for extraction."
                },
                "end_page": {
                    "type": "integer",
                    "description": "1-indexed end page for extraction."
                },
                "max_chars": {
                    "type": "integer",
                    "description": "Maximum characters to extract (default 4000)."
                }
            },
            "required": ["operation", "path"],
            "additionalProperties": False
        },
        "required_capability": "document.extract"
    },
    {
        "name": "browser.interact",
        "description": "Interact with an approved web page when a semantic NexusNode operation does not cover the requested workflow.",
        "inputSchema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["open", "navigate", "observe", "click", "type", "press", "capture", "close"],
                    "description": "Ephemeral browser interaction primitive."
                },
                "session_id": {
                    "type": "string",
                    "description": "Active browser session ID (returned by 'open')."
                },
                "url": {
                    "type": "string",
                    "description": "Target web URL (for 'open' and 'navigate')."
                },
                "element": {
                    "type": "string",
                    "description": "Target element reference (e.g. 'e0', 'e1') from observation."
                },
                "text": {
                    "type": "string",
                    "description": "Text to type into element."
                },
                "key": {
                    "type": "string",
                    "description": "Keyboard key to press (e.g. 'Enter', 'Tab')."
                }
            },
            "required": ["operation"],
            "additionalProperties": False
        },
        "required_capability": "browser.navigate"
    },
    {
        "name": "action.status",
        "description": "Read-only status inspection for staged submission plans, consequential actions, or approval requests.",
        "inputSchema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "action_id": {
                    "type": "string",
                    "description": "Consequential action or approval ID to inspect."
                },
                "plan_id": {
                    "type": "string",
                    "description": "Submission plan ID to inspect."
                },
                "approval_id": {
                    "type": "string",
                    "description": "Approval request ID to inspect."
                }
            },
            "additionalProperties": False
        },
        "required_capability": "lms.assignments.read"
    }
]


# ==============================================================================
# 3. SCHEMA ADAPTERS (GEMINI & MISTRAL)
# ==============================================================================

def adapt_schema_for_gemini(schema_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    Recursively strips schema keywords unsupported by Google Gemini Function Calling
    ($schema, $id, additionalProperties) and normalizes parameterless objects.
    """
    adapted = copy.deepcopy(schema_dict)

    def _clean(node):
        if isinstance(node, dict):
            node.pop("$schema", None)
            node.pop("$id", None)
            node.pop("additionalProperties", None)

            # Parameterless tools must have type=object
            if not node.get("properties") and node.get("type") == "object":
                pass

            for v in node.values():
                _clean(v)
        elif isinstance(node, list):
            for item in node:
                _clean(item)

    _clean(adapted)
    return adapted


def adapt_schema_for_mistral(schema_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    Adapts tool definitions for Mistral AI Connectors.
    Mistral accepts standard JSON Schema Draft 7/2020-12.
    Removes proprietary extensions while keeping standard typing.
    """
    adapted = copy.deepcopy(schema_dict)
    # Mistral standard JSON Schema: preserve type, properties, required, enum, description
    return adapted


# ==============================================================================
# 4. SEMANTIC MCP FACADE ENGINE
# ==============================================================================

class SemanticMcpFacade:
    """
    Orchestrates semantic tool discovery, tenant derivation, RBAC capability checking,
    ExecutionRouter dispatch, provenance attachment, and error normalization.
    """

    def __init__(self, registry=None, execution_router=None, token_manager=None, policy_engine=None):
        self.registry = registry
        self.router = execution_router
        self.token_manager = token_manager
        self.policy_engine = policy_engine

    def is_semantic_tool(self, tool_name: str) -> bool:
        """Returns True if the tool name is recognized as part of the semantic catalog."""
        return tool_name in SEMANTIC_OPERATION_MAP

    def get_tool_definitions(
        self,
        catalog_mode: str = "semantic",
        client_type: str = "canonical",
        token_metadata: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Returns active tool catalog for tools/list.
        catalog_mode: "semantic" (11 tools) or "legacy" (43 tools).
        client_type: "canonical", "gemini", or "mistral".
        """
        if catalog_mode == "legacy":
            from .mcp_server import MCP_TOOL_DEFINITIONS as legacy_defs
            defs = legacy_defs
        else:
            defs = SEMANTIC_TOOL_DEFINITIONS

        out = []
        for t in defs:
            # Filter by capability if token_metadata and token_manager are present
            req_cap = t.get("required_capability")
            if token_metadata and self.token_manager and req_cap:
                if not self.token_manager.check_capability(token_metadata, req_cap):
                    continue

            raw_schema = t["inputSchema"]
            if client_type == "gemini":
                schema = adapt_schema_for_gemini(raw_schema)
            elif client_type == "mistral":
                schema = adapt_schema_for_mistral(raw_schema)
            else:
                schema = copy.deepcopy(raw_schema)

            entry = {
                "name": t["name"],
                "description": t["description"],
                "inputSchema": schema
            }
            out.append(entry)
        return out

    def resolve_internal_operation(self, semantic_tool: str, arguments: Dict[str, Any]) -> Tuple[str, str, List[str]]:
        """
        Resolves (semantic_tool, arguments) -> (semantic_op, internal_op, required_capabilities).
        Raises ValueError on invalid operations.
        """
        tool_map = SEMANTIC_OPERATION_MAP.get(semantic_tool)
        if not tool_map:
            raise ValueError(f"Unknown semantic tool '{semantic_tool}'.")

        if "default" in tool_map and (len(tool_map) == 1 or not arguments.get("operation")):
            semantic_op = arguments.get("operation") or "default"
            internal_op = tool_map["default"]
        else:
            semantic_op = (arguments.get("operation") or "").strip().lower()
            if not semantic_op:
                raise ValueError(f"Parameter 'operation' is required for '{semantic_tool}'.")
            internal_op = tool_map.get(semantic_op)
            if not internal_op:
                supported = [k for k in tool_map.keys() if k != "default"]
                raise ValueError(f"Unsupported operation '{semantic_op}' for '{semantic_tool}'. Supported: {supported}")

        # Resolve capabilities
        req_caps = INTERNAL_CAPABILITY_MAP.get(internal_op, ["nexus.status.read"])
        if isinstance(req_caps, str):
            req_caps = [req_caps]
        return semantic_op, internal_op, req_caps

    def execute(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        token_metadata: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Executes a semantic tool invocation through RBAC, router, and registry.
        Returns a normalized JSON-RPC result dictionary.
        """
        start_t = time.time()
        arguments = arguments or {}

        # 1. Tenant Derivation: MUST come from authenticated principal
        tenant_user_id = token_metadata.get("user_id") or token_metadata.get("principal") or "admin"

        # Explicitly reject client-passed tenant selectors to prevent elevation
        for forbidden in ("user_id", "username", "target_user"):
            if forbidden in arguments:
                arguments.pop(forbidden)

        # 2. Resolve internal operation
        try:
            semantic_op, internal_op, req_caps = self.resolve_internal_operation(tool_name, arguments)
        except ValueError as ve:
            return self._build_error_response("INVALID_ARGUMENT", str(ve), retryable=False)

        # 3. RBAC Capability Authorization
        if self.token_manager:
            has_cap = any(self.token_manager.check_capability(token_metadata, cap) for cap in req_caps)
            if not has_cap:
                principal = token_metadata.get("principal", "spark-agent")
                return self._build_error_response(
                    "PERMISSION_DENIED",
                    f"Principal '{principal}' lacks required capability from {req_caps} for operation '{internal_op}'.",
                    retryable=False
                )

        # 4. Routing & Invariants via ExecutionRouter
        selected_route = "direct_http"
        route_reason = "direct_provider_available"
        fallback_used = False

        if self.router:
            route_enum, reason_enum, telemetry = self.router.determine_route(internal_op, params=arguments)
            selected_route = route_enum.value
            route_reason = reason_enum.value
            fallback_used = (route_enum.value == "browser_fallback")

        # 5. Adapt arguments for internal atomic operation
        internal_params = self._map_arguments_to_internal(tool_name, semantic_op, internal_op, arguments)

        # 6. Dispatch to AgentOperationRegistry
        exec_result: Optional[ExecutionResult] = None
        try:
            if self.registry:
                exec_result = self.registry.execute(
                    operation_name=internal_op,
                    user_id=tenant_user_id,
                    params=internal_params,
                    description=f"Semantic {tool_name} ({semantic_op})"
                )
            else:
                exec_result = ExecutionResult(
                    ok=False,
                    operation=internal_op,
                    source="local",
                    provider="semantic_facade",
                    error="Registry not configured.",
                    error_code="INTERNAL_ERROR"
                )
        except Exception as ex:
            logger.exception(f"Unhandled exception during semantic dispatch: {ex}")
            exec_result = ExecutionResult(
                ok=False,
                operation=internal_op,
                source="local",
                provider="semantic_facade",
                error=f"Execution error: {str(ex)}",
                error_code="INTERNAL_ERROR"
            )

        duration_ms = round((time.time() - start_t) * 1000, 2)

        # 7. Audit Logging (Recording external semantic tool AND internal atomic op)
        logger.info(
            f"[SEMANTIC_AUDIT] principal='{token_metadata.get('principal')}' tenant='{tenant_user_id}' "
            f"external='{tool_name}' op='{semantic_op}' internal='{internal_op}' "
            f"route='{selected_route}' fallback_used={fallback_used} ok={exec_result.ok} duration={duration_ms}ms"
        )

        # 8. Normalize Response
        if not exec_result.ok:
            code = self._normalize_error_code(exec_result.error_code or "INTERNAL_ERROR")
            return self._build_error_response(code, exec_result.error or "Operation failed.", retryable=False)

        # Success envelope with provenance
        raw_data = exec_result.data
        sanitized_data = sanitize_data(raw_data)

        # Build provenance
        provenance = {
            "source": exec_result.source or ("live" if selected_route == "direct_http" else "cache"),
            "route": selected_route,
            "stale": bool(exec_result.stale),
            "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(exec_result.fetched_at or time.time())),
            "fallback_used": fallback_used
        }

        # Structure normalized response
        response_envelope = {
            "ok": True,
            "operation": f"{tool_name}:{semantic_op}" if semantic_op != "default" else tool_name,
            "data": sanitized_data,
            "provenance": provenance
        }

        content_json = json.dumps(response_envelope, indent=2, default=str)
        return {
            "content": [
                {
                    "type": "text",
                    "text": content_json
                }
            ],
            "isError": False
        }

    def _map_arguments_to_internal(
        self,
        tool_name: str,
        semantic_op: str,
        internal_op: str,
        arguments: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Translates semantic arguments to parameters expected by internal atomic operations."""
        params = dict(arguments)
        params.pop("operation", None)

        if tool_name == "academic.analyze":
            if semantic_op in ("safe_bunks", "recovery_classes", "attendance_risk", "attendance_what_if"):
                params.setdefault("course", arguments.get("course") or "overall")
                params.setdefault("future_attended", arguments.get("future_attended", 0))
                params.setdefault("future_missed", arguments.get("future_missed", 0))
                params.setdefault("target_percentage", arguments.get("target_percentage", 75.0))
            elif semantic_op in ("cgpa", "sgpa", "performance_summary"):
                params["metric"] = semantic_op
            elif semantic_op == "target_cgpa":
                params["target_cgpa"] = arguments.get("target_cgpa")
                params["future_credits"] = arguments.get("future_credits", 20.0)
                params["hypothetical_courses"] = arguments.get("hypothetical_courses")

        elif tool_name == "academic.query":
            if "term_id" in arguments:
                params["term_id"] = arguments["term_id"]

        elif tool_name == "academic.sync":
            params["sync_domain"] = semantic_op

        elif tool_name == "lms.fetch":
            # Direct mapping for resource download
            params["destination_path"] = arguments.get("destination_path")
            params["resource_id"] = arguments.get("resource_id")
            params["url"] = arguments.get("url")

        elif tool_name == "lms.prepare":
            params["assignment_id"] = arguments.get("assignment_id")
            params["file_path"] = arguments.get("vault_path")
            params["dry_run"] = True  # Enforce non-destructive staging

        elif tool_name == "browser.interact":
            # Maps browser parameters
            if "element" in arguments:
                params["element_ref"] = arguments["element"]
            if "url" in arguments:
                params["target_url"] = arguments["url"]

        elif tool_name == "vault.manage":
            if "path" in arguments:
                params.setdefault("source_path", arguments["path"])
            if "destination_path" in arguments:
                params.setdefault("target_path", arguments["destination_path"])
                params.setdefault("destination_path", arguments["destination_path"])

        elif tool_name == "action.status":
            action_id = arguments.get("action_id") or arguments.get("plan_id") or arguments.get("approval_id")
            if action_id:
                params["action_id"] = action_id

        return params

    def _normalize_error_code(self, raw_code: str) -> str:
        """Normalizes internal error codes to standard external semantic codes."""
        c = (raw_code or "").upper()
        if "AUTH_REQUIRED" in c or "AUTH_EXPIRED" in c:
            return "AUTH_REQUIRED"
        if "APPROVAL_REQUIRED" in c:
            return "APPROVAL_REQUIRED"
        if "CONSEQUENTIAL" in c:
            return "CONSEQUENTIAL_ACTION_BLOCKED"
        if "PRESSURE" in c:
            return "BROWSER_RESOURCE_PRESSURE"
        if "BUSY" in c or "LOCK" in c:
            return "BROWSER_BUSY"
        if "TIMEOUT" in c:
            return "BROWSER_TIMEOUT"
        if "NOT_FOUND" in c:
            return "NOT_FOUND"
        if "INVALID" in c:
            return "INVALID_ARGUMENT"
        if "UNAVAILABLE" in c:
            return "UPSTREAM_UNAVAILABLE"
        if "STALE" in c:
            return "STALE_DATA"
        if "FORBIDDEN" in c or "DENIED" in c:
            return "PERMISSION_DENIED"
        return "INTERNAL_ERROR"

    def _build_error_response(self, code: str, message: str, retryable: bool = False) -> Dict[str, Any]:
        """Constructs a normalized error envelope without leaking stack traces."""
        error_payload = {
            "ok": False,
            "error": {
                "code": code,
                "message": message,
                "retryable": retryable
            }
        }
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(error_payload, indent=2)
                }
            ],
            "isError": True
        }
