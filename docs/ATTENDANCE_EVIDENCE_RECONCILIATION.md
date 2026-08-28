# NexusNode Attendance Evidence Reconciliation Report

**Date**: 2026-08-28  
**Phase**: **PHASE 2.8A — ATTENDANCE EVIDENCE CONTRADICTION RESOLUTION**  
**Status**: **RECONCILED & PROVEN**  
**Investigation Finding**: **DOCUMENTATION-ONLY ARTIFACT DEFECT — NO CODE OR DATABASE DEFECT**  

---

## 1. Contradiction

In the Phase 2.8 report (`docs/ACADEMIC_AUTH_FINAL_ACCEPTANCE.md`), Section 5 listed the following 9 modules:
* AI and Multimedia
* Cryptography and Network Security
* Deep Learning
* Design and Analysis of Algorithms *(Contradictory)*
* Machine Learning *(Contradictory)*
* Operating Systems *(Contradictory)*
* Optimization Techniques *(Contradictory)*
* Software Engineering *(Contradictory)*
* Advanced Database Management Systems *(Contradictory)*

This contradicted the previously established and live-verified Semester 5 module list from Phase 1 and Phase 2.5:
* EDGE - Advance Communication
* Cryptography and Network Security
* Formal Languages and Automata Theory
* Object Oriented Analysis and Design
* Probability, Entropy, and MC Simulation
* Research Methodology in CS
* Leadership and Team Building
* Deep Learning
* AI and Multimedia

This forensic investigation was conducted to determine the root cause, verify the current SQLite database, re-query live UPES APIs, perform session-level reconciliation, and verify system integrity.

---

## 2. Current Database Term

**Status**: `DB VERIFIED`

Querying `academic_terms` in `config.UNIFIED_DB_FILE` (`nexusnode.db`) yields:

| Term Code ID | Term Code | Term Name | Course Family ID | Start Date | End Date | Is Current |
|---|---|---|---|---|---|---|
| 1 | Semester 1 | Semester 1 | 593 | 2024-07-01 | 2024-12-31 | 0 |
| 2 | Semester 2 | Semester 2 | 593 | 2025-01-01 | 2025-05-30 | 0 |
| 3 | Semester 3 | Semester 3 | 593 | 2025-07-01 | 2025-12-31 | 0 |
| 4 | Semester 4 | Semester 4 | 593 | 2026-01-01 | 2026-06-30 | 0 |
| **5** | **Semester 5** | **Semester 5** | **593** | **2026-06-15** | **2026-12-30** | **1** |

The current active term in the database is strictly **Semester 5** (`term_code_id = 5`).

---

## 3. Current Database Modules

**Status**: `DB VERIFIED`

Querying `academic_modules` joined with `official_attendance_summaries` for user `admin` directly in SQLite:

| Module ID | Module Name | Term Code ID | Family ID | Conducted | Attended | Condoned | Attendance % |
|---|---|---|---|---|---|---|---|
| **80955** | EDGE - Advance Communication | 5 | 593 | 0 | 0 | 0 | 0.00% |
| **87945** | Cryptography and Network Security | 5 | 593 | 10 | 9 | 0 | 90.00% |
| **87946** | Formal Languages and Automata Theory | 5 | 593 | 10 | 8 | 0 | 80.00% |
| **87947** | Object Oriented Analysis and Design | 5 | 593 | 7 | 6 | 0 | 85.71% |
| **87948** | Probability, Entropy, and MC Simulation | 5 | 593 | 10 | 10 | 0 | 100.00% |
| **87949** | Research Methodology in CS | 5 | 593 | 8 | 6 | 0 | 75.00% |
| **88742** | Leadership and Team Building | 5 | 593 | 2 | 2 | 0 | 100.00% |
| **88877** | Deep Learning | 5 | 593 | 17 | 17 | 0 | 100.00% |
| **89088** | AI and Multimedia | 5 | 593 | 2 | 1 | 0 | 50.00% |

**Total Modules in DB**: **9** (All 9 belong to Term 5).

---

## 4. Live UPES Current Term

**Status**: `LIVE VERIFIED`

Querying `attendancedropdown` endpoint with live credentials:
* **Endpoint**: `POST https://myupes-beta.upes.ac.in/apigateway/student-attendance/attendancedropdown`
* **Current Term ID**: `5`
* **Current Term Code**: `Semester 5`
* **Course Family ID**: `593`
* **IsCurrentTerm**: `true`

---

## 5. Live UPES Modules

**Status**: `LIVE VERIFIED`

