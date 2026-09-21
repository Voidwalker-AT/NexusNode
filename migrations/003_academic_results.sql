-- Migration 003: Academic Results, Grades & Performance Storage
-- Phase 4.3A: Normalized, tenant-isolated, minimal-storage academic performance schema.

CREATE TABLE IF NOT EXISTS academic_results (
    user_id TEXT NOT NULL,
    term_id TEXT NOT NULL,
    semester_name TEXT NOT NULL,
    academic_year TEXT,
    official_sgpa REAL,
    calculated_sgpa REAL,
    official_cgpa REAL,
    calculated_cgpa REAL,
    credits_registered REAL NOT NULL DEFAULT 0.0,
    credits_earned REAL NOT NULL DEFAULT 0.0,
    status TEXT DEFAULT 'Passed',
    payload_fingerprint TEXT,
    provenance TEXT DEFAULT 'live',
    is_stale INTEGER DEFAULT 0,
    discrepancy INTEGER DEFAULT 0,
    discrepancy_details TEXT,
    last_synced_at REAL NOT NULL,
    PRIMARY KEY (user_id, term_id)
);

CREATE INDEX IF NOT EXISTS idx_acad_results_user ON academic_results(user_id);

CREATE TABLE IF NOT EXISTS academic_result_courses (
    user_id TEXT NOT NULL,
    term_id TEXT NOT NULL,
    course_code TEXT NOT NULL,
    course_name TEXT NOT NULL,
    credits REAL NOT NULL DEFAULT 0.0,
    letter_grade TEXT NOT NULL,
    grade_point REAL NOT NULL DEFAULT 0.0,
    status TEXT DEFAULT 'Passed',
    attempt INTEGER DEFAULT 1,
    is_backlog INTEGER DEFAULT 0,
    PRIMARY KEY (user_id, term_id, course_code),
    FOREIGN KEY (user_id, term_id) REFERENCES academic_results(user_id, term_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_acad_courses_user_term ON academic_result_courses(user_id, term_id);

CREATE TABLE IF NOT EXISTS academic_result_sync_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    timestamp REAL NOT NULL,
    source TEXT NOT NULL,
    status TEXT NOT NULL,
    terms_synced INTEGER DEFAULT 0,
    courses_synced INTEGER DEFAULT 0,
    duration_ms REAL DEFAULT 0.0,
    details TEXT
);

CREATE INDEX IF NOT EXISTS idx_acad_sync_history_user ON academic_result_sync_history(user_id, timestamp DESC);
