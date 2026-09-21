# NexusNode Glossary

> **Status**: VERIFIED CURRENT  
> **Scope**: Authoritative definitions of system terms, concepts, protocols, and components  
> **Last verified**: 2026-09-20 (Phase 4.2B Post-Rebase Audit)  
> **Evidence basis**: Architectural specifications, codebase nomenclature, and system audit

---

## A

### Academic Automation Engine
The subsystem within NexusNode responsible for interfacing with academic portals (specifically UPES Student Portal and Blackboard Learn LMS). It extracts attendance logs, class timetables, enrolled courses, and assignment metadata, persisting them into normalized SQLite tables.

### Admission Gate
A runtime memory governor in the browser execution engine. Before launching an ephemeral Chromium instance, the admission gate checks `/proc/meminfo`. If `MemAvailable` is less than `500 MB` (or swap/zram pressure exceeds threshold), browser launch requests are queued or rejected to protect system stability.

### Approval Grant (`ApprovalGrantManager`)
A security mechanism enforcing human-in-the-loop authorization for consequential or irreversible actions (e.g., submitting an LMS assignment, deleting academic records, purging Vault folders). Remote MCP clients receive an `APPROVAL_REQUIRED` challenge containing an action hash and human-readable explanation, requiring an out-of-band approval token generated via the web dashboard.

### Atomic Operation Registry
The internal collection of 43+ granular, low-level Python tool implementations (`scrape_attendance`, `fetch_lms_courses`, `calendar_insert_event`, etc.). These operations are encapsulated beneath the high-level Semantic Facade but remain available for internal pipelining and test execution.

---

## B

### Blackboard Learn LMS
The Learning Management System used by UPES. NexusNode connects to it via authenticated HTTP REST sessions to fetch assignment deadlines, announcements, course materials, and grade structures.

### Browser Engine (`src/browser/`)
The headless automation engine residing inside a `proot-distro` Alpine Linux container on the TECNO BG6 appliance. It orchestrates ephemeral Chromium processes via the Chrome DevTools Protocol (CDP) for dynamic pages that cannot be scraped via direct HTTP.

---

## C

### CDP (Chrome DevTools Protocol)
The WebSocket-based binary/JSON protocol used to communicate directly with Chromium. NexusNode uses CDP to navigate pages, inspect DOM elements, extract accessibility trees, and capture targeted screenshots without requiring heavy external browser drivers.

### Consequential Action
Any operation that modifies external state, publishes academic assignments, sends authenticated requests to institutional portals, or permanently removes stored user data. All consequential actions require explicit Approval Grants.

---

## E

### Ephemeral Browser Lifecycle
The operational model where Chromium is launched on demand for a single task or batch of actions, immediately dumps its findings, and is terminated. No long-running browser background daemon or persistent tab session is maintained.

### ExecutionRouter (`src/router/execution_router.py`)
The intelligent dispatch layer that resolves academic queries across three hierarchical tiers:
1. **Tier 1 (Local Cache)**: Immediate query against local SQLite tables.
2. **Tier 2 (Direct HTTP/API)**: Fast HTTP request using stored authenticated cookies.
3. **Tier 3 (Browser Fallback)**: Launching ephemeral Chromium to solve dynamic JavaScript challenges or session re-authentication.

---

## L

### Localtonet
The reverse tunneling daemon supervised by `runit` on the TECNO BG6. It securely exposes NexusNode's internal port 5000 to the public internet (`k09oezeyib.localto.net`) with TLS termination, allowing remote MCP clients to interact with the appliance.

---

## M

### MCP (Model Context Protocol)
An open standard developed by Anthropic allowing AI models to securely connect to external data sources and tools. NexusNode acts as an MCP server over HTTP/SSE, exposing tools to remote reasoning clients such as Gemini Spark and Mistral.

### Multi-Tenant User Isolation
The architectural guarantee that all stored records, credentials, session cookies, timetable events, and Vault documents are partitioned by a foreign key `user_id`. Queries and tool executions must validate user authorization; cross-tenant data leakage is strictly prohibited.

---

## P

### Proot-Distro Alpine
A userspace chroot/container environment running inside Termux on Android. It provides a standard glibc/musl Linux userspace with native package management (`apk`), allowing Chromium and font packages to run reliably without requiring Android OS root access.

---

## R

### Runit
The UNIX service supervision suite running under Termux on the BG6 appliance. It supervises background daemons (`nexusnode`, `localtonet`, `cloudflared`), automatically restarting them if they crash and handling signal termination.

---

## S

### Semantic Facade (`nexus-semantic-v1`)
The high-level MCP tool layer exposing exactly 11 curated tools to remote LLMs. It abstracts complex multi-step workflows (e.g., querying attendance + analyzing trends + timetable correlation) into single, context-efficient interfaces.

---

## T

### TECNO BG6
The hardware appliance hosting NexusNode: a TECNO Spark Go 2024 smartphone featuring an octa-core ARM64 Unisoc T606 processor, 3.77 GB RAM, Android 13 (Termux), operating 24/7 on continuous power.

### Tree Sanitizer (`AXSanitizer`)
A filter pipeline that processes raw Chromium CDP Accessibility Trees (often 200–500 KB) by stripping non-interactive nodes, empty layout containers, and redundant attributes. It yields a clean semantic tree (typically <10 KB, 97%+ reduction) that easily fits within LLM context windows.

---

## V

### Vault (`storage_vault/`)
The encrypted local file storage repository managed by NexusNode. It stores user-uploaded documents, academic syllabus archives, cached portal reports, and system backup snapshots.

---

## Z

### Zero-Touch Sync
The automated background synchronization worker. Periodically connects to academic portals using encrypted refresh tokens to update attendance and timetable data without requiring manual user intervention.
