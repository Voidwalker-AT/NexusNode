"""
NexusNode — Model Context Protocol (MCP) Server Adapter
Authoritative implementation of the MCP 2026-07-28 Stateless Protocol & Streamable HTTP specification.
Features:
- server/discover capability probe & negotiation
- Stateless request processing (zero mandatory initialize / session requirements)
- Modern header validation (MCP-Protocol-Version, Mcp-Method, Mcp-Name)
- Per-request _meta envelope extraction
- Structured JSON Schema 2020-12 tool definitions
- Capability authorization & sliding-window rate limiting
- Defense-in-depth output sanitization & prompt injection untrusted envelopes
- Graceful backward compatibility with legacy 2024-11-05 / 2025 clients
"""

import time
import json
import copy
import uuid
import logging
from typing import Dict, Any, List, Optional, Tuple, Callable

import config
from .models import ExecutionResult
from .registry import AgentOperationRegistry
from .mcp_auth import AgentTokenManager, AgentAuthError, AgentForbiddenError
from .rate_limiter import AgentRateLimiter
from .sanitizer import sanitize_data
from .semantic_facade import (
    SemanticMcpFacade,
    SEMANTIC_TOOL_DEFINITIONS,
    SEMANTIC_CATALOG_VERSION,
    adapt_schema_for_mistral
)

logger = logging.getLogger("NEXUS_MCP_GATEWAY")

# ==============================================================================
# AUTHORITATIVE MCP TOOL SCHEMAS (JSON Schema 2020-12)
# ==============================================================================

