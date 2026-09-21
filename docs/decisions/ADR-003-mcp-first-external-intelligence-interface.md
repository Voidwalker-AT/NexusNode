# ADR-003: MCP-First External Intelligence Interface

**Status:** ACCEPTED  
**Scope:** Client Integration & Protocol Standards  
**Last verified:** 2026-09-20  
**Evidence basis:** Phase 4.1C implementation, RFC 9728 implementation, `agent/mcp_server.py`  

---

## Context
External AI assistants (e.g. Gemini Spark, Claude, Mistral) need structured access to student schedules, attendance, LMS materials, and personal Vault storage. Custom proprietary REST APIs or ad-hoc webhooks require custom client plugins, lack standardized authentication discovery, and fail to provide structured capability negotiation.

## Decision
Adopt Anthropic's Model Context Protocol (MCP) as the sole external standard interface for AI client connectivity. NexusNode exposes an HTTP/SSE streamable MCP endpoint supporting RFC 9728 OAuth 2.0 discovery, protected resource metadata, dynamic tool catalogs, and JSON-RPC 2.0 dispatch.

## Alternatives Considered
1. **Custom REST API for Assistants**: Rejected due to lack of native client integration in frontier models and absence of standard schema reflection.
2. **OpenAI Assistant Function Calling Bridge**: Rejected due to proprietary lock-in; MCP provides an open, vendor-neutral standard supported by multiple leading model providers.

## Consequences
- **Positive**: Direct zero-plugin integration with Gemini Spark, Claude Desktop, and compatible MCP clients; standardized error codes, schema validation, and structured tool listing.
- **Negative**: Requires strict protocol compliance (e.g. handling protocol versions `2024-11-05`, `2026-07-28`); requires OAuth 2.0 token infrastructure.

## Evidence
- `agent/mcp_server.py` and `agent/oauth_provider.py` pass automated Gemini Spark compliance tests (`tests/test_gemini_spark_compliance.py`).
- RFC 9728 metadata successfully served at `/.well-known/oauth-authorization-server` and `/.well-known/oauth-protected-resource`.

## Related Components
- `agent/mcp_server.py`
- `agent/oauth_provider.py`
- `agent/mcp_auth.py`
