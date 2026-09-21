# ADR-004: Semantic Facade Over Granular Atomic Registry

**Status:** ACCEPTED  
**Scope:** MCP Surface Design & Tool Orchestration  
**Last verified:** 2026-09-20  
**Evidence basis:** Phase 4.1C benchmark, `tests/test_semantic_facade.py`, live BG6 deployment  

---

## Context
NexusNode's internal operation registry (`AgentOperationRegistry`) evolved to contain 43+ granular atomic tools (e.g. `upes.get_timetable`, `upes.get_attendance`, `upes.calculate_attendance`, `lms.list_courses`, `lms.get_assignment`). Directly exposing 43+ tools to remote LLMs resulted in:
1. Massive `tools/list` payloads (>30 KB), inflating prompt token overhead on every model turn.
2. Tool selection ambiguity and hallucinated parameter combinations by remote models.
3. Leaking low-level execution primitives directly to external clients.

## Decision
Introduce `nexus-semantic-v1`, a high-level semantic facade exposing exactly **11 high-order intent tools** (`nexus.status`, `academic.query`, `academic.sync`, `academic.analyze`, `lms.query`, `lms.fetch`, `lms.prepare`, `vault.manage`, `document.process`, `browser.interact`, `action.status`). The entire 43+ atomic registry is retained internally as the execution target for the facade.

## Alternatives Considered
1. **Direct Exposure of All 43+ Atomic Tools**: Rejected due to high token costs, model confusion, and security surface expansion.
2. **Deleting Granular Primitives and Hardcoding 11 Large Functions**: Rejected because atomic modularity is essential for fine-grained internal unit testing, route reuse, and security policy checks.

## Consequences
- **Positive**: Reduces `tools/list` payload from ~32 KB to 7.8 KB (76% reduction); eliminates tool hallucination; standardizes parameter validation and provenance envelopes.
- **Negative**: Adds an internal dispatch and translation layer between semantic tools and internal atomic operations.

## Evidence
- `tests/test_semantic_facade.py` confirms all 12 tests pass in <0.1s.
- Live BG6 response from `GET /api/mcp/summary` reports exactly 11 registered semantic tools.

## Related Components
- `agent/semantic_facade.py`
- `agent/registry.py`
- `agent/mcp_server.py`