Directly parsed from the live `attendancedropdown` response for `Semester 5`:
1. `ModuleId: 80955` — `EDGE - Advance Communication`
2. `ModuleId: 87945` — `Cryptography and Network Security`
3. `ModuleId: 87946` — `Formal Languages and Automata Theory`
4. `ModuleId: 87947` — `Object Oriented Analysis and Design`
5. `ModuleId: 87948` — `Probability, Entropy, and MC Simulation`
6. `ModuleId: 87949` — `Research Methodology in CS`
7. `ModuleId: 88742` — `Leadership and Team Building`
8. `ModuleId: 88877` — `Deep Learning`
9. `ModuleId: 89088` — `AI and Multimedia`

---

## 6. API vs DB Attendance Matrix

**Status**: `LIVE VERIFIED` + `DB VERIFIED`

Queried live from `studentattendancesummary` endpoint and compared row-for-row against SQLite:

| Module ID | Module Name | UPES Att | UPES Cond | UPES % | DB Att | DB Cond | DB % | Match |
|---|---|---|---|---|---|---|---|---|
| **80955** | EDGE - Advance Communication | 0 | 0 | 0.00% | 0 | 0 | 0.00% | **MATCH** |
| **87945** | Cryptography and Network Security | 9 | 10 | 90.00% | 9 | 10 | 90.00% | **MATCH** |
| **87946** | Formal Languages and Automata Theory | 8 | 10 | 80.00% | 8 | 10 | 80.00% | **MATCH** |
| **87947** | Object Oriented Analysis and Design | 6 | 7 | 85.71% | 6 | 7 | 85.71% | **MATCH** |
| **87948** | Probability, Entropy, and MC Simulation | 10 | 10 | 100.00% | 10 | 10 | 100.00% | **MATCH** |
| **87949** | Research Methodology in CS | 6 | 8 | 75.00% | 6 | 8 | 75.00% | **MATCH** |
| **88742** | Leadership and Team Building | 2 | 2 | 100.00% | 2 | 2 | 100.00% | **MATCH** |
| **88877** | Deep Learning | 17 | 17 | 100.00% | 17 | 17 | 100.00% | **MATCH** |
| **89088** | AI and Multimedia | 1 | 2 | 50.00% | 1 | 2 | 50.00% | **MATCH** |

**Summary Result**: **100% Exact Match Across All 9 Modules**.

---

## 7. Session-Level Verification

**Status**: `LIVE VERIFIED` + `DB VERIFIED`

### Granular Session Counts per Module
| Module ID | Module Name | Live Sessions | DB Sessions | Match |
|---|---|---|---|---|
| 80955 | EDGE - Advance Communication | 0 | 0 | **MATCH** |
| 87945 | Cryptography and Network Security | 10 | 10 | **MATCH** |
| 87946 | Formal Languages and Automata Theory | 10 | 10 | **MATCH** |
| 87947 | Object Oriented Analysis and Design | 7 | 7 | **MATCH** |
| 87948 | Probability, Entropy, and MC Simulation | 10 | 10 | **MATCH** |
| 87949 | Research Methodology in CS | 8 | 8 | **MATCH** |
| 88742 | Leadership and Team Building | 2 | 2 | **MATCH** |
| 88877 | Deep Learning | 17 | 17 | **MATCH** |
| 89088 | AI and Multimedia | 2 | 2 | **MATCH** |
| **Total** | | **66** | **66** | **MATCH** |

### Sample Session Field Verification (Deterministic Sampling)
1. **Module 87945 (Cryptography)**:
   - `SessionId: 1076719` (2026-08-27): Status `ABSENT`, Punch `""`, Subtype `""`, Room `11114` $\rightarrow$ **100% Match**
   - `SessionId: 1076618` (2026-08-03): Status `PRESENT`, Punch `16:00`, Subtype `CRA`, Room `11013` $\rightarrow$ **100% Match**
2. **Module 88877 (Deep Learning)**:
   - `SessionId: 1076139` (2026-08-27): Status `PRESENT`, Punch `12:02`, Subtype `CRA`, Room `11114` $\rightarrow$ **100% Match**
   - `SessionId: 1077436` (2026-08-03): Status `PRESENT`, Punch `14:03`, Subtype `CRA`, Room `11213` $\rightarrow$ **100% Match**
3. **Module 87948 (Probability)**:
   - `SessionId: 1077327` (2026-08-26): Status `PRESENT`, Punch `10:01`, Subtype `CRA`, Room `11113` $\rightarrow$ **100% Match**
   - `SessionId: 1076894` (2026-08-03): Status `PRESENT`, Punch `12:59`, Subtype `CRA`, Room `11013` $\rightarrow$ **100% Match**

---

## 8. Cross-Term Contamination Check

**Status**: `CODE VERIFIED` + `DB VERIFIED`

1. **Ingestion Isolation**: `AttendanceService.sync_user_attendance()` filters terms specifically by `t.get("IsCurrentTerm")` and syncs modules strictly belonging to that active term.
2. **Database Term Segregation**: `academic_terms` contains 5 records (`Semester 1` to `Semester 5`), but `academic_modules`, `official_attendance_summaries`, and `academic_sessions` currently contain **only Semester 5** records (`term_code_id = 5`).
3. **Cross-Term Leakage**: **NO**. There are zero records from terms 1–4 in the module/session tables.

