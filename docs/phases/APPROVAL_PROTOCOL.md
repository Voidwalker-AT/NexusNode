# NexusNode Approval Protocol

## Overview
The Approval Protocol defines the contract between autonomous agents (such as Gemini Spark), human operators, Samsung mobile devices, and the NexusNode core engine.

---

## Authentication & Authorization Boundaries

| Actor | Access Mechanism | Allowed Actions | Disallowed Actions |
|---|---|---|---|
| **Gemini Spark** | MCP Token / HTTP | Request submission (`lms.submit_assignment`), query status (`action.status`) | Approve, deny, receive signing keys / grants |
| **Human Operator** | Web Session / API Key | List pending (`GET /api/approvals/pending`), inspect details, approve, deny | Bypass TOCTOU hash verification |
| **Samsung Companion** | Mutual Auth / Device Key | Sign approval (`device_signature`, `device_id`), biometrics | Direct database mutation |

---

## Endpoints

### 1. `GET /api/approvals/pending`
Returns active pending approval requests for the authenticated user.

### 2. `GET /api/approvals/<approval_id>`
Retrieves full structured summary, target identity, and evidence references.

### 3. `POST /api/approvals/<approval_id>/approve`
Authorizes the action and triggers single-flight internal execution.
```json
{
  "device_id": "samsung_galaxy_s24",
  "method": "biometric_fingerprint",
  "user_presence": true
}
```

### 4. `POST /api/approvals/<approval_id>/deny`
Denies the action with optional rationale.
```json
{
  "reason": "Draft needs further review"
}
```
