# Academic Results, SGPA/CGPA & Performance Architecture

## Overview
NexusNode Phase 4.3A introduces the authoritative, tenant-isolated Academic Results subsystem for UPES Dehradun students. The engine normalizes semester grade cards, evaluates official 10-point scale grades, tracks cumulative credit history, performs automated discrepancy detection between disparate upstream portals, caches Last Known Good (LKG) transcripts, and provides deterministic What-If GPA modeling.

---

## 1. Dual Normalization Pipeline

The subsystem handles disparate upstream data representations across two UPES portals:

```
                      +-----------------------------+
                      |   UPES Academic Portals     |
                      +-----------------------------+
                                     |
               +---------------------+---------------------+
               |                                           |
               v                                           v
    +-----------------------+                   +-----------------------+
    |  ConnectPortal REST   |                   |  Exam-Pro Transcript  |
    |  (Program Progress &  |                   |  (HTML / JSON API     |
    |   Course Summary)     |                   |   Termwise Ledger)    |
    +-----------------------+                   +-----------------------+
               |                                           |
               v                                           v
    +-----------------------+                   +-----------------------+
    | normalize_            |                   | normalize_exam_       |
    | connectportal_results |                   | pro_transcript        |
    +-----------------------+                   +-----------------------+
               |                                           |
               +---------------------+---------------------+
                                     |
                                     v
                        +-------------------------+
                        |  AcademicRecord Model   |
                        |  - terms: List[Term]    |
                        |  - cgpa: Decimal        |
                        |  - total_credits: Dec   |
                        +-------------------------+
                                     |
                                     v
                        +-------------------------+
                        |  Discrepancy Detector   |
                        |  - Grade differences    |
                        |  - SGPA/CGPA mismatch   |
                        +-------------------------+
```

### 1.1 ConnectPortal Normalizer (`normalize_connectportal_results`)
- Ingests payloads from `studentProgramProgressV2` and `getCourseSummaryByTerm`.
- Resolves term identifiers (`term_id` e.g., `"SEM1"`, `"SEM2"`), credits registered, credits earned, and raw letter grades.
- Computes term GPA and cumulative CGPA using exact `Decimal` arithmetic.

### 1.2 Exam-Pro Normalizer (`normalize_exam_pro_transcript`)
- Ingests official tabular transcripts containing course codes, course titles, credits, letter grades, and grade points.
- Extracts published SGPA and CGPA figures recorded on university grade sheets.

### 1.3 Discrepancy Detection
- Compares computed SGPA/CGPA against published transcript figures.
- If $|SGPA_{published} - SGPA_{computed}| > 0.05$, a warning discrepancy flag is raised without failing the synchronization, recording forensic telemetry for auditing.

---

## 2. UPES Authoritative 10-Point Grading Scale

The calculation engine strictly implements the official UPES Academic Regulation 10-point scale:

| Letter Grade | Grade Point | Classification / Definition |
| :--- | :--- | :--- |
| **O** | `10.0` | Outstanding |
| **A+** | `9.0` | Excellent |
| **A** | `8.0` | Very Good |
| **B+** | `7.0` | Good |
| **B** | `6.0` | Above Average |
| **C** | `5.0` | Average |
| **P** | `4.0` | Pass (Minimum passing grade) |
| **F** | `0.0` | Fail |
| **Ab** | `0.0` | Absent |
| **I** | `0.0` | Incomplete (Pending resolution) |

### Non-Credit & Audit Grades
Non-credit courses and audit modules do not contribute to earned credits or GPA denominator:
- `S` (Satisfactory)
- `U` (Unsatisfactory)
- `W` (Withdrawn)

### Arithmetic Invariants
1. All GPA calculations are performed with Python `decimal.Decimal` with `ROUND_HALF_UP` precision to avoid IEEE 754 floating-point drift.
2. $\text{SGPA} = \frac{\sum (\text{Credits}_i \times \text{GradePoints}_i)}{\sum \text{Credits}_i}$ across credit-bearing courses in the term.
3. $\text{CGPA} = \frac{\sum (\text{SGPA}_t \times \text{Credits}_t)}{\sum \text{Credits}_t}$ across all completed terms.

---

## 3. Storage Schema & Multi-Tenant Data Model

The subsystem persists normalized academic data in SQLite via `migrations/003_academic_results.sql`:

### `academic_results`
Primary ledger for semester-level results:
- `user_id` (TEXT, NOT NULL)
- `term_id` (TEXT, NOT NULL)
- `term_name` (TEXT)
- `sgpa` (REAL)
- `cgpa` (REAL)
- `total_credits` (REAL)
- `earned_credits` (REAL)
- `raw_payload_hash` (TEXT, SHA-256 fingerprint)
- `source_portal` (TEXT)
- `is_lkg` (INTEGER DEFAULT 0)
- `synced_at` (REAL)
- PRIMARY KEY: `(user_id, term_id)`

### `academic_result_courses`
Course-level grade records:
- `course_id` (TEXT PRIMARY KEY)
- `user_id` (TEXT, NOT NULL)
- `term_id` (TEXT, NOT NULL)
- `course_code` (TEXT NOT NULL)
- `course_name` (TEXT NOT NULL)
- `credits` (REAL NOT NULL)
- `grade` (TEXT NOT NULL)
- `grade_point` (REAL NOT NULL)
- `is_backlog` (INTEGER DEFAULT 0)
- `synced_at` (REAL)

### `academic_result_sync_history`
Audit ledger of sync attempts, records updated, and errors.

---

## 4. What-If GPA Projection Engine

The `WhatIfEngine` (`upes/results.py`) enables students to model prospective academic scenarios:
1. **Target CGPA Projection**: Calculates the required average SGPA across remaining semesters to achieve a target CGPA:
   $$SGPA_{required} = \frac{CGPA_{target} \times (Credits_{current} + Credits_{remaining}) - (CGPA_{current} \times Credits_{current})}{Credits_{remaining}}$$
2. **Course Grade Simulation**: Evaluates the effect of specific predicted grades in upcoming courses on the semester SGPA and overall CGPA.

---

## 5. Security & Isolation

- **Tenant Scoping**: All database queries strictly require `WHERE user_id = ?`.
- **Privacy Preservation**: Raw authentication headers are never logged; payloads are stored only as normalized structured entities with SHA-256 hashes.
- **Circuit Breaker Integration**: Results synchronization failures increment the auth circuit breaker without halting timetable or calendar synchronization.
