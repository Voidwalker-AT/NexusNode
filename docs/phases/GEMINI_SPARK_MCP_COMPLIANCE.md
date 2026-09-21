# Gemini Spark & MCP Compliance Matrix

**Document Version**: 1.0.0  
**Audit Date**: 2026-08-31  
**Status**: Authoritative Compliance Specification

---

## 1. Compliance Matrix

| Requirement Area | Specification / Standard | Required by Gemini? | Required by MCP? | NexusNode Implementation | Compliance Status | Required Changes / Evidence |
|---|---|---|---|---|---|---|
| **MCP Transport** | Streamable HTTP (2026-07-28 / 2025-03-26) & SSE (2024-11-05) | YES | YES | `POST /api/mcp`, `GET /api/mcp` (SSE), `POST /messages` | **PASS** | Full dual-transport JSON-RPC 2.0 gateway implemented in `app.py` and `agent/mcp_server.py`. |
| **MCP Protocol Versions** | 2026-07-28, 2025-03-26, 2024-11-05 | YES | YES | Negotiates `2026-07-28` (default) and backwards-compatible with `2024-11-05` | **PASS** | `MCP-Protocol-Version` header emitted on all MCP responses. |
| **Unauthenticated Challenge** | RFC 9728 §5 / MCP Auth Spec | YES | YES | Returns HTTP 401 with `WWW-Authenticate: Bearer resource_metadata="<origin>/.well-known/oauth-protected-resource/api/mcp"` | **PASS** | Pointing directly to Protected Resource Metadata for automatic discovery. |
| **Protected Resource Metadata** | RFC 9728 | YES | YES | `GET /.well-known/oauth-protected-resource/api/mcp` and `GET /.well-known/oauth-protected-resource` | **PASS** | Emits JSON with `resource`, `authorization_servers`, `scopes_supported`, `bearer_methods_supported`. |
| **Authorization Server Metadata** | RFC 8414 | YES | YES | `GET /.well-known/oauth-authorization-server` and `GET /.well-known/openid-configuration` | **PASS** | Emits standard RFC 8414 metadata matching public HTTPS origin. |
| **Origin / Issuer Consistency** | RFC 8414 §2 / RFC 9728 §3 | YES | YES | Strict origin matching: `https://<public-origin>` used across all discovery docs, auth endpoints, token endpoints | **PASS** | Dynamically derived from reverse-proxy Host header or configured public origin. |
| **Client Authentication Methods** | RFC 6749 §2.3 | YES | YES | Supports `client_secret_basic` (HTTP Basic Authorization header) and `client_secret_post` (request body) | **PASS** | Both methods fully implemented and tested in `oauth_token_endpoint`. |
| **PKCE Verification** | RFC 7636 | YES | YES | S256 (`code_challenge` / `code_verifier`) and PLAIN supported | **PASS** | Validated and enforced atomically in `exchange_authorization_code`. |
| **Authorization Code Exchange** | RFC 6749 §4.1.3 | YES | YES | `POST /oauth/token` validates code, client_id, exact redirect_uri, unexpired TTL (300s), single-use atomic consume | **PASS** | Returns RFC 6749 JSON `{"access_token", "token_type": "Bearer", "expires_in", "refresh_token", "scope"}`. |
| **Refresh Token Rotation** | RFC 6749 §6 | OPTIONAL | OPTIONAL | Refresh token issued (30-day TTL) with atomic rotation | **PASS** | Enabled in `OAuthProvider.refresh_access_token`. |
| **Bearer Token Validation on MCP** | RFC 6750 / MCP Spec | YES | YES | `Authorization: Bearer <token>` validated against `oauth_tokens` table | **PASS** | Maps token to `spark-agent` principal with capability RBAC. |
| **Consequential Action Boundary** | NexusNode Security Architecture | YES | N/A | Consequential tools (e.g. `lms.submit_assignment`) strictly enforce separate interactive ApprovalGrant | **PASS** | Enforced by PolicyEngine and AgentOperationRegistry. |
| **Consent Page UTF-8 Encoding** | W3C HTML5 | YES | N/A | Consent screen renders UTF-8 `<meta charset="utf-8">` and `Content-Type: text/html; charset=utf-8` | **PASS** | Verified rendering without mojibake. |

---

## 2. Tool Catalog & Capabilities Summary

* **Total Exposed MCP Semantic Tools**: 43 tools
  * **System / Appliance**: `nexus.status` (READ_ONLY)
  * **UPES Academic**: `upes.auth_status`, `upes.get_attendance`, `upes.get_timetable`, `upes.get_next_classes`, `upes.get_courses`, `upes.calculate_attendance`, `upes.get_punches`, `upes.export_timetable`
  * **LMS / Moodle**: `lms.list_courses`, `lms.get_course`, `lms.list_resources`, `lms.download_resource`, `lms.list_assignments`, `lms.get_assignment`, `lms.prepare_submission`, `lms.submit_assignment` (CONSEQUENTIAL), `action.status`
  * **Vault / Files**: `vault.list`, `vault.search`, `vault.read`, `vault.mkdir`, `vault.create`, `vault.write`, `vault.rename`, `vault.move`, `vault.copy`, `vault.archive_list`, `vault.archive_extract`
  * **Documents**: `document.extract`, `document.create`
  * **Browser Automation**: `browser.status`, `browser.open`, `browser.close`, `browser.navigate`, `browser.snapshot`, `browser.screenshot`, `browser.capture`, `browser.click`, `browser.type`, `browser.press`, `browser.upload`, `browser.download`