MCP_TOOL_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "name": "nexus.status",
        "description": "Returns safe appliance status, hardware resource metrics (RAM, storage), and component health without sensitive configuration.",
        "inputSchema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {},
            "additionalProperties": False
        },
        "required_capability": "nexus.status.read"
    },
    {
        "name": "upes.auth_status",
        "description": "Returns safe UPES Connect Portal session status, credential format alignment, token lifetime, and autonomy levels. Zero secrets or tokens are returned.",
        "inputSchema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {},
            "additionalProperties": False
        },
        "required_capability": "upes.auth.read"
    },
    {
        "name": "upes.get_attendance",
        "description": "Queries live academic attendance analytics, overall percentage, and enrolled subject summaries from UPES Connect Portal.",
        "inputSchema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "threshold": {
                    "type": "number",
                    "description": "Attendance warning percentage threshold (default 0.75 for 75%)."
                }
            },
            "additionalProperties": False
        },
        "required_capability": "upes.attendance.read"
    },
    {
        "name": "upes.get_timetable",
        "description": "Queries the student's academic timetable schedule with date range filtering and bounded output pagination.",
        "inputSchema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": "Optional start date in YYYY-MM-DD format (e.g. '2026-08-30')."
                },
                "end_date": {
                    "type": "string",
                    "description": "Optional end date in YYYY-MM-DD format."
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of classes to return (default 20, max 100)."
                }
            },
            "additionalProperties": False
        },
        "required_capability": "upes.timetable.read"
    },
    {
        "name": "upes.get_next_classes",
        "description": "Convenience tool returning the student's immediate next upcoming classes relative to the current local time.",
        "inputSchema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Number of upcoming classes to return (default 3, max 10)."
                }
            },
            "additionalProperties": False
        },
        "required_capability": "upes.timetable.read"
    },
    {
        "name": "upes.get_courses",
        "description": "Queries enrolled academic courses, module codes, term identifiers, and total recorded attendance sessions.",
        "inputSchema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {},
            "additionalProperties": False
        },
        "required_capability": "upes.courses.read"
    },
    {
        "name": "vault.list",
        "description": "Lists files and subdirectories within the safe agent-visible user vault.",
        "inputSchema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative directory path inside the user vault (e.g. 'documents')."
                },
                "recursive": {
                    "type": "boolean",
                    "description": "Whether to list subdirectories recursively (max depth 2)."
                }
            },
            "additionalProperties": False
        },
        "required_capability": "vault.list"
    },
    {
        "name": "vault.search",
        "description": "Searches for keywords across indexed user documents within the agent-visible vault, returning relevance-ranked snippets.",
        "inputSchema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Keywords or search phrases to find."
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum snippet matches to return (default 5, max 20)."
                }
            },
            "required": ["query"],
            "additionalProperties": False
        },
        "required_capability": "vault.search"
    },
    {
        "name": "vault.read",
        "description": "Reads text content from a document in the user vault with pagination and prompt-injection untrusted boundary encapsulation.",
        "inputSchema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative file path inside the user vault (e.g. 'documents/syllabus.txt')."
                },
                "offset": {
                    "type": "integer",
                    "description": "Character offset to start reading from (default 0)."
                },
                "limit_chars": {
                    "type": "integer",
                    "description": "Maximum characters to return in this chunk (default 4000, max 10000)."
                }
            },
            "required": ["path"],
            "additionalProperties": False
        },
        "required_capability": "vault.read"
    },
    {
        "name": "browser.status",
        "description": "Checks the operational status and connectivity of the remote PinchTab browser automation daemon.",
        "inputSchema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {},
            "additionalProperties": False
        },
        "required_capability": "browser.status.read"
    },
    # --------------------------------------------------------------------------
    # Writable Vault Tools (Phase 3.4)
    # --------------------------------------------------------------------------
    {
        "name": "vault.mkdir",
        "description": "Creates a new directory inside the agent-visible user vault.",
        "inputSchema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative directory path to create inside vault (e.g. 'Deep Learning/Assignment 1')."
                },
                "parents": {
                    "type": "boolean",
                    "description": "Whether to create parent directories if missing (default True)."
                }
            },
            "required": ["path"],
            "additionalProperties": False
        },
        "required_capability": "vault.mkdir"
    },
    {
        "name": "vault.create",
        "description": "Creates a new text or markdown file in the user vault. Fails with FILE_EXISTS if the file already exists.",
        "inputSchema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative file path inside vault (e.g. 'notes/summary.md')."
                },
                "content": {
                    "type": "string",
                    "description": "Text or markdown content to write."
                },
                "source": {
                    "type": "string",
                    "description": "Optional provenance origin (default 'spark_generated')."
                }
            },
            "required": ["path", "content"],
            "additionalProperties": False
        },
        "required_capability": "vault.create"
    },
    {
        "name": "vault.write",
        "description": "Updates an existing file in the user vault (supports replace or append mode).",
        "inputSchema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative file path inside vault."
                },
                "content": {
                    "type": "string",
                    "description": "Text or markdown content to write."
                },
                "mode": {
                    "type": "string",
                    "enum": ["replace", "append"],
                    "description": "Write mode: 'replace' (overwrite full content) or 'append' (default 'replace')."
                },
                "create_if_missing": {
                    "type": "boolean",
                    "description": "Create the file if it does not exist (default True)."
                }
            },
            "required": ["path", "content"],
            "additionalProperties": False
        },
        "required_capability": "vault.write"
    },
    {
        "name": "vault.rename",
        "description": "Renames a file or directory within the user vault.",
        "inputSchema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "source_path": {
                    "type": "string",
                    "description": "Current relative path in vault."
                },
                "target_path": {
                    "type": "string",
                    "description": "New relative path or name in vault."
                }
            },
            "required": ["source_path", "target_path"],
            "additionalProperties": False
        },
        "required_capability": "vault.rename"
    },
    {
        "name": "vault.move",
        "description": "Moves a file or directory to a destination folder inside the user vault.",
        "inputSchema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "source_path": {
                    "type": "string",
                    "description": "Current relative path in vault."
                },
                "destination_path": {
                    "type": "string",
                    "description": "Destination directory or file path in vault."
                }
            },
            "required": ["source_path", "destination_path"],
            "additionalProperties": False
        },
        "required_capability": "vault.move"
    },
    {
        "name": "vault.copy",
        "description": "Copies a file or directory to a destination path inside the user vault.",
        "inputSchema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "source_path": {
                    "type": "string",
                    "description": "Source relative path in vault."
                },
                "destination_path": {
                    "type": "string",
                    "description": "Destination relative path in vault."
                }
            },
            "required": ["source_path", "destination_path"],
            "additionalProperties": False
        },
        "required_capability": "vault.copy"
    },
    # --------------------------------------------------------------------------
    # Browser Execution Tools (Phase 3.4)
    # --------------------------------------------------------------------------
    {
        "name": "browser.open",
        "description": "Allocates a new isolated browser session and optionally opens an initial URL.",
        "inputSchema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Initial URL to open (default 'about:blank')."
                },
                "profile": {
                    "type": "string",
                    "description": "Browser profile name (default 'nexusnode-browser-profile')."
                }
            },
            "additionalProperties": False
        },
        "required_capability": "browser.open"
    },
    {
        "name": "browser.close",
        "description": "Closes an active browser session and releases associated memory.",
        "inputSchema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "Active browser session identifier (e.g. 'brs_12345')."
                }
            },
            "required": ["session_id"],
            "additionalProperties": False
        },
        "required_capability": "browser.close"
    },
    {
        "name": "browser.navigate",
        "description": "Navigates active browser session to a validated HTTP/HTTPS URL.",
        "inputSchema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "Active browser session ID."
                },
                "url": {
                    "type": "string",
                    "description": "Destination HTTP/HTTPS URL."
                },
                "discovered_from": {
                    "type": "string",
                    "description": "Optional provenance origin URL where this link was discovered."
                }
            },
            "required": ["session_id", "url"],
            "additionalProperties": False
        },
        "required_capability": "browser.navigate"
    },
    {
        "name": "browser.snapshot",
        "description": "Extracts structured accessibility snapshot with numeric element references (e0, e1) and untrusted web envelope.",
        "inputSchema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "Active browser session ID."
                }
            },
            "required": ["session_id"],
            "additionalProperties": False
        },
        "required_capability": "browser.snapshot"
    },
    {
        "name": "browser.screenshot",
        "description": "Captures a page screenshot, stores it as an artifact, and returns safe metadata and inspection reference.",
        "inputSchema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "Active browser session ID."
                },
                "full_page": {
                    "type": "boolean",
                    "description": "Whether to capture full scrollable page (default False)."
                },
                "include_preview": {
                    "type": "boolean",
                    "description": "Whether to include bounded base64 preview image (default True)."
                }
            },
            "required": ["session_id"],
            "additionalProperties": False
        },
        "required_capability": "browser.screenshot"
    },
    {
        "name": "browser.capture",
        "description": "Paired operation: captures accessibility snapshot AND screenshot from the exact same page state for visual and structural reasoning.",
        "inputSchema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "Active browser session ID."
                }
            },
            "required": ["session_id"],
            "additionalProperties": False
        },
        "required_capability": "browser.capture"
    },
    {
        "name": "browser.click",
        "description": "Clicks an interactive element by reference (e.g. 'e1'). Consequential actions (Submit, Turn In, Delete) are strictly blocked.",
        "inputSchema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "Active browser session ID."
                },
                "element": {
                    "type": "string",
                    "description": "Element reference identifier from snapshot (e.g. 'e1')."
                }
            },
            "required": ["session_id", "element"],
            "additionalProperties": False
        },
        "required_capability": "browser.click"
    },
    {
        "name": "browser.type",
        "description": "Types text into an input element.",
        "inputSchema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "Active browser session ID."
                },
                "element": {
                    "type": "string",
                    "description": "Target input element reference (e.g. 'e2')."
                },
                "text": {
                    "type": "string",
                    "description": "Text to type into the element."
                },
                "submit": {
                    "type": "boolean",
                    "description": "Submit form after typing (default False; implicit submissions are blocked)."
                }
            },
            "required": ["session_id", "element", "text"],
            "additionalProperties": False
        },
        "required_capability": "browser.type"
    },
    {
        "name": "browser.press",
        "description": "Sends a keyboard key event (e.g. 'Enter', 'Tab', 'Escape', 'ArrowDown').",
        "inputSchema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "Active browser session ID."
                },
                "key": {
                    "type": "string",
                    "description": "Key name (e.g. 'Enter', 'Tab', 'Escape')."
                }
            },
            "required": ["session_id", "key"],
            "additionalProperties": False
        },
        "required_capability": "browser.press"
    },
    {
        "name": "browser.upload",
        "description": "Attaches a file from the user vault to a file input element in a draft form (strictly does NOT submit).",
        "inputSchema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "Active browser session ID."
                },
                "element": {
                    "type": "string",
                    "description": "File input element reference (e.g. 'e5')."
                },
                "vault_path": {
                    "type": "string",
                    "description": "Relative file path inside user vault (e.g. 'Deep Learning/solution.pdf')."
                }
            },
            "required": ["session_id", "element", "vault_path"],
            "additionalProperties": False
        },
        "required_capability": "browser.upload"
    },
    {
        "name": "browser.download",
        "description": "Triggers a controlled browser download and transfers the result atomically into a vault destination.",
        "inputSchema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "Active browser session ID."
                },
                "element": {
                    "type": "string",
                    "description": "Optional download link or button element reference (e.g. 'e8')."
                },
                "destination_path": {
                    "type": "string",
                    "description": "Destination path or directory inside vault (e.g. 'Deep Learning/syllabus.pdf')."
                }
            },
            "required": ["session_id", "destination_path"],
            "additionalProperties": False
        },
        "required_capability": "browser.download"
    },
    # --------------------------------------------------------------------------
    # LMS Semantic Tools (Phase 3.5)
    # --------------------------------------------------------------------------
    {
        "name": "lms.list_courses",
        "description": "Lists enrolled academic courses on UPES Moodle LMS with intelligent disambiguation and caching.",
        "inputSchema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Optional course name, code, or alias filter (e.g. 'Deep Learning', 'CNS', '100891')."
                },
                "active_only": {
                    "type": "boolean",
                    "description": "Filter to currently active semester courses (default True)."
                }
            },
            "additionalProperties": False
        },
        "required_capability": "lms.courses.read"
    },
    {
        "name": "lms.get_course",
        "description": "Retrieves comprehensive course outline, visible topics/sections, resource count, and assignment summary.",
        "inputSchema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "course_id": {
                    "type": "string",
                    "description": "Normalized course reference (e.g. 'lmscourse_100891') or unique course query."
                }
            },
            "required": ["course_id"],
            "additionalProperties": False
        },
        "required_capability": "lms.courses.read"
    },
    {
        "name": "lms.list_resources",
        "description": "Lists downloadable files, syllabus documents, and learning modules for a given LMS course.",
        "inputSchema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "course_id": {
                    "type": "string",
                    "description": "Course reference or name (e.g. 'lmscourse_100891' or 'Cryptography')."
                },
                "section": {
                    "type": "string",
                    "description": "Optional topic or module section title filter."
                }
            },
            "required": ["course_id"],
            "additionalProperties": False
        },
        "required_capability": "lms.resources.read"
    },
    {
        "name": "lms.download_resource",
        "description": "Downloads an academic resource directly from LMS into the user Vault, computing SHA-256 integrity and MIME metadata.",
        "inputSchema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "resource_id": {
                    "type": "string",
                    "description": "Normalized resource identifier (e.g. 'lmsres_103840')."
                },
                "destination_path": {
                    "type": "string",
                    "description": "Target file or directory path in Vault (e.g. 'Cryptography/Books.zip')."
                }
            },
            "required": ["resource_id", "destination_path"],
            "additionalProperties": False
        },
        "required_capability": "lms.resources.download"
    },
    {
        "name": "lms.list_assignments",
        "description": "Scans and lists academic assignments, due dates, and submission states across enrolled courses.",
        "inputSchema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "course_id": {
                    "type": "string",
                    "description": "Optional course identifier to restrict search to a specific course."
                },
                "upcoming_only": {
                    "type": "boolean",
                    "description": "Filter to open/upcoming assignments only (default False)."
                }
            },
            "additionalProperties": False
        },
        "required_capability": "lms.assignments.read"
    },
    {
        "name": "lms.get_assignment",
        "description": "Fetches detailed assignment requirements, submission parameters, allowed formats, and untrusted instructions.",
        "inputSchema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "assignment_id": {
                    "type": "string",
                    "description": "Normalized assignment identifier (e.g. 'lmsassign_112233')."
                }
            },
            "required": ["assignment_id"],
            "additionalProperties": False
        },
        "required_capability": "lms.assignments.read"
    },
    {
        "name": "lms.prepare_submission",
        "description": "Interactive preparatory workflow: validates files, verifies target assignment page, attaches draft files, and captures proof. Strictly does NOT finalize submit.",
        "inputSchema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "assignment_id": {
                    "type": "string",
                    "description": "Normalized assignment identifier (e.g. 'lmsassign_112233')."
                },
                "vault_paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of relative file paths in Vault to attach as submission drafts."
                }
            },
            "required": ["assignment_id", "vault_paths"],
            "additionalProperties": False
        },
        "required_capability": "lms.submission.prepare"
    },
    {
        "name": "lms.submit_assignment",
        "description": "Requests final assignment submission for a prepared SubmissionPlan. Always gated by human/device approval (returns APPROVAL_REQUIRED when requested).",
        "inputSchema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "submission_plan_id": {
                    "type": "string",
                    "description": "Unique SubmissionPlan identifier from lms.prepare_submission (e.g. 'subplan_112233445566')."
                }
            },
            "required": ["submission_plan_id"],
            "additionalProperties": False
        },
        "required_capability": "lms.submission.request"
    },
    {
        "name": "action.status",
        "description": "Queries the current lifecycle state, approval status, or execution outcome of a consequential action.",
        "inputSchema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "action_id": {
                    "type": "string",
                    "description": "Consequential action ID (e.g. 'act_112233445566')."
                }
            },
            "required": ["action_id"],
            "additionalProperties": False
        },
        "required_capability": "action.status.read"
    },

    # --------------------------------------------------------------------------
    # Archive Operations (Phase 3.5)
    # --------------------------------------------------------------------------
    {
        "name": "vault.archive_list",
        "description": "Inspects and lists file contents of a zip or tar archive in the Vault.",
        "inputSchema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path to archive file inside Vault (e.g. 'Cryptography/Books.zip')."
                }
            },
            "required": ["path"],
            "additionalProperties": False
        },
        "required_capability": "vault.archive.read"
    },
    {
        "name": "vault.archive_extract",
        "description": "Safely unpacks a zip or tar archive into a destination Vault directory with strict Zip Slip protection.",
        "inputSchema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path to archive in Vault."
                },
                "destination_dir": {
                    "type": "string",
                    "description": "Target destination directory in Vault (e.g. 'Cryptography/Extracted')."
                },
                "max_files": {
                    "type": "integer",
                    "description": "Maximum number of files allowed to extract (default 500)."
                }
            },
            "required": ["path", "destination_dir"],
            "additionalProperties": False
        },
        "required_capability": "vault.archive.extract"
    },
    # --------------------------------------------------------------------------
    # Document Extraction & Creation (Phase 3.5)
    # --------------------------------------------------------------------------
    {
        "name": "document.extract",
        "description": "Extracts text from academic documents (.pdf, .txt, .md) with page range controls.",
        "inputSchema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path to document inside Vault (e.g. 'Cryptography/syllabus.pdf')."
                },
                "start_page": {
                    "type": "integer",
                    "description": "1-indexed starting page for PDF extraction (default 1)."
                },
                "end_page": {
                    "type": "integer",
                    "description": "1-indexed ending page for PDF extraction (optional)."
                },
                "max_chars": {
                    "type": "integer",
                    "description": "Maximum characters to extract (default 4000, max 20000)."
                }
            },
            "required": ["path"],
            "additionalProperties": False
        },
        "required_capability": "document.extract"
    },
    {
        "name": "document.create",
        "description": "Generates a formatted academic document (.md, .txt, or publication-quality .pdf via ReportLab) in the Vault.",
        "inputSchema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative destination path in Vault (e.g. 'Notes/summary.pdf')."
                },
                "content": {
                    "type": "string",
                    "description": "Text or markdown content to render."
                },
                "format": {
                    "type": "string",
                    "enum": ["pdf", "md", "txt"],
                    "description": "Output format: 'pdf', 'md', or 'txt'."
                },
                "title": {
                    "type": "string",
                    "description": "Optional title for document heading."
                }
            },
            "required": ["path", "content"],
            "additionalProperties": False
        },
        "required_capability": "document.create"
    },
    # --------------------------------------------------------------------------
    # UPES Analytics & Timetable Tools (Phase 3.5)
    # --------------------------------------------------------------------------
    {
        "name": "upes.calculate_attendance",
        "description": "Deterministic what-if attendance projection: computes new attendance percentage, safe bunks, and recovery classes required for a target percentage.",
        "inputSchema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "course": {
                    "type": "string",
                    "description": "Course name or code (e.g. 'AI and Multimedia', 'FLAT', or 'overall')."
                },
                "future_attended": {
                    "type": "integer",
                    "description": "Additional consecutive classes attended (default 0)."
                },
                "future_missed": {
                    "type": "integer",
                    "description": "Additional consecutive classes missed (default 0)."
                },
                "target_percentage": {
                    "type": "number",
                    "description": "Desired minimum attendance percentage threshold (default 75.0)."
                }
            },
            "additionalProperties": False
        },
        "required_capability": "upes.attendance.calculate"
    },
    {
        "name": "upes.get_punches",
        "description": "Retrieves timestamped classroom RFID card reader punch records and attendance history.",
        "inputSchema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "Specific date in YYYY-MM-DD format (e.g. '2026-08-30')."
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum records to return (default 20, max 100)."
                }
            },
            "additionalProperties": False
        },
        "required_capability": "upes.punches.read"
    },
    {
        "name": "upes.export_timetable",
        "description": "Exports the normalized academic timetable to Vault in publication-quality PDF, CSV, or JSON format.",
        "inputSchema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "format": {
                    "type": "string",
                    "enum": ["pdf", "csv", "json"],
                    "description": "Export format: 'pdf' (default), 'csv', or 'json'."
                },
                "destination_path": {
                    "type": "string",
                    "description": "Target Vault path (default 'Timetable/my_timetable.<format>')."
                },
                "start_date": {
                    "type": "string",
                    "description": "Optional start date in YYYY-MM-DD format."
                },
                "end_date": {
                    "type": "string",
                    "description": "Optional end date in YYYY-MM-DD format."
                }
            },
            "additionalProperties": False
        },
        "required_capability": "upes.timetable.export"
    }
]


