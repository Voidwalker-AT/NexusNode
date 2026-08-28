# Production Attendance UI Failure Root Cause Investigation & Fix

---

## 1. Symptom

On the deployed TECNO BG6 production web UI, opening the Attendance tab triggered the error toast:
`Failed to load attendance data.`

The Attendance page remained permanently stuck in an unpopulated/loading state:
- Aggregate Attendance: `--%`
- Attended Classes: `0 / 0 classes attended`
- Subject-Allocated Safe Skips: `--`
- Total Conducted Sessions: `0`
- Today's Live Punch: `0 / 0`
- Today's Classes container: stuck displaying `Loading today's classes...`
- Module Attendance table: stuck displaying `Loading subject data...`

---

## 2. Production Reproduction

1. Authenticated to the live server on `http://192.168.29.211:5000` as user `papa` (and `admin`).
2. Navigated to the Attendance tab (`loadAttendanceData()`).
3. Reproduced the frontend JavaScript execution in a simulated browser DOM environment using Node.js VM:
   - Evaluated `static/js/app.js`.
   - Called `loadAttendanceData()`.
   - Result: `ReferenceError: apiRequest is not defined` occurred at `app.js:3174`, caught by the error handler, emitting `showToast('Failed to load attendance data.', 'error')`.
   - Verified that when `today_classes` contained items, `renderTodayClasses()` threw `ReferenceError: bool is not defined` at `app.js:3289`.

---

## 3. Exact Failed Request

- **Frontend Function**: `loadAttendanceData()` in `static/js/app.js` (line 3169)
- **Target Endpoint**: `GET /api/attendance/summary`
- **Failure Mechanism**: The HTTP request was never dispatched or failed inside JavaScript because `apiRequest` was an undeclared function in the frontend bundle. The resulting `ReferenceError` interrupted execution before DOM elements could be populated.

---

## 4. Root Cause

1. **Undeclared API Helper**: In `static/js/app.js`, attendance functions (`loadAttendanceData`, `triggerAttendanceSync`, `handlePunchClass`, `handleBulkPunchToday`, `handleDeletePunch`, `handleCustomPunch`) relied on `apiRequest(url, method, body)` which was not defined in the codebase (the rest of `app.js` uses `apiFetch(url, options)`).
2. **Pythonism in JavaScript**: In `renderTodayClasses()` (line 3289), `const isPunched = bool(c.is_punched || c.punch_in_time);` invoked the Python keyword `bool()` instead of JavaScript's `Boolean()`.
3. **Asset Cache Invalidation**: `index.html` loaded `./static/js/app.js` and `./static/css/index.css` without query parameter version hashing (`?v={{ version }}`), risking stale client caching across server updates.

---

## 5. Why Previous Tests Missed It

The Python test suite (376 unit tests) tested the backend API routes directly using Flask's `test_client`, verifying that `GET /api/attendance/summary` and related endpoints returned HTTP 200 with valid JSON. However, there were no frontend DOM / JavaScript execution tests validating that `static/js/app.js` could parse and render those responses without client-side runtime errors.

---

## 6. Fix

1. **Declared `apiRequest`**: Added `apiRequest(url, method = 'GET', body = null)` directly after `apiFetch` in `static/js/app.js`:
   - Handles HTTP method and JSON body serialization.
   - Forwards authorization tokens, headers, and LocalToNet skip-warning flags via `apiFetch`.
   - Verifies `res.ok` and parses the JSON response payload.
2. **Fixed `bool()`**: Replaced `bool(...)` with `Boolean(...)` in `renderTodayClasses()`.
3. **Added Cache-Busting**: Added `?v={{ version }}` to `<link rel="stylesheet" href="./static/css/index.css?v={{ version }}">` and `<script src="./static/js/app.js?v={{ version }}"></script>` in `index.html`.

---

## 7. Regression Test

Created `tests/test_attendance_frontend_contract.py`:
- `test_api_request_helper_defined`: Asserts `apiRequest` is declared in `static/js/app.js`.
- `test_no_pythonisms_in_javascript`: Asserts no `bool(...)` calls exist in JavaScript.
- `test_asset_version_cache_busting`: Asserts `index.html` includes `?v={{ version }}`.
- `test_node_dom_rendering_contract`: Uses Node.js to execute `loadAttendanceData()` against mock DOM and verify successful rendering without errors.

---

## 8. Production Deployment

- Committed changes to branch `feature/diagnostics-model-runtime`.
- Fast-forwarded the production TECNO checkout via SSH (`git merge --ff-only`).
- Zero database changes; zero credential alterations.
- Deployed files: `static/js/app.js`, `index.html`, `tests/test_attendance_frontend_contract.py`, `docs/PRODUCTION_ATTENDANCE_UI_FIX.md`.

---

## 9. API Acceptance

Verified live authenticated responses on TECNO BG6:
- `GET /api/attendance/status` $\rightarrow$ `200 OK` (dict, 9 keys, 733 bytes)
- `GET /api/attendance/summary` $\rightarrow$ `200 OK` (dict, 8 keys, 327 bytes)
- `GET /api/attendance/modules` $\rightarrow$ `200 OK` (dict, 2 keys, 32 bytes)
- `GET /api/attendance/sessions` $\rightarrow$ `200 OK` (dict, 3 keys, 43 bytes)
- `GET /api/attendance/today` $\rightarrow$ `200 OK` (dict, 3 keys, 64 bytes)
- `GET /api/attendance/punches` $\rightarrow$ `200 OK` (dict, 3 keys, 42 bytes)

---

## 10. UI Acceptance

Simulated and verified full frontend rendering:
- **Empty State (Case A)**:
  - Aggregate Percentage: `100%` (or `--%` when uncalculated)
  - Conducted Classes: `0 / 0 classes attended (0 missed)`
  - Today's Classes: `No sessions scheduled for today (...). Enjoy your day! 🎉`
  - Subjects Table: `No subjects found in official UPES attendance. Click "Sync with UPES" to refresh.`
  - Punches Table: `No official session records logged yet. Click "Sync with UPES" to load ledger.`
- **Populated State**:
  - Successfully parses subjects, safe bunk counters, today schedule cards, and session history ledger without throwing toasts or exceptions.

---

## 11. Data Preservation

- Production SQLite database: Untouched.
- User accounts & credentials: Preserved 100%.
- Vault & RAG state: Preserved 100%.

---

## 12. Remaining Limitations

- Official attendance synchronization on production requires an active UPES session for the target user. When not configured or expired, the UI displays the friendly empty state and provides the "Sync with UPES" trigger.
