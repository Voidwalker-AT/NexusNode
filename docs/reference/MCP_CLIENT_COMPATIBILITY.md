# MCP Client Compatibility & Protocol Invariants

## Overview
NexusNode implements the official Model Context Protocol (MCP) Streamable HTTP and SSE transport (`/mcp`, `/api/mcp`) supporting frontier AI client ecosystems including **Google Gemini Spark** and **Mistral AI**.

---

## 1. Exact 11 Semantic Tools Catalog Invariant

> [!IMPORTANT]
> The public semantic tool catalog exposed to MCP clients consists of **exactly 11 canonical tools**. Never add a 12th tool or remove any of the 11 tools.

The authoritative 11 semantic tools are:
1. `nexus.status`: System health, resource telemetry, browser status.
2. `academic.query`: Read timetable, next classes, attendance, punches, courses, results, SGPA/CGPA.
3. `academic.sync`: Trigger background synchronization (timetable, attendance, calendar, results).
4. `academic.analyze`: Deterministic calculations (safe bunks, recovery classes, CGPA/SGPA, What-If GPA).
5. `lms.query`: Course listings, assignment deadlines, resource links.
6. `lms.fetch`: Ingest course contents and materials into local Vault storage.
7. `lms.prepare`: Stage and validate assignment submission drafts (non-consequential).
8. `vault.manage`: File listing, reading, safe creation, and directory organization.
9. `document.process`: Extract and process PDF/Markdown documents in Vault.
10. `browser.interact`: Isolated browser fallback for complex interactive portals.
11. `action.status`: Inspect status of consequential approval requests.

---

## 2. Gemini Spark Compatibility & Schema Adaptation

Gemini models require clean, strict JSON schema declarations. `agent.semantic_facade.adapt_schema_for_gemini()` converts MCP schemas into Gemini function calling format:
- Strips unsupported schema draft keywords (`$schema`, `additionalProperties`).
- Enforces explicit `type: "object"` on nested objects.
- Preserves exact parameter enums, types, and descriptions.

---

## 3. Mistral AI Tool-Calling Compatibility

`agent.semantic_facade.adapt_schema_for_mistral()` formats tool definitions into standard OpenAI/Mistral function calling specifications:
```json
{
  "type": "function",
  "function": {
    "name": "academic.query",
    "description": "...",
    "parameters": { ... }
  }
}
```

---

## 4. Multi-Tenant Authorization & Principal Scoping

- **Authentication**: MCP requests require a Bearer agent token or OAuth 2.0 access token passed via `Authorization: Bearer <token>` or `X-Nexus-Agent-Token`.
- **Tenant Derivation**: The agent token resolves to an `AuthenticatedPrincipal`. The caller's effective tenant (`user_id`) is strictly bound to the token's authenticated principal.
- **Spoofing Rejection**: Parameter attempts to access or mutate other student accounts are rejected with `UNAUTHORIZED` or stripped.

---

## 5. Consequential Action Guardrails & LMS Safety

- **Read-Only Invariant**: Browsing LMS courses, reading assignment details, and downloading syllabus documents to Vault are classified as safe (`READ_ONLY` / `WRITE_LOW_RISK`) and execute over direct HTTPS with 0 Chromium browser launches.
- **Consequential Blocking**: Any assignment submission action (`lms.submit_assignment` via `lms.prepare`) is classified as `RiskClass.CONSEQUENTIAL`. Direct execution returns `APPROVAL_REQUIRED` and generates a non-repudiable `ConsequentialAction` approval request. Final submission cannot execute without explicit human approval grant.