def adapt_schema_for_gemini(canonical_schema: Dict[str, Any]) -> Dict[str, Any]:
    """
    Gemini Spark Schema Compatibility Adapter:
    Transforms a canonical MCP JSON Schema 2020-12 definition into a 
    Google Gemini / legacy 2024-11-05 FunctionDeclaration-compliant schema.
    Recursively strips metadata keywords ($schema, $id, additionalProperties) and normalizes empty objects.
    Canonical schemas in MCP_TOOL_DEFINITIONS and server-side validation remain untouched.
    """
    def _clean_node(node):
        if not isinstance(node, dict):
            return node
        cleaned = {}
        for k, v in node.items():
            # Strip JSON Schema metadata unsupported in Google Cloud FunctionDeclaration
            if k in ("$schema", "$id", "additionalProperties"):
                continue
            if isinstance(v, dict):
                cleaned[k] = _clean_node(v)
            elif isinstance(v, list):
                cleaned[k] = [_clean_node(item) for item in v]
            else:
                cleaned[k] = v
        # Normalize parameterless objects
        if cleaned.get("type") == "object":
            props = cleaned.get("properties")
            if props is not None and len(props) == 0 and not cleaned.get("required"):
                cleaned.pop("properties", None)
        return cleaned

    return _clean_node(copy.deepcopy(canonical_schema))


