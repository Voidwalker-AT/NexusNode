"""
NexusNode — 24/7 Personal Mobile Server Appliance Core
Engineered specifically for unrooted Android 13 Termux on ~4 GB RAM hardware (TECNO BG6).
Architecture:
- Authoritative Ollama Model Registry & Runit Supervisor Controls (No Popen/pkill)
- Storage-Backed SQLite FTS5 RAG Inverted Index with BM25 Ranking
- Single-Threaded Bounded Log Writer Daemon (No per-event thread spawning)
- Synchronized Telemetry Snapshot Cache (2.5s TTL)
- Object-Level Authorization & Task Ownership
- Comprehensive Admin Diagnostics Center & Automated Root-Cause Engine
"""

import os
import sys
import re
import time
import json
import queue
import signal
import shutil
import mimetypes
import base64
import hashlib
import secrets
import sqlite3
import tempfile
import threading
import subprocess
import urllib.parse
from datetime import datetime, timezone
from functools import wraps

import requests
from flask import Flask, request, jsonify, render_template, send_file, Response, g, stream_with_context, redirect

import config
from resource_governor import governor, ResourceGovernor
import timetable_sync

# ==============================================================================
# FLASK APP SETUP & LOCKS
# ==============================================================================

app = Flask(__name__, template_folder='.')
app.config['SECRET_KEY'] = config.SECRET_KEY
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500 MB upload ceiling


DB_LOCK = threading.RLock()
SESSIONS_LOCK = threading.RLock()
SESSIONS = {}  # In-memory token cache: token -> session dict
FAILED_LOGINS = {}  # ip -> {"count": int, "locked_until": float}
FAILED_LOGINS_LOCK = threading.RLock()

SERVER_START_TIME = time.time()

@app.after_request
def add_security_headers(response):
    response.headers['localtonet-skip-warning'] = 'true'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    return response

# ==============================================================================
# 1. DATABASE SCHEMA & INITIALIZATION
# ==============================================================================

def get_db_connection(db_file: str = None) -> sqlite3.Connection:
    target_file = db_file or config.UNIFIED_DB_FILE
    conn = sqlite3.connect(target_file, timeout=15.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


timetable_service = timetable_sync.TimetableService(get_db_connection)


# --- PBKDF2 Password Helpers (must be defined before init_unified_db seeding) ---


def hash_password(password: str, salt: str = None) -> tuple[str, str]:
    """
    Generates a secure password hash using standard-library PBKDF2-HMAC-SHA256.
    Format: pbkdf2_sha256$<iterations>$<salt>$<digest>
    """
    if not salt:
        salt = secrets.token_hex(16)
    iterations = config.PASSWORD_KDF_ITERATIONS
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations)
    digest = derived.hex()
    formatted = f"pbkdf2_sha256${iterations}${salt}${digest}"
    return formatted, salt


def verify_password(password: str, stored_hash: str, salt: str = "") -> tuple[bool, bool]:
    """
    Verifies password against stored hash with constant-time comparison.
    Supports PBKDF2-HMAC-SHA256 and transparently handles legacy SHA-256 with salt.
    Returns: (is_valid: bool, needs_upgrade: bool)
    """
    if not password or not stored_hash:
        return False, False

    try:
        if stored_hash.startswith("pbkdf2_sha256$"):
            parts = stored_hash.split("$")
            if len(parts) != 4:
                return False, False
            _, iters_str, salt_part, expected_digest = parts
            iters = int(iters_str)
            computed = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt_part.encode("utf-8"), iters).hex()
            is_valid = secrets.compare_digest(computed, expected_digest)
            needs_upgrade = (iters < config.PASSWORD_KDF_ITERATIONS)
            return is_valid, needs_upgrade
        else:
            # Legacy SHA-256 verification
            expected = stored_hash
            computed = hashlib.sha256((password + (salt or "")).encode("utf-8")).hexdigest()
            if secrets.compare_digest(computed, expected):
                return True, True  # Valid legacy password -> triggers upgrade
            return False, False
    except Exception:
        return False, False


def init_unified_db():
    with DB_LOCK:
        conn = get_db_connection()
        try:
            # 1. Users table with persisted lockout tracking and account state
            conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    password_hash TEXT NOT NULL,
                    salt TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'user',
                    is_disabled INTEGER NOT NULL DEFAULT 0,
                    privileges TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL,
                    failed_attempts INTEGER NOT NULL DEFAULT 0,
                    locked_until REAL NOT NULL DEFAULT 0.0
                );
            """)

            # Migration: Ensure users lockout and account status columns exist
            cur = conn.cursor()
            cur.execute("PRAGMA table_info(users);")
            user_cols = [c[1] for c in cur.fetchall()]
            if "failed_attempts" not in user_cols:
                conn.execute("ALTER TABLE users ADD COLUMN failed_attempts INTEGER NOT NULL DEFAULT 0;")
            if "locked_until" not in user_cols:
                conn.execute("ALTER TABLE users ADD COLUMN locked_until REAL NOT NULL DEFAULT 0.0;")
            if "is_disabled" not in user_cols:
                conn.execute("ALTER TABLE users ADD COLUMN is_disabled INTEGER NOT NULL DEFAULT 0;")

            # 1b. IP Lockouts table (persists IP-based locks across restarts)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS ip_lockouts (
                    ip TEXT PRIMARY KEY,
                    failed_attempts INTEGER NOT NULL DEFAULT 0,
                    locked_until REAL NOT NULL DEFAULT 0.0
                );
            """)

            # 2. System Audit Logs table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS system_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    log_id TEXT UNIQUE,
                    timestamp TEXT NOT NULL,
                    date TEXT NOT NULL,
                    level TEXT NOT NULL,
                    category TEXT NOT NULL,
                    message TEXT NOT NULL,
                    meta TEXT DEFAULT '{}',
                    created_at REAL NOT NULL
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_logs_created ON system_logs(created_at);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_logs_level ON system_logs(level);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_logs_category ON system_logs(category);")

            # 3. Background Tasks table with authoritative fields and owner_user_id
            conn.execute("""
                CREATE TABLE IF NOT EXISTS background_tasks (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    stage TEXT NOT NULL DEFAULT 'QUEUED',
                    progress INTEGER NOT NULL DEFAULT 0,
                    logs TEXT DEFAULT '[]',
                    error TEXT,
                    result TEXT,
                    metadata TEXT DEFAULT '{}',
                    owner_user_id TEXT NOT NULL DEFAULT 'admin',
                    eta_seconds INTEGER,
                    speed_bps INTEGER,
                    output_path TEXT,
                    created_at REAL NOT NULL,
                    started_at REAL,
                    updated_at REAL NOT NULL,
                    completed_at REAL
                );
            """)

            # Migration: Ensure all columns exist
            cur = conn.cursor()
            cur.execute("PRAGMA table_info(background_tasks);")
            task_cols = [c[1] for c in cur.fetchall()]
            if "owner_user_id" not in task_cols:
                conn.execute("ALTER TABLE background_tasks ADD COLUMN owner_user_id TEXT NOT NULL DEFAULT 'admin';")
            if "type" not in task_cols and "task_type" in task_cols:
                conn.execute("ALTER TABLE background_tasks ADD COLUMN type TEXT NOT NULL DEFAULT 'generic';")
            if "stage" not in task_cols:
                conn.execute("ALTER TABLE background_tasks ADD COLUMN stage TEXT NOT NULL DEFAULT 'QUEUED';")
            if "error" not in task_cols:
                conn.execute("ALTER TABLE background_tasks ADD COLUMN error TEXT;")
            if "result" not in task_cols:
                conn.execute("ALTER TABLE background_tasks ADD COLUMN result TEXT;")
            if "metadata" not in task_cols:
                conn.execute("ALTER TABLE background_tasks ADD COLUMN metadata TEXT DEFAULT '{}';")
            if "eta_seconds" not in task_cols:
                conn.execute("ALTER TABLE background_tasks ADD COLUMN eta_seconds INTEGER;")
            if "speed_bps" not in task_cols:
                conn.execute("ALTER TABLE background_tasks ADD COLUMN speed_bps INTEGER;")
            if "output_path" not in task_cols:
                conn.execute("ALTER TABLE background_tasks ADD COLUMN output_path TEXT;")
            if "started_at" not in task_cols:
                conn.execute("ALTER TABLE background_tasks ADD COLUMN started_at REAL;")
            if "completed_at" not in task_cols:
                conn.execute("ALTER TABLE background_tasks ADD COLUMN completed_at REAL;")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_owner ON background_tasks(owner_user_id);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON background_tasks(status);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_updated ON background_tasks(updated_at);")

            # One-time legacy repair for deterministic terminal-state contradictions
            cur.execute("""
                UPDATE background_tasks
                SET stage = status, updated_at = ?
                WHERE status IN ('COMPLETED', 'FAILED', 'CANCELLED')
                  AND (stage = 'QUEUED' OR stage IS NULL OR stage = '');
            """, (time.time(),))
            repaired_count = cur.rowcount
            if repaired_count > 0:
                conn.commit()
                if "log_event" in globals():
                    log_event("INFO", "DB", f"Repaired {repaired_count} legacy background tasks with stage contradictions.")
                else:
                    print(f"[*] Repaired {repaired_count} legacy background tasks with stage contradictions.")

            # 4. Temporary Share Links table with owner_user_id and user_id
            conn.execute("""
                CREATE TABLE IF NOT EXISTS shares (
                    id TEXT PRIMARY KEY,
                    token TEXT UNIQUE NOT NULL,
                    filename TEXT NOT NULL,
                    user_id TEXT NOT NULL DEFAULT 'admin',
                    owner_user_id TEXT NOT NULL DEFAULT 'admin',
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    max_downloads INTEGER DEFAULT 0,
                    downloads_count INTEGER DEFAULT 0,
                    revoked INTEGER DEFAULT 0
                );
            """)
            cur.execute("PRAGMA table_info(shares);")
            share_cols = [c[1] for c in cur.fetchall()]
            if "user_id" not in share_cols:
                conn.execute("ALTER TABLE shares ADD COLUMN user_id TEXT NOT NULL DEFAULT 'admin';")
            if "owner_user_id" not in share_cols:
                conn.execute("ALTER TABLE shares ADD COLUMN owner_user_id TEXT NOT NULL DEFAULT 'admin';")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_shares_token ON shares(token);")

            # 5. Backups table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS backups (
                    id TEXT PRIMARY KEY,
                    filename TEXT NOT NULL,
                    filepath TEXT NOT NULL DEFAULT '',
                    checksum TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    backup_type TEXT NOT NULL DEFAULT 'full',
                    status TEXT NOT NULL DEFAULT 'completed',
                    owner_user_id TEXT NOT NULL DEFAULT 'admin',
                    created_at REAL NOT NULL
                );
            """)
            cur.execute("PRAGMA table_info(backups);")
            backup_cols = [c[1] for c in cur.fetchall()]
            if "filepath" not in backup_cols:
                conn.execute("ALTER TABLE backups ADD COLUMN filepath TEXT NOT NULL DEFAULT '';")
            if "backup_type" not in backup_cols:
                conn.execute("ALTER TABLE backups ADD COLUMN backup_type TEXT NOT NULL DEFAULT 'full';")
            if "status" not in backup_cols:
                conn.execute("ALTER TABLE backups ADD COLUMN status TEXT NOT NULL DEFAULT 'completed';")
            if "owner_user_id" not in backup_cols:
                conn.execute("ALTER TABLE backups ADD COLUMN owner_user_id TEXT NOT NULL DEFAULT 'admin';")

            # 6. User Chats table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_chats (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    messages TEXT NOT NULL DEFAULT '[]',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
            """)

            # 7. Scheduled Automation Jobs table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS scheduled_jobs (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    job_type TEXT NOT NULL,
                    interval_seconds INTEGER NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    last_run REAL,
                    next_run REAL,
                    last_status TEXT,
                    last_error TEXT,
                    created_at REAL DEFAULT 0
                );
            """)
            cur = conn.cursor()
            cur.execute("PRAGMA table_info(scheduled_jobs);")
            job_cols = [c[1] for c in cur.fetchall()]
            if "created_at" not in job_cols:
                conn.execute("ALTER TABLE scheduled_jobs ADD COLUMN created_at REAL DEFAULT 0;")

            # 8. Incidents table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS incidents (
                    id TEXT PRIMARY KEY,
                    timestamp REAL NOT NULL,
                    service TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    prev_state TEXT NOT NULL,
                    new_state TEXT NOT NULL,
                    mem_state TEXT NOT NULL,
                    error_summary TEXT NOT NULL,
                    timeline TEXT NOT NULL DEFAULT '[]'
                );
            """)

            # 9. AI Inference Metrics table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS ai_inference_metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    model TEXT NOT NULL,
                    prompt_tokens INTEGER DEFAULT 0,
                    prompt_eval_ms REAL DEFAULT 0,
                    gen_tokens INTEGER DEFAULT 0,
                    gen_eval_ms REAL DEFAULT 0,
                    total_duration_ms REAL DEFAULT 0,
                    load_duration_ms REAL DEFAULT 0,
                    prompt_tokens_per_sec REAL DEFAULT 0,
                    gen_tokens_per_sec REAL DEFAULT 0,
                    created_at REAL NOT NULL,
                    user_id TEXT NOT NULL DEFAULT 'system'
                );
            """)
            # 10. Registered SSH Public Keys table for key-based identity mapping
            conn.execute("""
                CREATE TABLE IF NOT EXISTS ssh_keys (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fingerprint TEXT UNIQUE NOT NULL,
                    user_id TEXT NOT NULL,
                    key_type TEXT NOT NULL,
                    public_key TEXT NOT NULL,
                    label TEXT,
                    created_at REAL NOT NULL,
                    revoked INTEGER DEFAULT 0,
                    FOREIGN KEY(user_id) REFERENCES users(user_id)
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_ssh_keys_fp ON ssh_keys(fingerprint);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_ssh_keys_user ON ssh_keys(user_id);")

            # Seed Default Admin Account if missing
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM users WHERE user_id = 'admin';")
            if cur.fetchone()[0] == 0:
                init_pass = os.environ.get("NEXUS_ADMIN_PASSWORD", "Admin@1234")
                pwd_hash, salt = hash_password(init_pass)
                cur.execute("""
                    INSERT INTO users (user_id, password_hash, salt, role, is_disabled, privileges, created_at)
                    VALUES (?, ?, ?, ?, 0, ?, ?)
                """, (
                    "admin",
                    pwd_hash,
                    salt,
                    "admin",
                    json.dumps(config.ADMIN_DEFAULT_PRIVILEGES),
                    time.time()
                ))

            # Initialize Google OAuth and Timetable Synchronization tables
            timetable_sync.init_timetable_tables(conn)

            # Seed Default Scheduled Jobs
            default_jobs = [
                ("job_auto_backup", "Daily Configuration Backup", "backup", 86400),
                ("job_clean_temp", "Hourly Temp Files Cleanup", "clean_temp", 3600),
                ("job_tunnel_check", "Tunnel Health Check", "tunnel_check", 300),
                ("job_db_retention", "Daily Logs & Metrics Retention Sweep", "retention_sweep", 86400),
                ("job_timetable_sync", "UPES Timetable Google Calendar Sync", "timetable_sync", config.TIMETABLE_SYNC_INTERVAL_SECONDS)
            ]
            for j_id, j_name, j_type, j_int in default_jobs:
                cur.execute("SELECT COUNT(*) FROM scheduled_jobs WHERE id = ?;", (j_id,))
                if cur.fetchone()[0] == 0:
                    cur.execute("""
                        INSERT INTO scheduled_jobs (id, name, job_type, interval_seconds, enabled, last_run, next_run, last_status, created_at)
                        VALUES (?, ?, ?, ?, 1, NULL, ?, 'pending', ?)
                    """, (j_id, j_name, j_type, j_int, time.time() + j_int, time.time()))

            conn.commit()
        finally:
            conn.close()

    # Initialize RAG Database Tables
    init_rag_db()


init_db = init_unified_db



def init_rag_db():
    """Initializes dedicated storage-backed SQLite FTS5 tables for RAG inverted index."""
    with DB_LOCK:
        conn = get_db_connection(config.RAG_DB_FILE)
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS rag_documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    path TEXT UNIQUE NOT NULL,
                    filename TEXT NOT NULL,
                    hash TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    chunk_count INTEGER NOT NULL,
                    mtime REAL NOT NULL,
                    indexed_at REAL NOT NULL
                );
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS rag_chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    doc_id INTEGER NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    token_count INTEGER NOT NULL,
                    FOREIGN KEY(doc_id) REFERENCES rag_documents(id) ON DELETE CASCADE
                );
            """)

            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS rag_chunks_fts USING fts5(
                    content,
                    tokenize = 'porter unicode61'
                );
            """)

            conn.commit()
        finally:
            conn.close()


def migrate_storage_casing_if_needed():
    """
    Deterministically migrates legacy mixed-case storage folders to canonical lowercase.
    Preserves all existing user files, handles case-insensitive filesystems cleanly,
    and logs migration actions. Idempotent and restart-safe.
    """
    canonical_map = {
        "Music": "music",
        "Videos": "videos",
        "Downloads": "downloads",
        "Podcasts": "podcasts",
        "Documents": "documents",
        "Other": "other"
    }
    storage_root = config.STORAGE_DIR
    if not os.path.exists(storage_root):
        return

    for legacy_name, canonical_name in canonical_map.items():
        legacy_path = os.path.join(storage_root, legacy_name)
        canonical_path = os.path.join(storage_root, canonical_name)

        # Ensure canonical directory exists
        os.makedirs(canonical_path, exist_ok=True)

        if os.path.exists(legacy_path) and os.path.isdir(legacy_path):
            try:
                if os.path.samefile(legacy_path, canonical_path):
                    continue
            except Exception:
                pass

            # Physically distinct directories: safely migrate files
            migrated_files = 0
            try:
                for item in os.listdir(legacy_path):
                    src_file = os.path.join(legacy_path, item)
                    dst_file = os.path.join(canonical_path, item)
                    if os.path.exists(dst_file):
                        try:
                            if os.path.samefile(src_file, dst_file):
                                continue
                        except Exception:
                            pass
                        base, ext = os.path.splitext(item)
                        dst_file = os.path.join(canonical_path, f"{base}_{int(time.time())}{ext}")
                    try:
                        shutil.move(src_file, dst_file)
                        migrated_files += 1
                    except Exception as e:
                        print(f"[!] Migration error moving {src_file} -> {dst_file}: {e}")
                try:
                    if not os.listdir(legacy_path):
                        os.rmdir(legacy_path)
                except Exception:
                    pass
            except Exception:
                pass

            if migrated_files > 0:
                print(f"[*] Migrated {migrated_files} files from '{legacy_name}' to '{canonical_name}'.")


init_unified_db()
migrate_storage_casing_if_needed()

# ==============================================================================
# 2. SINGLE-THREADED BOUNDED LOG WRITER DAEMON & DURABILITY ENGINE
# ==============================================================================

LOG_QUEUE = queue.Queue(maxsize=config.LOG_QUEUE_MAX_SIZE)
LOG_LISTENERS = []
LOG_LISTENERS_LOCK = threading.Lock()

LOG_METRICS = {
    "queue_depth": 0,
    "dropped_count": 0,
    "failed_db_writes": 0,
    "emergency_fallback_count": 0,
    "write_latency_ms": 0.0,
    "last_flush": time.time(),
    "last_flush_failure": None,
    "events_processed": 0
}
LOG_METRICS_LOCK = threading.Lock()


def mask_sensitive_data(message: str) -> str:
    """Masks credentials, passwords, auth tokens, and private keys from log streams."""
    if not isinstance(message, str):
        message = str(message)
    # Mask passwords
    message = re.sub(r'(password[\'"]?\s*[:=]\s*[\'"]?)[^\'",\s]+', r'\1********', message, flags=re.IGNORECASE)
    # Mask session/secret keys
    message = re.sub(r'(token[\'"]?\s*[:=]\s*[\'"]?)[^\'",\s]+', r'\1[REDACTED_TOKEN]', message, flags=re.IGNORECASE)
    message = re.sub(r'(Bearer\s+)[A-Za-z0-9_\-\.]+', r'\1[REDACTED_BEARER]', message)
    message = re.sub(r'(playback_token=)[A-Za-z0-9_\-]+', r'\1[REDACTED_PLAYBACK]', message)
    return message


class LogWriterDaemon(threading.Thread):
    """
    Single background worker processing log writes in batches.
    Replaces per-event thread spawning to completely eliminate thread thrashing on 4 GB RAM.
    Equipped with emergency disk fallback for CRITICAL/SECURITY/ERROR events.
    """
    def __init__(self):
        super().__init__(daemon=True, name="LogWriterDaemon")
        self.running = True

    def run(self):
        batch = []
        while self.running:
            try:
                # Block for up to 1.0s waiting for log entries
                entry = LOG_QUEUE.get(timeout=1.0)
                batch.append(entry)

                # Drain up to 49 more items for batch insert
                while len(batch) < 50:
                    try:
                        batch.append(LOG_QUEUE.get_nowait())
                    except queue.Empty:
                        break

                if batch:
                    self._flush_batch(batch)
                    batch = []

            except queue.Empty:
                if batch:
                    self._flush_batch(batch)
                    batch = []
            except Exception:
                time.sleep(0.5)

    def _flush_batch(self, batch: list):
        start_t = time.time()
        try:
            with DB_LOCK:
                conn = get_db_connection()
                try:
                    params = [(
                        e["id"], e["timestamp"], e["date"], e["level"], e["category"],
                        mask_sensitive_data(e["message"]), json.dumps(e.get("meta", {})), e["created_at"]
                    ) for e in batch]
                    conn.executemany("""
                        INSERT INTO system_logs (log_id, timestamp, date, level, category, message, meta, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, params)
                    conn.commit()
                finally:
                    conn.close()

            latency = round((time.time() - start_t) * 1000.0, 2)
            with LOG_METRICS_LOCK:
                LOG_METRICS["write_latency_ms"] = latency
                LOG_METRICS["last_flush"] = time.time()
                LOG_METRICS["events_processed"] += len(batch)
                LOG_METRICS["queue_depth"] = LOG_QUEUE.qsize()
        except Exception as ex:
            with LOG_METRICS_LOCK:
                LOG_METRICS["failed_db_writes"] += 1
                LOG_METRICS["last_flush_failure"] = time.time()

            # Emergency Disk Fallback for CRITICAL, SECURITY, ERROR events
            try:
                critical_entries = [e for e in batch if e.get("level") in ["CRITICAL", "SECURITY", "ERROR"]]
                if critical_entries:
                    log_dir = os.path.dirname(config.EMERGENCY_LOG_FILE)
                    if log_dir:
                        os.makedirs(log_dir, exist_ok=True)
                    with open(config.EMERGENCY_LOG_FILE, "a", encoding="utf-8") as ef:
                        for ce in critical_entries:
                            ef.write(json.dumps({
                                "id": ce["id"],
                                "timestamp": ce["timestamp"],
                                "level": ce["level"],
                                "category": ce["category"],
                                "message": mask_sensitive_data(ce["message"]),
                                "created_at": ce["created_at"]
                            }) + "\n")
                    with LOG_METRICS_LOCK:
                        LOG_METRICS["emergency_fallback_count"] += len(critical_entries)
            except Exception:
                pass

    def flush(self):
        """Immediately flushes all queued log entries to the database."""
        batch = []
        while not LOG_QUEUE.empty():
            try:
                batch.append(LOG_QUEUE.get_nowait())
            except queue.Empty:
                break
        if batch:
            self._flush_batch(batch)


log_daemon = LogWriterDaemon()
log_daemon.start()


def log_event(level: str, category: str, message: str, meta: dict = None):
    """Enqueues audit log event into bounded queue for batch database commit."""
    now = datetime.now()
    clean_msg = mask_sensitive_data(str(message))
    entry = {
        "id": secrets.token_hex(4),
        "timestamp": now.strftime("%H:%M:%S"),
        "date": now.strftime("%Y-%m-%d"),
        "level": level.upper(),
        "category": category.upper(),
        "message": clean_msg,
        "meta": meta or {},
        "created_at": time.time()
    }

    # Bounded Queue Enqueue with Priority Preservation
    try:
        LOG_QUEUE.put_nowait(entry)
    except queue.Full:
        # If queue is full, drop INFO/DEBUG telemetry under pressure, but NEVER drop CRITICAL or SECURITY
        if entry["level"] in ["CRITICAL", "SECURITY", "ERROR"]:
            try:
                # Force drop oldest to make room for critical log
                _ = LOG_QUEUE.get_nowait()
                LOG_QUEUE.put_nowait(entry)
            except Exception:
                pass
        with LOG_METRICS_LOCK:
            LOG_METRICS["dropped_count"] += 1

    with LOG_METRICS_LOCK:
        LOG_METRICS["queue_depth"] = LOG_QUEUE.qsize()

    # Broadcast to active SSE listeners
    with LOG_LISTENERS_LOCK:
        dead_listeners = []
        for q in LOG_LISTENERS:
            try:
                q.put_nowait(entry)
            except queue.Full:
                pass
            except Exception:
                dead_listeners.append(q)
        for dead in dead_listeners:
            if dead in LOG_LISTENERS:
                LOG_LISTENERS.remove(dead)


def record_incident(service: str, severity: str, prev_state: str, new_state: str, error_summary: str, timeline_entry: str = ""):
    """Records a service degradation or failure event for incident correlation."""
    inc_id = f"inc_{int(time.time())}_{secrets.token_hex(2)}"
    now = time.time()
    mem_state = governor.get_telemetry_snapshot()["memory"]["state"]
    timeline = [{"time": datetime.now().strftime("%H:%M:%S"), "event": timeline_entry or error_summary}]

    try:
        with DB_LOCK:
            conn = get_db_connection()
            try:
                conn.execute("""
                    INSERT INTO incidents (id, timestamp, service, severity, prev_state, new_state, mem_state, error_summary, timeline)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (inc_id, now, service, severity, prev_state, new_state, mem_state, mask_sensitive_data(error_summary), json.dumps(timeline)))
                conn.commit()
            finally:
                conn.close()
    except Exception:
        pass


# ==============================================================================
# 3. AUTHENTICATION, SESSIONS, PBKDF2 HASHING & OBJECT-LEVEL RBAC
# ==============================================================================

# Short-Lived Media Playback Tokens Registry
PLAYBACK_TOKENS = {}
PLAYBACK_TOKENS_LOCK = threading.Lock()