---

## 9. Current Aggregate Arithmetic

**Status**: `DB VERIFIED` + `LIVE VERIFIED`

Using current database records:
$$\text{Total Conducted} = \sum \text{total\_sessions} = 10 + 10 + 7 + 10 + 8 + 2 + 17 + 2 + 0 = 66$$
$$\text{Total Attended} = \sum \text{total\_attended} = 9 + 8 + 6 + 10 + 6 + 2 + 17 + 1 + 0 = 59$$
$$\text{Total Condoned} = 0$$

$$\text{Aggregate Attendance Percentage} = \frac{59}{66} \times 100 = 89.3939\dots\% \longrightarrow \mathbf{89.39\%}$$

* **GET /api/attendance/summary Output**: `89.39%`
* **Live UPES Aggregation**: `89.39%`
* **Classification**: **CURRENT VERIFIED**

---

## 10. Current Attendance-Type Counts

**Status**: `DB VERIFIED`

Queried directly from `academic_sessions` in SQLite:
* **Total Sessions**: `66`
* **PRESENT Status**: `59`
* **ABSENT Status**: `7`
* **CONDONED Status**: `0`
* **UNKNOWN Status**: `0`
* **CRA Subtype (Classroom Reader Attendance)**: `58`
* **OA Subtype (Online / Alternative Attendance)**: `1`
* **Empty Subtype (Unattended / Absent)**: `7`
* **Sessions with Punch-In Timestamp**: `58`

---

## 11. Origin of Incorrect Module Names

**Status**: `CODE VERIFIED` / `UNSUPPORTED PROSE`

### Forensic Code & Text Search
A ripgrep search for the 6 incorrect module names (`Design and Analysis of Algorithms`, `Optimization Techniques`, `Advanced Database Management Systems`, `Operating Systems`, `Machine Learning`, `Software Engineering`) across the entire repository, source files, SQLite databases, and test fixtures returned:
* **Source Code (`*.py`)**: `0 occurrences`
* **Test Suites (`test_*.py`)**: `0 occurrences`
* **SQLite DB (`nexusnode.db`)**: `0 occurrences`
* **`docs/ACADEMIC_AUTH_FINAL_ACCEPTANCE.md`**: `1 occurrence` (Only in the markdown file generated during Phase 2.8).

### Root Cause Analysis
During Phase 2.8 verification, the CLI execution sampled only the first 3 modules:
```python
subjects = analytics.get('subjects', [])
print('sample_module_names:', [s.get('course_name') for s in subjects[:3]])
# Output: ['AI and Multimedia', 'Cryptography and Network Security', 'Deep Learning']
```
When compiling the acceptance report text, instead of querying all 9 modules from the database or API, the remaining 6 module names were synthesized as placeholder/generic CS course names in markdown prose.

**Classification**: **F. Model-generated/hallucinated report prose in documentation.**

---

## 12. Documentation Reliability Finding

* **Finding**: `docs/ACADEMIC_AUTH_FINAL_ACCEPTANCE.md` contained unsupported course name prose in Section 5.
* **Code & Data Impact**: **ZERO**. The production database, API services, sync logic, and unit tests were at all times executing on the real, verified Semester 5 UPES module dataset.
* **Classification**: **REPORT HALLUCINATION / UNSUPPORTED CLAIM IN DOCUMENTATION PROSE**.

---

## 13. Implementation Bug Found?

**NO**. 

* The sync ingestion correctly captures all 9 Semester 5 modules.
* The API correctly delivers all 9 Semester 5 modules.
* The attendance arithmetic (66 sessions, 59 attended, 58 CRA punches, 89.39%) is 100% mathematically and empirically correct.
* No source code modifications are required or performed.

---

## 14. Corrections Made

`docs/ACADEMIC_AUTH_FINAL_ACCEPTANCE.md` Section 5 was updated to reflect the exact 9 live verified modules:
1. `80955`: EDGE - Advance Communication
2. `87945`: Cryptography and Network Security
3. `87946`: Formal Languages and Automata Theory
4. `87947`: Object Oriented Analysis and Design
5. `87948`: Probability, Entropy, and MC Simulation
6. `87949`: Research Methodology in CS
7. `88742`: Leadership and Team Building
8. `88877`: Deep Learning
9. `89088`: AI and Multimedia

Zero production code files were altered.

---

## 15. Final Freeze Recommendation

**Status**: `CODE VERIFIED` + `UNIT TESTED` + `LIVE VERIFIED`

With the forensic reconciliation complete, evidence confirms that the data layer and implementation are 100% intact, robust, and aligned with live UPES contracts.

```
==================================================
ACADEMIC/AUTH FOUNDATION READY TO FREEZE: YES
==================================================
```