class McpServerAdapter:
    """
    Authoritative Model Context Protocol (MCP 2026-07-28) server adapter for NexusNode.
    Exposes AgentOperationRegistry tools over modern stateless Streamable HTTP transport.
    """

    def __init__(
        self,
        registry: AgentOperationRegistry,
        token_manager: AgentTokenManager,
        rate_limiter: Optional[AgentRateLimiter] = None,
        execution_router: Optional[Any] = None,
        semantic_facade: Optional[Any] = None
    ):
        self.registry = registry
        self.token_manager = token_manager
        self.rate_limiter = rate_limiter or AgentRateLimiter(default_principal_rpm=config.MCP_DEFAULT_RATE_LIMIT)
        self.execution_router = execution_router or getattr(registry, "execution_router", None)
        self.semantic_facade = semantic_facade or SemanticMcpFacade(
            registry=self.registry,
            execution_router=self.execution_router,
            token_manager=self.token_manager,
            policy_engine=getattr(self.registry, "policy_engine", None)
        )
        self.tool_defs = {t["name"]: t for t in MCP_TOOL_DEFINITIONS}
        self.server_name = getattr(config, "MCP_SERVER_NAME", "nexusnode-mcp")
        self.server_version = getattr(config, "MCP_SERVER_VERSION", "2.3.2")
        self.protocol_version = getattr(config, "MCP_PROTOCOL_VERSION", "2026-07-28")
        self.supported_versions = getattr(config, "MCP_SUPPORTED_PROTOCOL_VERSIONS", ["2026-07-28", "2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05"])

    def validate_request_headers(
        self,
        request: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Validates HTTP headers against the MCP 2026-07-28 Streamable HTTP specification.
        Returns a JSON-RPC error dict if invalid, or None if valid.
        """
        if not headers:
            return None

        # Normalize header keys to lowercase
        norm_headers = {k.lower(): v for k, v in headers.items()}
        req_id = request.get("id")
        method = request.get("method")
        params = request.get("params") or {}

        # 1. MCP-Protocol-Version validation
        proto_ver = norm_headers.get("mcp-protocol-version")
        if proto_ver and proto_ver not in self.supported_versions:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": -32600,
                    "message": f"Unsupported MCP-Protocol-Version '{proto_ver}'. Supported: {self.supported_versions}"
                }
            }

        # 2. Mcp-Method header validation
        mcp_method = norm_headers.get("mcp-method")
        if mcp_method and mcp_method != method:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": -32600,
                    "message": f"Header Mcp-Method '{mcp_method}' does not match JSON-RPC request method '{method}'."
                }
            }

        # 3. Mcp-Name header validation for tools/call
        mcp_name = norm_headers.get("mcp-name")
        if mcp_name and method == "tools/call":
            target_name = params.get("name")
            if mcp_name != target_name:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {
                        "code": -32600,
                        "message": f"Header Mcp-Name '{mcp_name}' does not match tools/call target '{target_name}'."
                    }
                }

        return None

    def handle_json_rpc(
        self,
        request: Dict[str, Any],
        token_metadata: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Dispatches a single JSON-RPC 2.0 message against the MCP 2026-07-28 specification.
        Returns a JSON-RPC 2.0 response dictionary (or None for notifications).
        """
        req_id = request.get("id") if isinstance(request, dict) else None
        method = request.get("method") if isinstance(request, dict) else None
        params = (request.get("params") or {}) if isinstance(request, dict) else {}
        norm_headers = {k.lower(): v for k, v in (headers or {}).items()}
        principal = token_metadata.get("principal", "spark-agent")
        proto_ver = norm_headers.get("mcp-protocol-version")
        user_agent = norm_headers.get("user-agent", "")
        meta = params.get("_meta", {}) if isinstance(params, dict) else {}
        meta_ver = meta.get("io.modelcontextprotocol/protocolVersion")
        # If client explicitly requests modern 2026-07-28, preserve full canonical JSON Schema 2020-12
        if proto_ver == "2026-07-28" or meta_ver == "2026-07-28":
            is_gemini_client = False
        else:
            is_gemini_client = (
                ("google" in user_agent.lower()) or 
                ("gemini" in user_agent.lower()) or 
                (principal in ("spark-agent", "gemini-spark")) or 
                (proto_ver in ("2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25")) or 
                (self.protocol_version != "2026-07-28")
            )

        # Detect client types for schema adaptation
        is_mistral_client = (
            ("mistral" in user_agent.lower()) or 
            (principal in ("mistral-agent", "mistral-client"))
        )

        # Validate JSON-RPC structure
        if not isinstance(request, dict) or request.get("jsonrpc") != "2.0" or not method:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": -32600,
                    "message": "Invalid Request: expected jsonrpc='2.0' and valid method."
                }
            }

        # Validate MCP 2026-07-28 Streamable HTTP headers if provided
        header_err = self.validate_request_headers(request, headers)
        if header_err:
            return header_err

        # ======================================================================
        # 1. server/discover (MCP 2026-07-28 Modern Capability Probe)
        # ======================================================================
        if method == "server/discover":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersions": self.supported_versions,
                    "defaultProtocolVersion": self.protocol_version,
                    "serverInfo": {
                        "name": self.server_name,
                        "version": self.server_version
                    },
                    "capabilities": {
                        "tools": {
                            "listChanged": False
                        }
                    }
                }
            }

        # ======================================================================
        # 2. tools/list (Modern Stateless Tool Catalog Discovery)
        # ======================================================================
        elif method == "tools/list":
            catalog_mode = getattr(config, "MCP_CATALOG_MODE", "semantic")
            client_type = "gemini" if is_gemini_client else ("mistral" if is_mistral_client else "canonical")

            if catalog_mode == "semantic":
                tools = self.semantic_facade.get_tool_definitions(
                    catalog_mode="semantic",
                    client_type=client_type,
                    token_metadata=token_metadata
                )
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "tools": tools
                    }
                }
            else:
                # Legacy catalog mode (43+ granular tools)
                exposed_filter = getattr(config, "MCP_EXPOSED_TOOLS", None)
                available_tools = []
                for t in MCP_TOOL_DEFINITIONS:
                    if exposed_filter is not None and t["name"] not in exposed_filter:
                        continue
                    if self.token_manager.check_capability(token_metadata, t["required_capability"]):
                        raw_schema = t["inputSchema"]
                        if client_type == "gemini":
                            schema = adapt_schema_for_gemini(raw_schema)
                        elif client_type == "mistral":
                            schema = adapt_schema_for_mistral(raw_schema)
                        else:
                            schema = copy.deepcopy(raw_schema)
                        available_tools.append({
                            "name": t["name"],
                            "description": t["description"],
                            "inputSchema": schema
                        })
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "tools": available_tools
                    }
                }

        # ======================================================================
        # 3. tools/call (Modern Stateless Semantic Execution)
        # ======================================================================
        elif method == "tools/call":
            tool_name = params.get("name")
            tool_args = params.get("arguments") or {}

            if not tool_name or not isinstance(tool_name, str):
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {
                        "code": -32602,
                        "message": "Invalid params: 'name' is required for tools/call."
                    }
                }

            catalog_mode = getattr(config, "MCP_CATALOG_MODE", "semantic")

            # Check if handled by Semantic Facade
            if self.semantic_facade.is_semantic_tool(tool_name):
                principal = token_metadata.get("principal", "spark-agent")
                allowed, rate_err, retry_sec = self.rate_limiter.check_rate_limit(principal, tool_name)
                if not allowed:
                    return {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "error": {
                            "code": -32000,
                            "message": f"Rate limit exceeded: {rate_err}",
                            "data": {"retry_after_seconds": retry_sec}
                        }
                    }

                facade_res = self.semantic_facade.execute(
                    tool_name=tool_name,
                    arguments=tool_args,
                    token_metadata=token_metadata
                )
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": facade_res
                }

            # In semantic mode, unknown or legacy tools are not directly accessible
            if catalog_mode == "semantic":
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {
                        "code": -32601,
                        "message": f"Method/Tool '{tool_name}' not found in active catalog '{catalog_mode}'."
                    }
                }

            # Legacy mode tool dispatch
            tool_def = self.tool_defs.get(tool_name)
            if not tool_def:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {
                        "code": -32601,
                        "message": f"Method/Tool '{tool_name}' not found on MCP gateway."
                    }
                }

            # Check Capability Authorization
            req_cap = tool_def["required_capability"]
            if not self.token_manager.check_capability(token_metadata, req_cap):
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {
                        "code": -32000,
                        "message": f"Principal '{token_metadata.get('principal')}' lacks capability '{req_cap}' for tool '{tool_name}'."
                    }
                }

            # Check Rate Limits
            principal = token_metadata.get("principal", "spark-agent")
            allowed, rate_err, retry_sec = self.rate_limiter.check_rate_limit(principal, tool_name)
            if not allowed:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {
                        "code": -32000,
                        "message": f"Rate limit exceeded: {rate_err}",
                        "data": {"retry_after_seconds": retry_sec}
                    }
                }

            # Execute Tool through Registry & Policy Engine
            start_t = time.time()
            target_user_id = token_metadata.get("user_id") or "admin"
            try:
                exec_result: ExecutionResult = self.registry.execute(
                    operation_name=tool_name,
                    user_id=target_user_id,
                    params=tool_args
                )
            except Exception as ex:
                logger.exception(f"Unhandled exception executing MCP tool '{tool_name}': {ex}")
                exec_result = ExecutionResult(
                    ok=False,
                    operation=tool_name,
                    source="local",
                    provider="mcp_gateway",
                    error=f"Tool execution failed: {str(ex)}",
                    error_code="INTERNAL_ERROR"
                )

            duration_ms = round((time.time() - start_t) * 1000, 2)
            logger.info(f"[MCP_CALL] principal='{principal}' tool='{tool_name}' ok={exec_result.ok} duration={duration_ms}ms")

            # Defensive Output Sanitization
            raw_dict = exec_result.to_dict()
            sanitized_dict = sanitize_data(raw_dict)
            content_json = json.dumps(sanitized_dict, indent=2, default=str)

            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": content_json
                        }
                    ],
                    "isError": not exec_result.ok
                }
            }

        # ======================================================================
        # 4. Backward-Compatible Handlers (Legacy 2024-11-05 Clients)
        # ======================================================================
        elif method == "initialize":
            req_version = params.get("protocolVersion") if isinstance(params, dict) else None
            # Standard exact-match version negotiation:
            # If client specifies a supported version, negotiate to it; otherwise default to server's protocol_version
            if req_version and req_version in self.supported_versions:
                negotiated_version = req_version
            elif not req_version:
                negotiated_version = self.protocol_version
            else:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {
                        "code": -32602,
                        "message": f"Unsupported protocolVersion '{req_version}'. Supported versions: {self.supported_versions}",
                        "data": {
                            "supported": self.supported_versions
                        }
                    }
                }

            self.protocol_version = negotiated_version

            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": negotiated_version,
                    "capabilities": {
                        "tools": {
                            "listChanged": False
                        }
                    },
                    "serverInfo": {
                        "name": self.server_name,
                        "version": self.server_version
                    }
                }
            }

        elif method in ("notifications/initialized", "initialized"):
            return None

        elif method == "ping":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {}
            }

        # ======================================================================
        # 5. Unknown Method
        # ======================================================================
        else:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": -32601,
                    "message": f"Method '{method}' is not implemented by this MCP server."
                }
            }
