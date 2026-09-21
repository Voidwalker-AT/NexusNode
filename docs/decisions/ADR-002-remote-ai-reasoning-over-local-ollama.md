# ADR-002: Remote AI Reasoning Instead of Local Ollama

**Status:** ACCEPTED  
**Scope:** AI Architecture & Inference Engine  
**Last verified:** 2026-09-20  
**Evidence basis:** Phase 4.0A forensic inventory, BG6 memory measurements, Phase 4.2A UI rebase  

---

## Context
Initial iterations of NexusNode included a local Ollama daemon, quantized GGUF models, RAG vector indexing, and local inference controls. On the TECNO BG6's ~3.77 GB physical RAM, loading even a 1.5B–3B parameter quantized model consumed 1.5–2.5 GB of RAM, causing severe Android low-memory killer (LMK) thrashing, swapping, and frequent process termination of the core server.

## Decision
Permanently decommission and eliminate all local LLM inference, Ollama services, and in-process neural model execution from the BG6. AI reasoning is entirely outsourced to remote high-capability frontier models (such as Gemini 2.5 Spark and Mistral) via the Model Context Protocol (MCP). NexusNode acts strictly as the tool execution, state management, and academic data appliance.

## Alternatives Considered
1. **Local TinyLLM (e.g. Qwen 0.5B / SmolLM)**: Rejected because reasoning quality on complex academic scheduling, multi-step LMS workflows, and tool calling was inadequate, while still incurring an unacceptable ~400–600 MB memory overhead.
2. **Hybrid Workstation Offload**: Rejected due to lack of a permanent 24/7 workstation (ADR-001).

## Consequences
- **Positive**: Frees ~2 GB of appliance memory; eliminates Android LMK crashes; delivers frontier-class reasoning and multimodal capabilities to student workflows via MCP.
- **Negative**: Requires outbound internet connectivity to cloud LLM providers; introduces network latency for model turns.

## Evidence
- Elimination of Ollama reduced idle system memory footprint from critical pressure (<400 MB free) to healthy headroom (>1.6 GB free).
- Live BG6 telemetry confirms 0 Ollama processes active.

## Related Components
- `agent/mcp_server.py`
- `agent/semantic_facade.py`
- `services/ollama` (marked as DEAD_CODE_CANDIDATE)
