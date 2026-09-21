# NexusNode — Gemini Spark Model Context Protocol (MCP) Gateway
**Authoritative Architectural Specification & Integration Reference**
*Phase 3.3B — Modern Stateless MCP (2026-07-28) Production Baseline*

---

## 1. Overview & Architectural Role

The **NexusNode MCP Gateway** provides a secure, stateless, protocol-compliant integration bridge between **Gemini Spark** (acting as the remote reasoning and planning agent) and **NexusNode** (running locally on the TECNO BG6 mobile hardware appliance).

```
 ┌─────────────────────────────────────────────────────────────────────────┐
 │                       GEMINI SPARK (Remote Agent)                       │
 │      Main Plan / Goal Reasoning / User Dialogue / Tool Invocations     │
 └────────────────────────────────────┬────────────────────────────────────┘
                                      │ HTTPS / Streamable HTTP (JSON-RPC 2.0)
                                      │ MCP-Protocol-Version: 2026-07-28
                                      │ Mcp-Method: <method>  |  Mcp-Name: <name>
                                      │ Authorization: Bearer <agent_token>
                                      ▼
 ┌─────────────────────────────────────────────────────────────────────────┐
 │                  NEXUSNODE MODERN MCP GATEWAY (2026-07-28)              │
 │    Endpoint: /api/mcp  |  Protocol: 2026-07-28  |  Port: 5000 / Tunnel   │
 ├─────────────────────────────────────────────────────────────────────────┤
 │ 1. Modern Header Validation (MCP-Protocol-Version, Mcp-Method, Mcp-Name)│
 │ 2. Agent Authentication Layer (AgentTokenManager: SHA-256 Verifier)     │
 │ 3. Rate Limiting Layer (AgentRateLimiter: Sliding-Window per Principal)  │
 │ 4. Policy & Provenance Engine (RiskClass.READ_ONLY, Audit Tracking)     │
 │ 5. Dispatch Adapter -> AgentOperationRegistry.execute(...)              │
 ├────────────────────────────────────┬────────────────────────────────────┤
 │                                    │                                    │
 │   ┌──────────────────────────┐     │     ┌──────────────────────────┐   │
 │   │  UPES Semantic Router    │     │     │   Vault Semantic Service │   │
 │   │  • upes.auth_status      │     │     │   (AGENT_VAULT_ROOT only)│   │
 │   │  • upes.get_attendance   │     │     │   • vault.list           │   │
 │   │  • upes.get_timetable    │     │     │   • vault.search         │   │
 │   │  • upes.get_next_classes │     │     │   • vault.read           │   │
 │   │  • upes.get_courses      │     │     └──────────────────────────┘   │
 │   └──────────────────────────┘     │     ┌──────────────────────────┐   │
 │   ┌──────────────────────────┐     │     │   Browser & Health       │   │
 │   │  Appliance Status        │     │     │   • browser.status       │   │
 │   │  • nexus.status          │     │     │   (No click/type/action) │   │
 │   └──────────────────────────┘     │     └──────────────────────────┘   │
 ├────────────────────────────────────┴────────────────────────────────────┤
 │ 6. Output Sanitizer (Defense-in-Depth Secret & Token Redaction)          │
 │ 7. Structural Untrusted Document Packaging (<untrusted_document>)       │
 └─────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Protocol Specification & Transport (MCP 2026-07-28)

NexusNode implements the official **Model Context Protocol (MCP 2026-07-28)** specification.

### Key Architectural Characteristics
1. **Stateless Core**:
   - The protocol-level initialization handshake (`initialize` / `notifications/initialized`) and `Mcp-Session-Id` header are **removed** for modern clients.
   - Every request is self-contained and carries its own version and client information in the `_meta` field.
2. **Streamable HTTP Transport**:
   - `POST /api/mcp` and `POST /mcp` handle all JSON-RPC 2.0 methods.
   - Health check available at `GET /api/mcp/health`.
3. **Required & Validated Headers**:
   - `MCP-Protocol-Version`: `2026-07-28`
   - `Mcp-Method`: The JSON-RPC method (e.g. `server/discover`, `tools/list`, `tools/call`, `ping`)
   - `Mcp-Name`: Tool name (required when `Mcp-Method` is `tools/call`)
   - `Authorization`: `Bearer <agent_token>`
4. **Header Consistency Enforcement**:
   - If `Mcp-Method` does not match `body.method`, request is rejected with `-32600`.
   - If `Mcp-Name` does not match `body.params.name`, request is rejected with `-32600`.
5. **Backward Compatibility**:
   - Legacy 2024-11-05 / 2025 requests (`initialize`, `notifications/initialized`, `ping`) continue to be supported gracefully.

---

## 3. Supported Methods

### 1. `server/discover`
Primary capability discovery query for modern MCP 2026-07-28 clients.
- **Request**:
  ```json
  {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "server/discover",
    "params": {
      "_meta": {
        "io.modelcontextprotocol/protocolVersion": "2026-07-28"
      }
    }
  }
  ```
- **Response**:
  ```json
  {
    "jsonrpc": "2.0",
    "id": 1,
    "result": {
      "protocolVersions": ["2026-07-28", "2024-11-05"],
      "defaultProtocolVersion": "2026-07-28",
      "serverInfo": {
        "name": "nexusnode-mcp",
        "version": "2.3.2"
      },
      "capabilities": {
        "tools": {
          "listChanged": false
        }
      }
    }
  }
  ```

### 2. `tools/list`
Stateless tool discovery returning all authorized tools for the authenticated principal.
- **Response**: Returns list of tools formatted in **JSON Schema 2020-12**.

### 3. `tools/call`
Stateless semantic tool invocation.
- **Headers**:
  - `Mcp-Method: tools/call`
  - `Mcp-Name: <tool_name>`
- **Request Body**:
  ```json
  {
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/call",
    "params": {
      "name": "upes.get_next_classes",
      "arguments": { "limit": 2 },
      "_meta": {
        "io.modelcontextprotocol/protocolVersion": "2026-07-28"
      }
    }
  }
  ```

---

## 4. Authoritative Tool Surface (41 Total Tools)

### Appliance Status (1)
- `nexus.status`: Safe appliance metrics and subsystem health.

### UPES Academic Analytics & Timetable (8)
- `upes.auth_status`: Session status and token TTL.
- `upes.get_attendance`: Official real-time attendance ledger.
- `upes.get_timetable`: Class schedule with date range bounds.
- `upes.get_next_classes`: Next upcoming class slots.
- `upes.get_courses`: Registered courses and module codes.
- `upes.calculate_attendance`: Integer-count attendance projection, safe bunks, and recovery math.
- `upes.get_punches`: RFID punch card history with local provenance.
- `upes.export_timetable`: Export schedule to PDF (ReportLab), CSV, or JSON in Vault.

### LMS & Moodle Integration (7)
- `lms.list_courses`: Discovered courses on UPES Moodle LMS.
- `lms.get_course`: Course syllabus outline, modules, and resources.
- `lms.list_resources`: All downloadable documents, PDFs, and files in a course.
- `lms.download_resource`: Transfer course file from LMS directly into BG6 Vault.
- `lms.list_assignments`: Discover open assignments, due dates, and status.
- `lms.get_assignment`: Assignment details with untrusted content boundaries.
- `lms.prepare_submission`: Assemble, verify, and stage submission files into a persistent `SubmissionPlan`.

### Vault & Document Processing (11)
- `vault.list`, `vault.search`, `vault.read`: Read and discover documents in Vault.
- `vault.mkdir`, `vault.create`, `vault.write`, `vault.rename`, `vault.move`, `vault.copy`: Full writable Vault file management.
- `vault.archive_list`: Inspect `.zip` / `.tar.gz` archive contents safely.
- `vault.archive_extract`: Safe archive extraction with strict Zip Slip defense and resource bounds.
- `document.extract`: Extract text from PDF, Markdown, or Text with bounded pagination.
- `document.create`: Generate Markdown, Text, or publication-quality PDF via ReportLab.

### Controlled Browser Execution (Fallback / Interactive) (14)
- `browser.status`, `browser.health`: PinchTab worker diagnostic.
- `browser.open`, `browser.close`, `browser.navigate`: Tab session management.
- `browser.snapshot`, `browser.screenshot`, `browser.capture`: Multi-modal state perception.
- `browser.click`, `browser.type`, `browser.press`: Controlled input events (guarded against consequential actions).
- `browser.upload`, `browser.download`: Bidirectional file transfer.
- *(Note: `upes.submit_assignment` is strictly `CONSEQUENTIAL` and blocked behind user approval).*

---

## 5. Safe Vault Allowlist Security Boundary

- **Isolated Agent Root**: Locked strictly to `config.AGENT_VAULT_ROOT` (`storage_vault/user_files/`).
- **Infrastructure File Protection**: Hard-blocks access to `nexus_unified.db`, `.nexus_secret`, `backups/`, `*.enc`, internal indexes, or logs.
- **Path Traversal & Symlink Defense**: Full canonical path validation with `os.path.commonpath` verification; external symlinks are rejected.
- **Prompt Injection Defense**: File read contents are encapsulated in structural `<untrusted_document_content>` envelopes.

---

## 6. Verification with MCP 2026-07-28 Client

NexusNode includes a built-in modern verification client (`agent/mcp_client.py`):

```bash
python -m agent.mcp_client --url http://127.0.0.1:5000/api/mcp --token <AGENT_TOKEN>
```

---

## 7. Connecting Gemini Spark to NexusNode

When configuring Gemini Spark in the agent management interface / settings:

1. **MCP Endpoint URL**:
   - Local Network: `http://<BG6_IP>:5000/api/mcp`
   - Remote Localtonet Tunnel: `https://<YOUR_LOCALTONET_TUNNEL>/api/mcp`
2. **Transport Type**: `Streamable HTTP` / `HTTP POST`
3. **Protocol Version**: `2026-07-28`
4. **HTTP Headers**:
   ```http
   Authorization: Bearer <AGENT_TOKEN>
   MCP-Protocol-Version: 2026-07-28
   localtonet-skip-warning: true
   ```
5. **Tool Discovery**: Gemini Spark will discover tools statelessly via `tools/list` or `server/discover`.