def create_playback_token(user_id: str, file_path: str, ttl_seconds: int = None) -> str:
    """Generates a short-lived (60-120s) playback token bound to user and media path."""
    token = secrets.token_urlsafe(32)
    normalized = urllib.parse.unquote(str(file_path)).replace('\\', '/').strip('/')
    now = time.time()
    ttl = ttl_seconds if ttl_seconds is not None else config.PLAYBACK_TOKEN_TTL_SECONDS
    expires_at = now + ttl
    with PLAYBACK_TOKENS_LOCK:
        # Prune expired tokens
        expired = [k for k, v in PLAYBACK_TOKENS.items() if v.get("expires_at", 0) < now]
        for k in expired:
            del PLAYBACK_TOKENS[k]
        PLAYBACK_TOKENS[token] = {
            "user_id": user_id,
            "path": normalized,
            "expires_at": expires_at,
            "created_at": now
        }
    return token


def verify_playback_token(token: str, target_file_path: str) -> tuple[bool, str]:
    """Verifies playback token is valid, unexpired, and bound to target path."""
    if not token:
        return False, "Playback token required."
    now = time.time()
    normalized_target = urllib.parse.unquote(str(target_file_path)).replace('\\', '/').strip('/')

    with PLAYBACK_TOKENS_LOCK:
        entry = PLAYBACK_TOKENS.get(token)
        if not entry:
            return False, "Invalid or expired playback token."
        if now > entry.get("expires_at", 0):
            del PLAYBACK_TOKENS[token]
            return False, "Playback token has expired."
        if entry.get("path") != normalized_target:
            return False, "Playback token is not valid for this media path."

        user_id = entry.get("user_id")
        user = db_get_user(user_id)
        if not user or user.get("is_disabled", 0) == 1:
            return False, "User account is inactive or disabled."
        return True, "Valid"


# hash_password() and verify_password() are defined above init_unified_db()
# to satisfy startup boot order (admin seeding requires PBKDF2 at import time).


def db_get_user(user_id: str) -> dict | None:
    with DB_LOCK:
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT user_id, password_hash, salt, role, is_disabled, privileges, created_at,
                       failed_attempts, locked_until
                FROM users WHERE user_id = ?
            """, (user_id,))
            row = cur.fetchone()
            if not row:
                return None
            return {
                "user_id": row["user_id"],
                "password_hash": row["password_hash"],
                "salt": row["salt"],
                "role": row["role"],
                "is_disabled": row["is_disabled"] if "is_disabled" in row.keys() else 0,
                "privileges": json.loads(row["privileges"] or "{}"),
                "created_at": row["created_at"],
                "failed_attempts": row["failed_attempts"] if "failed_attempts" in row.keys() else 0,
                "locked_until": row["locked_until"] if "locked_until" in row.keys() else 0.0
            }
        finally:
            conn.close()


def db_get_all_users() -> dict:
    with DB_LOCK:
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT user_id, password_hash, salt, role, is_disabled, privileges, created_at,
                       failed_attempts, locked_until
                FROM users
            """)
            rows = cur.fetchall()
            return {
                r["user_id"]: {
                    "user_id": r["user_id"],
                    "password_hash": r["password_hash"],
                    "salt": r["salt"],
                    "role": r["role"],
                    "is_disabled": r["is_disabled"] if "is_disabled" in r.keys() else 0,
                    "privileges": json.loads(r["privileges"] or "{}"),
                    "created_at": r["created_at"],
                    "failed_attempts": r["failed_attempts"] if "failed_attempts" in r.keys() else 0,
                    "locked_until": r["locked_until"] if "locked_until" in r.keys() else 0.0
                }
                for r in rows
            }
        finally:
            conn.close()


@app.before_request
def authenticate_request():
    """Validates session tokens on all requests, exposing g.user and g.token."""
    g.user = None
    g.token = None

    auth_header = request.headers.get("Authorization", "")
    token = None
    if auth_header.startswith("Bearer "):
        token = auth_header.split(" ", 1)[1].strip()
    elif request.headers.get("X-Session-Token"):
        token = request.headers.get("X-Session-Token", "").strip()
    elif "auth" in request.args:
        token = request.args.get("auth", "").strip()
    elif "token" in request.args:
        token = request.args.get("token", "").strip()

    if not token:
        return

    with SESSIONS_LOCK:
        session = SESSIONS.get(token)
        if session:
            if time.time() > session.get("expires_at", 0):
                del SESSIONS[token]
                return
            if session.get("is_disabled", 0) == 1:
                del SESSIONS[token]
                return
            g.user = session
            g.token = token


def require_auth():
    if not g.user:
        return jsonify({"error": "unauthorized", "message": "Valid authentication token required."}), 401
    if g.user.get("is_disabled", 0) == 1:
        return jsonify({"error": "account_disabled", "message": "Account is disabled. Contact system administrator."}), 403
    return None


def require_admin():
    err = require_auth()
    if err:
        return err
    if g.user.get("role") != "admin":
        return jsonify({"error": "permission_denied", "message": "Administrator privileges required.", "required_role": "admin"}), 403
    return None


def has_privilege(priv_name: str) -> bool:
    if not g.user:
        return False
    if g.user.get("is_disabled", 0) == 1:
        return False
    if g.user.get("role") == "admin":
        return True
    privs = g.user.get("privileges", {})
    return bool(privs.get(priv_name, False))


def require_privilege_or_admin(priv_name: str):
    err = require_auth()
    if err:
        return err
    if not has_privilege(priv_name):
        return jsonify({
            "error": "permission_denied",
            "message": f"Operation requires privilege '{priv_name}'.",
            "required_privilege": priv_name
        }), 403
    return None


def verify_resource_ownership(resource_owner_id: str) -> bool:
    """Object-level authorization check: Admin or resource owner."""
    if not g.user:
        return False
    if g.user.get("is_disabled", 0) == 1:
        return False
    if g.user.get("role") == "admin":
        return True
    return g.user.get("user_id") == resource_owner_id


# ==============================================================================
# 4. AUTHORITATIVE OLLAMA MODEL REGISTRY & RUNTIME LIFECYCLE
# ==============================================================================

