# ADR-008: Consequential Action Approval Grants & Zero Self-Approval

**Status:** ACCEPTED  
**Scope:** Safety Guardrails & Agent Autonomy  
**Last verified:** 2026-09-20  
**Evidence basis:** Phase 3.4 implementation, `agent/consequential.py`, `tests/test_consequential_actions.py`  

---

## Context
When remote AI agents (via MCP) interact with academic infrastructure, actions can be divided into:
- **Read / Diagnostic**: Safe, idempotent operations (e.g. querying timetable, viewing attendance).
- **Consequential / Irreversible**: Operations that alter external academic reality or destroy data (e.g. submitting an LMS assignment, deleting files, modifying portal state).
Allowing an autonomous remote agent to unilaterally perform consequential actions risks irreversible damage from model hallucinations or compromised prompts.

## Decision
Enforce a two-phase commit protocol with an immutable Approval Grant system:
1. **Prepare Phase**: The agent stages the proposed action, computing a deterministic SHA-256 parameter digest and creating an `ApprovalRequest`.
2. **Approval Phase**: An explicit human operator grant (`ApprovalGrant`) must be created out-of-band via the web dashboard or admin interface.
3. **Zero Self-Approval Invariant**: An MCP agent is cryptographically and procedurally prevented from self-approving its own action requests (attempts return JSON-RPC error `-32601` or `-32000`).
4. **Parameter Immutability**: Any discrepancy between the parameters hashed in the approval grant and the parameters passed at execution time results in immediate abort.
5. **Single-Use & Expiry**: Grants expire after a strict TTL (default 15 minutes) and are burned immediately upon execution.

## Alternatives Considered
1. **Prompt-Based Confirmation (Asking the LLM "Are you sure?")**: Rejected because LLMs will routinely confirm their own hallucinated decisions.
2. **Global Pre-Approval Flag (`auto_approve=True`)**: Rejected as an unacceptable security risk for academic submissions.

## Consequences
- **Positive**: Eliminates rogue agent submissions; guarantees complete auditability; protects student GPA and submission integrity.
- **Negative**: Adds a human-in-the-loop step before consequential actions can finalize.

## Evidence
- `tests/test_consequential_actions.py` verifies all 16 safety invariant tests pass, including zero self-approval and parameter tampering rejection.

## Related Components
- `agent/consequential.py`
- `agent/policy.py`
- `agent/lms_service.py`
