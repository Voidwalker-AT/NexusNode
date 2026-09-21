# LMS Semantic Tools Architecture & Specification (Phase 3.5)

## 1. Executive Summary

Phase 3.5 implements native, semantic academic and LMS workflows for NexusNode and Gemini Spark. Instead of exposing raw browser automation (clicking, typing, arbitrary JavaScript execution) to the reasoning agent, NexusNode exposes **domain-level semantic tools** backed by an authoritative **Direct HTTP Priority** engine and an isolated **BrowserService bridge** when interactive browser workflows are mandatory.

```
       Gemini Spark / MCP Client
                  │
                  ▼  (JSON-RPC 2026-07-28)
       NexusNode MCP Gateway (41 Tools)
                  │
       AgentOperationRegistry + PolicyEngine
                  │
     ┌────────────┴────────────┐
     ▼                         ▼
LMSService / MoodleProvider  VaultService / UPES Router
  ├── Direct Authenticated     ├── ReportLab Engine (PDF)
  │   HTTP (Fast, Headless)    ├── Safe Archive Engine (ZipSlip Guard)
  └── BrowserService Bridge    └── Integer-count Attendance Engine
      └── PinchTab Profile
```

---

## 2. The 41-Tool Authoritative MCP Catalog

NexusNode exposes exactly **41 MCP Tools** grouped into 5 functional subsystems:

### A. Appliance Status & Diagnostics (1 Tool)
1. `nexus.status`: Health, battery, uptime, storage, UPES/LMS authentication, and browser worker status.

### B. UPES Student Portal & Academic Analytics (8 Tools)
2. `upes.auth_status`: UPES OAuth session status and token expiration.
3. `upes.get_attendance`: Official real-time attendance ledger from UPES API.
4. `upes.get_timetable`: Today's and rolling 2-week class timetable schedule.
5. `upes.get_next_classes`: Next immediate academic lecture and location.
6. `upes.get_courses`: Enrolled academic courses and module IDs.
7. `upes.calculate_attendance`: **[NEW]** Integer-count attendance projection, safe bunks, and recovery calculator.
8. `upes.get_punches`: **[NEW]** RFID classroom punch clock history query with explicit local provenance.
9. `upes.export_timetable`: **[NEW]** Export schedule to Vault in PDF (ReportLab), CSV, or JSON.

### C. LMS & Moodle Integration (8 Tools)
10. `lms.list_courses`: Enrolled courses on Moodle LMS (`https://lms.upes.ac.in/my/courses.php`).
11. `lms.get_course`: Course syllabus outline, modules, resources, and assignment list.
12. `lms.list_resources`: All downloadable documents, PDFs, slides, and files in a course.
13. `lms.download_resource`: Transfer course file from LMS directly into BG6 Vault.
14. `lms.list_assignments`: Discover open assignments, due dates, and submission statuses.
15. `lms.get_assignment`: Assignment details with untrusted content boundaries.
16. `lms.prepare_submission`: Assemble, verify, and stage submission files into a persistent `SubmissionPlan`.
17. `lms.submit_assignment`: **[NEW Phase 3.6A]** Requests consequential assignment submission gated by user/companion approval.

### D. Consequential Actions & Execution Status (1 Tool)
18. `action.status`: **[NEW Phase 3.6A]** Query status and execution results for a consequential action.

### E. Vault & Document Processing (11 Tools)
19. `vault.list`: List directory contents in student Vault.
20. `vault.search`: Glob/regex file search within Vault.
21. `vault.read`: Read raw text/markdown file content.
22. `vault.mkdir`: Create directories.
23. `vault.create`: Create a new file.
24. `vault.write`: Write/overwrite file contents.
25. `vault.rename`: Rename file or directory.
26. `vault.move`: Move file or directory.
27. `vault.copy`: Copy file or directory.
28. `vault.archive_list`: Inspect archive `.zip` / `.tar.gz` entries safely.
29. `vault.archive_extract`: Safe archive extraction with strict Zip Slip & resource quota protection.
30. `document.extract`: Extract text from PDF, Markdown, or plain text with bounded pagination.
31. `document.create`: Generate Markdown, Text, or publication-quality PDF via ReportLab.

### F. Controlled Browser Execution (Fallback / Interactive) (12 Tools)
32. `browser.status`: PinchTab worker status.
33. `browser.open`: Open dedicated browser tab.
34. `browser.close`: Close browser tab session.
35. `browser.navigate`: Navigate to verified target URL.
36. `browser.snapshot`: Accessibility tree text snapshot.
37. `browser.screenshot`: Visual viewport screenshot into Vault.
38. `browser.capture`: Paired snapshot + screenshot.
39. `browser.click`: Click accessible element.
40. `browser.type`: Type into input element.
41. `browser.press`: Send keyboard event.
42. `browser.upload`: Upload file to active file input.
43. `browser.download`: Download file to Vault.


---

## 3. Transport Determination & Cookie Ownership

1. **Cookie Ownership**:
   - The dedicated persistent Chrome profile (`nexusnode-browser-profile`) owns the authenticated `MoodleSession` cookie.
   - NexusNode extracts `MoodleSession` in memory only. Raw cookie headers are never logged, persisted in plaintext, or exposed in MCP tool responses.
2. **Transport Hierarchy**:
   - **Direct Authenticated HTTP** (`direct_http`): Used for `lms.list_courses`, `lms.get_course`, `lms.list_resources`, `lms.download_resource`, `lms.list_assignments`, and `lms.get_assignment`.
   - **BrowserService Bridge** (`browser`): Used for `lms.prepare_submission` where interactive DOM manipulation and file input attachment are required.

---

## 4. SubmissionPlan Lifecycle & Final Submission Barrier

1. **SubmissionPlan Entity**:
   - Persisted in SQLite table `submission_plans`.
   - Stores immutable SHA-256 hashes of all staged files.
   - Enforces a 3600-second (1-hour) TTL.
   - States: `DRAFT` $\rightarrow$ `READY_FOR_REVIEW` $\rightarrow$ `EXPIRED` $\rightarrow$ `SUBMITTED`.
2. **Strict Submission Barrier**:
   - `lms.prepare_submission` stages files and verifies page structure, but **never** clicks the final confirmation or turn-in buttons.
   - Returns `final_action_required: true` and `state: DRAFT`.
   - Final submission requires explicit human intervention or the `CONSEQUENTIAL` approval workflow.
