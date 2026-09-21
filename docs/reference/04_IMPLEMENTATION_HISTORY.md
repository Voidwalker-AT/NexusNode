# 04. Implementation History

**Status:** VERIFIED CURRENT  
**Scope:** Chronological Evolution & Architectural Pivot History  
**Last verified:** 2026-09-20  
**Evidence basis:** Repository commit logs, phase documentation artifacts, historical test records  

---

## 1. Evolution Overview

NexusNode underwent an architectural transformation across four major eras:
1. **Phase 1–2 (General-Purpose AI Media Server)**: Conceived as a home server running Ollama, RAG indexing, local models, audio streaming, and generic automation.
2. **Phase 3 (Academic Specialization & Multi-User)**: Shifted focus toward student productivity: UPES portal scraping, Google Calendar reconciliation, multi-tenant database isolation, and initial MCP experimentation.
3. **Phase 4.0–4.1 (BG6 Ephemeral Browser & Semantic Facade)**: Decommissioned local Ollama; proved headless Chromium viability on the TECNO BG6 via Alpine proot; reduced the MCP surface from 43+ internal atomic tools to an authoritative 11-tool semantic catalog (`nexus-semantic-v1`).
4. **Phase 4.2 (Product Rebase & Canonical Freeze)**: Permanently eliminated obsolete AI Studio/Ollama/Media frontend code; modularized the UI into 10 ES6 controllers; established canonical documentation and repository truth.

---

## 2. Major Decisions & Architectural Transitions

### Transition 1: Decommissioning Local Ollama & AI Workstation Identity
- **Problem**: On the TECNO BG6's ~3.77 GB RAM, running Ollama (even small 1.5B/3B models) consumed 1.5–2.5 GB of RAM, causing Android Low Memory Killer (LMK) crashes and server downtime.
- **Old Approach**: Local Ollama server process supervised by runit, exposed via local chat UI.
- **Evidence**: Measured system memory pressure; frequent server restarts; model loading failures.
- **Decision**: Permanently eliminate local LLM inference. Rely on external frontier models (Gemini Spark, Mistral) via MCP.
- **New Approach**: Lightweight appliance exposing MCP tools over HTTPS; zero local model inference.
- **Current Status**: VERIFIED CURRENT (See [ADR-002](file:///E:/Workspace/Active/server/docs/decisions/ADR-002-remote-ai-reasoning-over-local-ollama.md)).

### Transition 2: Eliminating Windows / PinchTab Browser Dependencies
- **Problem**: Academic browser automation originally relied on "PinchTab", a Windows-only browser utility requiring a connected desktop workstation.
- **Old Approach**: Offloading browser actions over network to a permanent desktop workstation.
- **Evidence**: The user's operational requirement confirmed the TECNO BG6 is the *only* permanently available 24/7 compute appliance.
- **Decision**: Eliminate PinchTab and workstation dependencies. Port headless browser execution directly to the BG6.
- **New Approach**: Ephemeral Chromium running inside Alpine Linux proot on Android/Termux, controlled directly via Chrome DevTools Protocol (CDP).
- **Current Status**: VERIFIED CURRENT (See [ADR-001](file:///E:/Workspace/Active/server/docs/decisions/ADR-001-tecno-bg6-sole-appliance.md) and [ADR-006](file:///E:/Workspace/Active/server/docs/decisions/ADR-006-ephemeral-chromium-instead-of-browser-daemon.md)).

### Transition 3: Proving Ephemeral Chromium Feasibility on BG6 (Phase 4.1A)
- **Problem**: Uncertainty regarding whether ARM64 Android Termux could run Chromium without crashing due to memory limits.
- **Old Approach**: Theoretical estimates mixing desktop benchmarks with mobile assumptions.
- **Evidence**: Conducted 10 controlled benchmark runs on the physical BG6 (`run_bg6_browser_benchmarks.py`). Proved cold-start in 2.15s, single-page render at ~320 MB RSS, and 100% process cleanup with 0 orphaned PIDs.
- **Decision**: Adopt ephemeral single-flight Chromium execution gated by a hardware memory admission check (`MemAvailable >= 500 MB`).
- **New Approach**: Ephemeral browser runtime with 30s watchdog and process tree sweep.
- **Current Status**: VERIFIED CURRENT (See [ADR-006](file:///E:/Workspace/Active/server/docs/decisions/ADR-006-ephemeral-chromium-instead-of-browser-daemon.md)).

### Transition 4: Consolidation to Semantic Facade `nexus-semantic-v1` (Phase 4.1C)
- **Problem**: Directly exposing 43+ atomic tools to Gemini Spark inflated `tools/list` payloads to >32 KB, consumed excessive tokens, and caused tool hallucination.
- **Old Approach**: Registering every internal Python function directly into the external MCP tool catalog.
- **Evidence**: Gemini Spark failed to parse complex multi-tool schemas and hallucinated arguments; excessive token billing per turn.
- **Decision**: Consolidate the external MCP surface to 11 high-order semantic tools while preserving the internal 43+ atomic registry as execution targets.
- **New Approach**: `nexus-semantic-v1` facade handling tenant derivation, validation, and error normalization.
- **Current Status**: VERIFIED CURRENT (See [ADR-004](file:///E:/Workspace/Active/server/docs/decisions/ADR-004-semantic-facade-over-atomic-registry.md)).

### Transition 5: Frontend Product Rebase (Phase 4.2A)
- **Problem**: The web frontend (`index.html`) was a 126 KB monolith containing obsolete AI Studio controls, Ollama selectors, chat message feeds, and broken media widgets.
- **Old Approach**: Monolithic HTML shell with 182 KB `app.js` spaghetti code.
- **Evidence**: Confusion over appliance purpose; dead UI elements throwing 404s on model endpoints; excessive DOM size.
- **Decision**: Full frontend rebase: strip dead code permanently (no CSS hiding), establish exactly 7 canonical views, modularize into 10 ES6 modules, and enforce mobile-first bottom navigation.
- **New Approach**: 14.9 KB semantic `index.html`, 10 modular controllers in `static/js/`, and 100% REST-based communication.
- **Current Status**: VERIFIED CURRENT (See [ADR-010](file:///E:/Workspace/Active/server/docs/decisions/ADR-010-first-party-dashboard-uses-rest-not-mcp.md)).
