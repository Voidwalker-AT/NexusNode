# ADR-010: First-Party Dashboard Uses REST Instead of MCP Internally

**Status:** ACCEPTED  
**Scope:** Frontend Architecture & Protocol Boundaries  
**Last verified:** 2026-09-20  
**Evidence basis:** Phase 4.2A product rebase, `static/js/`, `tests/test_ui_rebase_contract.py`  

---

## Context
During the design of the Phase 4.2A UI rebase, an architectural question arose: Should the first-party web interface also use the MCP JSON-RPC protocol over HTTP to query server state, or should it use domain-specific REST endpoints?

## Decision
Enforce a clean protocol separation:
1. **External AI Clients**: Connect exclusively via **Model Context Protocol (MCP)** using `nexus-semantic-v1`.
2. **First-Party Web Dashboard**: Connects exclusively via **direct REST endpoints** (`/api/dashboard/summary`, `/api/mcp/summary`, `/api/lms/*`, `/files`, `/api/system/*`).
3. **Rationale**: Web UI interactions require granular status codes, fast JSON payloads, HTTP caching, and standard session cookies/bearer headers. Forcing the web UI to format JSON-RPC 2.0 requests with tool names and unpack semantic envelopes introduces unnecessary serialization overhead, complex client-side state machines, and couples the human UI to the AI model interface.

## Alternatives Considered
1. **Dogfooding MCP for Web UI**: Rejected because MCP is designed for asynchronous LLM tool calling, not synchronous human UI interactions (e.g. paginating 500 files or rendering a timetable grid).
2. **GraphQL**: Rejected because standard Flask REST endpoints are simpler, require zero third-party dependencies, and execute with minimal memory overhead on Termux.

## Consequences
- **Positive**: First-party dashboard queries execute in <20ms; UI code is clean and modular; MCP schema changes for external AI models do not break the human interface.
- **Negative**: Requires maintaining first-party REST endpoints alongside the MCP semantic facade (though both delegate to the same underlying domain services).

## Evidence
- `tests/test_ui_rebase_contract.py` and `tests/test_phase42a_endpoints.py` confirm first-party REST endpoints operate with 0 MCP overhead and 0 browser launches.

## Related Components
- `app.py`
- `static/js/api.js`
- `static/js/dashboard.js`
- `static/js/academics.js`
