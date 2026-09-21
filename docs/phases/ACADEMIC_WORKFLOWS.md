# Academic Workflows & Analytics Specification (Phase 3.5)

## 1. Attendance Calculation & Projection Mathematics

The `upes.calculate_attendance` tool performs deterministic integer-count arithmetic based on official UPES attendance data and hypothetical student scenarios.

### Formulas & Derivations

Let:
- $A$ = Current Attended Classes (`current_attended`)
- $T$ = Current Total Conducted Classes (`current_total`)
- $F_A$ = Future Attended Classes (`future_attended`)
- $F_M$ = Future Missed Classes (`future_missed`)
- $P$ = Target Attendance Percentage as a fraction (e.g. $0.75$ for $75\%$)

#### Projected Attendance
$$A' = A + F_A$$
$$T' = T + F_A + F_M$$
$$\text{Projected Percentage} = \text{round}\left(\frac{A'}{T'} \times 100, 2\right)$$

#### Safe Bunks (Maximum Missed Classes while staying $\ge P$)
Solving $\frac{A'}{T' + B} \ge P \implies A' \ge P(T' + B) \implies B \le \frac{A' - P \cdot T'}{P}$:
$$\text{Safe Bunks} = \begin{cases} \left\lfloor \frac{A' - P \cdot T'}{P} \right\rfloor & \text{if } A' \ge P \cdot T' \\ 0 & \text{otherwise} \end{cases}$$

#### Recovery Classes (Minimum Attended Classes needed to reach $\ge P$)
Solving $\frac{A' + R}{T' + R} \ge P \implies A' + R \ge P \cdot T' + P \cdot R \implies R(1 - P) \ge P \cdot T' - A'$:
$$\text{Recovery Needed} = \begin{cases} \left\lceil \frac{P \cdot T' - A'}{1 - P} \right\rceil & \text{if } A' < P \cdot T' \\ 0 & \text{otherwise} \end{cases}$$

---

## 2. RFID Punch Clock Audit & Provenance

The `upes.get_punches` tool queries the local `academic_sessions` ledger populated from UPES classroom RFID card readers.

- **Provenance**: Marked as `source: local`, `provider: local_db`.
- **Fields**: `session_id`, `course_name`, `course_code`, `session_date`, `start_time`, `end_time`, `faculty`, `room`, `attendance_status` (`Present` / `Absent`), `attendance_subtype` (`CRA` = Classroom RFID Reader), `punch_in_time`.

---

## 3. Timetable Schedule Exporter

The `upes.export_timetable` tool exports normalized academic schedules from `user_timetables` into the user's Vault.

- **Formats**:
  - `pdf`: Formatted timetable document generated using `reportlab.platypus` with structured column layouts, wrapped headers, and alternating row styling. Validated with `pypdf`.
  - `csv`: Standard comma-separated spreadsheet format.
  - `json`: Normalized JSON array format.
- **Output Destination**: User-specified path within Vault (e.g. `Timetable/schedule_sem5.pdf`).

---

## 4. Archive Safety & Document Processing

### A. Archive Extraction Security
`vault.archive_extract` implements multi-layer defense against malicious archives:
- **Zip Slip Defense**: Canonical path validation ensures no target entry escapes the destination root directory.
- **Symlink Rejection**: Rejects symlinks and hardlinks in archives.
- **Resource Quotas**: Limits extraction to a maximum of 500 files and 100 MB decompressed size.

### B. Document Extraction & Creation
- `document.extract`:
  - Supports `.pdf`, `.md`, `.txt`.
  - PDF parsing powered by `pypdf` with bounded pagination (`start_page`, `end_page`, `max_chars`).
- `document.create`:
  - Supports `.md`, `.txt`, `.pdf`.
  - PDF generation powered by `reportlab.platypus.SimpleDocTemplate` with clean typography and heading styling.