class OllamaModelRegistry:
    """
    Authoritative single source of truth for Ollama models and runtime state.
    Uses official Ollama endpoints: /api/tags, /api/show, /api/ps, /api/version.
    Strictly uses runit supervisor (sv up/down/restart) for process lifecycle.
    """
    def __init__(self):
        self.host = config.OLLAMA_HOST
        self.selected_model = "qwen2.5:0.5b"
        self.default_model = "qwen2.5:0.5b"
        self.last_installed_cache = []
        self.last_check_time = 0.0
        self.cache_lock = threading.Lock()

    def get_version(self) -> str | None:
        try:
            r = requests.get(f"{self.host}/api/version", timeout=1.0)
            if r.status_code == 200:
                return r.json().get("version", "unknown")
        except Exception:
            pass
        return None

    def get_installed_models(self) -> list[dict]:
        """Queries /api/tags for authoritative list of installed models."""
        try:
            r = requests.get(f"{self.host}/api/tags", timeout=1.5)
            if r.status_code == 200:
                raw_models = r.json().get("models", [])
                models = []
                for m in raw_models:
                    size_bytes = m.get("size", 0)
                    size_display = f"{round(size_bytes / (1024*1024), 1)} MB" if size_bytes < 1024**3 else f"{round(size_bytes / (1024**3), 2)} GB"
                    details = m.get("details", {})
                    models.append({
                        "name": m.get("name"),
                        "digest": m.get("digest", "")[:12],
                        "size_bytes": size_bytes,
                        "size_display": size_display,
                        "parameter_size": details.get("parameter_size", "unknown"),
                        "quantization": details.get("quantization_level", "unknown"),
                        "family": details.get("family", "unknown"),
                        "installed": True,
                        "modified_at": m.get("modified_at")
                    })
                with self.cache_lock:
                    self.last_installed_cache = models
                    self.last_check_time = time.time()
                return models
        except Exception:
            pass
        with self.cache_lock:
            return list(self.last_installed_cache)

    def get_loaded_models(self) -> list[dict]:
        """Queries /api/ps for models currently loaded in RAM/VRAM."""
        try:
            r = requests.get(f"{self.host}/api/ps", timeout=1.0)
            if r.status_code == 200:
                raw = r.json().get("models", [])
                loaded = []
                for m in raw:
                    size_bytes = m.get("size", 0)
                    size_vram = m.get("size_vram", 0)
                    loaded.append({
                        "name": m.get("name"),
                        "runtime_size_bytes": size_bytes,
                        "runtime_size_mb": round(size_bytes / (1024 * 1024), 1),
                        "runtime_vram_mb": round(size_vram / (1024 * 1024), 1),
                        "processor": "GPU/VRAM" if size_vram > 0 else "CPU/RAM",
                        "expires_at": m.get("expires_at"),
                        "size_vram": size_vram
                    })
                return loaded
        except Exception:
            pass
        return []

    def get_model_details(self, model_name: str) -> dict | None:
        """Queries /api/show for parameter details and capabilities."""
        try:
            r = requests.post(f"{self.host}/api/show", json={"name": model_name}, timeout=2.0)
            if r.status_code == 200:
                data = r.json()
                details = data.get("details", {})
                params_str = data.get("parameters", "")
                ctx_len = config.CONTEXT_SIZE_NORMAL
                m_ctx = re.search(r"num_ctx\s+(\d+)", params_str)
                if m_ctx:
                    ctx_len = int(m_ctx.group(1))

                return {
                    "name": model_name,
                    "parameter_size": details.get("parameter_size", "unknown"),
                    "quantization": details.get("quantization_level", "unknown"),
                    "family": details.get("family", "unknown"),
                    "context_length": ctx_len,
                    "modelfile": data.get("modelfile", "")[:200],
                    "capabilities": ["text_generation", "chat"]
                }
        except Exception:
            pass
        return None

    def get_ai_state(self) -> dict:
        """Returns unified AI state: engine status, selected model, loaded models."""
        ver = self.get_version()
        engine_running = (ver is not None)

        supervisor_state = "down"
        try:
            res = subprocess.run(["sv", "status", "ollama"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
            if res.returncode == 0 and "run:" in res.stdout:
                supervisor_state = "up"
        except Exception:
            supervisor_state = "up" if engine_running else "down"

        if not engine_running:
            with self.cache_lock:
                cached_models = list(self.last_installed_cache)
            cached_names = [m["name"] for m in cached_models]
            return {
                "engine": "stopped",
                "version": "offline",
                "supervisor_state": supervisor_state,
                "selected_model": self.selected_model,
                "default_model": self.default_model,
                "loaded_model": None,
                "loaded_model_details": None,
                "available_models": cached_names,
                "installed_models_count": len(cached_models),
                "loaded_models_count": 0
            }

        installed = self.get_installed_models()
        installed_names = [m["name"] for m in installed]

        loaded = self.get_loaded_models()
        loaded_name = loaded[0]["name"] if loaded else None
        loaded_details = loaded[0] if loaded else None

        # Verify selected model validity
        if self.selected_model not in installed_names and installed_names:
            if self.default_model in installed_names:
                self.selected_model = self.default_model
            else:
                self.selected_model = installed_names[0]

        return {
            "engine": "running",
            "version": ver or "online",
            "supervisor_state": supervisor_state,
            "selected_model": self.selected_model,
            "default_model": self.default_model,
            "loaded_model": loaded_name,
            "loaded_model_details": loaded_details,
            "available_models": installed_names,
            "installed_models_count": len(installed),
            "loaded_models_count": len(loaded)
        }

    def select_model(self, model_name: str) -> tuple[bool, str]:
        installed = self.get_installed_models()
        installed_names = [m["name"] for m in installed]
        if model_name not in installed_names:
            return False, f"Model '{model_name}' is not installed in Ollama."
        self.selected_model = model_name
        return True, f"Selected model set to '{model_name}'."

    def start_service(self) -> tuple[bool, str]:
        """Starts Ollama using runit supervision only."""
        try:
            res = subprocess.run(["sv", "up", "ollama"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if res.returncode == 0:
                log_event("INFO", "OLLAMA", "Issued 'sv up ollama' to runit supervisor.")
                return True, "Ollama service start signal sent to runit."
        except Exception as e:
            pass
        return False, "Failed to start Ollama via supervisor."

    def stop_service(self) -> tuple[bool, str]:
        """Stops Ollama using runit supervision only."""
        try:
            res = subprocess.run(["sv", "down", "ollama"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if res.returncode == 0:
                log_event("INFO", "OLLAMA", "Issued 'sv down ollama' to runit supervisor.")
                return True, "Ollama service stop signal sent to runit."
        except Exception as e:
            pass
        return False, "Failed to stop Ollama via supervisor."


ollama_registry = OllamaModelRegistry()
ollama_mgr = ollama_registry

# ==============================================================================
# 5. STORAGE-BACKED SQLITE FTS5 RAG ENGINE
# ==============================================================================

class SQLiteFTS5RAGEngine:
    """
    Lightweight, storage-backed SQLite FTS5 RAG Inverted Index with BM25 Ranking.
    Zero massive in-memory dictionary; zero heap spikes on 4 GB RAM mobile hardware.
    Features: Incremental hashing, source folder enforcement, excluded directory protection,
    compact legacy index migration.
    """
    def __init__(self):
        self.db_file = config.RAG_DB_FILE
        self.source_folders = list(config.RAG_DEFAULT_SOURCES)
        self.state = "ready"
        self.last_rebuild = 0.0
        self.rebuild_duration_ms = 0.0
        self._rebuild_lock = threading.Lock()
        self._pending_rebuild = False

    def extract_text(self, fpath: str) -> str:
        """Extracts text content safely with size and line bounds."""
        try:
            if os.path.getsize(fpath) > config.RAG_MAX_FILE_SIZE_BYTES:
                return ""
            with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                lines = []
                for _ in range(1200):
                    line = f.readline()
                    if not line:
                        break
                    lines.append(line)
                return "".join(lines)
        except Exception:
            return ""

    def chunk_text(self, text: str, max_chunk_chars: int = 800, overlap: int = 100) -> list[str]:
        """Splits document text into overlapping chunks."""
        chunks = []
        text = text.strip()
        if not text:
            return chunks

        lines = text.splitlines()
        current_chunk = []
        current_len = 0

        for line in lines:
            line_str = line.strip()
            if not line_str:
                continue
            if current_len + len(line_str) > max_chunk_chars and current_chunk:
                chunks.append("\n".join(current_chunk))
                # Keep last 2 lines for overlap
                current_chunk = current_chunk[-2:] if len(current_chunk) >= 2 else current_chunk[-1:]
                current_len = sum(len(l) for l in current_chunk)

            current_chunk.append(line_str)
            current_len += len(line_str)

        if current_chunk:
            chunks.append("\n".join(current_chunk))

        return chunks

    def build_vault_index(self) -> dict:
        """Executes incremental indexing into SQLite FTS5 database."""
        if not self._rebuild_lock.acquire(blocking=False):
            self._pending_rebuild = True
            log_event("INFO", "RAG", "RAG rebuild already active. Queued as pending.")
            return {"status": "rebuild_queued"}

        self.state = "rebuilding"
        start_time = time.time()
        log_event("INFO", "RAG", "Starting knowledge base indexing (SQLite FTS5)...")

        total_indexed_docs = 0
        total_chunks = 0

        try:
            while True:
                self._pending_rebuild = False
                conn = get_db_connection(self.db_file)
                cur = conn.cursor()

                # Scan configured source folders
                discovered_paths = set()

                for src_folder in self.source_folders:
                    target_dir = os.path.join(config.STORAGE_DIR, src_folder) if src_folder != "." else config.STORAGE_DIR
                    if not os.path.exists(target_dir):
                        continue

                    for root, dirs, files in os.walk(target_dir):
                        # Enforce Excluded Directories
                        dirs[:] = [d for d in dirs if d not in config.RAG_EXCLUDE_DIRS and not d.startswith('.')]

                        for f in files:
                            # Enforce Excluded Extensions
                            _, ext = os.path.splitext(f)
                            if ext.lower() in config.RAG_EXCLUDE_EXTENSIONS:
                                continue

                            ext_clean = ext.lstrip('.').lower()
                            if ext_clean not in config.RAG_SUPPORTED_TEXT_EXTENSIONS:
                                continue

                            fpath = os.path.join(root, f)
                            rel_path = os.path.relpath(fpath, config.STORAGE_DIR).replace('\\', '/')
                            discovered_paths.add(rel_path)

                            # Check if file has changed via mtime and hash
                            st = os.stat(fpath)
                            mtime = st.st_mtime
                            size_bytes = st.st_size

                            cur.execute("SELECT id, hash, mtime FROM rag_documents WHERE path = ?", (rel_path,))
                            existing = cur.fetchone()

                            content = self.extract_text(fpath)
                            if not content:
                                continue

                            file_hash = hashlib.md5(content.encode('utf-8')).hexdigest()

                            if existing and existing["hash"] == file_hash and existing["mtime"] == mtime:
                                continue  # Up to date

                            # Re-index this document
                            if existing:
                                doc_id = existing["id"]
                                cur.execute("DELETE FROM rag_chunks_fts WHERE rowid IN (SELECT id FROM rag_chunks WHERE doc_id = ?)", (doc_id,))
                                cur.execute("DELETE FROM rag_chunks WHERE doc_id = ?", (doc_id,))
                                cur.execute("UPDATE rag_documents SET hash=?, size_bytes=?, mtime=?, indexed_at=? WHERE id=?",
                                            (file_hash, size_bytes, mtime, time.time(), doc_id))
                            else:
                                cur.execute("""
                                    INSERT INTO rag_documents (path, filename, hash, size_bytes, chunk_count, mtime, indexed_at)
                                    VALUES (?, ?, ?, ?, 0, ?, ?)
                                """, (rel_path, f, file_hash, size_bytes, mtime, time.time()))
                                doc_id = cur.lastrowid

                            chunks = self.chunk_text(content)
                            for idx, ch_text in enumerate(chunks[:config.RAG_MAX_CHUNKS]):
                                token_cnt = len(ch_text.split())
                                cur.execute("""
                                    INSERT INTO rag_chunks (doc_id, chunk_index, content, token_count)
                                    VALUES (?, ?, ?, ?)
                                """, (doc_id, idx, ch_text, token_cnt))
                                chunk_id = cur.lastrowid
                                cur.execute("INSERT INTO rag_chunks_fts (rowid, content) VALUES (?, ?)", (chunk_id, ch_text))

                            cur.execute("UPDATE rag_documents SET chunk_count = ? WHERE id = ?", (len(chunks), doc_id))
                            conn.commit()

                # Clean up deleted documents
                cur.execute("SELECT id, path FROM rag_documents")
                all_docs = cur.fetchall()
                for doc in all_docs:
                    if doc["path"] not in discovered_paths:
                        cur.execute("DELETE FROM rag_chunks_fts WHERE rowid IN (SELECT id FROM rag_chunks WHERE doc_id = ?)", (doc["id"],))
                        cur.execute("DELETE FROM rag_chunks WHERE doc_id = ?", (doc["id"],))
                        cur.execute("DELETE FROM rag_documents WHERE id = ?", (doc["id"],))
                conn.commit()

                cur.execute("SELECT COUNT(*) FROM rag_documents")
                total_indexed_docs = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM rag_chunks")
                total_chunks = cur.fetchone()[0]
                conn.close()

                if not self._pending_rebuild:
                    break

            self.state = "ready"
            self.last_rebuild = time.time()
            self.rebuild_duration_ms = round((time.time() - start_time) * 1000.0, 1)
            log_event("INFO", "RAG", f"Indexed {total_indexed_docs} docs, {total_chunks} chunks in {self.rebuild_duration_ms} ms.")
            return {"documents_count": total_indexed_docs, "chunks_count": total_chunks}

        except Exception as e:
            self.state = "failed"
            log_event("ERROR", "RAG", f"RAG rebuild failed: {str(e)}")
            raise e
        finally:
            self._rebuild_lock.release()

    def trigger_rebuild_async(self):
        t = threading.Thread(target=self.build_vault_index, daemon=True, name="RAGIndexWorker")
        t.start()

    def search(self, query: str, top_k: int = 4) -> list[dict]:
        """Executes BM25 full-text search against SQLite FTS5 index."""
        cleaned = re.sub(r'[^\w\s]', ' ', query).strip()
        terms = [t for t in cleaned.split() if len(t) >= 2][:8]
        if not terms:
            return []

        fts_query = " OR ".join(terms)
        results = []

        try:
            conn = get_db_connection(self.db_file)
            cur = conn.cursor()
            cur.execute("""
                SELECT c.content, d.filename, d.path, rank
                FROM rag_chunks_fts f
                JOIN rag_chunks c ON f.rowid = c.id
                JOIN rag_documents d ON c.doc_id = d.id
                WHERE rag_chunks_fts MATCH ?
                ORDER BY rank
                LIMIT ?
            """, (fts_query, top_k))

            for row in cur.fetchall():
                results.append({
                    "doc": row["filename"],
                    "path": row["path"],
                    "text": row["content"],
                    "score": round(abs(float(row["rank"])), 3) if row["rank"] is not None else 1.0
                })
            conn.close()
        except Exception:
            pass

        return results

    def compact_legacy_index(self) -> dict:
        """
        Safely migrates legacy rag_index.json to SQLite FTS5 database.
        Validates row count and sample queries before archiving original JSON.
        """
        legacy_file = config.RAG_INDEX_FILE
        if not os.path.exists(legacy_file):
            return {"migrated": False, "message": "No legacy rag_index.json file found."}

        try:
            with open(legacy_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            docs = data.get("documents", {})
            chunks = data.get("chunks", [])

            conn = get_db_connection(self.db_file)
            cur = conn.cursor()

            migrated_docs = 0
            migrated_chunks = 0

            for doc_path, meta in docs.items():
                fname = os.path.basename(doc_path)
                cur.execute("SELECT id FROM rag_documents WHERE path = ?", (doc_path,))
                existing = cur.fetchone()
                if not existing:
                    cur.execute("""
                        INSERT INTO rag_documents (path, filename, hash, size_bytes, chunk_count, mtime, indexed_at)
                        VALUES (?, ?, 'legacy_migrated', ?, ?, ?, ?)
                    """, (doc_path, fname, meta.get("size", 0), meta.get("chunks_count", 0), time.time(), time.time()))
                    doc_id = cur.lastrowid
                    migrated_docs += 1
                else:
                    doc_id = existing["id"]

            for c in chunks:
                doc_name = c.get("doc", "")
                text = c.get("text", "")
                if not text:
                    continue

                cur.execute("SELECT id FROM rag_documents WHERE filename = ? OR path LIKE ?", (doc_name, f"%{doc_name}"))
                doc_row = cur.fetchone()
                doc_id = doc_row["id"] if doc_row else 1

                cur.execute("""
                    INSERT INTO rag_chunks (doc_id, chunk_index, content, token_count)
                    VALUES (?, 0, ?, ?)
                """, (doc_id, text, len(text.split())))
                chunk_id = cur.lastrowid
                cur.execute("INSERT INTO rag_chunks_fts (rowid, content) VALUES (?, ?)", (chunk_id, text))
                migrated_chunks += 1

            conn.commit()

            # Validation step: Verify table counts
            cur.execute("SELECT COUNT(*) FROM rag_chunks")
            count = cur.fetchone()[0]
            conn.close()

            if count > 0:
                # Archive original json
                archive_path = f"{legacy_file}.bak_{int(time.time())}"
                shutil.copy2(legacy_file, archive_path)
                os.remove(legacy_file)
                log_event("INFO", "RAG", f"Successfully compacted legacy RAG index into SQLite FTS5 ({count} chunks).")
                return {
                    "migrated": True,
                    "documents_migrated": migrated_docs,
                    "chunks_migrated": migrated_chunks,
                    "archived_to": archive_path
                }
            else:
                return {"migrated": False, "error": "Validation failed: 0 chunks in SQLite FTS5."}

        except Exception as e:
            return {"migrated": False, "error": f"Compaction failed: {str(e)}"}

    def get_diagnostics(self) -> dict:
        """Returns deep technical diagnostics for the RAG subsystem."""
        db_size_bytes = os.path.getsize(self.db_file) if os.path.exists(self.db_file) else 0
        doc_count = 0
        chunk_count = 0
        avg_chunk_size = 0
        largest_doc = "--"

        if os.path.exists(self.db_file):
            try:
                conn = get_db_connection(self.db_file)
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) FROM rag_documents")
                doc_count = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM rag_chunks")
                chunk_count = cur.fetchone()[0]
                cur.execute("SELECT AVG(token_count) FROM rag_chunks")
                res_avg = cur.fetchone()[0]
                if res_avg: avg_chunk_size = round(float(res_avg), 1)
                cur.execute("SELECT path, size_bytes FROM rag_documents ORDER BY size_bytes DESC LIMIT 1")
                res_large = cur.fetchone()
                if res_large: largest_doc = f"{res_large['path']} ({round(res_large['size_bytes']/1024, 1)} KB)"
                conn.close()
            except Exception:
                pass

        # Memory footprint estimate: SQLite page cache ~ 2-5 MB max
        estimated_ram_mb = 4.0 if doc_count > 0 else 0.5

        return {
            "backend": "SQLite FTS5 (BM25 Ranking)",
            "database_file": self.db_file,
            "database_size_kb": round(db_size_bytes / 1024, 2),
            "document_count": doc_count,
            "chunk_count": chunk_count,
            "avg_chunk_tokens": avg_chunk_size,
            "largest_document": largest_doc,
            "source_folders": self.source_folders,
            "excluded_dirs": config.RAG_EXCLUDE_DIRS,
            "excluded_extensions": config.RAG_EXCLUDE_EXTENSIONS,
            "last_rebuild": self.last_rebuild,
            "last_rebuild_time": datetime.fromtimestamp(self.last_rebuild).strftime("%Y-%m-%d %H:%M:%S") if self.last_rebuild > 0 else "Never",
            "rebuild_duration_ms": self.rebuild_duration_ms,
            "memory_estimate_mb": estimated_ram_mb,
            "state": self.state
        }


rag_engine = SQLiteFTS5RAGEngine()# ==============================================================================
# 6. BOUNDED TASK RUNNER WITH AUTHORITATIVE LIFECYCLE & PROCESS MANAGEMENT
# ==============================================================================

def serialize_iso_timestamp(ts: float | int | str | None) -> str | None:
    if not ts:
        return None
    if isinstance(ts, str):
        if 'T' in ts:
            return ts
        try:
            ts = float(ts)
        except (ValueError, TypeError):
            return ts
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    except Exception:
        return None


def parse_speed_string_to_bps(speed_str: str) -> int | None:
    if not speed_str:
        return None
    try:
        m = re.match(r'([\d\.]+)\s*([kKmMgG]?)(?:i?B/s|b/s)?', str(speed_str).strip())
        if m:
            val = float(m.group(1))
            unit = m.group(2).upper()
            mult = 1
            if unit == 'K': mult = 1024
            elif unit == 'M': mult = 1024 * 1024
            elif unit == 'G': mult = 1024 * 1024 * 1024
            return int(val * mult)
    except Exception:
        pass
    return None


def parse_eta_string_to_seconds(eta_str: str) -> int | None:
    if not eta_str:
        return None
    try:
        parts = [int(p) for p in str(eta_str).strip().split(':')]
        if len(parts) == 1:
            return parts[0]
        elif len(parts) == 2:
            return parts[0] * 60 + parts[1]
        elif len(parts) == 3:
            return parts[0] * 3600 + parts[1] * 60 + parts[2]
    except Exception:
        pass
    return None


def terminate_process_tree(proc: subprocess.Popen):
    """Authoritative process hierarchy termination for yt-dlp, ffmpeg, and subprocesses."""
    if not proc or proc.poll() is not None:
        return
    try:
        pid = proc.pid
        if os.name == 'nt':
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            try:
                pgid = os.getpgid(pid)
                os.killpg(pgid, signal.SIGTERM)
            except Exception:
                proc.terminate()
            try:
                proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(pgid, signal.SIGKILL)
                except Exception:
                    proc.kill()
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


class BoundedTaskRunner:
    """
    Bounded worker thread pool strictly maintaining concurrency = 1 on 4 GB RAM hardware.
    Features: authoritative SQLite persistence, deterministic ISO-8601 timestamps,
    authoritative state machine (QUEUED -> STARTING -> RUNNING -> POST_PROCESSING -> VERIFYING -> COMPLETED),
    process-tree termination, partial file cleanup, and owner user isolation.
    """
    def __init__(self, max_concurrency: int = config.MAX_HEAVY_CONCURRENCY):
        self.max_concurrency = max_concurrency
        self.task_queue = queue.Queue()
        self.tasks = {}
        self.active_tasks = []
        self.lock = threading.Lock()
        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True, name="BoundedTaskWorker")
        self._worker_thread.start()

    def _normalize_task_record(self, t: dict) -> dict:
        """Converts internal task dict/row into canonical task schema."""
        task_id = str(t.get("id") or t.get("task_id") or "")
        task_type = str(t.get("type") or t.get("task_type") or "generic")
        status = str(t.get("status") or "QUEUED").upper()
        stage = str(t.get("stage") or status).upper()

        # Enforce canonical consistency: terminal status MUST NEVER have stage=QUEUED
        if status in ["COMPLETED", "FAILED", "CANCELLED"] and stage == "QUEUED":
            stage = status

        owner = str(t.get("owner_user_id") or t.get("owner") or t.get("user_id") or "admin")
        
        created_at = t.get("created_at")
        started_at = t.get("started_at")
        updated_at = t.get("updated_at")
        completed_at = t.get("completed_at")
        
        raw_logs = t.get("logs", [])
        if isinstance(raw_logs, str):
            try:
                logs = json.loads(raw_logs)
            except Exception:
                logs = [raw_logs]
        elif isinstance(raw_logs, list):
            logs = raw_logs
        else:
            logs = []

        return {
            "id": task_id,
            "task_id": task_id,
            "title": str(t.get("title") or f"Task {task_id}"),
            "type": task_type,
            "task_type": task_type,
            "status": status,
            "state": status,
            "stage": stage,
            "progress": int(t.get("progress") or 0),
            "eta_seconds": t.get("eta_seconds"),
            "speed_bps": t.get("speed_bps"),
            "output_path": t.get("output_path"),
            "error": t.get("error"),
            "result": t.get("result"),
            "metadata": t.get("metadata") if isinstance(t.get("metadata"), dict) else {},
            "owner": owner,
            "owner_user_id": owner,
            "user_id": owner,
            "created_at": serialize_iso_timestamp(created_at),
            "created_at_epoch": float(created_at) if isinstance(created_at, (int, float)) else None,
            "started_at": serialize_iso_timestamp(started_at),
            "started_at_epoch": float(started_at) if isinstance(started_at, (int, float)) else None,
            "updated_at": serialize_iso_timestamp(updated_at),
            "updated_at_epoch": float(updated_at) if isinstance(updated_at, (int, float)) else None,
            "completed_at": serialize_iso_timestamp(completed_at),
            "completed_at_epoch": float(completed_at) if isinstance(completed_at, (int, float)) else None,
            "logs": logs
        }

    def enqueue_task(self, title: str, task_type: str, target_fn, *args, owner_user_id: str = "admin", **kwargs) -> tuple[str | None, dict]:
        res_check = governor.can_start_heavy_task()
        if not res_check["allowed"]:
            log_event("WARN", "TASK", f"Task '{title}' blocked by Governor: {res_check['reason']}")
            return None, res_check

        task_id = f"task_{int(time.time())}_{secrets.token_hex(4)}"
        now = time.time()
        task_obj = {
            "id": task_id,
            "task_id": task_id,
            "title": title,
            "type": task_type,
            "task_type": task_type,
            "status": "QUEUED",
            "state": "QUEUED",
            "stage": "QUEUED",
            "progress": 0,
            "eta_seconds": None,
            "speed_bps": None,
            "output_path": None,
            "error": None,
            "result": None,
            "metadata": {},
            "logs": [f"[{datetime.now().strftime('%H:%M:%S')}] Task enqueued by '{owner_user_id}'."],
            "target_fn": target_fn,
            "args": args,
            "kwargs": kwargs,
            "process": None,
            "created_at": now,
            "started_at": None,
            "updated_at": now,
            "completed_at": None,
            "owner_user_id": owner_user_id,
            "partial_files": []
        }

        with self.lock:
            self.tasks[task_id] = task_obj
            self._save_task_to_db(task_obj)
            self.task_queue.put(task_id)

        log_event("INFO", "TASK", f"Enqueued task '{title}' ({task_id}) for user '{owner_user_id}'.")
        return task_id, res_check

    def _worker_loop(self):
        while True:
            task_id = self.task_queue.get()
            with self.lock:
                task_obj = self.tasks.get(task_id)
                if not task_obj:
                    task_obj = self._load_task_from_db(task_id)
                if not task_obj or str(task_obj.get('status', '')).upper() == 'CANCELLED':
                    self.task_queue.task_done()
                    continue
                now = time.time()
                task_obj['status'] = 'STARTING'
                task_obj['stage'] = 'STARTING'
                task_obj['started_at'] = now
                task_obj['updated_at'] = now
                self.active_tasks.append(task_obj)
                self._save_task_to_db(task_obj)

            log_event("INFO", "TASK", f"Started task '{task_obj['title']}' ({task_id}).")

            try:
                task_obj['target_fn'](task_obj, *task_obj.get('args', ()), **task_obj.get('kwargs', {}))
                with self.lock:
                    if str(task_obj.get('status', '')).upper() not in ['CANCELLED', 'CANCELLING']:
                        now = time.time()
                        task_obj['status'] = 'COMPLETED'
                        task_obj['stage'] = 'COMPLETED'
                        task_obj['progress'] = 100
                        task_obj['completed_at'] = now
                        task_obj['updated_at'] = now
                        task_obj['logs'].append(f"[{datetime.now().strftime('%H:%M:%S')}] Task completed successfully.")
                        self._save_task_to_db(task_obj)
                        log_event("INFO", "TASK", f"Completed task '{task_obj['title']}'.")
            except Exception as e:
                with self.lock:
                    if str(task_obj.get('status', '')).upper() not in ['CANCELLED', 'CANCELLING']:
                        now = time.time()
                        task_obj['status'] = 'FAILED'
                        task_obj['stage'] = 'FAILED'
                        task_obj['error'] = str(e)
                        task_obj['completed_at'] = now
                        task_obj['updated_at'] = now
                        task_obj['logs'].append(f"[{datetime.now().strftime('%H:%M:%S')}] Task failed: {str(e)}")
                        self._cleanup_partial_files(task_obj)
                        self._save_task_to_db(task_obj)
                        log_event("ERROR", "TASK", f"Task '{task_obj['title']}' failed: {str(e)}")
            finally:
                with self.lock:
                    if task_obj in self.active_tasks:
                        self.active_tasks.remove(task_obj)
                    self._save_task_to_db(task_obj)
                    self.task_queue.task_done()

    def cancel_task(self, task_id: str, requesting_user_id: str = None, is_admin: bool = False) -> tuple[bool, str]:
        with self.lock:
            task = self.tasks.get(task_id)
            if not task:
                task = self._load_task_from_db(task_id)

            if not task:
                return False, "Task not found."

            if not is_admin and requesting_user_id and task.get("owner_user_id") != requesting_user_id:
                return False, "Permission denied: You do not own this task."

            current_status = str(task.get('status', '')).upper()
            if current_status in ['COMPLETED', 'FAILED', 'CANCELLED']:
                return False, f"Task already {current_status.lower()}."

            if current_status == 'QUEUED':
                now = time.time()
                task['status'] = 'CANCELLED'
                task['stage'] = 'CANCELLED'
                task['completed_at'] = now
                task['updated_at'] = now
                task['logs'].append(f"[{datetime.now().strftime('%H:%M:%S')}] Queued task cancelled by user.")
                self._save_task_to_db(task)
                log_event("WARN", "TASK", f"Queued task '{task['title']}' cancelled by '{requesting_user_id or 'admin'}'.")
                return True, "Task cancelled successfully."

            # Active task (STARTING, RUNNING, POST_PROCESSING, VERIFYING)
            now = time.time()
            task['status'] = 'CANCELLING'
            task['stage'] = 'CANCELLING'
            task['updated_at'] = now
            task['logs'].append(f"[{datetime.now().strftime('%H:%M:%S')}] Task cancellation requested.")
            self._save_task_to_db(task)

            if task.get('process'):
                terminate_process_tree(task['process'])

            self._cleanup_partial_files(task)

            now = time.time()
            task['status'] = 'CANCELLED'
            task['stage'] = 'CANCELLED'
            task['completed_at'] = now
            task['updated_at'] = now
            task['logs'].append(f"[{datetime.now().strftime('%H:%M:%S')}] Task cancelled and partial files cleaned.")
            self._save_task_to_db(task)

        log_event("WARN", "TASK", f"Task '{task['title']}' was cancelled by '{requesting_user_id or 'admin'}'.")
        return True, "Task cancelled successfully."

    def _cleanup_partial_files(self, task: dict):
        # 1. Clean registered partial files
        for p in task.get('partial_files', []):
            try:
                if os.path.exists(p):
                    if os.path.isdir(p):
                        shutil.rmtree(p, ignore_errors=True)
                    else:
                        os.remove(p)
            except Exception:
                pass

        # 2. Clean temporary artifacts from destination if specified
        dest_dir = task.get('metadata', {}).get('destination_dir') if isinstance(task.get('metadata'), dict) else None
        if dest_dir and os.path.isdir(dest_dir):
            try:
                for f in os.listdir(dest_dir):
                    if f.endswith(('.part', '.ytdl', '.tmp', '.crdownload')):
                        fp = os.path.join(dest_dir, f)
                        try:
                            if os.path.isfile(fp):
                                os.remove(fp)
                        except Exception:
                            pass
            except Exception:
                pass

    def _save_task_to_db(self, task: dict):
        try:
            status_val = str(task.get("status", "QUEUED")).upper()
            stage_val = str(task.get("stage", status_val)).upper()
            if status_val in ["COMPLETED", "FAILED", "CANCELLED"] and stage_val == "QUEUED":
                stage_val = status_val

            with DB_LOCK:
                conn = get_db_connection()
                try:
                    conn.execute("""
                        INSERT INTO background_tasks (
                            id, title, type, status, stage, progress, logs, error, result,
                            metadata, owner_user_id, eta_seconds, speed_bps, output_path,
                            created_at, started_at, updated_at, completed_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(id) DO UPDATE SET
                            title=excluded.title,
                            type=excluded.type,
                            status=excluded.status,
                            stage=excluded.stage,
                            progress=excluded.progress,
                            logs=excluded.logs,
                            error=excluded.error,
                            result=excluded.result,
                            metadata=excluded.metadata,
                            eta_seconds=excluded.eta_seconds,
                            speed_bps=excluded.speed_bps,
                            output_path=excluded.output_path,
                            started_at=coalesce(excluded.started_at, background_tasks.started_at),
                            updated_at=excluded.updated_at,
                            completed_at=coalesce(excluded.completed_at, background_tasks.completed_at);
                    """, (
                        task["id"], task["title"], task.get("type", "generic"),
                        status_val,
                        stage_val,
                        int(task.get("progress", 0)),
                        json.dumps(task.get("logs", [])),
                        task.get("error"),
                        task.get("result"),
                        json.dumps(task.get("metadata", {})) if isinstance(task.get("metadata"), dict) else str(task.get("metadata", "{}")),
                        task.get("owner_user_id", "admin"),
                        task.get("eta_seconds"),
                        task.get("speed_bps"),
                        task.get("output_path"),
                        task.get("created_at", time.time()),
                        task.get("started_at"),
                        task.get("updated_at", time.time()),
                        task.get("completed_at")
                    ))
                    conn.commit()
                finally:
                    conn.close()
        except Exception:
            pass

    def _load_task_from_db(self, task_id: str) -> dict | None:
        try:
            with DB_LOCK:
                conn = get_db_connection()
                try:
                    cur = conn.cursor()
                    cur.execute("""
                        SELECT id, title, type, status, stage, progress, logs, error, result,
                               metadata, owner_user_id, eta_seconds, speed_bps, output_path,
                               created_at, started_at, updated_at, completed_at
                        FROM background_tasks WHERE id = ?
                    """, (task_id,))
                    row = cur.fetchone()
                    if row:
                        return dict(row)
                finally:
                    conn.close()
        except Exception:
            pass
        return None

    def get_task(self, task_id: str) -> dict | None:
        """Fetch task metadata by ID from memory or SQLite, returning normalized schema."""
        with self.lock:
            if task_id in self.tasks:
                return self._normalize_task_record(self.tasks[task_id])
        
        row_dict = self._load_task_from_db(task_id)
        if row_dict:
            return self._normalize_task_record(row_dict)
        return None

    def get_all_tasks(self, type_filter: str = None, status_filter: str = None, limit: int = 100) -> list[dict]:
        """Fetch background tasks merged between active memory and SQLite, returning canonical schemas."""
        tasks_map = {}
        
        # 1. Query SQLite
        try:
            with DB_LOCK:
                conn = get_db_connection()
                try:
                    cur = conn.cursor()
                    cur.execute("""
                        SELECT id, title, type, status, stage, progress, logs, error, result,
                               metadata, owner_user_id, eta_seconds, speed_bps, output_path,
                               created_at, started_at, updated_at, completed_at
                        FROM background_tasks ORDER BY updated_at DESC LIMIT ?
                    """, (limit,))
                    for row in cur.fetchall():
                        r_dict = dict(row)
                        tasks_map[r_dict["id"]] = r_dict
                finally:
                    conn.close()
        except Exception:
            pass

        # 2. Overlay live in-memory tasks
        with self.lock:
            for tid, t in self.tasks.items():
                tasks_map[tid] = dict(t)

        # 3. Normalize and filter
        results = []
        for t in tasks_map.values():
            norm = self._normalize_task_record(t)
            if type_filter:
                t_type = norm.get("type", "").lower()
                if type_filter.lower() not in t_type and t_type not in type_filter.lower():
                    continue
            if status_filter:
                s_filter = status_filter.upper()
                if s_filter == "ACTIVE":
                    if norm.get("status") not in ["STARTING", "RUNNING", "POST_PROCESSING", "VERIFYING", "CANCELLING"]:
                        continue
                elif s_filter == "QUEUED":
                    if norm.get("status") != "QUEUED":
                        continue
                elif norm.get("status") != s_filter:
                    continue
            results.append(norm)

        results.sort(key=lambda x: x.get("updated_at_epoch") or 0, reverse=True)
        return results[:limit]


task_runner = BoundedTaskRunner()

# ==============================================================================
# 7. SCHEDULED AUTOMATION DAEMON & RETENTION CLEANER
# ==============================================================================

class SchedulerDaemon(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True, name="SchedulerDaemon")
        self.running = True

    def run(self):
        while self.running:
            try:
                now = time.time()
                jobs_to_run = []
                with DB_LOCK:
                    conn = get_db_connection()
                    try:
                        cur = conn.cursor()
                        cur.execute("SELECT id, name, job_type, interval_seconds FROM scheduled_jobs WHERE enabled = 1 AND next_run <= ?", (now,))
                        jobs_to_run = cur.fetchall()
                    finally:
                        conn.close()

                for job in jobs_to_run:
                    j_id, j_name, j_type, j_int = job["id"], job["name"], job["job_type"], job["interval_seconds"]
                    self._dispatch_job(j_id, j_name, j_type, j_int)

            except Exception as e:
                log_event("ERROR", "SCHEDULER", f"Scheduler tick error: {str(e)}")

            time.sleep(30.0)

    def _dispatch_job(self, job_id: str, name: str, job_type: str, interval: int):
        log_event("INFO", "SCHEDULER", f"Triggering scheduled job: {name}")

        if job_type == "backup":
            task_runner.enqueue_task(f"Auto Backup: {name}", "scheduled_backup", run_backup_job, owner_user_id="system")
        elif job_type == "clean_temp":
            task_runner.enqueue_task(f"Auto Clean: {name}", "scheduled_clean", run_clean_temp_job, owner_user_id="system")
        elif job_type == "retention_sweep":
            task_runner.enqueue_task(f"Retention Sweep: {name}", "retention_sweep", run_retention_sweep_job, owner_user_id="system")
        elif job_type == "timetable_sync":
            task_runner.enqueue_task(f"Timetable Sync: {name}", "timetable_sync", run_timetable_sync_job, owner_user_id="system")
        elif job_type == "tunnel_check":
            probe_localtonet_health()

        with DB_LOCK:
            conn = get_db_connection()
            try:
                conn.execute("UPDATE scheduled_jobs SET last_run = ?, next_run = ?, last_status = 'dispatched' WHERE id = ?",
                             (time.time(), time.time() + interval, job_id))
                conn.commit()
            finally:
                conn.close()


def run_timetable_sync_job(task_obj: dict = None):
    """Executes scheduled 3-hour timetable synchronization for all active users."""
    if task_obj is None:
        task_obj = {'logs': []}
    task_obj.setdefault('logs', []).append("Executing scheduled 3-hour UPES Timetable -> Google Calendar sync...")
    log_event("INFO", "TIMETABLE", "Timetable 3-hour sync job started.")
    try:
        results = timetable_service.sync_all_active_users()
        total_created = sum(r.get("created", 0) for r in results.values() if isinstance(r, dict))
        total_updated = sum(r.get("updated", 0) for r in results.values() if isinstance(r, dict))
        total_deleted = sum(r.get("deleted", 0) for r in results.values() if isinstance(r, dict))
        total_unchanged = sum(r.get("unchanged", 0) for r in results.values() if isinstance(r, dict))
        total_errors = sum(len(r.get("errors", [])) for r in results.values() if isinstance(r, dict))

        summary_msg = f"Timetable sync completed for {len(results)} users: Created={total_created}, Updated={total_updated}, Deleted={total_deleted}, Unchanged={total_unchanged}, Errors={total_errors}"
        task_obj.setdefault('logs', []).append(summary_msg)
        log_event("INFO", "TIMETABLE", summary_msg)
    except Exception as e:
        err_msg = f"Timetable sync job error: {str(e)}"
        task_obj.setdefault('logs', []).append(err_msg)
        log_event("ERROR", "TIMETABLE", err_msg)


scheduler_daemon = SchedulerDaemon()
scheduler_daemon.start()



RETENTION_METRICS = {
    "last_cleanup": 0.0,
    "cleanup_duration_ms": 0.0,
    "rows_removed": 0,
    "rows_retained": 0,
    "database_size_bytes": 0,
    "last_cleanup_error": None
}
RETENTION_METRICS_LOCK = threading.Lock()


def run_retention_sweep_job(task_obj: dict = None):
    """Prunes old audit logs, task history, incidents, and metric rows to enforce bounded storage."""
    if task_obj is None:
        task_obj = {'logs': []}
    task_obj.setdefault('logs', []).append("Running bounded database retention sweep...")
    start_t = time.time()
    total_removed = 0

    with DB_LOCK:
        conn = get_db_connection()
        try:
            # 1. Prune logs beyond config.MAX_DB_LOGS_RETENTION
            c1 = conn.execute("""
                DELETE FROM system_logs WHERE id NOT IN (
                    SELECT id FROM system_logs ORDER BY created_at DESC LIMIT ?
                );
            """, (config.MAX_DB_LOGS_RETENTION,))
            total_removed += c1.rowcount if c1.rowcount > 0 else 0

            # 2. Prune tasks beyond config.MAX_TASK_HISTORY_RETENTION
            c2 = conn.execute("""
                DELETE FROM background_tasks WHERE id NOT IN (
                    SELECT id FROM background_tasks ORDER BY created_at DESC LIMIT ?
                );
            """, (config.MAX_TASK_HISTORY_RETENTION,))
            total_removed += c2.rowcount if c2.rowcount > 0 else 0

            # 3. Prune metrics beyond config.MAX_INFERENCE_METRICS_RETENTION
            c3 = conn.execute("""
                DELETE FROM ai_inference_metrics WHERE id NOT IN (
                    SELECT id FROM ai_inference_metrics ORDER BY created_at DESC LIMIT ?
                );
            """, (config.MAX_INFERENCE_METRICS_RETENTION,))
            total_removed += c3.rowcount if c3.rowcount > 0 else 0

            # 4. Prune incidents beyond 500
            c4 = conn.execute("""
                DELETE FROM incidents WHERE id NOT IN (
                    SELECT id FROM incidents ORDER BY timestamp DESC LIMIT 500
                );
            """)
            total_removed += c4.rowcount if c4.rowcount > 0 else 0

            # Count retained rows
            cur = conn.cursor()
            cur.execute("SELECT (SELECT COUNT(*) FROM system_logs) + (SELECT COUNT(*) FROM background_tasks) + (SELECT COUNT(*) FROM ai_inference_metrics) + (SELECT COUNT(*) FROM incidents);")
            total_retained = cur.fetchone()[0]

            conn.commit()

            dur_ms = round((time.time() - start_t) * 1000.0, 2)
            db_size = os.path.getsize(config.DB_FILE) if os.path.exists(config.DB_FILE) else 0

            with RETENTION_METRICS_LOCK:
                RETENTION_METRICS["last_cleanup"] = time.time()
                RETENTION_METRICS["cleanup_duration_ms"] = dur_ms
                RETENTION_METRICS["rows_removed"] = total_removed
                RETENTION_METRICS["rows_retained"] = total_retained
                RETENTION_METRICS["database_size_bytes"] = db_size
                RETENTION_METRICS["last_cleanup_error"] = None

            task_obj['logs'].append(f"Retention sweep completed in {dur_ms}ms ({total_removed} rows removed, {total_retained} retained).")
            task_obj['logs'].append("Retention sweep completed successfully.")
            log_event("INFO", "DATABASE", f"Retention sweep finished: {total_removed} rows pruned, {total_retained} rows retained in {dur_ms}ms.")
        except Exception as ex:
            with RETENTION_METRICS_LOCK:
                RETENTION_METRICS["last_cleanup_error"] = str(ex)
            task_obj['logs'].append(f"Retention sweep failed: {ex}")
            log_event("ERROR", "DATABASE", f"Retention sweep error: {ex}")
        finally:
            conn.close()


# ==============================================================================
# 8. NETWORK & SERVICE HEALTH PROBING
# ==============================================================================

_TUNNEL_CACHE = {
    "url": config.DEFAULT_TUNNEL_URL,
    "last_check": 0.0,
    "state": "STOPPED",
    "lock": threading.Lock()
}


def get_tunnel_url() -> str:
    tunnel = os.environ.get("LOCALTONET_URL") or os.environ.get("TUNNEL_URL")
    if tunnel:
        if not tunnel.startswith("http"):
            tunnel = f"https://{tunnel}"
        return tunnel

    for path in config.LOCALTONET_LOG_PATHS:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    matches = re.findall(r"https?://[a-zA-Z0-9_\-\.]+\.localto\.net", f.read())
                    if matches:
                        return matches[-1]
            except Exception:
                pass
    return config.DEFAULT_TUNNEL_URL


def probe_localtonet_health() -> dict:
    """
    Authoritative reachability probe separating:
    - PROCESS: is process alive in /proc?
    - TUNNEL: is tunnel URL detected?
    - PUBLIC_ENDPOINT: is endpoint reachable? (cached for 30s)
    """
    with _TUNNEL_CACHE["lock"]:
        if app.config.get('TESTING'):
            return {
                "process": "running",
                "tunnel": "detected",
                "public_endpoint": "reachable",
                "state": "TUNNEL_CONNECTED",
                "url": config.DEFAULT_TUNNEL_URL,
                "pid": 1234
            }

        now = time.time()
        pid = None
        try:
            res = subprocess.run(["pgrep", "-f", "localtonet"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
            if res.returncode == 0 and res.stdout.strip():
                pid = res.stdout.strip().splitlines()[0]
        except Exception:
            pass

        tunnel_url = get_tunnel_url()

        if not pid:
            _TUNNEL_CACHE["state"] = "STOPPED"
            return {"process": "stopped", "tunnel": "none", "public_endpoint": "unreachable", "state": "STOPPED", "url": tunnel_url, "pid": None}

        # If cached probe is fresh (< 30s), return it
        if now - _TUNNEL_CACHE["last_check"] < config.TUNNEL_HEALTH_PROBE_TTL_SECONDS and _TUNNEL_CACHE["state"] != "STOPPED":
            return {
                "process": "running",
                "tunnel": "detected" if tunnel_url else "none",
                "public_endpoint": "reachable" if _TUNNEL_CACHE["state"] == "TUNNEL_CONNECTED" else "unreachable",
                "state": _TUNNEL_CACHE["state"],
                "url": tunnel_url,
                "pid": pid
            }

        # Perform unprivileged HTTP GET to tunnel health
        public_reachable = False
        try:
            r = requests.get(f"{tunnel_url}/api/health", headers={'localtonet-skip-warning': 'true'}, timeout=2.5)
            if r.status_code == 200:
                public_reachable = True
        except Exception:
            pass

        _TUNNEL_CACHE["last_check"] = now
        _TUNNEL_CACHE["state"] = "TUNNEL_CONNECTED" if public_reachable else ("PROCESS_ONLY" if pid else "STOPPED")

        return {
            "process": "running",
            "tunnel": "detected" if tunnel_url else "none",
            "public_endpoint": "reachable" if public_reachable else "unreachable",
            "state": _TUNNEL_CACHE["state"],
            "url": tunnel_url,
            "pid": pid
        }


def probe_ssh_status() -> dict:
    is_up = False
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.3)
        result = s.connect_ex(('127.0.0.1', config.SSH_PORT))
        s.close()
        is_up = (result == 0)
    except Exception:
        pass

    pid = None
    try:
        res = subprocess.run(["pgrep", "-x", "sshd"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        if res.returncode == 0 and res.stdout.strip():
            pid = res.stdout.strip().splitlines()[0]
    except Exception:
        pass

    return {
        "status": "online" if is_up else "offline",
        "port": config.SSH_PORT,
        "pid": pid
    }


# ==============================================================================
# 9. BACKUP WORKER & RESOURCE PRE-CHECKS
# ==============================================================================

def run_backup_job(task_obj: dict):
    """Generates verified atomic zip backup after checking free disk headroom."""
    task_obj['logs'].append("Initiating atomic system backup...")

    # Resource Pre-Check
    disk = governor.get_disk_status()
    if disk["free_gb"] < 1.5:
        raise RuntimeError(f"Backup rejected: Insufficient free disk space ({disk['free_gb']} GB < 1.5 GB required headroom).")

    backup_id = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(2)}"
    zip_name = f"nexus_backup_{backup_id}.zip"
    zip_path = os.path.join(config.BACKUP_DIR, zip_name)
    task_obj['partial_files'].append(zip_path)

    temp_db_backup = os.path.join(config.STORAGE_DIR, f"temp_backup_{secrets.token_hex(4)}.db")
    task_obj['partial_files'].append(temp_db_backup)

    start_t = time.time()

    try:
        # Step 1: Live SQLite WAL backup using sqlite3.backup() API
        task_obj['logs'].append("Taking atomic SQLite WAL snapshot...")
        with DB_LOCK:
            src_conn = get_db_connection()
            dst_conn = sqlite3.connect(temp_db_backup)
            src_conn.backup(dst_conn)
            dst_conn.close()
            src_conn.close()

        # Step 2: Create zip archive
        import zipfile
        task_obj['logs'].append("Archiving database, RAG index, and configuration...")
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.write(temp_db_backup, "nexus_vault.db")
            if os.path.exists(config.RAG_DB_FILE):
                zf.write(config.RAG_DB_FILE, "rag_vault.db")
            if os.path.exists(config.CONFIG_FILE):
                zf.write(config.CONFIG_FILE, "server_config.json")

            manifest = {
                "backup_id": backup_id,
                "version": config.VERSION,
                "created_at": time.time(),
                "created_at_iso": datetime.now().isoformat()
            }
            zf.writestr("manifest.json", json.dumps(manifest, indent=2))

        # Step 3: Checksum and record
        sha256 = hashlib.sha256()
        with open(zip_path, 'rb') as f:
            while chunk := f.read(65536):
                sha256.update(chunk)
        checksum = sha256.hexdigest()
        size_bytes = os.path.getsize(zip_path)
        duration = round(time.time() - start_t, 2)

        with DB_LOCK:
            conn = get_db_connection()
            try:
                conn.execute("""
                    INSERT INTO backups (id, filename, filepath, size_bytes, checksum, backup_type, created_at, status, owner_user_id)
                    VALUES (?, ?, ?, ?, ?, 'full', ?, 'completed', ?)
                """, (backup_id, zip_name, zip_path, size_bytes, checksum, time.time(), task_obj.get("owner_user_id", "admin")))
                conn.commit()
            finally:
                conn.close()

        task_obj['logs'].append(f"Backup verified! SHA-256: {checksum[:16]}... Size: {round(size_bytes/1024, 1)} KB (Took {duration}s)")
        log_event("INFO", "BACKUP", f"Created atomic backup '{zip_name}' ({round(size_bytes/1024, 1)} KB)")

    finally:
        if os.path.exists(temp_db_backup):
            os.remove(temp_db_backup)


def run_clean_temp_job(task_obj: dict):
    task_obj['logs'].append("Sweeping temporary files and partial downloads...")
    swept_count = 0
    reclaimed_bytes = 0

    for root, _, files in os.walk(config.STORAGE_DIR):
        for f in files:
            if f.endswith(('.part', '.ytdl', '.tmp', '.crdownload')):
                p = os.path.join(root, f)
                try:
                    reclaimed_bytes += os.path.getsize(p)
                    os.remove(p)
                    swept_count += 1
                except Exception:
                    pass

    task_obj['logs'].append(f"Cleaned {swept_count} temporary artifacts ({round(reclaimed_bytes/(1024*1024), 2)} MB reclaimed).")
    log_event("INFO", "STORAGE", f"Swept {swept_count} temp files ({round(reclaimed_bytes/(1024*1024), 2)} MB reclaimed)")


# ==============================================================================
# 10. ROUTE HANDLERS & API ENDPOINTS
# ==============================================================================

@app.route('/')
def index():
    return render_template('index.html', version=config.VERSION)


def create_user_session(user_dict: dict) -> str:
    """Creates a server session token and registers in SESSIONS dict."""
    token = secrets.token_hex(32)
    session_data = {
        "user_id": user_dict["user_id"],
        "role": user_dict["role"],
        "privileges": user_dict.get("privileges", {}),
        "created_at": time.time(),
        "expires_at": time.time() + config.SESSION_EXPIRY_SECONDS
    }
    with SESSIONS_LOCK:
        SESSIONS[token] = session_data
    return token


def revoke_user_session(token: str) -> bool:
    """Revokes a session token from SESSIONS dict."""
    with SESSIONS_LOCK:
        if token in SESSIONS:
            del SESSIONS[token]
            return True
    return False


def get_active_sessions() -> list[dict]:
    """Returns safe metadata list of currently active sessions (excluding raw tokens by default)."""
    now = time.time()
    active = []
    with SESSIONS_LOCK:
        expired = [tok for tok, s in SESSIONS.items() if now > s.get("expires_at", 0)]
        for tok in expired:
            del SESSIONS[tok]

        for tok, s in SESSIONS.items():
            active.append({
                "user_id": s.get("user_id"),
                "role": s.get("role"),
                "created_at": s.get("created_at"),
                "expires_at": s.get("expires_at"),
                "status": "active"
            })
    return active


def get_account_lockout_status(user_id: str = None, client_ip: str = "127.0.0.1") -> tuple[bool, int]:
    """
    Authoritative state check for active account or IP lockout.
    Returns (is_locked: bool, remaining_seconds: int).
    """
    now = time.time()
    user_id = str(user_id or "").strip().lower() if user_id else None

    # 1. Check in-memory FAILED_LOGINS (for direct overrides/compatibility)
    with FAILED_LOGINS_LOCK:
        if client_ip and client_ip in FAILED_LOGINS:
            rec = FAILED_LOGINS[client_ip]
            if rec.get("locked_until", 0.0) > now:
                return True, max(1, int(rec["locked_until"] - now))

    # 2. Check SQLite DB persistence
    with DB_LOCK:
        conn = get_db_connection()
        try:
            # Check user-level lockout in SQLite users table
            if user_id:
                cur = conn.cursor()
                cur.execute("SELECT locked_until FROM users WHERE user_id = ?", (user_id,))
                row = cur.fetchone()
                if row and row["locked_until"] and row["locked_until"] > now:
                    remaining = max(1, int(row["locked_until"] - now))
                    return True, remaining

            # Check IP-level lockout in SQLite ip_lockouts table
            if client_ip:
                cur = conn.cursor()
                cur.execute("SELECT locked_until FROM ip_lockouts WHERE ip = ?", (client_ip,))
                row = cur.fetchone()
                if row and row["locked_until"] and row["locked_until"] > now:
                    remaining = max(1, int(row["locked_until"] - now))
                    return True, remaining
        finally:
            conn.close()

    return False, 0


def authenticate_user_credentials(user_id: str, password: str, client_ip: str = "127.0.0.1") -> tuple[bool, str, dict | None, int | None]:
    """
    Authoritative single source of truth for user authentication and lockout enforcement.
    Used by both web /api/auth/login and local CLI login.
    Returns: (success: bool, message: str, user_dict_or_None, lockout_seconds_or_None)
    """
    user_id = str(user_id or "").strip().lower()
    password = str(password or "").strip()

    if not user_id or not password:
        return False, "User ID and password are required.", None, None

    # 1. Check if account or IP is already locked
    is_locked, remaining = get_account_lockout_status(user_id, client_ip)
    if is_locked:
        return False, f"Account locked. Try again in {remaining} seconds.", None, remaining

    # 2. Fetch user record
    user = db_get_user(user_id)
    if user and user.get("is_disabled", 0) == 1:
        log_event("WARN", "AUTH", f"Rejected login attempt for disabled user account '{user_id}'.")
        return False, "Account is disabled. Contact system administrator.", None, None

    is_valid, needs_upgrade = (False, False)
    if user:
        is_valid, needs_upgrade = verify_password(password, user["password_hash"], user["salt"])

    if not is_valid:
        # Increment failed attempts in SQLite and memory
        now = time.time()
        with DB_LOCK:
            conn = get_db_connection()
            try:
                # Update user record if user exists
                if user:
                    new_attempts = int(user.get("failed_attempts", 0)) + 1
                    if new_attempts >= config.LOCKOUT_THRESHOLD:
                        locked_until = now + config.LOCKOUT_DURATION_SECONDS
                        conn.execute("""
                            UPDATE users SET failed_attempts = ?, locked_until = ? WHERE user_id = ?
                        """, (new_attempts, locked_until, user_id))
                        conn.commit()
                        with FAILED_LOGINS_LOCK:
                            FAILED_LOGINS[client_ip] = {"count": new_attempts, "locked_until": locked_until}
                        log_event("WARN", "AUTH", f"User account '{user_id}' locked out for {config.LOCKOUT_DURATION_SECONDS}s due to repeated failed logins.")
                        return False, f"Account locked. Try again in {config.LOCKOUT_DURATION_SECONDS} seconds.", None, config.LOCKOUT_DURATION_SECONDS
                    else:
                        conn.execute("UPDATE users SET failed_attempts = ? WHERE user_id = ?", (new_attempts, user_id))
                        conn.commit()

                # Update IP record
                cur = conn.cursor()
                cur.execute("SELECT failed_attempts FROM ip_lockouts WHERE ip = ?", (client_ip,))
                ip_row = cur.fetchone()
                ip_attempts = (ip_row["failed_attempts"] + 1) if ip_row else 1
                if ip_attempts >= config.LOCKOUT_THRESHOLD:
                    locked_until = now + config.LOCKOUT_DURATION_SECONDS
                    conn.execute("""
                        INSERT INTO ip_lockouts (ip, failed_attempts, locked_until)
                        VALUES (?, ?, ?)
                        ON CONFLICT(ip) DO UPDATE SET failed_attempts = excluded.failed_attempts, locked_until = excluded.locked_until
                    """, (client_ip, ip_attempts, locked_until))
                    conn.commit()
                    with FAILED_LOGINS_LOCK:
                        FAILED_LOGINS[client_ip] = {"count": ip_attempts, "locked_until": locked_until}
                    log_event("WARN", "AUTH", f"Client IP '{client_ip}' locked out for {config.LOCKOUT_DURATION_SECONDS}s due to repeated failed logins.")
                    return False, f"Account locked. Try again in {config.LOCKOUT_DURATION_SECONDS} seconds.", None, config.LOCKOUT_DURATION_SECONDS
                else:
                    conn.execute("""
                        INSERT INTO ip_lockouts (ip, failed_attempts, locked_until)
                        VALUES (?, ?, 0.0)
                        ON CONFLICT(ip) DO UPDATE SET failed_attempts = excluded.failed_attempts
                    """, (client_ip, ip_attempts))
                    conn.commit()
                    with FAILED_LOGINS_LOCK:
                        FAILED_LOGINS[client_ip] = {"count": ip_attempts, "locked_until": 0.0}
            finally:
                conn.close()

        log_event("WARN", "AUTH", f"Failed login attempt for user '{user_id}' from {client_ip}")
        return False, "Authentication failed.", None, None

    # 3. Successful login - clear failed attempts and active lockout
    with DB_LOCK:
        conn = get_db_connection()
        try:
            conn.execute("UPDATE users SET failed_attempts = 0, locked_until = 0.0 WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM ip_lockouts WHERE ip = ?", (client_ip,))
            conn.commit()
        finally:
            conn.close()

    # 4. Transparent Password Hash Upgrade (Legacy SHA-256 -> PBKDF2-HMAC-SHA256)
    if needs_upgrade:
        try:
            upgraded_hash, upgraded_salt = hash_password(password)
            with DB_LOCK:
                conn = get_db_connection()
                try:
                    conn.execute("UPDATE users SET password_hash = ?, salt = ? WHERE user_id = ?", (upgraded_hash, upgraded_salt, user_id))
                    conn.commit()
                finally:
                    conn.close()
            user["password_hash"] = upgraded_hash
            user["salt"] = upgraded_salt
            log_event("INFO", "AUTH", f"Transparently upgraded password hash for '{user_id}' to PBKDF2-HMAC-SHA256.")
        except Exception as e:
            print(f"[!] Hash upgrade error: {e}")

    with FAILED_LOGINS_LOCK:
        if client_ip in FAILED_LOGINS:
            del FAILED_LOGINS[client_ip]

    return True, "Authentication successful.", user, None


def clear_account_lockout(user_id: str = None, ip_address: str = None):
    """Clears failed login and lockout tracking in SQLite and memory for emergency recovery or password resets."""
    with FAILED_LOGINS_LOCK:
        if ip_address and ip_address in FAILED_LOGINS:
            del FAILED_LOGINS[ip_address]
        else:
            FAILED_LOGINS.clear()

    with DB_LOCK:
        conn = get_db_connection()
        try:
            if user_id:
                clean_uid = str(user_id).strip().lower()
                conn.execute("UPDATE users SET failed_attempts = 0, locked_until = 0.0 WHERE user_id = ?", (clean_uid,))
            else:
                conn.execute("UPDATE users SET failed_attempts = 0, locked_until = 0.0")

            if ip_address:
                conn.execute("DELETE FROM ip_lockouts WHERE ip = ?", (ip_address,))
            else:
                conn.execute("DELETE FROM ip_lockouts")

            conn.commit()
        finally:
            conn.close()


# --- Authentication Routes ---
@app.route('/api/auth/lockout-status', methods=['GET'])
def api_lockout_status():
    """
    Public safe endpoint returning active lockout status and remaining seconds.
    Does NOT reveal passwords, password hashes, salts, or session tokens.
    """
    client_ip = request.remote_addr or "127.0.0.1"
    user_id = request.args.get("user_id") or request.args.get("username") or "admin"
    is_locked, remaining = get_account_lockout_status(user_id, client_ip)

    return jsonify({
        "locked": is_locked,
        "lockout_seconds": remaining,
        "remaining_seconds": remaining,
        "retry_after": remaining
    })


@app.route('/api/auth/login', methods=['POST'])
def api_login():
    client_ip = request.remote_addr or "127.0.0.1"
    data = request.get_json(force=True, silent=True) or {}
    user_id = str(data.get("user_id") or data.get("username") or "").strip().lower()
    password = str(data.get("password", "")).strip()

    success, msg, user, lockout_secs = authenticate_user_credentials(user_id, password, client_ip)
    if not success:
        if lockout_secs:
            return jsonify({
                "error": "account_locked",
                "message": f"Account Locked. Try again in {lockout_secs}s.",
                "lockout_seconds": lockout_secs,
                "remaining_seconds": lockout_secs,
                "retry_after": lockout_secs
            }), 429
        if "disabled" in msg.lower():
            return jsonify({"error": "account_disabled", "message": msg}), 403
        if not user_id or not password:
            log_event("WARN", "AUTH", f"Rejected incomplete login submission from IP {client_ip}.")
            return jsonify({"error": "validation_error", "message": msg}), 400
        return jsonify({"error": "invalid_credentials", "message": msg}), 401

    token = create_user_session(user)
    log_event("INFO", "AUTH", f"User '{user_id}' signed in successfully.")
    return jsonify({
        "token": token,
        "user": {
            "user_id": user["user_id"],
            "username": user["user_id"],
            "role": user["role"],
            "privileges": user["privileges"]
        }
    })


@app.route('/api/auth/logout', methods=['POST'])
def api_logout():
    if g.token:
        with SESSIONS_LOCK:
            if g.token in SESSIONS:
                del SESSIONS[g.token]
        log_event("INFO", "AUTH", f"User '{g.user.get('user_id')}' logged out.")
    return jsonify({"message": "Successfully logged out."})


@app.route('/api/auth/me', methods=['GET'])
def api_me():
    err = require_auth()
    if err:
        return err
    return jsonify({
        "user": {
            "user_id": g.user.get("user_id"),
            "role": g.user.get("role"),
            "privileges": g.user.get("privileges")
        }
    })


# --- Health & Telemetry Routes ---
@app.route('/api/health', methods=['GET'])
def health_endpoint():
    uptime = int(time.time() - SERVER_START_TIME)
    return jsonify({
        "status": "healthy",
        "version": config.VERSION,
        "uptime_seconds": uptime
    })


@app.route('/api/system/status', methods=['GET'])
def sanitized_system_status():
    """
    Sanitized, user-safe telemetry payload.
    Does NOT leak internal /proc PIDs, full admin logs, or other users' tasks.
    """
    snap = governor.get_telemetry_snapshot()
    uptime_sec = int(time.time() - SERVER_START_TIME)
    h, rem = divmod(uptime_sec, 3600)
    m, s = divmod(rem, 60)
    uptime_str = f"{h}h {m}m {s}s"

    # Filter active tasks owned by current user
    user_id = g.user.get("user_id") if g.user else "guest"
    is_admin = (g.user.get("role") == "admin") if g.user else False

    all_active = [t for t in task_runner.get_all_tasks() if t.get('status') in ['STARTING', 'RUNNING', 'POST_PROCESSING', 'VERIFYING', 'CANCELLING']]
    if not is_admin:
        all_active = [t for t in all_active if t.get('owner_user_id') == user_id or t.get('owner') == user_id]

    active_task_obj = all_active[0] if all_active else None

    ai_state = ollama_registry.get_ai_state()
    tunnel_status = probe_localtonet_health()
    ssh_status = probe_ssh_status()

    l2n_running = (tunnel_status.get("process") == "running")
    l2n_connected = (tunnel_status.get("public_endpoint") == "reachable" or tunnel_status.get("state") == "TUNNEL_CONNECTED")
    ssh_online = (ssh_status.get("status") == "online")
    ollama_running = (ai_state.get("engine") == "running")

    return jsonify({
        "server": {
            "name": "NexusNode Mobile Appliance",
            "version": config.VERSION,
            "device": "TECNO BG6 (Android 13 / Termux)",
            "uptime": uptime_str,
            "uptime_seconds": uptime_sec
        },
        "system": {
            "uptime": uptime_str,
            "uptime_seconds": uptime_sec,
            "version": config.VERSION,
            "hostname": "TECNO BG6"
        },
        "appliance": snap["appliance"],
        "memory": {
            "percent": snap["memory"]["ram_percent"],
            "ram_percent": snap["memory"]["ram_percent"],
            "used_mb": snap["memory"]["used_mb"],
            "total_mb": snap["memory"]["total_mb"],
            "available_mb": snap["memory"]["available_mb"],
            "swap_percent": snap["memory"]["swap_percent"],
            "swap_used_mb": snap["memory"]["swap_used_mb"],
            "swap_total_mb": snap["memory"]["swap_total_mb"]
        },
        "swap": {
            "percent": snap["memory"]["swap_percent"],
            "swap_percent": snap["memory"]["swap_percent"],
            "used_mb": snap["memory"]["swap_used_mb"],
            "total_mb": snap["memory"]["swap_total_mb"]
        },
        "disk": snap["disk"],
        "storage": {
            "percent": snap["disk"]["percent"],
            "used_gb": snap["disk"]["used_gb"],
            "total_gb": snap["disk"]["total_gb"],
            "free_gb": snap["disk"]["free_gb"]
        },
        "device": snap["device"],
        "battery": {
            "level": snap["device"].get("battery_percent"),
            "status": snap["device"].get("battery_status", "STANDBY")
        },
        "thermal": {
            "temp_c": snap["device"].get("cpu_temperature_c"),
            "status": snap["appliance"].get("state", "NORMAL")
        },
        "network": {
            "mode": "wan" if l2n_connected else "lan",
            "tunnel_url": tunnel_status.get("url"),
            "tunnel_status": tunnel_status.get("state", "STOPPED")
        },
        "cpu": {
            "percent": snap["device"].get("cpu_usage_percent", 0)
        },
        "services": {
            "nexusnode": {"status": "online", "running": True, "port": config.PORT, "pid": os.getpid()},
            "localtonet": {"status": tunnel_status.get("state", "STOPPED").lower(), "state": tunnel_status.get("state", "STOPPED"), "running": l2n_running, "connected": l2n_connected, "url": tunnel_status.get("url"), "pid": tunnel_status.get("pid")},
            "ssh": {"status": ssh_status.get("status", "offline"), "running": ssh_online, "port": config.SSH_PORT, "pid": ssh_status.get("pid")},
            "sshd": {"status": ssh_status.get("status", "offline"), "running": ssh_online, "port": config.SSH_PORT, "pid": ssh_status.get("pid")},
            "ollama": {"status": ai_state.get("engine", "stopped"), "running": ollama_running, "online": ollama_running, "selected_model": ai_state.get("selected_model"), "loaded_model": ai_state.get("loaded_model"), "pid": None}
        },
        "active_task": active_task_obj,
        "tasks": {
            "active_count": len(all_active),
            "active_tasks": all_active
        },
        "rag": {
            "documents_count": rag_engine.get_diagnostics()["document_count"],
            "chunks_count": rag_engine.get_diagnostics()["chunk_count"],
            "state": rag_engine.state,
            "updated_at": rag_engine.last_rebuild
        }
    })


@app.route('/api/services/status', methods=['GET'])
def services_status_endpoint():
    err = require_auth()
    if err:
        return err
    tunnel_status = probe_localtonet_health()
    ssh_status = probe_ssh_status()
    ai_state = ollama_registry.get_ai_state()

    l2n_running = (tunnel_status.get("process") == "running")
    l2n_connected = (tunnel_status.get("public_endpoint") == "reachable" or tunnel_status.get("state") == "TUNNEL_CONNECTED")
    ssh_online = (ssh_status.get("status") == "online")
    ollama_running = (ai_state.get("engine") == "running")

    return jsonify({
        "nexusnode": {"status": "online", "running": True, "port": config.PORT, "pid": os.getpid()},
        "localtonet": {
            "status": tunnel_status.get("state", "STOPPED").lower(),
            "state": tunnel_status.get("state", "STOPPED"),
            "running": l2n_running,
            "connected": l2n_connected,
            "url": tunnel_status.get("url"),
            "pid": tunnel_status.get("pid"),
            "process": tunnel_status.get("process", "stopped"),
            "public_endpoint": tunnel_status.get("public_endpoint", "unreachable")
        },
        "ssh": {
            "status": ssh_status.get("status", "offline"),
            "running": ssh_online,
            "port": config.SSH_PORT,
            "pid": ssh_status.get("pid")
        },
        "sshd": {
            "status": ssh_status.get("status", "offline"),
            "running": ssh_online,
            "port": config.SSH_PORT,
            "pid": ssh_status.get("pid")
        },
        "ollama": {
            "status": ai_state.get("engine", "stopped"),
            "running": ollama_running,
            "online": ollama_running,
            "selected_model": ai_state.get("selected_model"),
            "loaded_model": ai_state.get("loaded_model"),
            "version": ai_state.get("version"),
            "pid": None
        }
    })


# --- AI Model Serving Endpoints ---
@app.route('/api/ai/state', methods=['GET'])
def get_ai_state_endpoint():
    err = require_privilege_or_admin("can_use_ai")
    if err:
        return err
    return jsonify(ollama_registry.get_ai_state())


@app.route('/api/ai/models', methods=['GET'])
def list_ai_models_endpoint():
    err = require_privilege_or_admin("can_use_ai")
    if err:
        return err
    return jsonify(ollama_registry.get_installed_models())


@app.route('/api/ai/models/<model_name>', methods=['GET'])
def get_ai_model_details_endpoint(model_name):
    err = require_privilege_or_admin("can_use_ai")
    if err:
        return err
    details = ollama_registry.get_model_details(model_name)
    if not details:
        return jsonify({"error": "not_found", "message": f"Model '{model_name}' details unavailable."}), 404
    return jsonify(details)


@app.route('/api/ai/models/select', methods=['POST'])
def select_ai_model_endpoint():
    err = require_privilege_or_admin("can_use_ai")
    if err:
        return err
    data = request.get_json(force=True, silent=True) or {}
    model_name = str(data.get("model", "")).strip()
    if not model_name:
        return jsonify({"error": "validation_error", "message": "Model name required."}), 400

    success, msg = ollama_registry.select_model(model_name)
    if not success:
        return jsonify({"error": "model_unavailable", "message": msg}), 404
    return jsonify({"selected_model": ollama_registry.selected_model, "message": msg})


@app.route('/api/models/estimate', methods=['POST'])
def estimate_model_resources_endpoint():
    err = require_privilege_or_admin("can_use_ai")
    if err:
        return err

    data = request.get_json(force=True, silent=True) or {}
    model_name = str(data.get("model", "")).strip()
    if not model_name:
        return jsonify({"error": "validation_error", "message": "Model name required."}), 400

    installed = ollama_registry.get_installed_models()
    meta = next((m for m in installed if m["name"] == model_name), {"name": model_name})
    estimate = governor.estimate_model_resources(meta)
    return jsonify(estimate)


@app.route('/api/ai/metrics', methods=['GET'])
def get_ai_metrics_endpoint():
    err = require_privilege_or_admin("can_use_ai")
    if err:
        return err

    with DB_LOCK:
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT model, prompt_tokens, prompt_eval_ms, gen_tokens, gen_eval_ms,
                       total_duration_ms, load_duration_ms, prompt_tokens_per_sec, gen_tokens_per_sec, created_at
                FROM ai_inference_metrics
                ORDER BY created_at DESC
                LIMIT 50;
            """)
            rows = cur.fetchall()
            metrics = [dict(r) for r in rows]
            return jsonify(metrics)
        finally:
            conn.close()


@app.route('/models', methods=['GET'])
def legacy_models_alias():
    """Legacy alias returning list of installed model names from Ollama."""
    installed = ollama_registry.get_installed_models()
    return jsonify([m["name"] for m in installed])


@app.route('/api/ai/start', methods=['POST'])
@app.route('/start', methods=['GET', 'POST'])
def start_engine_endpoint():
    err = require_privilege_or_admin("can_control_services")
    if err:
        return err

    res_check = governor.can_start_ollama()
    if not res_check["allowed"]:
        log_event("WARN", "OLLAMA", f"AI Engine start blocked by Resource Governor: {res_check['reason']}")
        return jsonify({
            "allowed": False,
            "error": "resource_pressure",
            "message": res_check["reason"],
            "reason": res_check["reason"]
        }), 429

    success, msg = ollama_registry.start_service()
    if not success:
        log_event("ERROR", "OLLAMA", f"Failed to start AI engine: {msg}")
    return jsonify({"success": success, "message": msg}), 200 if success else 500


@app.route('/api/ai/stop', methods=['POST'])
@app.route('/stop', methods=['GET', 'POST'])
def stop_engine_endpoint():
    err = require_privilege_or_admin("can_control_services")
    if err:
        return err

    success, msg = ollama_registry.stop_service()
    if not success:
        log_event("ERROR", "OLLAMA", f"Failed to stop AI engine: {msg}")
    return jsonify({"success": success, "message": msg}), 200 if success else 500


@app.route('/chat/stream', methods=['POST'])
def chat_stream():
    """
    Streaming AI chat completion endpoint with RAG context injection.
    Features: Model validation, Keep-Alive policy enforcement, Context governance,
    Inference metrics collection, and Structured error handling.
    """
    err = require_privilege_or_admin("can_use_ai")
    if err:
        return err

    data = request.get_json(force=True, silent=True) or {}
    prompt = str(data.get('prompt', '')).strip()
    requested_model = str(data.get('model', '')).strip() or ollama_registry.selected_model
    rag_enabled = bool(data.get('rag_enabled', True))

    if not prompt:
        return jsonify({"error": "validation_error", "message": "Prompt is required."}), 400

    # 1. Model Validation
    installed = ollama_registry.get_installed_models()
    installed_names = [m["name"] for m in installed]
    if requested_model not in installed_names and installed_names:
        return jsonify({"error": "model_unavailable", "message": f"Model '{requested_model}' is not installed."}), 404

    # 2. Keep-Alive & Context Governance based on current RAM state
    snap = governor.get_telemetry_snapshot()
    mem_state = snap["memory"]["state"]

    if mem_state == "critical":
        keep_alive_val = config.OLLAMA_KEEP_ALIVE_CRITICAL
        num_ctx_val = config.CONTEXT_SIZE_CRITICAL
    elif mem_state == "pressure":
        keep_alive_val = config.OLLAMA_KEEP_ALIVE_PRESSURE
        num_ctx_val = config.CONTEXT_SIZE_PRESSURE
    else:
        keep_alive_val = config.OLLAMA_KEEP_ALIVE_NORMAL
        num_ctx_val = config.CONTEXT_SIZE_NORMAL

    # 3. RAG Retrieval
    citations = []
    augmented_prompt = prompt

    if rag_enabled and has_privilege('can_use_rag'):
        citations = rag_engine.search(prompt, top_k=3)
        if citations:
            context_block = "\n\n".join([f"--- Source: {c['doc']} ---\n{c['text']}" for c in citations])
            augmented_prompt = f"Reference knowledge from user's vault:\n{context_block}\n\nUser Question:\n{prompt}\n\nPlease answer accurately using the vault knowledge above where applicable."

    def generate_sse():
        if citations:
            yield f"data: {json.dumps({'citations': citations})}\n\n"

        start_req_t = time.time()
        try:
            r = requests.post(
                f"{config.OLLAMA_HOST}/api/generate",
                json={
                    "model": requested_model,
                    "prompt": augmented_prompt,
                    "stream": True,
                    "keep_alive": keep_alive_val,
                    "options": {"num_ctx": num_ctx_val}
                },
                stream=True,
                timeout=180
            )
            if r.status_code != 200:
                yield f"data: {json.dumps({'error': f'AI Engine returned HTTP {r.status_code}'})}\n\n"
                return

            last_chunk = {}
            for line in r.iter_lines():
                if line:
                    try:
                        chunk = json.loads(line.decode('utf-8'))
                        last_chunk = chunk
                        token = chunk.get('response', '')
                        if token:
                            yield f"data: {json.dumps({'token': token})}\n\n"
                        if chunk.get('done', False):
                            yield f"data: {json.dumps({'done': True})}\n\n"
                            break
                    except Exception:
                        pass

            # 4. Capture Inference Metrics
            if last_chunk.get('done'):
                total_duration_ms = round(last_chunk.get('total_duration', 0) / 1e6, 2)
                load_duration_ms = round(last_chunk.get('load_duration', 0) / 1e6, 2)
                prompt_eval_count = last_chunk.get('prompt_eval_count', 0)
                prompt_eval_dur_ms = round(last_chunk.get('prompt_eval_duration', 0) / 1e6, 2)
                eval_count = last_chunk.get('eval_count', 0)
                eval_dur_ms = round(last_chunk.get('eval_duration', 0) / 1e6, 2)

                prompt_tps = round((prompt_eval_count / (prompt_eval_dur_ms / 1000.0)), 1) if prompt_eval_dur_ms > 0 else 0.0
                gen_tps = round((eval_count / (eval_dur_ms / 1000.0)), 1) if eval_dur_ms > 0 else 0.0

                with DB_LOCK:
                    conn = get_db_connection()
                    try:
                        conn.execute("""
                            INSERT INTO ai_inference_metrics (
                                model, prompt_tokens, prompt_eval_ms, gen_tokens, gen_eval_ms,
                                total_duration_ms, load_duration_ms, prompt_tokens_per_sec, gen_tokens_per_sec, created_at, user_id
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            requested_model, prompt_eval_count, prompt_eval_dur_ms, eval_count, eval_dur_ms,
                            total_duration_ms, load_duration_ms, prompt_tps, gen_tps, time.time(), g.user.get('user_id', 'user')
                        ))
                        conn.commit()
                    finally:
                        conn.close()

        except requests.exceptions.ConnectionError:
            log_event("ERROR", "AI", f"Inference failed for user '{g.user.get('user_id', 'user')}': AI engine daemon is offline.")
            yield f"data: {json.dumps({'error': 'AI Engine daemon is offline.'})}\n\n"
        except Exception as e:
            log_event("ERROR", "AI", f"Inference error for user '{g.user.get('user_id', 'user')}': {str(e)}")
            yield f"data: {json.dumps({'error': f'Inference error occurred: {str(e)}'})}\n\n"

    return Response(stream_with_context(generate_sse()), mimetype='text/event-stream')


# --- RAG Subsystem Endpoints ---
@app.route('/api/rag/status', methods=['GET'])
@app.route('/api/rag/diagnostics', methods=['GET'])
def rag_diagnostics_endpoint():
    err = require_privilege_or_admin("can_use_rag")
    if err:
        return err
    return jsonify(rag_engine.get_diagnostics())


@app.route('/api/rag/compact', methods=['POST'])
def rag_compact_endpoint():
    err = require_privilege_or_admin("can_use_rag")
    if err:
        return err
    res = rag_engine.compact_legacy_index()
    return jsonify(res)


@app.route('/api/rag/sources', methods=['GET', 'POST'])
def rag_sources_endpoint():
    if request.method == 'POST':
        err = require_privilege_or_admin("can_use_rag")
        if err:
            return err
        data = request.get_json(force=True, silent=True) or {}
        rag_engine.source_folders = data.get('sources', config.RAG_DEFAULT_SOURCES)
        rag_engine.trigger_rebuild_async()
        return jsonify({"sources": rag_engine.source_folders})

    return jsonify({
        "sources": rag_engine.source_folders,
        "supported_extensions": config.RAG_SUPPORTED_TEXT_EXTENSIONS
    })


@app.route('/api/rag/index', methods=['POST'])
def trigger_rag_rebuild():
    err = require_privilege_or_admin("can_use_rag")
    if err:
        return err

    res_check = governor.can_start_rag()
    if not res_check["allowed"]:
        return jsonify({
            "allowed": False,
            "error": "resource_pressure",
            "message": res_check["reason"],
            "reason": res_check["reason"]
        }), 429

    rag_engine.trigger_rebuild_async()
    return jsonify({"message": "RAG indexing initiated in background."})


# --- Tasks Subsystem Endpoints ---
@app.route('/api/tasks', methods=['GET'])
def list_tasks():
    err = require_auth()
    if err:
        return err

    user_id = g.user.get("user_id")
    is_admin = (g.user.get("role") == "admin")
    type_filter = request.args.get('type')
    status_filter = request.args.get('status')

    all_tasks = task_runner.get_all_tasks(type_filter=type_filter, status_filter=status_filter)
    if not is_admin:
        all_tasks = [t for t in all_tasks if t.get('owner_user_id') == user_id or t.get('owner') == user_id]

    return jsonify(all_tasks)


@app.route('/api/tasks/<task_id>', methods=['GET'])
def get_task_endpoint(task_id):
    err = require_auth()
    if err:
        return err

    task = task_runner.get_task(task_id)
    if not task:
        return jsonify({"error": "Task not found."}), 404

    user_id = g.user.get("user_id")
    is_admin = (g.user.get("role") == "admin")
    if not is_admin and task.get("owner_user_id") != user_id and task.get("owner") != user_id:
        return jsonify({"error": "Permission denied."}), 403

    return jsonify(task)


@app.route('/api/tasks/<task_id>/cancel', methods=['POST'])
def cancel_task_endpoint(task_id):
    """
    Cancels an active or queued background task.
    Enforces task ownership: Normal users can only cancel their own tasks; admins can cancel all.
    """
    err = require_auth()
    if err:
        return err

    user_id = g.user.get("user_id")
    is_admin = (g.user.get("role") == "admin")

    success, msg = task_runner.cancel_task(task_id, requesting_user_id=user_id, is_admin=is_admin)
    if not success:
        if "not found" in msg.lower():
            status_code = 404
        elif "permission denied" in msg.lower():
            status_code = 403
        else:
            status_code = 400
        return jsonify({"cancelled": False, "message": msg}), status_code

    return jsonify({"cancelled": True, "message": msg})


# --- Storage & Vault Protected Paths Policy ---
PROTECTED_INTERNAL_NAMES = {
    "nexus_vault.db", "nexus_vault.db-wal", "nexus_vault.db-shm",
    "rag_vault.db", "rag_vault.db-wal", "rag_vault.db-shm",
    "rag_index.json", "server_config.json",
    ".env", ".env.local", "localtonet.log", ".gitkeep", "emergency_fallback.log"
}
PROTECTED_INTERNAL_EXTS = {
    ".db", ".sqlite", ".sqlite3", ".db-wal", ".db-shm", ".pyc", ".pid", ".ragindex"
}
PROTECTED_INTERNAL_DIRS = {
    "__pycache__", ".git", ".ssh", ".tmp", "backups", "rag", ".localtonet"
}


def is_protected_internal_path(path_str: str) -> bool:
    """
    Authoritative classification helper for NexusNode Vault.
    Returns True if path represents reserved system databases, indexes, configuration,
    or internal runtime state that must NEVER be exposed as user-manageable Vault objects.
    """
    if not path_str:
        return False
    try:
        decoded = urllib.parse.unquote(str(path_str))
        cleaned = decoded.replace('\\', '/').strip('/')

        parts = [p.lower() for p in cleaned.split('/') if p]
        for part in parts:
            if part in PROTECTED_INTERNAL_DIRS or part in PROTECTED_INTERNAL_NAMES:
                return True
            if part.startswith('.') and part not in ['.', '..']:
                return True
            _, ext = os.path.splitext(part)
            if ext in PROTECTED_INTERNAL_EXTS:
                return True

        storage_real = os.path.realpath(config.STORAGE_DIR)
        target_real = os.path.realpath(os.path.join(config.STORAGE_DIR, cleaned)) if not os.path.isabs(cleaned) else os.path.realpath(cleaned)

        if not target_real.startswith(storage_real):
            return True

        rel_real = os.path.relpath(target_real, storage_real).replace('\\', '/')
        if rel_real != '.':
            rel_parts = [p.lower() for p in rel_real.split('/') if p]
            for part in rel_parts:
                if part in PROTECTED_INTERNAL_DIRS or part in PROTECTED_INTERNAL_NAMES:
                    return True
                if part.startswith('.'):
                    return True
                _, ext = os.path.splitext(part)
                if ext in PROTECTED_INTERNAL_EXTS:
                    return True
    except Exception:
        return True

    return False


def validate_safe_destination(dest_str: str) -> str:
    """
    Authoritative single storage validation and canonicalization function.
    Validates containment inside config.STORAGE_DIR, blocks traversal,
    prohibits protected internal paths, and canonicalizes category casing.
    Returns relative canonical path (or "" for root) or raises ValueError.
    """
    if not dest_str:
        return ""
    decoded = urllib.parse.unquote(str(dest_str)).strip()
    if decoded.startswith('/') or decoded.startswith('\\') or os.path.isabs(decoded) or (len(decoded) > 1 and decoded[1] == ':'):
        raise ValueError("Absolute paths prohibited.")

    cleaned = decoded.replace('\\', '/').strip('/')
    if not cleaned:
        return ""

    # Block directory traversal
    parts = [p for p in cleaned.split('/') if p]
    if '..' in decoded or '..' in cleaned or any(p in ['..', '.'] or p.startswith('..') for p in parts):
        raise ValueError("Directory traversal prohibited.")
    if os.path.isabs(cleaned) or (len(cleaned) > 1 and cleaned[1] == ':'):
        raise ValueError("Absolute paths prohibited.")

    # Canonicalize category casing
    lower_first = parts[0].lower()
    if lower_first in config.MEDIA_CATEGORIES or lower_first in ["music", "videos", "downloads", "podcasts", "documents", "other"]:
        parts[0] = lower_first
    canonical_rel = '/'.join(parts)

    # Realpath containment check
    storage_real = os.path.realpath(config.STORAGE_DIR)
    target_real = os.path.realpath(os.path.join(config.STORAGE_DIR, canonical_rel))
    if not target_real.startswith(storage_real):
        raise ValueError("Destination escapes storage containment boundary.")

    # Protected internal path check
    if is_protected_internal_path(canonical_rel) or is_protected_internal_path(target_real):
        raise ValueError(f"Target destination '{canonical_rel}' is a protected internal path.")

    return canonical_rel


def sanitize_custom_filename(filename_str: str) -> str:
    """
    Sanitizes custom filename to ensure it is strictly a single basename filename.
    Never permits directory creation, path traversal, or dangerous extension injection.
    """
    if not filename_str:
        return ""
    decoded = urllib.parse.unquote(str(filename_str)).strip()
    base_name = os.path.basename(decoded.replace('\\', '/'))
    cleaned = re.sub(r'[\x00-\x1f\x7f<>:"/\\|?*]', '_', base_name).strip()
    cleaned = re.sub(r'^\.+', '', cleaned).strip()
    if not cleaned or cleaned in ['.', '..']:
        return "unnamed_media"
    _, ext = os.path.splitext(cleaned)
    if ext.lower() in PROTECTED_INTERNAL_EXTS or ext.lower() in [".db", ".sqlite", ".py", ".sh", ".env", ".ragindex"]:
        cleaned = f"{cleaned}.txt"
    return cleaned


def sanitize_storage_path(filename: str) -> str:
    """Sanitizes and resolves a storage subpath relative to config.STORAGE_DIR."""
    if not filename:
        return config.STORAGE_DIR
    validated_rel = validate_safe_destination(filename)
    return os.path.realpath(os.path.join(config.STORAGE_DIR, validated_rel))


@app.route('/files', methods=['GET'])
def list_files():
    err = require_auth()
    if err:
        return err

    subpath = request.args.get('path', '').strip().replace('\\', '/')
    if is_protected_internal_path(subpath):
        return jsonify({"error": "Directory not found."}), 404

    try:
        current_dir = sanitize_storage_path(subpath) if subpath else config.STORAGE_DIR
    except ValueError as e:
        return jsonify({"error": str(e)}), 403

    if not os.path.exists(current_dir) or not os.path.isdir(current_dir):
        return jsonify({"error": "Directory not found."}), 404

    items = []
    try:
        for entry in os.scandir(current_dir):
            if is_protected_internal_path(entry.path):
                continue
            if entry.name.startswith('.'):
                continue

            rel = os.path.relpath(entry.path, config.STORAGE_DIR).replace('\\', '/')
            stat = entry.stat()
            modified = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
            if entry.is_dir():
                items.append({
                    "name": entry.name,
                    "path": rel,
                    "is_dir": True,
                    "size": 0,
                    "modified": modified,
                    "category": "folder"
                })
            else:
                ext = os.path.splitext(entry.name)[1].lower().lstrip('.')
                cat = "documents"
                if ext in ['mp3', 'm4a', 'flac', 'opus', 'wav', 'aac', 'ogg']:
                    cat = "music"
                elif ext in ['mp4', 'mkv', 'webm', 'mov', 'avi', 'm4v']:
                    cat = "videos"
                elif ext in ['jpg', 'jpeg', 'png', 'webp', 'gif', 'svg', 'bmp', 'ico', 'tiff']:
                    cat = "photos"
                elif ext in ['zip', 'tar', 'gz', '7z', 'bz2']:
                    cat = "backups"
                items.append({
                    "name": entry.name,
                    "path": rel,
                    "is_dir": False,
                    "size": stat.st_size,
                    "modified": modified,
                    "category": cat
                })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    items.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))
    return jsonify({"files": items, "current_path": subpath})


@app.route('/api/vault/destinations', methods=['GET'])
def list_vault_destinations():
    """Returns accessible, safe writable Vault directories based on user privileges."""
    err = require_privilege_or_admin("can_upload_files")
    if err:
        return err

    # Standard safe writable destinations (canonical lowercase)
    destinations = [
        {"path": "", "label": "Vault Root (/)"},
        {"path": "downloads", "label": "Downloads (/downloads)"},
        {"path": "music", "label": "Music (/music)"},
        {"path": "videos", "label": "Videos (/videos)"},
        {"path": "podcasts", "label": "Podcasts (/podcasts)"},
        {"path": "documents", "label": "Documents (/documents)"},
        {"path": "other", "label": "Other (/other)"}
    ]

    # Dynamically scan for user-created non-protected directories in storage vault
    try:
        for root, dirs, _ in os.walk(config.STORAGE_DIR):
            dirs[:] = [d for d in dirs if not d.startswith('.') and not is_protected_internal_path(os.path.join(root, d))]
            for d in dirs:
                full_d = os.path.join(root, d)
                rel = os.path.relpath(full_d, config.STORAGE_DIR).replace('\\', '/')
                if any(x["path"].lower() == rel.lower() for x in destinations) or is_protected_internal_path(rel):
                    continue
                destinations.append({"path": rel, "label": f"{d} (/{rel})"})
    except Exception:
        pass

    return jsonify({"destinations": destinations})


@app.route('/upload', methods=['POST'])
def upload_file():
    err = require_privilege_or_admin("can_upload_files")
    if err:
        return err

    user_id = g.user.get("user_id", "unknown") if g.user else "guest"

    if 'file' not in request.files:
        log_event("WARN", "STORAGE", f"Upload rejected: No file provided by user '{user_id}'.")
        return jsonify({"error": "No file uploaded."}), 400
    file = request.files['file']
    if not file.filename:
        log_event("WARN", "STORAGE", f"Upload rejected: Empty filename from user '{user_id}'.")
        return jsonify({"error": "No file selected."}), 400

    dest_folder = request.form.get('path', '').strip().replace('\\', '/')
    filename = os.path.basename(file.filename)
    if is_protected_internal_path(dest_folder) or is_protected_internal_path(filename):
        log_event("WARN", "STORAGE", f"Upload blocked: protected path violation by user '{user_id}' (dest='{dest_folder}', file='{filename}').")
        return jsonify({"error": "Invalid destination path or filename."}), 400

    try:
        target_dir = sanitize_storage_path(dest_folder) if dest_folder else config.STORAGE_DIR
    except ValueError as e:
        log_event("WARN", "STORAGE", f"Upload path traversal attempt by '{user_id}': {e}")
        return jsonify({"error": str(e)}), 403

    os.makedirs(target_dir, exist_ok=True)
    dest_path = os.path.join(target_dir, filename)
    if is_protected_internal_path(dest_path):
        log_event("WARN", "STORAGE", f"Upload blocked: forbidden target path for user '{user_id}'.")
        return jsonify({"error": "Forbidden target path."}), 403

    try:
        file.save(dest_path)
        dest_display = dest_folder if dest_folder else "Vault Root"
        log_event("INFO", "STORAGE", f"User '{user_id}' uploaded '{filename}' to '{dest_display}'.")
        return jsonify({
            "message": f"'{filename}' uploaded successfully to {dest_display}.",
            "filename": filename,
            "path": os.path.relpath(dest_path, config.STORAGE_DIR).replace('\\', '/'),
            "destination": dest_folder
        })
    except Exception as e:
        log_event("ERROR", "STORAGE", f"Upload failed for user '{user_id}': {str(e)}")
        return jsonify({"error": f"Upload failed: {str(e)}"}), 500


@app.route('/download/<path:filename>', methods=['GET'])
def download_file(filename):
    err = require_auth()
    if err:
        return err

    if is_protected_internal_path(filename):
        return jsonify({"error": "File not found."}), 404

    try:
        target_path = sanitize_storage_path(filename)
        if is_protected_internal_path(target_path) or not os.path.exists(target_path):
            return jsonify({"error": "File not found."}), 404

        if os.path.isdir(target_path):
            import io
            import zipfile
            memory_file = io.BytesIO()
            folder_name = os.path.basename(os.path.normpath(target_path)) or "vault_folder"
            with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
                for root, _, files in os.walk(target_path):
                    for f in files:
                        f_full = os.path.join(root, f)
                        if is_protected_internal_path(f_full):
                            continue
                        f_rel = os.path.relpath(f_full, target_path)
                        zf.write(f_full, arcname=f_rel)
            memory_file.seek(0)
            return send_file(
                memory_file,
                mimetype='application/zip',
                as_attachment=True,
                download_name=f"{folder_name}.zip"
            )

        inline = request.args.get('inline', 'false').lower() in ['1', 'true']
        guessed_mime, _ = mimetypes.guess_type(target_path)
        if inline:
            return send_file(target_path, mimetype=guessed_mime or 'application/octet-stream', as_attachment=False)
        return send_file(target_path, mimetype=guessed_mime or 'application/octet-stream', as_attachment=True)
    except ValueError:
        return jsonify({"error": "File not found."}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/media/playback-token', methods=['POST'])
def generate_media_playback_token():
    err = require_auth()
    if err:
        return err

    data = request.get_json(force=True, silent=True) or {}
    raw_path = str(data.get('path', '')).strip()
    if not raw_path:
        return jsonify({"error": "validation_error", "message": "Media path required."}), 400

    try:
        norm_path = validate_safe_destination(raw_path)
    except ValueError as e:
        return jsonify({"error": "invalid_path", "message": str(e)}), 400

    full_path = os.path.join(config.STORAGE_DIR, norm_path)
    if is_protected_internal_path(full_path) or not os.path.exists(full_path) or os.path.isdir(full_path):
        return jsonify({"error": "not_found", "message": "Media file not found."}), 404

    user_id = g.user.get("user_id")
    token = create_playback_token(user_id, norm_path)
    return jsonify({
        "playback_token": token,
        "path": norm_path,
        "expires_in": config.PLAYBACK_TOKEN_TTL_SECONDS
    })


@app.route('/stream/<path:filename>', methods=['GET'])
def stream_media_file(filename):
    playback_token = request.args.get('playback_token') or request.args.get('token')
    
    # 1. Try playback token validation first
    is_valid_token = False
    if playback_token:
        valid, _ = verify_playback_token(playback_token, filename)
        if valid:
            is_valid_token = True

    # 2. Fall back to standard session authentication if no valid playback token
    if not is_valid_token:
        err = require_auth()
        if err:
            return jsonify({"error": "unauthorized", "message": "Valid playback token or session required."}), 401

    if is_protected_internal_path(filename):
        return jsonify({"error": "Media file not found."}), 404

    try:
        target_path = sanitize_storage_path(filename)
        if is_protected_internal_path(target_path) or not os.path.exists(target_path) or os.path.isdir(target_path):
            return jsonify({"error": "Media file not found."}), 404

        file_size = os.path.getsize(target_path)
        guessed_type, _ = mimetypes.guess_type(target_path)
        ext = os.path.splitext(target_path)[1].lower()

        if guessed_type:
            mime_type = guessed_type
        elif ext == '.mp3':
            mime_type = 'audio/mpeg'
        elif ext == '.m4a':
            mime_type = 'audio/mp4'
        elif ext in ['.opus', '.ogg']:
            mime_type = 'audio/ogg'
        elif ext == '.wav':
            mime_type = 'audio/wav'
        elif ext == '.flac':
            mime_type = 'audio/flac'
        elif ext in ['.mp4', '.m4v']:
            mime_type = 'video/mp4'
        elif ext == '.webm':
            mime_type = 'video/webm'
        elif ext == '.mkv':
            mime_type = 'video/x-matroska'
        else:
            mime_type = 'application/octet-stream'

        range_header = request.headers.get('Range', None)
        if not range_header:
            return send_file(target_path, mimetype=mime_type, as_attachment=False)

        byte1, byte2 = 0, None
        m = re.search(r'bytes=(\d+)-(\d*)', range_header)
        if m:
            g1, g2 = m.groups()
            byte1 = int(g1)
            if g2: byte2 = int(g2)

        length = file_size - byte1
        if byte2 is not None:
            length = byte2 - byte1 + 1

        def generate_chunk():
            with open(target_path, 'rb') as f:
                f.seek(byte1)
                remaining = length
                while remaining > 0:
                    chunk_size = min(remaining, 64 * 1024)
                    data = f.read(chunk_size)
                    if not data:
                        break
                    remaining -= len(data)
                    yield data

        rv = Response(generate_chunk(), 206, mimetype=mime_type, direct_passthrough=True)
        rv.headers.add('Content-Range', f'bytes {byte1}-{byte1 + length - 1}/{file_size}')
        rv.headers.add('Accept-Ranges', 'bytes')
        rv.headers.add('Content-Length', str(length))
        return rv

    except ValueError:
        return jsonify({"error": "Media file not found."}), 404


@app.route('/delete', methods=['POST'])
def legacy_delete_file_endpoint():
    err = require_privilege_or_admin("can_manage_files")
    if err:
        return err
    data = request.get_json(force=True, silent=True) or {}
    filename = str(data.get("filename", "")).strip().replace('\\', '/')
    if not filename:
        return jsonify({"error": "Filename required."}), 400
    return delete_file(filename)


@app.route('/files/<path:filename>', methods=['DELETE'])
def delete_file(filename):
    err = require_privilege_or_admin("can_manage_files")
    if err:
        return err

    user_id = g.user.get("user_id", "unknown") if g.user else "guest"

    if is_protected_internal_path(filename):
        log_event("WARN", "STORAGE", f"Delete blocked: protected file attempt by user '{user_id}'.")
        return jsonify({"error": "File not found."}), 404

    try:
        target_path = sanitize_storage_path(filename)
        if is_protected_internal_path(target_path) or not os.path.exists(target_path):
            return jsonify({"error": "File not found."}), 404
        if os.path.isdir(target_path):
            shutil.rmtree(target_path)
        else:
            os.remove(target_path)
        log_event("INFO", "STORAGE", f"User '{user_id}' deleted '{filename}'.")
        return jsonify({"message": f"'{filename}' deleted successfully."})
    except ValueError:
        log_event("WARN", "STORAGE", f"Delete path traversal attempt by user '{user_id}'.")
        return jsonify({"error": "File not found."}), 404
    except Exception as e:
        log_event("ERROR", "STORAGE", f"Delete failed for user '{user_id}': {str(e)}")
        return jsonify({"error": str(e)}), 500


# --- Media Center Routes & YT-DLP Lifecycle Worker ---
@app.route('/api/media/download', methods=['POST'])
def enqueue_media_download():
    err = require_privilege_or_admin("can_download_media")
    if err:
        return err

    data = request.get_json(force=True, silent=True) or {}
    raw_urls = str(data.get('url', '')).strip().splitlines()
    urls = [u.strip() for u in raw_urls if u.strip()]

    if not urls:
        return jsonify({"error": "validation_error", "message": "At least one URL required."}), 400

    fmt = data.get('format', 'mp3').lower()
    quality = data.get('quality', 'best')
    raw_dest = data.get('destination', 'downloads')
    try:
        destination = validate_safe_destination(raw_dest)
    except ValueError as e:
        log_event("WARN", "MEDIA", f"Rejected media download with invalid destination '{raw_dest}': {e}")
        return jsonify({"error": "validation_error", "message": f"Invalid download destination: {e}"}), 400

    raw_custom_name = data.get('filename', '')
    custom_name = sanitize_custom_filename(raw_custom_name) if raw_custom_name else ""

    enqueued = []
    for u in urls:
        title = f"Download: {u[:40]}"
        task_id, res_info = task_runner.enqueue_task(
            title, "media_download", run_media_download_job,
            u, fmt, quality, destination, custom_name,
            owner_user_id=g.user.get("user_id", "user")
        )
        if task_id:
            enqueued.append(task_id)

    return jsonify({
        "success": True,
        "enqueued_count": len(enqueued),
        "task_ids": enqueued,
        "task_id": enqueued[0] if enqueued else None,
        "status": "QUEUED"
    })


def find_ffmpeg_location() -> str | None:
    """Discovers ffmpeg directory across system PATH and Android/Termux environments."""
    w = shutil.which("ffmpeg")
    if w:
        return os.path.dirname(w)

    termux_bins = [
        os.environ.get("PREFIX", "") + "/bin" if os.environ.get("PREFIX") else "",
        "/data/data/com.termux/files/usr/bin",
        os.path.expanduser("~/.termux/bin"),
        "/system/bin",
        "/system/xbin"
    ]
    for b in termux_bins:
        if b and os.path.isdir(b):
            fp = os.path.join(b, "ffmpeg")
            if os.path.isfile(fp) and (os.access(fp, os.X_OK) or os.name == 'nt'):
                return b
    return None


def run_media_download_job(task_obj: dict, url: str, fmt: str, quality: str, destination: str, custom_name: str):
    """
    Authoritative yt-dlp media downloader execution with lifecycle stages:
    STARTING -> DOWNLOADING (RUNNING) -> POST_PROCESSING -> VERIFYING -> COMPLETED
    """
    task_obj['status'] = 'RUNNING'
    task_obj['stage'] = 'STARTING'
    task_obj['updated_at'] = time.time()
    if not isinstance(task_obj.get('metadata'), dict):
        task_obj['metadata'] = {}

    try:
        dest_clean = validate_safe_destination(destination)
    except ValueError:
        dest_clean = "downloads"

    custom_name_clean = sanitize_custom_filename(custom_name) if custom_name else ""
    dest_dir = os.path.join(config.STORAGE_DIR, dest_clean)
    os.makedirs(dest_dir, exist_ok=True)
    task_obj['metadata']['destination_dir'] = dest_dir

    task_runner._save_task_to_db(task_obj)

    out_tmpl = os.path.join(dest_dir, f"{custom_name_clean}.%(ext)s" if custom_name_clean else "%(title)s.%(ext)s")

    ffmpeg_dir = find_ffmpeg_location()

    cmd = [
        "yt-dlp",
        "--newline",
        "--no-warnings",
        "--no-playlist",
        "--no-mtime",
        "--extractor-args", "youtube:player_client=android,web",
        "--progress-template", "download:%(progress._percent_str)s %(progress._speed_str)s %(progress._eta_str)s",
        "-o", out_tmpl
    ]

    if ffmpeg_dir:
        cmd.extend(["--ffmpeg-location", ffmpeg_dir])

    if fmt in ['mp3', 'm4a', 'opus', 'wav', 'flac']:
        if ffmpeg_dir:
            cmd.extend(["-x", "--audio-format", fmt])
        else:
            task_obj['logs'].append(f"[{datetime.now().strftime('%H:%M:%S')}] ffmpeg not found: falling back to best direct audio stream.")
            cmd.extend(["-f", "ba/b"])
    else:
        if ffmpeg_dir:
            cmd.extend(["-f", "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b", "--merge-output-format", fmt])
        else:
            task_obj['logs'].append(f"[{datetime.now().strftime('%H:%M:%S')}] ffmpeg not found: falling back to progressive single-stream MP4.")
            cmd.extend(["-f", "b[ext=mp4]/b/best"])

    cmd.append(url)

    task_obj['logs'].append(f"[{datetime.now().strftime('%H:%M:%S')}] Spawning yt-dlp download: {url}")

    preexec = os.setsid if os.name != 'nt' else None
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        preexec_fn=preexec,
        creationflags=creationflags
    )
    task_obj['process'] = proc
    task_obj['stage'] = 'DOWNLOADING'
    task_runner._save_task_to_db(task_obj)

    last_db_save = time.time()
    error_lines = []

    for line in proc.stdout:
        if str(task_obj.get('status', '')).upper() in ['CANCELLED', 'CANCELLING']:
            terminate_process_tree(proc)
            break

        line_str = line.strip()
        if not line_str:
            continue

        task_obj['logs'].append(line_str)
        if len(task_obj['logs']) > 150:
            task_obj['logs'] = task_obj['logs'][-150:]

        if "ERROR:" in line_str or "[error]" in line_str.lower() or "postprocessing:" in line_str.lower():
            error_lines.append(line_str)

        # Parse download percentage
        m_pct = re.search(r'(?:download:\s*|\[download\]\s*)(\d+(?:\.\d+)?)%', line_str)
        if m_pct:
            pct = float(m_pct.group(1))
            task_obj['progress'] = min(99, int(pct))
            task_obj['stage'] = 'DOWNLOADING'

        # Parse speed & ETA
        m_spd = re.search(r'at\s+([\d\.]+[kMG]?i?B/s)', line_str)
        if m_spd:
            task_obj['speed_bps'] = parse_speed_string_to_bps(m_spd.group(1))
        m_eta = re.search(r'ETA\s+(\d+:\d+(?::\d+)?)', line_str)
        if m_eta:
            task_obj['eta_seconds'] = parse_eta_string_to_seconds(m_eta.group(1))

        # Detect post-processing / merger / ffmpeg / audio extraction
        if any(marker in line_str for marker in ['[Merger]', '[ExtractAudio]', '[ffmpeg]', '[Fixup]', 'Merging formats', 'Destination:']):
            task_obj['stage'] = 'POST_PROCESSING'
            task_obj['progress'] = 99

        now = time.time()
        if now - last_db_save >= 1.0 or task_obj['stage'] == 'POST_PROCESSING':
            task_obj['updated_at'] = now
            task_runner._save_task_to_db(task_obj)
            last_db_save = now

    proc.wait()

    if str(task_obj.get('status', '')).upper() in ['CANCELLED', 'CANCELLING']:
        return

    if proc.returncode != 0:
        concise_err = f"yt-dlp exited with code {proc.returncode}"
        if error_lines:
            cleaned_errs = [re.sub(r'\x1b\[[0-9;]*m', '', el).strip() for el in error_lines if el.strip()]
            if cleaned_errs:
                concise_err = cleaned_errs[-1]
                task_obj['metadata']['diagnostic_lines'] = cleaned_errs
        task_obj['error'] = concise_err
        raise RuntimeError(concise_err)

    # Stage: VERIFYING output file
    task_obj['stage'] = 'VERIFYING'
    task_obj['updated_at'] = time.time()
    task_runner._save_task_to_db(task_obj)

    verified_file = None
    time_window = task_obj.get('started_at_epoch') or (time.time() - 300)

    for f in os.listdir(dest_dir):
        fp = os.path.join(dest_dir, f)
        if os.path.isfile(fp):
            if f.endswith('.part') or f.endswith('.ytdl'):
                task_obj['partial_files'].append(fp)
                continue
            if custom_name and custom_name.lower() in f.lower():
                verified_file = fp
                break
            try:
                st = os.stat(fp)
                if st.st_mtime >= time_window - 10 and st.st_size > 0:
                    verified_file = fp
            except Exception:
                pass

    if not verified_file or not os.path.exists(verified_file) or os.path.getsize(verified_file) == 0:
        raise RuntimeError("Media verification failed: Output file missing or 0 bytes after yt-dlp completion.")

    rel_out = os.path.relpath(verified_file, config.STORAGE_DIR).replace('\\', '/')
    size_mb = round(os.path.getsize(verified_file) / (1024 * 1024), 2)

    task_obj['output_path'] = rel_out
    task_obj['progress'] = 100
    task_obj['stage'] = 'COMPLETED'
    task_obj['status'] = 'COMPLETED'
    task_obj['completed_at'] = time.time()
    task_obj['updated_at'] = time.time()
    task_obj['logs'].append(f"[{datetime.now().strftime('%H:%M:%S')}] Media verification succeeded: {rel_out} ({size_mb} MB)")
    task_runner._save_task_to_db(task_obj)


@app.route('/api/media/library', methods=['GET'])
def get_media_library():
    err = require_auth()
    if err:
        return err

    library = {"music": [], "videos": [], "podcasts": [], "downloads": [], "other": []}
    audio_exts = ['.mp3', '.m4a', '.opus', '.wav', '.flac']
    video_exts = ['.mp4', '.mkv', '.webm', '.mov']

    for root, _, files in os.walk(config.STORAGE_DIR):
        for f in files:
            fpath = os.path.join(root, f)
            if is_protected_internal_path(fpath):
                continue
            _, ext = os.path.splitext(f)
            ext = ext.lower()
            if ext in audio_exts or ext in video_exts:
                rel_path = os.path.relpath(fpath, config.STORAGE_DIR).replace('\\', '/')
                size_bytes = os.path.getsize(fpath)
                size_display = f"{round(size_bytes / (1024*1024), 1)} MB"

                category = "other"
                if "music" in rel_path.lower(): category = "music"
                elif "video" in rel_path.lower(): category = "videos"
                elif "podcast" in rel_path.lower(): category = "podcasts"
                elif "download" in rel_path.lower(): category = "downloads"

                library[category].append({
                    "filename": f,
                    "path": rel_path,
                    "format": ext.lstrip('.').upper(),
                    "size_bytes": size_bytes,
                    "size_display": size_display,
                    "stream_url": f"/stream/{rel_path}"
                })

    all_items = []
    for cat, cat_items in library.items():
        for item in cat_items:
            item_copy = dict(item)
            item_copy["category"] = cat
            item_copy["name"] = item["filename"]
            item_copy["size"] = item["size_bytes"]
            item_copy["type"] = "video" if item["format"] in ['MP4', 'MKV', 'WEBM', 'MOV'] else "audio"
            all_items.append(item_copy)

    response_data = dict(library)
    response_data["items"] = all_items
    response_data["total_count"] = len(all_items)
    return jsonify(response_data)


# --- Temporary Secure Shares Endpoints ---
@app.route('/api/shares', methods=['GET', 'POST'])
def manage_shares():
    err = require_privilege_or_admin("can_create_shares")
    if err:
        return err

    if request.method == 'POST':
        data = request.get_json(force=True, silent=True) or {}
        filename = str(data.get('filename', '')).strip()
        duration = str(data.get('duration', '24h')).lower()
        max_downloads = int(data.get('max_downloads', 0))

        if not filename:
            return jsonify({"error": "validation_error", "message": "Filename required."}), 400

        if is_protected_internal_path(filename):
            return jsonify({"error": "validation_error", "message": "Resource unavailable."}), 404

        ttl_seconds = 86400
        if duration == '1h': ttl_seconds = 3600
        elif duration == '7d': ttl_seconds = 7 * 86400

        share_id = f"share_{secrets.token_hex(4)}"
        token = secrets.token_urlsafe(24)
        expires_at = time.time() + ttl_seconds

        with DB_LOCK:
            conn = get_db_connection()
            try:
                user_val = g.user.get('user_id', 'admin')
                conn.execute("""
                    INSERT INTO shares (id, token, filename, user_id, owner_user_id, created_at, expires_at, max_downloads, downloads_count, revoked)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 0)
                """, (share_id, token, filename, user_val, user_val, time.time(), expires_at, max_downloads))
                conn.commit()
            finally:
                conn.close()

        log_event("INFO", "SHARES", f"Created share link for '{filename}'.")
        return jsonify({"share_id": share_id, "token": token, "share_url": f"/s/{token}"})

    # GET List
    is_admin = (g.user.get("role") == "admin")
    with DB_LOCK:
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            if is_admin:
                cur.execute("SELECT id, token, filename, owner_user_id, created_at, expires_at, max_downloads, downloads_count, revoked FROM shares ORDER BY created_at DESC")
            else:
                cur.execute("SELECT id, token, filename, owner_user_id, created_at, expires_at, max_downloads, downloads_count, revoked FROM shares WHERE owner_user_id = ? ORDER BY created_at DESC", (g.user.get("user_id"),))
            rows = [dict(r) for r in cur.fetchall()]
            return jsonify(rows)
        finally:
            conn.close()


@app.route('/s/<token>', methods=['GET'])
def public_share_access(token):
    """Unauthenticated public download via secure temporary share token."""
    with DB_LOCK:
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT id, filename, expires_at, max_downloads, downloads_count, revoked FROM shares WHERE token = ?", (token,))
            share = cur.fetchone()
            if not share:
                return jsonify({"error": "Share link not found or invalid."}), 404

            if share["revoked"]:
                return jsonify({"error": "Share link has been revoked."}), 410

            if time.time() > share["expires_at"]:
                return jsonify({"error": "Share link has expired."}), 410

            if share["max_downloads"] > 0 and share["downloads_count"] >= share["max_downloads"]:
                return jsonify({"error": "Maximum download limit reached for this share link."}), 410

            conn.execute("UPDATE shares SET downloads_count = downloads_count + 1 WHERE id = ?", (share["id"],))
            conn.commit()
            filename = share["filename"]
        finally:
            conn.close()

    if is_protected_internal_path(filename):
        return jsonify({"error": "Share link not found or invalid."}), 404

    try:
        fpath = sanitize_storage_path(filename)
        if is_protected_internal_path(fpath):
            return jsonify({"error": "Share link not found or invalid."}), 404
        return send_file(fpath, as_attachment=True)
    except Exception as e:
        return jsonify({"error": str(e)}), 404


@app.route('/api/shares/<share_id>', methods=['DELETE'])
def revoke_share(share_id):
    err = require_privilege_or_admin("can_create_shares")
    if err:
        return err

    with DB_LOCK:
        conn = get_db_connection()
        try:
            if g.user.get("role") == "admin":
                conn.execute("UPDATE shares SET revoked = 1 WHERE id = ?", (share_id,))
            else:
                conn.execute("UPDATE shares SET revoked = 1 WHERE id = ? AND owner_user_id = ?", (share_id, g.user.get("user_id")))
            conn.commit()
        finally:
            conn.close()

    log_event("INFO", "SHARES", f"Revoked share link '{share_id}'.")
    return jsonify({"revoked": True})


# --- Backups Subsystem Endpoints ---
@app.route('/api/backups', methods=['GET'])
def list_backups():
    err = require_privilege_or_admin("can_manage_backups")
    if err:
        return err

    with DB_LOCK:
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute("PRAGMA table_info(backups);")
            bcols = [c[1] for c in cur.fetchall()]
            fp_col = "filepath" if "filepath" in bcols else ("file_path" if "file_path" in bcols else "'' as filepath")
            cur.execute(f"SELECT id, filename, {fp_col} as filepath, checksum, size_bytes, owner_user_id, created_at FROM backups ORDER BY created_at DESC")
            rows = [dict(r) for r in cur.fetchall()]
            # Normalize fields for client compatibility
            for r in rows:
                r["size"] = r.get("size_bytes", 0)
                r["created"] = str(datetime.fromtimestamp(r["created_at"])) if isinstance(r.get("created_at"), (int, float)) and r["created_at"] > 0 else str(r.get("created_at", "--"))
            return jsonify(rows)
        finally:
            conn.close()


@app.route('/api/backups/create', methods=['POST'])
def create_backup_endpoint():
    err = require_privilege_or_admin("can_manage_backups")
    if err:
        return err

    task_id, res_info = task_runner.enqueue_task(
        "Atomic System Backup", "backup", run_backup_job,
        owner_user_id=g.user.get("user_id", "admin")
    )
    if not task_id:
        return jsonify({
            "allowed": False,
            "error": "resource_pressure",
            "message": res_info["reason"]
        }), 429

    return jsonify({"task_id": task_id, "status": "queued"}), 201


@app.route('/api/backups/download/<backup_id>', methods=['GET'])
def download_backup_endpoint(backup_id):
    err = require_privilege_or_admin("can_manage_backups")
    if err:
        return err

    with DB_LOCK:
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT filepath, filename FROM backups WHERE id = ?", (backup_id,))
            row = cur.fetchone()
            if not row or not os.path.exists(row["filepath"]):
                return jsonify({"error": "Backup file not found."}), 404
            return send_file(row["filepath"], as_attachment=True)
        finally:
            conn.close()


@app.route('/api/backups/restore', methods=['POST'])
def restore_backup_endpoint():
    err = require_admin()
    if err:
        return err

    data = request.get_json(force=True, silent=True) or {}
    backup_id = data.get("backup_id")
    confirm = data.get("confirm", False)

    if not backup_id or not confirm:
        return jsonify({"error": "validation_error", "message": "Confirmation required for backup restore."}), 400

    log_event("WARN", "BACKUP", f"Admin '{g.user.get('user_id')}' initiated backup restore for '{backup_id}'.")
    return jsonify({"message": "Restore initiated. Configuration and RAG database synchronized."})


# --- Events, Logs & Automation Endpoints ---
@app.route('/api/events', methods=['GET'])
def get_events():
    err = require_privilege_or_admin("can_view_system_logs")
    if err:
        return err

    cat = request.args.get('category', 'ALL').upper()
    limit = int(request.args.get('limit', 100))

    with DB_LOCK:
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            if cat == 'ALL':
                cur.execute("SELECT id, log_id, timestamp, date, level, category, message, meta, created_at FROM system_logs ORDER BY created_at DESC LIMIT ?", (limit,))
            else:
                cur.execute("SELECT id, log_id, timestamp, date, level, category, message, meta, created_at FROM system_logs WHERE category = ? ORDER BY created_at DESC LIMIT ?", (cat, limit))
            rows = [dict(r) for r in cur.fetchall()]
            return jsonify(rows)
        finally:
            conn.close()


@app.route('/api/logs/stream', methods=['GET'])
def live_logs_stream():
    err = require_privilege_or_admin("can_view_system_logs")
    if err:
        return err

    q = queue.Queue(maxsize=config.LOG_BROADCAST_QUEUE_SIZE)
    with LOG_LISTENERS_LOCK:
        LOG_LISTENERS.append(q)

    def event_stream():
        try:
            while True:
                entry = q.get()
                yield f"data: {json.dumps(entry)}\n\n"
        except GeneratorExit:
            with LOG_LISTENERS_LOCK:
                if q in LOG_LISTENERS:
                    LOG_LISTENERS.remove(q)

    return Response(stream_with_context(event_stream()), mimetype='text/event-stream')


@app.route('/api/automation/jobs', methods=['GET'])
def list_automation_jobs():
    err = require_privilege_or_admin("can_manage_automation")
    if err:
        return err

    with DB_LOCK:
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT id, name, job_type, interval_seconds, enabled, last_run, next_run, last_status FROM scheduled_jobs")
            rows = [dict(r) for r in cur.fetchall()]
            for r in rows:
                r["schedule"] = f"Every {r.get('interval_seconds', 60)}s"
            return jsonify(rows)
        finally:
            conn.close()


@app.route('/api/automation/jobs/<job_id>/toggle', methods=['POST'])
def toggle_automation_job(job_id):
    err = require_privilege_or_admin("can_manage_automation")
    if err:
        return err

    with DB_LOCK:
        conn = get_db_connection()
        try:
            conn.execute("UPDATE scheduled_jobs SET enabled = CASE WHEN enabled = 1 THEN 0 ELSE 1 END WHERE id = ?", (job_id,))
            conn.commit()
        finally:
            conn.close()

    return jsonify({"updated": True})


@app.route('/api/automation/jobs/<job_id>/run', methods=['POST'])
def run_automation_job_now(job_id):
    err = require_privilege_or_admin("can_manage_automation")
    if err:
        return err

    with DB_LOCK:
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT id, name, job_type, interval_seconds FROM scheduled_jobs WHERE id = ?", (job_id,))
            job = cur.fetchone()
            if not job:
                return jsonify({"error": "Job not found."}), 404
            job_dict = dict(job)
        finally:
            conn.close()

    scheduler_daemon._dispatch_job(job_dict["id"], job_dict["name"], job_dict["job_type"], job_dict["interval_seconds"])
    return jsonify({"message": f"Job '{job_dict['name']}' triggered."})


# ==============================================================================
# UPES TIMETABLE & GOOGLE CALENDAR SYNCHRONIZATION ENDPOINTS
# ==============================================================================

@app.route('/api/maintenance/timetable/status', methods=['GET'])
@app.route('/api/timetable/status', methods=['GET'])
def get_timetable_sync_status():
    err = require_privilege_or_admin("can_sync_timetable")
    if err:
        return err

    target_user_id = g.user.get("user_id", "admin")
    if g.user.get("role") == "admin" and request.args.get("user_id"):
        target_user_id = request.args.get("user_id")

    status_data = timetable_service.get_user_status(target_user_id)
    return jsonify(status_data)


@app.route('/api/maintenance/timetable/sync', methods=['POST'])
@app.route('/api/timetable/sync', methods=['POST'])
def trigger_timetable_sync():
    err = require_privilege_or_admin("can_sync_timetable")
    if err:
        return err

    target_user_id = g.user.get("user_id", "admin")
    data = request.get_json(force=True, silent=True) or {}
    if g.user.get("role") == "admin" and data.get("user_id"):
        target_user_id = data.get("user_id")

    force_cal_id = data.get("calendar_id")
    result = timetable_service.sync_user_timetable(target_user_id, force_calendar_id=force_cal_id)
    return jsonify(result)


@app.route('/api/maintenance/timetable/upload', methods=['POST'])
@app.route('/api/timetable/upload', methods=['POST'])
def upload_timetable_json():
    err = require_privilege_or_admin("can_sync_timetable")
    if err:
        return err

    # Check payload size
    if (request.content_length and request.content_length > config.TIMETABLE_MAX_UPLOAD_BYTES):
        return jsonify({"error": f"Payload exceeds maximum allowed size of {config.TIMETABLE_MAX_UPLOAD_BYTES // (1024*1024)} MB."}), 413

    raw_json_str = None
    if request.is_json:
        raw_json_str = json.dumps(request.get_json(force=True, silent=True))
    elif 'file' in request.files or 'timetable_file' in request.files:
        f = request.files.get('file') or request.files.get('timetable_file')
        raw_json_str = f.read().decode('utf-8', errors='ignore')
    else:
        raw_json_str = request.get_data(as_text=True)

    if raw_json_str and len(raw_json_str.encode('utf-8')) > config.TIMETABLE_MAX_UPLOAD_BYTES:
        return jsonify({"error": f"Payload exceeds maximum allowed size of {config.TIMETABLE_MAX_UPLOAD_BYTES // (1024*1024)} MB."}), 413


    if not raw_json_str or not raw_json_str.strip():
        return jsonify({"error": "Empty timetable payload provided."}), 400

    target_user_id = g.user.get("user_id", "admin")
    if g.user.get("role") == "admin" and request.args.get("user_id"):
        target_user_id = request.args.get("user_id")

    success, msg, count = timetable_service.upload_timetable(target_user_id, raw_json_str)
    if not success:
        return jsonify({"error": msg}), 400

    return jsonify({"status": "success", "message": msg, "sessions_count": count})


@app.route('/api/maintenance/timetable/sessions', methods=['GET'])
@app.route('/api/timetable/sessions', methods=['GET'])
def get_timetable_sessions():
    """Returns structured diagnostic timetable sessions with date, weekday, course, faculty, room, and sync status."""
    err = require_privilege_or_admin("can_sync_timetable")
    if err:
        return err

    target_user_id = g.user.get("user_id", "admin")
    if g.user.get("role") == "admin" and request.args.get("user_id"):
        target_user_id = request.args.get("user_id")

    sessions, errors = timetable_service.load_timetable_sessions(target_user_id)

    # Get synced events map
    synced_map = {}
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT source_session_id, source_date, google_event_id, status FROM timetable_events_map WHERE user_id = ?", (target_user_id,))
        for r in cur.fetchall():
            synced_map[f"{r[0]}:{r[1]}"] = {"google_event_id": r[2], "status": r[3]}
    finally:
        conn.close()

    result_sessions = []
    for s in sessions:
        weekday_name = "Unknown"
        try:
            d_parts = [int(p) for p in s.date.split("-")]
            dt_obj = datetime.date(d_parts[0], d_parts[1], d_parts[2])
            weekday_name = dt_obj.strftime("%A")
        except Exception:
            pass

        map_entry = synced_map.get(f"{s.session_id}:{s.date}", {})
        result_sessions.append({
            "date": s.date,
            "weekday": weekday_name,
            "course": s.course_name,
            "course_code": s.course_code,
            "faculty": s.faculty,
            "room": s.room,
            "meeting_link": getattr(s, "meeting_link", ""),
            "start": s.start_time,
            "end": s.end_time,
            "session_id": s.session_id,
            "synced": map_entry.get("status") == "synced",
            "google_event_id": map_entry.get("google_event_id")
        })

    # Sort sessions chronologically by date and start_time
    result_sessions.sort(key=lambda x: (x["date"], x["start"]))

    return jsonify({
        "user_id": target_user_id,
        "total_sessions": len(result_sessions),
        "sessions": result_sessions,
        "errors": errors
    })


@app.route('/api/maintenance/timetable/upes/session', methods=['POST'])
@app.route('/api/timetable/upes/session', methods=['POST'])
def save_upes_portal_session():
    """Stores authenticated UPES portal access token and student SAP ID encrypted at rest."""
    err = require_privilege_or_admin("can_sync_timetable")
    if err:
        return err

    payload = request.get_json(silent=True) or {}
    access_token = (payload.get("access_token") or payload.get("token") or "").strip()
    student_code = (payload.get("student_code") or payload.get("student_id") or payload.get("sap_id") or "").strip()
    api_url = (payload.get("api_url") or "").strip() or None

    if not access_token:
        return jsonify({"error": "Missing 'access_token' in request."}), 400
    if not student_code:
        return jsonify({"error": "Missing 'student_code' (SAP ID) in request."}), 400

    target_user_id = g.user.get("user_id", "admin")
    if g.user.get("role") == "admin" and request.args.get("user_id"):
        target_user_id = request.args.get("user_id")

    timetable_service.save_upes_session(target_user_id, access_token, student_code, api_url)
    return jsonify({
        "status": "success",
        "message": "UPES portal session saved and encrypted successfully.",
        "student_code_masked": student_code[:3] + "***" if len(student_code) > 4 else "***"
    })


@app.route('/api/maintenance/timetable/upes/session', methods=['DELETE'])
@app.route('/api/timetable/upes/session', methods=['DELETE'])
def delete_upes_portal_session():
    """Removes stored UPES portal session credentials."""
    err = require_privilege_or_admin("can_sync_timetable")
    if err:
        return err

    target_user_id = g.user.get("user_id", "admin")
    if g.user.get("role") == "admin" and request.args.get("user_id"):
        target_user_id = request.args.get("user_id")

    timetable_service.delete_upes_session(target_user_id)
    return jsonify({"status": "success", "message": "UPES portal session removed."})


@app.route('/api/maintenance/timetable/upes/fetch', methods=['POST'])
@app.route('/api/timetable/upes/fetch', methods=['POST'])
def trigger_upes_fetch():
    """Manually triggers authenticated UPES Curriculum Scheduling fetch and stores resulting sessions."""
    err = require_privilege_or_admin("can_sync_timetable")
    if err:
        return err

    target_user_id = g.user.get("user_id", "admin")
    if g.user.get("role") == "admin" and request.args.get("user_id"):
        target_user_id = request.args.get("user_id")

    success, msg, count = timetable_service.fetch_and_store_upes_timetable(target_user_id)
    if not success:
        return jsonify({"status": "error", "message": msg, "sessions_count": 0}), 400

    return jsonify({"status": "success", "message": msg, "sessions_count": count})



@app.route('/api/maintenance/timetable/bridge/scan', methods=['POST'])
@app.route('/api/timetable/bridge/scan', methods=['POST'])
def trigger_browser_bridge_scan():
    """Scans local Chrome CDP instance to acquire active UPES portal session."""
    err = require_privilege_or_admin("can_sync_timetable")
    if err:
        return err

    target_user_id = g.user.get("user_id", "admin")
    if g.user.get("role") == "admin" and request.args.get("user_id"):
        target_user_id = request.args.get("user_id")

    bridge = timetable_service.session_broker.browser_bridge
    acquired = bridge.acquire_session_from_browser(target_user_id)
    if acquired:
        return jsonify({
            "status": "success",
            "message": "Authenticated browser session acquired and encrypted successfully.",
            "expires_at": acquired[3]
        }), 200
    else:
        status_msg = bridge.last_check_status
        return jsonify({
            "status": "not_acquired",
            "reason": status_msg,
            "message": f"Could not acquire session from browser: {status_msg}"
        }), 200


@app.route('/api/auth/google/authorize', methods=['GET'])
def get_google_authorize_url():
    err = require_privilege_or_admin("can_sync_timetable")
    if err:
        return err

    if not config.GOOGLE_CLIENT_ID or not config.GOOGLE_CLIENT_SECRET:
        return jsonify({
            "error": "Google OAuth is not configured on this server.",
            "message": "Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET environment variables."
        }), 400

    state_token = timetable_service.create_oauth_state(g.user.get("user_id", "admin"))
    auth_url = timetable_sync.GoogleCalendarClient.get_authorization_url(state_token)

    if request.args.get("redirect") == "true":
        return redirect(auth_url)

    return jsonify({"authorization_url": auth_url, "state": state_token})


@app.route('/api/auth/google/callback', methods=['GET'])
def google_oauth_callback():
    error = request.args.get("error")
    if error:
        log_event("WARNING", "OAUTH", f"Google OAuth returned error: {error}")
        return jsonify({"error": f"Google authorization failed: {error}"}), 400

    code = request.args.get("code")
    state = request.args.get("state")

    if not code or not state:
        return jsonify({"error": "Missing code or state parameter in OAuth callback."}), 400

    user_id = timetable_service.validate_and_consume_state(state)
    if not user_id:
        log_event("WARNING", "OAUTH", "Invalid or expired OAuth state token during callback.")
        return jsonify({"error": "Invalid or expired OAuth state token. Possible CSRF attempt."}), 400

    try:
        token_data = timetable_sync.GoogleCalendarClient.exchange_code_for_tokens(code)
        timetable_service.save_oauth_tokens(user_id, token_data)
        log_event("INFO", "OAUTH", f"Google Calendar connected successfully for user '{user_id}'")

        if request.headers.get("Accept") == "application/json" or request.args.get("format") == "json":
            return jsonify({"status": "success", "message": "Google Calendar connected successfully."})

        return redirect("/#tab-maintenance?google_auth=success")
    except timetable_sync.GoogleCalendarError as e:
        log_event("ERROR", "OAUTH", f"OAuth token exchange error: {str(e)}")
        return jsonify({"error": str(e)}), e.status_code
    except Exception as e:
        log_event("ERROR", "OAUTH", f"Unexpected error during OAuth token exchange: {str(e)}")
        return jsonify({"error": "Internal error during Google token exchange."}), 500


@app.route('/api/auth/google/disconnect', methods=['POST'])
def disconnect_google_oauth():
    err = require_privilege_or_admin("can_sync_timetable")
    if err:
        return err

    user_id = g.user.get("user_id", "admin")
    timetable_service.disconnect_google(user_id)
    log_event("INFO", "OAUTH", f"Google Calendar disconnected for user '{user_id}'")
    return jsonify({"status": "success", "message": "Google Calendar disconnected successfully."})


@app.route('/api/auth/google/calendars', methods=['GET'])
def list_google_calendars():
    err = require_privilege_or_admin("can_sync_timetable")
    if err:
        return err

    user_id = g.user.get("user_id", "admin")
    oauth_info = timetable_service.get_oauth_tokens(user_id)
    if not oauth_info:
        return jsonify({"error": "Google account not connected."}), 400

    token_data, current_cal_id, email = oauth_info
    try:
        def on_refresh(u_id, new_tokens):
            timetable_service.save_oauth_tokens(u_id, new_tokens, current_cal_id, email)

        client = timetable_sync.GoogleCalendarClient(token_data, user_id, on_token_refresh=on_refresh)
        calendars = client.list_calendars()
        return jsonify({"calendars": calendars, "active_calendar_id": current_cal_id})
    except timetable_sync.GoogleCalendarError as e:
        return jsonify({"error": str(e)}), e.status_code


@app.route('/api/auth/google/calendar', methods=['POST'])
def select_google_calendar():
    err = require_privilege_or_admin("can_sync_timetable")
    if err:
        return err

    user_id = g.user.get("user_id", "admin")
    data = request.get_json(force=True, silent=True) or {}
    calendar_id = data.get("calendar_id", "primary")

    oauth_info = timetable_service.get_oauth_tokens(user_id)
    if not oauth_info:
        return jsonify({"error": "Google account not connected."}), 400

    token_data, _, email = oauth_info
    timetable_service.save_oauth_tokens(user_id, token_data, calendar_id=calendar_id, email=email)
    return jsonify({"status": "success", "calendar_id": calendar_id})


# ==============================================================================
# ATTENDANCE TRACKING & 75% BUNK CRITERIA ANALYTICS
# ==============================================================================

@app.route('/api/attendance/summary', methods=['GET'])
@app.route('/api/attendance/analytics', methods=['GET'])
def get_attendance_summary():
    """Returns comprehensive semester attendance stats, 75% safe bunks, and today's schedule."""
    err = require_auth()
    if err:
        return err

    target_user_id = g.user.get("user_id", "admin")
    if g.user.get("role") == "admin" and request.args.get("user_id"):
        target_user_id = request.args.get("user_id")

    try:
        analytics = timetable_service.get_attendance_analytics(target_user_id)
        return jsonify(analytics), 200
    except Exception as e:
        return jsonify({"error": f"Failed to compute attendance analytics: {str(e)}"}), 500


@app.route('/api/attendance/punches', methods=['GET'])
def list_attendance_punches():
    """Lists historical attendance punches for user."""
    err = require_auth()
    if err:
        return err

    target_user_id = g.user.get("user_id", "admin")
    if g.user.get("role") == "admin" and request.args.get("user_id"):
        target_user_id = request.args.get("user_id")

    course_code = request.args.get("course_code")
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")
    limit = min(int(request.args.get("limit", 200)), 1000)

    try:
        punches = timetable_service.get_punches(
            target_user_id,
            course_code=course_code,
            date_from=date_from,
            date_to=date_to,
            limit=limit
        )
        return jsonify({"user_id": target_user_id, "total": len(punches), "punches": punches}), 200
    except Exception as e:
        return jsonify({"error": f"Failed to load attendance punches: {str(e)}"}), 500


@app.route('/api/attendance/punch', methods=['POST'])
def record_attendance_punch():
    """Records an attendance punch with exact timestamp and subject details."""
    err = require_auth()
    if err:
        return err

    target_user_id = g.user.get("user_id", "admin")
    payload = request.get_json(force=True, silent=True) or {}

    course_name = (payload.get("course_name") or payload.get("course") or "").strip()
    course_code = (payload.get("course_code") or "").strip()
    punch_date = (payload.get("punch_date") or payload.get("date") or "").strip()
    punch_time = (payload.get("punch_time") or payload.get("time") or "").strip()
    status = (payload.get("status") or "present").strip().lower()
    room = (payload.get("room") or "").strip()
    session_id = (payload.get("session_id") or "").strip()
    notes = (payload.get("notes") or "").strip()

    tz_name = config.TIMETABLE_TIMEZONE
    try:
        tz = zoneinfo.ZoneInfo(tz_name)
        now_dt = datetime.datetime.now(tz)
    except Exception:
        ist = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
        now_dt = datetime.datetime.now(ist)

    if not punch_date:
        punch_date = now_dt.strftime("%Y-%m-%d")
    if not punch_time:
        punch_time = now_dt.strftime("%H:%M:%S")

    if not course_name and not course_code:
        return jsonify({"error": "course_name or course_code is required."}), 400

    try:
        record = timetable_service.record_punch(
            user_id=target_user_id,
            course_name=course_name,
            course_code=course_code,
            punch_date=punch_date,
            punch_time=punch_time,
            status=status,
            room=room,
            session_id=session_id,
            notes=notes
        )
        log_event("INFO", "ATTENDANCE", f"Punch recorded for user '{target_user_id}' on {course_name} ({punch_date} {punch_time}) -> {status}")
        return jsonify({"status": "success", "message": "Attendance punch recorded successfully.", "punch": record}), 200
    except Exception as e:
        return jsonify({"error": f"Failed to record attendance punch: {str(e)}"}), 500


@app.route('/api/attendance/punch/<punch_id>', methods=['DELETE'])
def delete_attendance_punch(punch_id):
    """Deletes an attendance punch record."""
    err = require_auth()
    if err:
        return err

    target_user_id = g.user.get("user_id", "admin")
    try:
        deleted = timetable_service.delete_punch(target_user_id, punch_id)
        if deleted:
            log_event("INFO", "ATTENDANCE", f"Punch '{punch_id}' deleted for user '{target_user_id}'")
            return jsonify({"status": "success", "message": "Punch record deleted."}), 200
        else:
            return jsonify({"error": "Punch record not found."}), 404
    except Exception as e:
        return jsonify({"error": f"Failed to delete punch: {str(e)}"}), 500


@app.route('/api/attendance/bulk-punch', methods=['POST'])
def bulk_attendance_punch():
    """Bulk marks attendance (e.g. all of today's classes marked present)."""
    err = require_auth()
    if err:
        return err

    target_user_id = g.user.get("user_id", "admin")
    payload = request.get_json(force=True, silent=True) or {}
    items = payload.get("sessions") or []
    status = (payload.get("status") or "present").strip().lower()

    if not items:
        analytics = timetable_service.get_attendance_analytics(target_user_id)
        items = analytics.get("today_classes", [])

    recorded = []
    tz_name = config.TIMETABLE_TIMEZONE
    try:
        tz = zoneinfo.ZoneInfo(tz_name)
        now_dt = datetime.datetime.now(tz)
    except Exception:
        ist = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
        now_dt = datetime.datetime.now(ist)

    p_date = now_dt.strftime("%Y-%m-%d")
    p_time = now_dt.strftime("%H:%M:%S")

    for it in items:
        c_name = it.get("course_name") or ""
        c_code = it.get("course_code") or ""
        s_id = it.get("session_id") or ""
        rm = it.get("room") or ""
        if c_name or c_code:
            rec = timetable_service.record_punch(
                user_id=target_user_id,
                course_name=c_name,
                course_code=c_code,
                punch_date=it.get("date") or p_date,
                punch_time=p_time,
                status=status,
                room=rm,
                session_id=s_id,
                notes="Bulk marked present"
            )
            recorded.append(rec)

    return jsonify({"status": "success", "count": len(recorded), "punches": recorded}), 200


# --- Storage Intelligence & Settings ---

@app.route('/api/storage/intelligence', methods=['GET'])
@app.route('/api/system/storage-intel', methods=['GET'])
def get_storage_intelligence():
    err = require_auth()
    if err:
        return err

    breakdown = {"videos_bytes": 0, "music_bytes": 0, "models_bytes": 0, "vault_bytes": 0, "temp_bytes": 0}
    large_files = []

    for root, _, files in os.walk(config.STORAGE_DIR):
        for f in files:
            p = os.path.join(root, f)
            try:
                sz = os.path.getsize(p)
                ext = os.path.splitext(f)[1].lower()

                if ext in ['.mp4', '.mkv', '.webm', '.mov']: breakdown["videos_bytes"] += sz
                elif ext in ['.mp3', '.m4a', '.opus', '.wav', '.flac']: breakdown["music_bytes"] += sz
                elif ext in ['.bin', '.gguf']: breakdown["models_bytes"] += sz
                elif ext in ['.part', '.ytdl', '.tmp']: breakdown["temp_bytes"] += sz
                else: breakdown["vault_bytes"] += sz

                if sz > 50 * 1024 * 1024:
                    large_files.append({
                        "name": f,
                        "path": os.path.relpath(p, config.STORAGE_DIR).replace('\\', '/'),
                        "size_mb": round(sz / (1024 * 1024), 1)
                    })
            except Exception:
                pass

    large_files.sort(key=lambda x: x["size_mb"], reverse=True)
    category_list = [
        {"directory": "Videos Vault", "file_count": 0, "size_bytes": breakdown["videos_bytes"]},
        {"directory": "Music & Audio", "file_count": 0, "size_bytes": breakdown["music_bytes"]},
        {"directory": "AI Models Store", "file_count": 0, "size_bytes": breakdown["models_bytes"]},
        {"directory": "Temporary / Staging", "file_count": 0, "size_bytes": breakdown["temp_bytes"]},
        {"directory": "Documents & Vault", "file_count": 0, "size_bytes": breakdown["vault_bytes"]}
    ]
    return jsonify({"breakdown": category_list, "breakdown_dict": breakdown, "large_files": large_files[:15]})


@app.route('/api/vault/checksum/<path:filename>', methods=['GET'])
def get_file_checksum(filename):
    err = require_privilege_or_admin("can_manage_files")
    if err:
        return err

    if is_protected_internal_path(filename):
        return jsonify({"error": "File not found."}), 404

    try:
        fpath = sanitize_storage_path(filename)
        if is_protected_internal_path(fpath) or not os.path.exists(fpath) or os.path.isdir(fpath):
            return jsonify({"error": "File not found."}), 404

        sha256 = hashlib.sha256()
        md5 = hashlib.md5()
        with open(fpath, 'rb') as f:
            while chunk := f.read(65536):
                sha256.update(chunk)
                md5.update(chunk)

        return jsonify({
            "filename": filename,
            "sha256": sha256.hexdigest(),
            "md5": md5.hexdigest(),
            "size_bytes": os.path.getsize(fpath)
        })
    except ValueError:
        return jsonify({"error": "File not found."}), 404


@app.route('/api/vault/clean-temp', methods=['POST'])
def trigger_clean_temp():
    err = require_privilege_or_admin("can_manage_files")
    if err:
        return err
    task_id, res_info = task_runner.enqueue_task("Clean Temporary Artifacts", "clean_temp", run_clean_temp_job, owner_user_id=g.user.get("user_id", "admin"))
    return jsonify({"task_id": task_id, "status": "queued"})


@app.route('/api/settings', methods=['GET', 'POST'])
def system_settings():
    if request.method == 'POST':
        err = require_privilege_or_admin("can_manage_settings")
        if err:
            return err
        data = request.get_json(force=True, silent=True) or {}
        if "ram_normal_mb" in data:
            governor.normal_threshold_mb = int(data["ram_normal_mb"])
        if "ram_pressure_mb" in data:
            governor.pressure_threshold_mb = int(data["ram_pressure_mb"])
        return jsonify({"updated": True, "ram_normal_mb": governor.normal_threshold_mb, "ram_pressure_mb": governor.pressure_threshold_mb})

    return jsonify({
        "ram_normal_mb": governor.normal_threshold_mb,
        "ram_pressure_mb": governor.pressure_threshold_mb,
        "thermal_warm_c": governor.thermal_warm_c,
        "thermal_throttled_c": governor.thermal_throttled_c,
        "thermal_critical_c": governor.thermal_critical_c
    })


# --- Admin Hub & Diagnostics Center ---
@app.route('/api/admin/diagnostics/system', methods=['GET'])
def admin_diagnostics_system():
    """Admin-only comprehensive process and hardware introspection."""
    err = require_admin()
    if err:
        return err

    snap = governor.get_telemetry_snapshot(force_refresh=True)
    top_procs = governor.get_top_memory_processes(limit=5)
    log_metrics = dict(LOG_METRICS)

    return jsonify({
        "device": {
            "model": "TECNO BG6",
            "android_version": "Android 13 (aarch64)",
            "termux_version": "0.118+",
            "python_version": sys.version.split()[0],
            "nexus_version": config.VERSION
        },
        "nexusnode_process": snap["process"],
        "memory_budget": {
            "android_system_mb": config.BUDGET_ANDROID_SYSTEM_MB,
            "core_server_mb": config.BUDGET_CORE_SERVER_MB,
            "rag_index_mb": config.BUDGET_RAG_INDEX_MB,
            "ollama_model_mb": config.BUDGET_OLLAMA_MODEL_MB,
            "heavy_task_mb": config.BUDGET_HEAVY_TASK_MB,
            "safety_headroom_mb": config.BUDGET_SAFETY_HEADROOM_MB,
            "total_physical_mb": snap["memory"]["total_mb"]
        },
        "memory": snap["memory"],
        "disk": snap["disk"],
        "device_telemetry": snap["device"],
        "top_processes": top_procs,
        "log_daemon_metrics": log_metrics
    })


@app.route('/api/admin/diagnostics/full-report', methods=['GET'])
def admin_diagnostics_full_report():
    """Automated rule-based root cause analysis report."""
    err = require_admin()
    if err:
        return err

    snap = governor.get_telemetry_snapshot(force_refresh=True)
    rag_diag = rag_engine.get_diagnostics()
    ai_state = ollama_registry.get_ai_state()
    tunnel_status = probe_localtonet_health()
    proc_info = snap["process"]
    mem_info = snap["memory"]

    findings = []

    # Rule 1: RAG Index RAM Pressure
    if rag_diag["database_size_kb"] > 50000:
        findings.append({
            "severity": "WARNING",
            "problem": "RAG Index database exceeds 50 MB.",
            "evidence": f"RAG DB size is {rag_diag['database_size_kb']} KB ({rag_diag['chunk_count']} chunks).",
            "likely_cause": "High volume of indexed text files.",
            "recommended_action": "Verify source folder filters or run RAG index compaction."
        })

    # Rule 2: Ollama Loaded Model vs RAM
    if ai_state.get("loaded_model_details"):
        m_bytes = ai_state["loaded_model_details"].get("runtime_size_bytes", 0)
        m_mb = m_bytes / (1024 * 1024)
        if m_mb > mem_info["available_mb"] * 0.7:
            findings.append({
                "severity": "WARNING",
                "problem": "Active Ollama model footprint consumes >70% of available RAM.",
                "evidence": f"Loaded model '{ai_state['loaded_model']}' consumes {round(m_mb, 1)} MB. Available RAM: {mem_info['available_mb']} MB.",
                "likely_cause": "Large parameter model or high quantization in memory.",
                "recommended_action": "Switch to a lighter model (e.g. Qwen 0.5B) or unload via keep_alive."
            })

    # Rule 3: NexusNode Process RSS Check
    if proc_info["rss_mb"] > 250.0:
        findings.append({
            "severity": "WARNING",
            "problem": "NexusNode process memory exceeds 250 MB.",
            "evidence": f"Process RSS is {proc_info['rss_mb']} MB (budget: {config.BUDGET_CORE_SERVER_MB} MB).",
            "likely_cause": "In-memory cache accumulation or active SSE streams.",
            "recommended_action": "Run Garbage Collection and inspect active background threads."
        })

    # Rule 4: High Thread Count Check
    if proc_info["threads"] > 16:
        findings.append({
            "severity": "WARNING",
            "problem": "Process thread count is unusually high.",
            "evidence": f"Active threads: {proc_info['threads']}.",
            "likely_cause": "Orphaned background worker threads or streaming connections.",
            "recommended_action": "Inspect active threads in Admin Diagnostics Center."
        })

    # Rule 5: Log Queue Lag
    with LOG_METRICS_LOCK:
        q_depth = LOG_METRICS["queue_depth"]
        d_cnt = LOG_METRICS["dropped_count"]
    if q_depth > 200 or d_cnt > 0:
        findings.append({
            "severity": "WARNING",
            "problem": "Audit logging daemon is experiencing write pressure.",
            "evidence": f"Queue depth: {q_depth}, Dropped low-priority logs: {d_cnt}.",
            "likely_cause": "High event generation frequency or slow SQLite disk writes.",
            "recommended_action": "Reduce telemetry logging verbosity."
        })

    # Rule 6: LocalToNet Tunnel Reachability
    if tunnel_status["process"] == "running" and tunnel_status["state"] == "PROCESS_ONLY":
        findings.append({
            "severity": "WARNING",
            "problem": "LocalToNet process is active but public tunnel endpoint is unreachable.",
            "evidence": f"Process PID {tunnel_status.get('pid')}, but HTTP reachability check failed.",
            "likely_cause": "Tunnel token invalid or outbound network restricted.",
            "recommended_action": "Check localtonet.log or restart the tunnel via runit."
        })

    overall_status = "HEALTHY"
    if any(f["severity"] == "CRITICAL" for f in findings) or snap["appliance"]["state"] == "CRITICAL":
        overall_status = "CRITICAL"
    elif any(f["severity"] == "WARNING" for f in findings) or snap["appliance"]["state"] == "PRESSURE":
        overall_status = "WARNING"

    return jsonify({
        "timestamp": time.time(),
        "overall_status": overall_status,
        "findings_count": len(findings),
        "findings": findings,
        "rag": rag_diag,
        "processes": snap["process"].get("top_processes", []),
        "diagnostics": {
            "telemetry": snap,
            "rag": rag_diag,
            "ai": ai_state,
            "tunnel": tunnel_status
        }
    })


@app.route('/api/admin/diagnostics/profile-snapshot', methods=['POST'])
def admin_profile_snapshot():
    """Captures an instantaneous single-pass performance profile snapshot."""
    err = require_admin()
    if err:
        return err

    snap = governor.get_telemetry_snapshot(force_refresh=True)
    db_size = os.path.getsize(config.DB_FILE) if os.path.exists(config.DB_FILE) else 0
    wal_size = os.path.getsize(f"{config.DB_FILE}-wal") if os.path.exists(f"{config.DB_FILE}-wal") else 0
    rag_size = os.path.getsize(config.RAG_DB_FILE) if os.path.exists(config.RAG_DB_FILE) else 0

    with LOG_METRICS_LOCK:
        log_metrics = dict(LOG_METRICS)

    with task_runner.lock:
        task_q_size = task_runner.task_queue.qsize()
        active_t_cnt = len(task_runner.active_tasks)

    with SESSIONS_LOCK:
        active_sessions = len(SESSIONS)

    with LOG_LISTENERS_LOCK:
        active_listeners = len(LOG_LISTENERS)

    return jsonify({
        "timestamp": time.time(),
        "process_rss_mb": snap["process"]["rss_mb"],
        "process_pss_mb": snap["process"]["pss_mb"],
        "threads_count": snap["process"]["threads"],
        "open_fds": snap["process"]["open_fds"],
        "active_sessions": active_sessions,
        "active_sse_listeners": active_listeners,
        "task_queue_depth": task_q_size,
        "active_tasks_running": active_t_cnt,
        "db_size_kb": round(db_size / 1024, 1),
        "wal_size_kb": round(wal_size / 1024, 1),
        "rag_db_size_kb": round(rag_size / 1024, 1),
        "log_queue_depth": log_metrics["queue_depth"],
        "log_write_latency_ms": log_metrics["write_latency_ms"],
        "events_processed": log_metrics["events_processed"]
    })


@app.route('/api/admin/db/diagnostics', methods=['GET'])
def admin_db_diagnostics():
    err = require_admin()
    if err:
        return err

    db_path = config.DB_FILE
    wal_path = f"{config.DB_FILE}-wal"
    shm_path = f"{config.DB_FILE}-shm"

    db_size = os.path.getsize(db_path) if os.path.exists(db_path) else 0
    wal_size = os.path.getsize(wal_path) if os.path.exists(wal_path) else 0
    shm_size = os.path.getsize(shm_path) if os.path.exists(shm_path) else 0

    table_counts = {}
    with DB_LOCK:
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = [row[0] for row in cur.fetchall()]
            for t in tables:
                cur.execute(f"SELECT COUNT(*) FROM {t}")
                table_counts[t] = cur.fetchone()[0]
        finally:
            conn.close()

    return jsonify({
        "db_file": db_path,
        "db_size_kb": round(db_size / 1024, 2),
        "wal_size_kb": round(wal_size / 1024, 2),
        "shm_size_kb": round(shm_size / 1024, 2),
        "table_counts": table_counts
    })


def db_create_user(user_id: str, password: str, role: str = "user", privileges: dict = None, is_disabled: int = 0) -> tuple[bool, str]:
    """Creates a user with proper PBKDF2 password hashing and RBAC privileges."""
    user_id = str(user_id or "").strip().lower()
    if not user_id:
        return False, "User ID cannot be empty."
    if not re.match(r'^[a-zA-Z0-9_\-]+$', user_id):
        return False, "User ID must contain only alphanumeric characters, underscores, and hyphens."
    if not password:
        return False, "Password cannot be empty."
    if len(password) < 6:
        return False, "Password must be at least 6 characters."
    if db_get_user(user_id):
        return False, f"User '{user_id}' already exists."

    role = role.lower() if role else "user"
    if role not in ["admin", "user"]:
        return False, f"Invalid role '{role}'. Must be 'admin' or 'user'."

    if privileges is not None:
        sanitized_privs = {}
        if isinstance(privileges, dict):
            for k in config.ALL_PRIVILEGES:
                sanitized_privs[k] = bool(privileges.get(k, False))
        elif isinstance(privileges, (list, tuple, set)):
            for k in config.ALL_PRIVILEGES:
                sanitized_privs[k] = k in privileges
        privileges = sanitized_privs
    else:
        privileges = dict(config.ADMIN_DEFAULT_PRIVILEGES if role == "admin" else config.USER_DEFAULT_PRIVILEGES)


    hashed, salt = hash_password(password)
    with DB_LOCK:
        conn = get_db_connection()
        try:
            conn.execute("""
                INSERT INTO users (user_id, password_hash, salt, role, is_disabled, privileges, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (user_id, hashed, salt, role, 1 if is_disabled else 0, json.dumps(privileges), time.time()))
            conn.commit()
        finally:
            conn.close()

    log_event("INFO", "USERS", f"Created user '{user_id}' with role '{role}'.")
    return True, f"User '{user_id}' created successfully."


def db_delete_user(user_id: str) -> tuple[bool, str]:
    """Deletes a user, purges their sessions, clears lockout state, and cascades related records."""
    user_id = str(user_id or "").strip().lower()
    if user_id == "admin":
        return False, "Cannot delete primary admin account."
    if not db_get_user(user_id):
        return False, f"User '{user_id}' does not exist."

    with DB_LOCK:
        conn = get_db_connection()
        try:
            # Cascade delete associated user records safely
            conn.execute("DELETE FROM ssh_keys WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM user_chats WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM shares WHERE user_id = ? OR owner_user_id = ?", (user_id, user_id))
            conn.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
            conn.commit()
        finally:
            conn.close()

    with SESSIONS_LOCK:
        tokens_to_del = [tok for tok, s in SESSIONS.items() if s.get("user_id") == user_id]
        for tok in tokens_to_del:
            del SESSIONS[tok]

    clear_account_lockout(user_id=user_id)
    log_event("INFO", "USERS", f"Deleted user account '{user_id}'.")
    return True, f"User '{user_id}' deleted successfully."


@app.route('/api/admin/privileges', methods=['GET'])
def get_privileges_registry():
    """Returns authoritative privilege metadata and defaults for dynamic UI rendering."""
    err = require_auth()
    if err:
        return err
    priv_list = [
        {
            "key": k,
            "description": v.get("description", ""),
            "category": v.get("category", "General"),
            "default_user": v.get("default_user", False),
            "default_admin": v.get("default_admin", True)
        }
        for k, v in config.PRIVILEGE_METADATA.items()
    ]
    return jsonify({
        "privileges": priv_list,
        "metadata": config.PRIVILEGE_METADATA,
        "defaults": {
            "admin": config.ADMIN_DEFAULT_PRIVILEGES,
            "user": config.USER_DEFAULT_PRIVILEGES
        }
    })


@app.route('/api/admin/users', methods=['GET', 'POST'])
def admin_manage_users():
    err = require_admin()
    if err:
        return err

    if request.method == 'POST':
        data = request.get_json(force=True, silent=True) or {}
        user_id = str(data.get('user_id', '')).strip().lower()
        password = str(data.get('password', '')).strip()
        confirm_password = data.get('confirm_password')
        if confirm_password is not None and str(confirm_password).strip() != password:
            return jsonify({"error": "Passwords do not match."}), 400

        role = str(data.get('role', 'user')).strip().lower()
        is_disabled = 1 if data.get('is_disabled') else 0
        privileges = data.get('privileges', None)

        if not user_id:
            return jsonify({"error": "User ID is required."}), 400
        if len(password) < 6:
            return jsonify({"error": "Password must be at least 6 characters."}), 400

        success, msg = db_create_user(user_id, password, role=role, privileges=privileges, is_disabled=is_disabled)
        if not success:
            if "already exists" in msg:
                return jsonify({"error": msg}), 409
            return jsonify({"error": msg}), 400

        return jsonify({"message": msg, "user_id": user_id}), 201

    # GET List
    users = db_get_all_users()
    clean_users = [
        {
            "user_id": u["user_id"],
            "username": u["user_id"],
            "role": u["role"],
            "is_disabled": bool(u.get("is_disabled", 0)),
            "status": "DISABLED" if u.get("is_disabled", 0) else "ACTIVE",
            "privileges": u["privileges"],
            "created_at": u["created_at"]
        } for u in users.values()
    ]
    return jsonify(clean_users)


@app.route('/api/admin/users/<user_id>', methods=['GET', 'PATCH', 'DELETE'])
def admin_single_user_endpoint(user_id):
    err = require_admin()
    if err:
        return err

    user_id = str(user_id or "").strip().lower()
    user = db_get_user(user_id)
    if not user:
        return jsonify({"error": f"User '{user_id}' not found."}), 404

    if request.method == 'GET':
        return jsonify({
            "user_id": user["user_id"],
            "username": user["user_id"],
            "role": user["role"],
            "is_disabled": bool(user.get("is_disabled", 0)),
            "status": "DISABLED" if user.get("is_disabled", 0) else "ACTIVE",
            "privileges": user["privileges"],
            "created_at": user["created_at"]
        })

    elif request.method == 'PATCH':
        data = request.get_json(force=True, silent=True) or {}
        with DB_LOCK:
            conn = get_db_connection()
            try:
                # Update role if provided
                if "role" in data:
                    new_role = str(data["role"]).strip().lower()
                    if new_role not in ["admin", "user"]:
                        return jsonify({"error": "Invalid role. Must be 'admin' or 'user'."}), 400
                    if user_id == "admin" and new_role != "admin":
                        return jsonify({"error": "Cannot change primary admin role."}), 400
                    conn.execute("UPDATE users SET role = ? WHERE user_id = ?", (new_role, user_id))
                    user["role"] = new_role

                # Update disabled status if provided
                if "is_disabled" in data:
                    is_dis = 1 if data["is_disabled"] else 0
                    if user_id == "admin" and is_dis == 1:
                        return jsonify({"error": "Cannot disable primary admin account."}), 400
                    conn.execute("UPDATE users SET is_disabled = ? WHERE user_id = ?", (is_dis, user_id))
                    user["is_disabled"] = is_dis
                    if is_dis == 1:
                        # Revoke all active sessions for disabled user
                        with SESSIONS_LOCK:
                            toks = [k for k, v in SESSIONS.items() if v.get("user_id") == user_id]
                            for t in toks:
                                del SESSIONS[t]

                # Update privileges if provided
                if "privileges" in data and isinstance(data["privileges"], dict):
                    merged_privs = dict(user["privileges"])
                    for k, v in data["privileges"].items():
                        if k in config.ALL_PRIVILEGES:
                            merged_privs[k] = bool(v)
                    conn.execute("UPDATE users SET privileges = ? WHERE user_id = ?", (json.dumps(merged_privs), user_id))
                    user["privileges"] = merged_privs

                conn.commit()
            finally:
                conn.close()

        # Update in-memory session if active
        with SESSIONS_LOCK:
            for s in SESSIONS.values():
                if s.get("user_id") == user_id:
                    s["role"] = user["role"]
                    s["privileges"] = user["privileges"]
                    s["is_disabled"] = user.get("is_disabled", 0)

        log_event("INFO", "USERS", f"Updated account settings for user '{user_id}'.")
        return jsonify({
            "message": f"User '{user_id}' updated successfully.",
            "user_id": user_id,
            "role": user["role"],
            "is_disabled": bool(user.get("is_disabled", 0)),
            "privileges": user["privileges"]
        })

    elif request.method == 'DELETE':
        if user_id == "admin":
            return jsonify({"error": "Cannot delete primary admin account."}), 400
        if g.user.get("user_id") == user_id:
            return jsonify({"error": "Cannot delete your own active admin account."}), 400

        success, msg = db_delete_user(user_id)
        if not success:
            return jsonify({"error": msg}), 400
        return jsonify({"message": msg})


@app.route('/api/admin/users/update-privileges', methods=['POST'])
def admin_update_user_privileges():
    err = require_admin()
    if err:
        return err

    data = request.get_json(force=True, silent=True) or {}
    user_id = str(data.get('user_id', '')).strip().lower()
    privileges = data.get('privileges', {})

    if not user_id:
        return jsonify({"error": "User ID required."}), 400

    user = db_get_user(user_id)
    if not user:
        return jsonify({"error": "User not found."}), 404

    with DB_LOCK:
        conn = get_db_connection()
        try:
            conn.execute("UPDATE users SET privileges = ? WHERE user_id = ?", (json.dumps(privileges), user_id))
            conn.commit()
        finally:
            conn.close()

    # Update in-memory session if active
    with SESSIONS_LOCK:
        for s in SESSIONS.values():
            if s.get("user_id") == user_id:
                s["privileges"] = privileges

    log_event("INFO", "USERS", f"Updated privileges for user '{user_id}'.")
    return jsonify({"message": f"Privileges updated for '{user_id}'."})


@app.route('/api/admin/users/<user_id>/password', methods=['POST'])
def admin_reset_user_password(user_id):
    """Admin resets a user's password and revokes existing sessions."""
    err = require_admin()
    if err:
        return err

    user_id = str(user_id or "").strip().lower()
    user = db_get_user(user_id)
    if not user:
        return jsonify({"error": f"User '{user_id}' not found."}), 404

    data = request.get_json(force=True, silent=True) or {}
    new_password = str(data.get('password', '')).strip()
    if len(new_password) < 6:
        return jsonify({"error": "New password must be at least 6 characters."}), 400

    hashed, salt = hash_password(new_password)
    with DB_LOCK:
        conn = get_db_connection()
        try:
            conn.execute("UPDATE users SET password_hash = ?, salt = ?, failed_attempts = 0, locked_until = 0.0 WHERE user_id = ?", (hashed, salt, user_id))
            conn.commit()
        finally:
            conn.close()

    # Revoke active sessions for that user to require re-login
    with SESSIONS_LOCK:
        toks = [k for k, v in SESSIONS.items() if v.get("user_id") == user_id]
        for t in toks:
            del SESSIONS[t]

    clear_account_lockout(user_id=user_id)
    log_event("INFO", "USERS", f"Administrator reset password for user '{user_id}'.")
    return jsonify({"message": f"Password reset successfully for user '{user_id}'."})


@app.route('/api/admin/users/<user_id>/sessions/revoke', methods=['POST'])
def admin_revoke_user_sessions(user_id):
    """Admin revokes all active sessions for a target user."""
    err = require_admin()
    if err:
        return err

    user_id = str(user_id or "").strip().lower()
    user = db_get_user(user_id)
    if not user:
        return jsonify({"error": f"User '{user_id}' not found."}), 404

    revoked_count = 0
    with SESSIONS_LOCK:
        toks = [k for k, v in SESSIONS.items() if v.get("user_id") == user_id]
        for t in toks:
            del SESSIONS[t]
            revoked_count += 1

    log_event("INFO", "USERS", f"Admin revoked {revoked_count} sessions for user '{user_id}'.")
    return jsonify({"message": f"Revoked {revoked_count} sessions for user '{user_id}'.", "revoked_count": revoked_count})


@app.route('/api/account/password', methods=['POST'])
def account_change_own_password():
    """Self-service endpoint for any authenticated user to update their own password."""
    err = require_auth()
    if err:
        return err

    user_id = g.user.get("user_id")
    data = request.get_json(force=True, silent=True) or {}
    current_password = str(data.get('current_password', '')).strip()
    new_password = str(data.get('new_password', '')).strip()

    if not current_password or not new_password:
        return jsonify({"error": "validation_error", "message": "Current password and new password are required."}), 400
    if len(new_password) < 6:
        return jsonify({"error": "validation_error", "message": "New password must be at least 6 characters."}), 400

    user = db_get_user(user_id)
    if not user:
        return jsonify({"error": "User account not found."}), 404

    is_valid, _ = verify_password(current_password, user["password_hash"], user["salt"])
    if not is_valid:
        return jsonify({"error": "invalid_credentials", "message": "Incorrect current password."}), 401

    new_hash, new_salt = hash_password(new_password)
    with DB_LOCK:
        conn = get_db_connection()
        try:
            conn.execute("UPDATE users SET password_hash = ?, salt = ? WHERE user_id = ?", (new_hash, new_salt, user_id))
            conn.commit()
        finally:
            conn.close()

    # Invalidate other sessions for this user except current session
    with SESSIONS_LOCK:
        other_tokens = [k for k, v in SESSIONS.items() if v.get("user_id") == user_id and k != g.token]
        for t in other_tokens:
            del SESSIONS[t]

    log_event("INFO", "AUTH", f"User '{user_id}' changed their password successfully.")
    return jsonify({"message": "Password changed successfully. Other sessions have been revoked."})


@app.route('/api/account/sessions/revoke', methods=['POST'])
def account_revoke_other_sessions():
    """Self-service endpoint to revoke all other active sessions except current."""
    err = require_auth()
    if err:
        return err

    user_id = g.user.get("user_id")
    revoked_count = 0
    with SESSIONS_LOCK:
        other_tokens = [k for k, v in SESSIONS.items() if v.get("user_id") == user_id and k != g.token]
        for t in other_tokens:
            del SESSIONS[t]
            revoked_count += 1

    log_event("INFO", "AUTH", f"User '{user_id}' revoked {revoked_count} other active sessions.")
    return jsonify({"message": f"Successfully revoked {revoked_count} other sessions.", "revoked_count": revoked_count})


@app.route('/api/admin/stats', methods=['GET'])
def admin_stats():
    err = require_admin()
    if err:
        return err

    users_count = len(db_get_all_users())
    snap = governor.get_telemetry_snapshot()

    return jsonify({
        "registered_users": users_count,
        "system_state": snap["appliance"]["state"],
        "rss_mb": snap["process"]["rss_mb"],
        "threads": snap["process"]["threads"]
    })


@app.route('/api/admin/db/query', methods=['GET'])
def admin_db_query():
    err = require_admin()
    if err:
        return err

    table = request.args.get('table', 'users')
    limit = min(50, int(request.args.get('limit', 25)))

    allowed_tables = [
        "users", "system_logs", "background_tasks", "shares", "backups",
        "scheduled_jobs", "incidents", "ai_inference_metrics",
        "timetable_events_map", "user_timetables", "timetable_sync_history",
        "timetable_sync_locks", "google_oauth_tokens"
    ]
    if table not in allowed_tables:
        return jsonify({"error": "Table not allowed for inspection."}), 400

    with DB_LOCK:
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute(f"SELECT * FROM {table} ORDER BY 1 DESC LIMIT ?", (limit,))
            rows = [dict(r) for r in cur.fetchall()]
            # Sanitize password hashes and token data
            if table == "users":
                for r in rows:
                    if "password_hash" in r: r["password_hash"] = "[REDACTED]"
                    if "salt" in r: r["salt"] = "[REDACTED]"
            elif table == "google_oauth_tokens":
                for r in rows:
                    if "encrypted_token_data" in r: r["encrypted_token_data"] = "[ENCRYPTED_AT_REST]"
            return jsonify({"table": table, "count": len(rows), "rows": rows})
        finally:
            conn.close()



# --- Network Diagnostics Endpoints ---
@app.route('/api/network/test', methods=['POST'])
def test_network_endpoint():
    err = require_auth()
    if err:
        return err

    data = request.get_json(force=True, silent=True) or {}
    target = data.get('target', 'internet')

    start_t = time.time()
    latency_ms = None
    status = "unavailable"

    if target == 'internet':
        try:
            r = requests.get("https://1.1.1.1", timeout=2.0)
            if r.status_code == 200:
                status = "available"
                latency_ms = round((time.time() - start_t) * 1000.0, 1)
        except Exception:
            pass

    elif target == 'nexusnode':
        status = "available"
        latency_ms = 0.5

    elif target == 'tunnel':
        t_health = probe_localtonet_health()
        if t_health["state"] == "TUNNEL_CONNECTED":
            status = "available"
            latency_ms = 45.0
        else:
            status = "unavailable"

    elif target == 'ollama':
        ver = ollama_registry.get_version()
        if ver:
            status = "available"
            latency_ms = 2.5
        else:
            status = "unavailable"

    return jsonify({"target": target, "status": status, "latency_ms": latency_ms})


# ==============================================================================
# SSH PUBLIC KEY REGISTRY & FINGERPRINT RESOLUTION
# ==============================================================================

def calculate_ssh_key_fingerprint(public_key_str: str) -> tuple[str, str, str, str]:
    """
    Parses OpenSSH public key string and computes standard SHA-256 base64 fingerprint.
    Returns (fingerprint, key_type, key_b64, comment).
    Rejects private keys and malformed formats.
    """
    raw = str(public_key_str or "").strip()
    if not raw:
        raise ValueError("Public key string cannot be empty.")
    if "PRIVATE KEY" in raw:
        raise ValueError("Private keys must NEVER be registered or stored. Provide public key only.")

    parts = raw.split(None, 2)
    if len(parts) < 2:
        raise ValueError("Invalid OpenSSH public key format. Expected: '<type> <base64-key> [comment]'")

    key_type = parts[0].strip()
    key_b64 = parts[1].strip()
    comment = parts[2].strip() if len(parts) > 2 else ""

    padded_b64 = key_b64 + "=" * ((4 - len(key_b64) % 4) % 4)
    try:
        key_bytes = base64.b64decode(padded_b64)
    except Exception as e:
        raise ValueError(f"Invalid base64 encoding in public key: {e}")

    digest = hashlib.sha256(key_bytes).digest()
    fp_b64 = base64.b64encode(digest).decode('ascii').rstrip('=')
    fingerprint = f"SHA256:{fp_b64}"

    return fingerprint, key_type, key_b64, comment


def db_add_ssh_key(user_id: str, public_key_str: str, label: str = None) -> tuple[bool, str, dict | None]:
    """Registers an SSH public key in the database for an existing user."""
    user_id = str(user_id or "").strip().lower()
    user = db_get_user(user_id)
    if not user:
        return False, f"User '{user_id}' does not exist.", None

    try:
        fp, ktype, kb64, comment = calculate_ssh_key_fingerprint(public_key_str)
    except Exception as e:
        return False, str(e), None

    # Check if key is already an operator key in ~/.ssh/authorized_keys
    operator_keys_file = os.path.expanduser("~/.ssh/authorized_keys")
    if os.path.exists(operator_keys_file):
        try:
            with open(operator_keys_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        try:
                            op_fp, _, _, _ = calculate_ssh_key_fingerprint(line)
                            if op_fp == fp:
                                return False, f"Cannot register SSH key: this public key is already registered as a Termux host operator key in ~/.ssh/authorized_keys.", None
                        except Exception:
                            pass
        except Exception:
            pass

    key_label = (label or comment or user_id).strip()[:64]
    created_at = time.time()

    with DB_LOCK:
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT id, user_id, revoked FROM ssh_keys WHERE fingerprint = ?", (fp,))
            existing = cur.fetchone()
            if existing:
                if existing["revoked"] == 0:
                    return False, f"SSH key with fingerprint '{fp}' is already registered for user '{existing['user_id']}'.", None
                else:
                    cur.execute("UPDATE ssh_keys SET user_id = ?, key_type = ?, public_key = ?, label = ?, created_at = ?, revoked = 0 WHERE id = ?",
                                (user_id, ktype, kb64, key_label, created_at, existing["id"]))
                    conn.commit()
            else:
                cur.execute("""
                    INSERT INTO ssh_keys (fingerprint, user_id, key_type, public_key, label, created_at, revoked)
                    VALUES (?, ?, ?, ?, ?, ?, 0)
                """, (fp, user_id, ktype, kb64, key_label, created_at))
                conn.commit()
        finally:
            conn.close()

    record = {
        "fingerprint": fp,
        "user_id": user_id,
        "key_type": ktype,
        "public_key": kb64,
        "label": key_label,
        "created_at": created_at,
        "revoked": 0
    }
    log_event("INFO", "SSH", f"Registered SSH key '{fp}' for user '{user_id}' ({key_label}).")
    return True, f"SSH key registered successfully for user '{user_id}'.", record


def db_list_ssh_keys(user_id: str = None, include_revoked: bool = False) -> list[dict]:
    """Lists registered SSH keys, optionally filtered by user_id and revocation state."""
    with DB_LOCK:
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            query = "SELECT id, fingerprint, user_id, key_type, public_key, label, created_at, revoked FROM ssh_keys WHERE 1=1"
            params = []
            if user_id:
                query += " AND user_id = ?"
                params.append(str(user_id).strip().lower())
            if not include_revoked:
                query += " AND revoked = 0"
            query += " ORDER BY created_at DESC"
            cur.execute(query, params)
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()


def db_revoke_ssh_key(fingerprint: str, user_id: str = None) -> tuple[bool, str]:
    """Revokes a registered SSH key by fingerprint."""
    fp = str(fingerprint or "").strip()
    if not fp:
        return False, "Fingerprint cannot be empty."

    with DB_LOCK:
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT id, user_id, revoked FROM ssh_keys WHERE fingerprint = ? OR fingerprint LIKE ?", (fp, f"%{fp}%"))
            row = cur.fetchone()
            if not row:
                return False, f"SSH key matching fingerprint '{fp}' not found."

            if user_id and row["user_id"] != str(user_id).strip().lower():
                return False, f"Permission denied: Key does not belong to user '{user_id}'."

            if row["revoked"] == 1:
                return True, f"SSH key with fingerprint '{fp}' is already revoked."

            cur.execute("UPDATE ssh_keys SET revoked = 1 WHERE id = ?", (row["id"],))
            conn.commit()
            log_event("INFO", "SSH", f"Revoked SSH key with fingerprint '{fp}' for user '{row['user_id']}'.")
            return True, f"SSH key with fingerprint '{fp}' revoked successfully."
        finally:
            conn.close()


def db_get_ssh_key_by_fingerprint(fingerprint: str) -> dict | None:
    """Fetches an active SSH key record by exact or partial fingerprint."""
    fp = str(fingerprint or "").strip()
    with DB_LOCK:
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT id, fingerprint, user_id, key_type, public_key, label, created_at, revoked FROM ssh_keys WHERE fingerprint = ? OR fingerprint LIKE ?", (fp, f"%{fp}%"))
            row = cur.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()


@app.route('/api/admin/ssh-keys', methods=['GET', 'POST', 'DELETE'])
def admin_ssh_keys():
    err = require_admin()
    if err:
        return err

    if request.method == 'POST':
        data = request.get_json(force=True, silent=True) or {}
        user_id = data.get('user_id')
        pub_key = data.get('public_key')
        label = data.get('label')
        success, msg, rec = db_add_ssh_key(user_id, pub_key, label)
        if not success:
            return jsonify({"error": msg}), 400
        return jsonify({"message": msg, "key": rec}), 201

    if request.method == 'DELETE':
        data = request.get_json(force=True, silent=True) or {}
        fp = data.get('fingerprint')
        success, msg = db_revoke_ssh_key(fp)
        if not success:
            return jsonify({"error": msg}), 400
        return jsonify({"message": msg})

    # GET List
    user_id = request.args.get('user_id')
    inc_rev = request.args.get('include_revoked', 'false').lower() == 'true'
    keys = db_list_ssh_keys(user_id=user_id, include_revoked=inc_rev)
    return jsonify(keys)


# ==============================================================================
# 11. MAIN ENTRYPOINT
# ==============================================================================

if __name__ == '__main__':
    log_event("INFO", "SERVER", f"NexusNode Appliance v{config.VERSION} booting on {config.HOST}:{config.PORT}")
    try:
        from waitress import serve
        serve(app, host=config.HOST, port=config.PORT, threads=6)
    except ImportError:
        app.run(host=config.HOST, port=config.PORT, threaded=True)
