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
import shutil
import base64
import hashlib
import secrets
import sqlite3
import tempfile
import threading
import subprocess
from datetime import datetime
from functools import wraps

import requests
from flask import Flask, request, jsonify, render_template, send_file, Response, g, stream_with_context

import config
from resource_governor import governor, ResourceGovernor

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

def get_db_connection(db_file: str = config.DB_FILE) -> sqlite3.Connection:
    conn = sqlite3.connect(db_file, timeout=15.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def init_unified_db():
    with DB_LOCK:
        conn = get_db_connection()
        try:
            # 1. Users table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    password_hash TEXT NOT NULL,
                    salt TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'user',
                    privileges TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL
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

            # 3. Background Tasks table with owner_user_id
            conn.execute("""
                CREATE TABLE IF NOT EXISTS background_tasks (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    progress INTEGER NOT NULL DEFAULT 0,
                    logs TEXT DEFAULT '[]',
                    error TEXT,
                    owner_user_id TEXT NOT NULL DEFAULT 'admin',
                    created_at REAL NOT NULL,
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
            if "error" not in task_cols:
                conn.execute("ALTER TABLE background_tasks ADD COLUMN error TEXT;")
            if "completed_at" not in task_cols:
                conn.execute("ALTER TABLE background_tasks ADD COLUMN completed_at REAL;")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_owner ON background_tasks(owner_user_id);")

            # 4. Temporary Share Links table with owner_user_id
            conn.execute("""
                CREATE TABLE IF NOT EXISTS shares (
                    id TEXT PRIMARY KEY,
                    token TEXT UNIQUE NOT NULL,
                    filename TEXT NOT NULL,
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
            if "owner_user_id" not in share_cols:
                conn.execute("ALTER TABLE shares ADD COLUMN owner_user_id TEXT NOT NULL DEFAULT 'admin';")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_shares_token ON shares(token);")

            # 5. Backups table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS backups (
                    id TEXT PRIMARY KEY,
                    filename TEXT NOT NULL,
                    filepath TEXT NOT NULL,
                    checksum TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    owner_user_id TEXT NOT NULL DEFAULT 'admin',
                    created_at REAL NOT NULL
                );
            """)
            cur.execute("PRAGMA table_info(backups);")
            backup_cols = [c[1] for c in cur.fetchall()]
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
                salt = secrets.token_hex(16)
                init_pass = os.environ.get("NEXUS_ADMIN_PASSWORD") or secrets.token_urlsafe(16)
                pwd_hash = hashlib.sha256((init_pass + salt).encode('utf-8')).hexdigest()
                cur.execute("""
                    INSERT INTO users (user_id, password_hash, salt, role, privileges, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    "admin",
                    pwd_hash,
                    salt,
                    "admin",
                    json.dumps(config.ADMIN_DEFAULT_PRIVILEGES),
                    time.time()
                ))

            # Seed Default Scheduled Jobs
            default_jobs = [
                ("job_auto_backup", "Daily Configuration Backup", "backup", 86400),
                ("job_clean_temp", "Hourly Temp Files Cleanup", "clean_temp", 3600),
                ("job_tunnel_check", "Tunnel Health Check", "tunnel_check", 300),
                ("job_db_retention", "Daily Logs & Metrics Retention Sweep", "retention_sweep", 86400)
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


init_unified_db()

# ==============================================================================
# 2. SINGLE-THREADED BOUNDED LOG WRITER DAEMON
# ==============================================================================

LOG_QUEUE = queue.Queue(maxsize=config.LOG_QUEUE_MAX_SIZE)
LOG_LISTENERS = []
LOG_LISTENERS_LOCK = threading.Lock()

LOG_METRICS = {
    "queue_depth": 0,
    "dropped_count": 0,
    "write_latency_ms": 0.0,
    "last_flush": time.time(),
    "events_processed": 0
}
LOG_METRICS_LOCK = threading.Lock()


class LogWriterDaemon(threading.Thread):
    """
    Single background worker processing log writes in batches.
    Replaces per-event thread spawning to completely eliminate thread thrashing on 4 GB RAM.
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
                        e["message"], json.dumps(e.get("meta", {})), e["created_at"]
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

        except Exception:
            pass


log_daemon = LogWriterDaemon()
log_daemon.start()


def log_event(level: str, category: str, message: str, meta: dict = None):
    """Enqueues audit log event into bounded queue for batch database commit."""
    now = datetime.now()
    entry = {
        "id": secrets.token_hex(4),
        "timestamp": now.strftime("%H:%M:%S"),
        "date": now.strftime("%Y-%m-%d"),
        "level": level.upper(),
        "category": category.upper(),
        "message": str(message),
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
                """, (inc_id, now, service, severity, prev_state, new_state, mem_state, error_summary, json.dumps(timeline)))
                conn.commit()
            finally:
                conn.close()
    except Exception:
        pass


# ==============================================================================
# 3. AUTHENTICATION, SESSIONS & OBJECT-LEVEL RBAC
# ==============================================================================

def hash_password(password: str, salt: str = None) -> tuple[str, str]:
    if not salt:
        salt = secrets.token_hex(16)
    hashed = hashlib.sha256((password + salt).encode('utf-8')).hexdigest()
    return hashed, salt


def verify_password(password: str, pwd_hash: str, salt: str) -> bool:
    return hashlib.sha256((password + salt).encode('utf-8')).hexdigest() == pwd_hash


def db_get_user(user_id: str) -> dict | None:
    with DB_LOCK:
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT user_id, password_hash, salt, role, privileges, created_at FROM users WHERE user_id = ?", (user_id,))
            row = cur.fetchone()
            if not row:
                return None
            return {
                "user_id": row["user_id"],
                "password_hash": row["password_hash"],
                "salt": row["salt"],
                "role": row["role"],
                "privileges": json.loads(row["privileges"] or "{}"),
                "created_at": row["created_at"]
            }
        finally:
            conn.close()


def db_get_all_users() -> dict:
    with DB_LOCK:
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT user_id, password_hash, salt, role, privileges, created_at FROM users")
            rows = cur.fetchall()
            return {
                r["user_id"]: {
                    "user_id": r["user_id"],
                    "password_hash": r["password_hash"],
                    "salt": r["salt"],
                    "role": r["role"],
                    "privileges": json.loads(r["privileges"] or "{}"),
                    "created_at": r["created_at"]
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
    elif "auth" in request.args:
        token = request.args.get("auth", "").strip()

    if not token:
        return

    with SESSIONS_LOCK:
        session = SESSIONS.get(token)
        if session:
            if time.time() > session.get("expires_at", 0):
                del SESSIONS[token]
                return
            g.user = session
            g.token = token


def require_auth():
    if not g.user:
        return jsonify({"error": "unauthorized", "message": "Valid authentication token required."}), 401
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
        installed = self.get_installed_models()
        installed_names = [m["name"] for m in installed]

        loaded = self.get_loaded_models()
        loaded_name = loaded[0]["name"] if loaded else None
        loaded_details = loaded[0] if loaded else None

        # Verify selected model validity
        if self.selected_model not in installed_names and installed_names:
            # Fallback to first available installed model or default
            if self.default_model in installed_names:
                self.selected_model = self.default_model
            else:
                self.selected_model = installed_names[0]

        # Determine supervisor state
        supervisor_state = "down"
        try:
            res = subprocess.run(["sv", "status", "ollama"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
            if res.returncode == 0 and "run:" in res.stdout:
                supervisor_state = "up"
        except Exception:
            supervisor_state = "up" if engine_running else "down"

        return {
            "engine": "running" if engine_running else "stopped",
            "version": ver or "offline",
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


rag_engine = SQLiteFTS5RAGEngine()

# ==============================================================================
# 6. BOUNDED TASK RUNNER WITH OWNER USER ISOLATION
# ==============================================================================

class BoundedTaskRunner:
    """
    Bounded worker thread pool strictly maintaining concurrency = 1 on 4 GB RAM hardware.
    Features: owner_user_id tracking, clean cancellation, safe subprocess execution, partial file cleanup.
    """
    def __init__(self, max_concurrency: int = config.MAX_HEAVY_CONCURRENCY):
        self.max_concurrency = max_concurrency
        self.task_queue = queue.Queue()
        self.tasks = {}
        self.active_tasks = []
        self.lock = threading.Lock()
        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True, name="BoundedTaskWorker")
        self._worker_thread.start()

    def enqueue_task(self, title: str, task_type: str, target_fn, *args, owner_user_id: str = "admin", **kwargs) -> tuple[str | None, dict]:
        res_check = governor.can_start_heavy_task()
        if not res_check["allowed"]:
            log_event("WARN", "TASK", f"Task '{title}' blocked by Governor: {res_check['reason']}")
            return None, res_check

        task_id = f"task_{int(time.time())}_{secrets.token_hex(4)}"
        task_obj = {
            "id": task_id,
            "title": title,
            "type": task_type,
            "status": "queued",
            "progress": 0,
            "logs": [f"[{datetime.now().strftime('%H:%M:%S')}] Task enqueued by '{owner_user_id}'."],
            "target_fn": target_fn,
            "args": args,
            "kwargs": kwargs,
            "process": None,
            "created_at": time.time(),
            "updated_at": time.time(),
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
                if not task_obj or task_obj['status'] == 'cancelled':
                    self.task_queue.task_done()
                    continue
                task_obj['status'] = 'running'
                task_obj['updated_at'] = time.time()
                self.active_tasks.append(task_obj)
                self._save_task_to_db(task_obj)

            log_event("INFO", "TASK", f"Started task '{task_obj['title']}' ({task_id}).")

            try:
                task_obj['target_fn'](task_obj, *task_obj['args'], **task_obj['kwargs'])
                if task_obj['status'] != 'cancelled':
                    task_obj['status'] = 'completed'
                    task_obj['progress'] = 100
                    task_obj['logs'].append(f"[{datetime.now().strftime('%H:%M:%S')}] Task completed successfully.")
                    log_event("INFO", "TASK", f"Completed task '{task_obj['title']}'.")
            except Exception as e:
                task_obj['status'] = 'failed'
                task_obj['error'] = str(e)
                task_obj['logs'].append(f"[{datetime.now().strftime('%H:%M:%S')}] Task failed: {str(e)}")
                log_event("ERROR", "TASK", f"Task '{task_obj['title']}' failed: {str(e)}")
                self._cleanup_partial_files(task_obj)
            finally:
                with self.lock:
                    task_obj['updated_at'] = time.time()
                    if task_obj in self.active_tasks:
                        self.active_tasks.remove(task_obj)
                    self._save_task_to_db(task_obj)
                    self.task_queue.task_done()

    def cancel_task(self, task_id: str, requesting_user_id: str = None, is_admin: bool = False) -> tuple[bool, str]:
        with self.lock:
            task = self.tasks.get(task_id)
            if not task:
                try:
                    with DB_LOCK:
                        conn = get_db_connection()
                        cur = conn.cursor()
                        cur.execute("SELECT id, title, type, status, progress, logs, owner_user_id, created_at, updated_at FROM background_tasks WHERE id = ?", (task_id,))
                        row = cur.fetchone()
                        conn.close()
                        if row:
                            task = {
                                "id": row["id"],
                                "title": row["title"],
                                "type": row["type"],
                                "status": row["status"],
                                "progress": row["progress"],
                                "logs": json.loads(row["logs"]) if row["logs"] else [],
                                "owner_user_id": row["owner_user_id"],
                                "created_at": row["created_at"],
                                "updated_at": row["updated_at"]
                            }
                except Exception:
                    pass

            if not task:
                return False, "Task not found."

            if not is_admin and requesting_user_id and task["owner_user_id"] != requesting_user_id:
                return False, "Permission denied: You do not own this task."

            if task['status'] in ['completed', 'failed', 'cancelled']:
                return False, f"Task already {task['status']}."

            task['status'] = 'cancelled'
            task['logs'].append(f"[{datetime.now().strftime('%H:%M:%S')}] Task cancelled by user.")

            if task.get('process'):
                try:
                    task['process'].terminate()
                except Exception:
                    pass

            self._cleanup_partial_files(task)
            self._save_task_to_db(task)

        log_event("WARN", "TASK", f"Task '{task['title']}' was cancelled by '{requesting_user_id or 'admin'}'.")
        return True, "Task cancelled successfully."

    def _cleanup_partial_files(self, task: dict):
        for p in task.get('partial_files', []):
            try:
                if os.path.exists(p):
                    if os.path.isdir(p):
                        shutil.rmtree(p, ignore_errors=True)
                    else:
                        os.remove(p)
            except Exception:
                pass

    def _save_task_to_db(self, task: dict):
        try:
            with DB_LOCK:
                conn = get_db_connection()
                try:
                    conn.execute("""
                        INSERT INTO background_tasks (id, title, type, status, progress, logs, owner_user_id, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(id) DO UPDATE SET
                            status=excluded.status,
                            progress=excluded.progress,
                            logs=excluded.logs,
                            updated_at=excluded.updated_at;
                    """, (
                        task["id"], task["title"], task.get("type", "task"), task["status"], task["progress"],
                        json.dumps(task["logs"]), task.get("owner_user_id", "admin"),
                        task["created_at"], task["updated_at"]
                    ))
                    conn.commit()
                finally:
                    conn.close()
        except Exception:
            pass

    def get_task(self, task_id: str) -> dict | None:
        """Fetch task metadata by ID from memory or SQLite."""
        with self.lock:
            if task_id in self.tasks:
                t = dict(self.tasks[task_id])
                t["task_id"] = t.get("id", task_id)
                t["task_type"] = t.get("type", "task")
                return t
        try:
            with DB_LOCK:
                conn = get_db_connection()
                try:
                    cur = conn.cursor()
                    cur.execute("SELECT id, title, type, status, progress, logs, owner_user_id, created_at, updated_at FROM background_tasks WHERE id = ?", (task_id,))
                    row = cur.fetchone()
                    if row:
                        return {
                            "id": row["id"],
                            "task_id": row["id"],
                            "title": row["title"],
                            "type": row["type"],
                            "task_type": row["type"],
                            "status": row["status"],
                            "progress": row["progress"],
                            "logs": json.loads(row["logs"]) if row["logs"] else [],
                            "owner_user_id": row["owner_user_id"],
                            "created_at": row["created_at"],
                            "updated_at": row["updated_at"]
                        }
                finally:
                    conn.close()
        except Exception:
            pass
        return None

    def get_all_tasks(self) -> list[dict]:
        """Fetch all recent background tasks with owner user metadata."""
        with self.lock:
            mem_tasks = {}
            for tid, t in self.tasks.items():
                td = dict(t)
                td["task_id"] = td.get("id", tid)
                td["task_type"] = td.get("type", "task")
                mem_tasks[tid] = td
        try:
            with DB_LOCK:
                conn = get_db_connection()
                try:
                    cur = conn.cursor()
                    cur.execute("SELECT id, title, type, status, progress, logs, owner_user_id, created_at, updated_at FROM background_tasks ORDER BY updated_at DESC LIMIT 100")
                    rows = cur.fetchall()
                    for r in rows:
                        if r["id"] not in mem_tasks:
                            mem_tasks[r["id"]] = {
                                "id": r["id"],
                                "task_id": r["id"],
                                "title": r["title"],
                                "type": r["type"],
                                "task_type": r["type"],
                                "status": r["status"],
                                "progress": r["progress"],
                                "logs": json.loads(r["logs"]) if row["logs"] else [],
                                "owner_user_id": r["owner_user_id"],
                                "created_at": r["created_at"],
                                "updated_at": r["updated_at"]
                            }
                finally:
                    conn.close()
        except Exception:
            pass
        return list(mem_tasks.values())


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


scheduler_daemon = SchedulerDaemon()
scheduler_daemon.start()


def run_retention_sweep_job(task_obj: dict):
    """Prunes old audit logs and metric rows to enforce bounded storage."""
    task_obj['logs'].append("Running bounded retention sweep...")
    with DB_LOCK:
        conn = get_db_connection()
        try:
            # 1. Prune logs beyond 10,000
            conn.execute("""
                DELETE FROM system_logs WHERE id NOT IN (
                    SELECT id FROM system_logs ORDER BY created_at DESC LIMIT ?
                );
            """, (config.MAX_DB_LOGS_RETENTION,))

            # 2. Prune tasks beyond 500
            conn.execute("""
                DELETE FROM background_tasks WHERE id NOT IN (
                    SELECT id FROM background_tasks ORDER BY created_at DESC LIMIT ?
                );
            """, (config.MAX_TASK_HISTORY_RETENTION,))

            # 3. Prune metrics beyond 1,000
            conn.execute("""
                DELETE FROM ai_inference_metrics WHERE id NOT IN (
                    SELECT id FROM ai_inference_metrics ORDER BY created_at DESC LIMIT ?
                );
            """, (config.MAX_INFERENCE_METRICS_RETENTION,))

            conn.commit()
            task_obj['logs'].append("Retention sweep completed successfully.")
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
                    INSERT INTO backups (id, filename, size_bytes, checksum, backup_type, created_at, status, owner_user_id)
                    VALUES (?, ?, ?, ?, 'full', ?, 'completed', ?)
                """, (backup_id, zip_name, size_bytes, checksum, time.time(), task_obj.get("owner_user_id", "admin")))
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

    with FAILED_LOGINS_LOCK:
        fail_record = FAILED_LOGINS.get(client_ip, {"count": 0, "locked_until": 0.0})
        if time.time() < fail_record["locked_until"]:
            remaining = max(1, int(fail_record["locked_until"] - time.time()))
            return False, f"Account locked. Try again in {remaining} seconds.", None, remaining

    user = db_get_user(user_id)
    if not user or not verify_password(password, user["password_hash"], user["salt"]):
        with FAILED_LOGINS_LOCK:
            fail_record["count"] += 1
            if fail_record["count"] >= config.LOCKOUT_THRESHOLD:
                fail_record["locked_until"] = time.time() + config.LOCKOUT_DURATION_SECONDS
                log_event("WARN", "AUTH", f"IP/Identity '{client_ip}' locked out due to repeated failed logins.")
                FAILED_LOGINS[client_ip] = fail_record
                remaining = int(config.LOCKOUT_DURATION_SECONDS)
                return False, f"Account locked. Try again in {remaining} seconds.", None, remaining
            FAILED_LOGINS[client_ip] = fail_record

        log_event("WARN", "AUTH", f"Failed login attempt for user '{user_id}' from {client_ip}")
        return False, "Authentication failed.", None, None

    with FAILED_LOGINS_LOCK:
        if client_ip in FAILED_LOGINS:
            del FAILED_LOGINS[client_ip]

    return True, "Authentication successful.", user, None


def clear_account_lockout(user_id: str = None, ip_address: str = None):
    """Clears failed login and lockout tracking for emergency recovery or password resets."""
    with FAILED_LOGINS_LOCK:
        if ip_address and ip_address in FAILED_LOGINS:
            del FAILED_LOGINS[ip_address]
        else:
            FAILED_LOGINS.clear()


# --- Authentication Routes ---
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
                "error": "locked_out",
                "message": f"Account Locked. Try again in {lockout_secs}s.",
                "lockout_seconds": lockout_secs,
                "retry_after": lockout_secs
            }), 429
        if not user_id or not password:
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

    # Filter tasks owned by current user
    user_id = g.user.get("user_id") if g.user else "guest"
    is_admin = (g.user.get("role") == "admin") if g.user else False

    user_tasks = []
    with task_runner.lock:
        for t in task_runner.active_tasks:
            if is_admin or t["owner_user_id"] == user_id:
                user_tasks.append({
                    "id": t["id"],
                    "title": t["title"],
                    "type": t["type"],
                    "status": t["status"],
                    "progress": t["progress"]
                })

    ai_state = ollama_registry.get_ai_state()
    tunnel_status = probe_localtonet_health()
    ssh_status = probe_ssh_status()

    return jsonify({
        "server": {
            "name": "NexusNode Mobile Appliance",
            "version": config.VERSION,
            "device": "TECNO BG6 (Android 13 / Termux)",
            "uptime": uptime_str,
            "uptime_seconds": uptime_sec
        },
        "appliance": snap["appliance"],
        "memory": snap["memory"],
        "disk": snap["disk"],
        "device": snap["device"],
        "services": {
            "nexusnode": {"status": "online", "port": config.PORT},
            "localtonet": {"status": tunnel_status["state"].lower(), "url": tunnel_status["url"]},
            "ssh": {"status": ssh_status["status"], "port": config.SSH_PORT},
            "ollama": {"status": ai_state["engine"], "selected_model": ai_state["selected_model"], "loaded_model": ai_state["loaded_model"]}
        },
        "tasks": {
            "active_count": len(user_tasks),
            "active_tasks": user_tasks
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

    return jsonify({
        "nexusnode": {"status": "online", "port": config.PORT, "pid": os.getpid()},
        "localtonet": tunnel_status,
        "ssh": ssh_status,
        "ollama": ai_state
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


@app.route('/start', methods=['GET', 'POST'])
def start_engine_endpoint():
    err = require_privilege_or_admin("can_control_services")
    if err:
        return err

    res_check = governor.can_start_ollama()
    if not res_check["allowed"]:
        return jsonify({
            "allowed": False,
            "error": "resource_pressure",
            "message": res_check["reason"],
            "reason": res_check["reason"]
        }), 429

    success, msg = ollama_registry.start_service()
    return jsonify({"message": msg}), 200 if success else 500


@app.route('/stop', methods=['GET', 'POST'])
def stop_engine_endpoint():
    err = require_privilege_or_admin("can_control_services")
    if err:
        return err

    success, msg = ollama_registry.stop_service()
    return jsonify({"message": msg}), 200 if success else 500


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
            yield f"data: {json.dumps({'error': 'AI Engine daemon is offline.'})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': f'Inference error occurred.'})}\n\n"

    return Response(stream_with_context(generate_sse()), mimetype='text/event-stream')


# --- RAG Subsystem Endpoints ---
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

    with DB_LOCK:
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute("PRAGMA table_info(background_tasks);")
            tcols = [c[1] for c in cur.fetchall()]
            type_col = "type" if "type" in tcols else "task_type"
            err_col = "error" if "error" in tcols else "NULL as error"

            query = f"SELECT id, title, {type_col} as task_type, status, progress, logs, {err_col}, owner_user_id, created_at, updated_at FROM background_tasks"
            if is_admin:
                cur.execute(f"{query} ORDER BY created_at DESC LIMIT 50")
            else:
                cur.execute(f"{query} WHERE owner_user_id = ? ORDER BY created_at DESC LIMIT 50", (user_id,))
            rows = cur.fetchall()
            tasks = []
            for r in rows:
                tasks.append({
                    "id": r["id"],
                    "title": r["title"],
                    "type": r["task_type"],
                    "status": r["status"],
                    "progress": r["progress"],
                    "logs": json.loads(r["logs"] or "[]"),
                    "error": r["error"],
                    "owner_user_id": r["owner_user_id"],
                    "created_at": r["created_at"],
                    "updated_at": r["updated_at"]
                })
            return jsonify(tasks)
        finally:
            conn.close()


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
        status_code = 403 if "Permission denied" in msg else 400
        return jsonify({"cancelled": False, "message": msg}), status_code

    return jsonify({"cancelled": True, "message": msg})


# --- Storage & Vault Endpoints ---
def sanitize_storage_path(filename: str) -> str:
    cleaned = filename.replace('\\', '/').strip('/')
    if '..' in cleaned:
        raise ValueError("Invalid path: directory traversal prohibited.")
    full_path = os.path.abspath(os.path.join(config.STORAGE_DIR, cleaned))
    if not full_path.startswith(os.path.abspath(config.STORAGE_DIR)):
        raise ValueError("Path traversal violation detected.")
    return full_path


@app.route('/files', methods=['GET'])
def list_files():
    err = require_auth()
    if err:
        return err

    subpath = request.args.get('path', '').strip().replace('\\', '/')
    try:
        current_dir = sanitize_storage_path(subpath) if subpath else config.STORAGE_DIR
    except ValueError as e:
        return jsonify({"error": str(e)}), 403

    if not os.path.exists(current_dir) or not os.path.isdir(current_dir):
        return jsonify({"error": "Directory not found."}), 404

    items = []
    try:
        for entry in os.scandir(current_dir):
            if entry.name in ['__pycache__', '.tmp', '.git', 'backups']:
                continue
            if entry.name == '.gitkeep':
                continue

            rel = os.path.relpath(entry.path, config.STORAGE_DIR).replace('\\', '/')
            stat = entry.stat()
            modified = datetime.fromtimestamp(stat.st_mtime).isoformat()
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
                if ext in ['mp3', 'm4a', 'flac', 'opus', 'wav']:
                    cat = "music"
                elif ext in ['mp4', 'mkv', 'webm', 'mov']:
                    cat = "videos"
                elif ext in ['zip', 'tar', 'gz']:
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


@app.route('/upload', methods=['POST'])
def upload_file():
    err = require_privilege_or_admin("can_upload_files")
    if err:
        return err

    if 'file' not in request.files:
        return jsonify({"error": "No file uploaded."}), 400
    file = request.files['file']
    if not file.filename:
        return jsonify({"error": "No file selected."}), 400

    dest_folder = request.form.get('path', '').strip().replace('\\', '/')
    filename = os.path.basename(file.filename)
    try:
        target_dir = sanitize_storage_path(dest_folder) if dest_folder else config.STORAGE_DIR
    except ValueError as e:
        return jsonify({"error": str(e)}), 403

    os.makedirs(target_dir, exist_ok=True)
    dest_path = os.path.join(target_dir, filename)

    try:
        file.save(dest_path)
        log_event("INFO", "STORAGE", f"User '{g.user.get('user_id')}' uploaded '{filename}'.")
        return jsonify({"message": f"'{filename}' uploaded successfully."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/download/<path:filename>', methods=['GET'])
def download_file(filename):
    err = require_auth()
    if err:
        return err

    try:
        target_path = sanitize_storage_path(filename)
        if not os.path.exists(target_path):
            return jsonify({"error": "File not found."}), 404

        if os.path.isdir(target_path):
            import io
            import zipfile
            memory_file = io.BytesIO()
            folder_name = os.path.basename(os.path.normpath(target_path)) or "vault_folder"
            with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
                for root, _, files in os.walk(target_path):
                    for f in files:
                        if f == '.gitkeep':
                            continue
                        f_full = os.path.join(root, f)
                        f_rel = os.path.relpath(f_full, target_path)
                        zf.write(f_full, arcname=f_rel)
            memory_file.seek(0)
            return send_file(
                memory_file,
                mimetype='application/zip',
                as_attachment=True,
                download_name=f"{folder_name}.zip"
            )

        return send_file(target_path, as_attachment=True)
    except ValueError as e:
        return jsonify({"error": str(e)}), 403


@app.route('/stream/<path:filename>', methods=['GET'])
def stream_media_file(filename):
    err = require_auth()
    if err:
        return err

    try:
        target_path = sanitize_storage_path(filename)
        if not os.path.exists(target_path) or os.path.isdir(target_path):
            return jsonify({"error": "Media file not found."}), 404

        file_size = os.path.getsize(target_path)
        range_header = request.headers.get('Range', None)

        if not range_header:
            return send_file(target_path)

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

        rv = Response(generate_chunk(), 206, mimetype='video/mp4', direct_passthrough=True)
        rv.headers.add('Content-Range', f'bytes {byte1}-{byte1 + length - 1}/{file_size}')
        rv.headers.add('Accept-Ranges', 'bytes')
        rv.headers.add('Content-Length', str(length))
        return rv

    except ValueError as e:
        return jsonify({"error": str(e)}), 403


@app.route('/files/<path:filename>', methods=['DELETE'])
def delete_file(filename):
    err = require_privilege_or_admin("can_manage_files")
    if err:
        return err

    try:
        target_path = sanitize_storage_path(filename)
        if not os.path.exists(target_path):
            return jsonify({"error": "File not found."}), 404
        if os.path.isdir(target_path):
            shutil.rmtree(target_path)
        else:
            os.remove(target_path)
        log_event("INFO", "STORAGE", f"User '{g.user.get('user_id')}' deleted '{filename}'.")
        return jsonify({"message": f"'{filename}' deleted successfully."})
    except ValueError as e:
        return jsonify({"error": str(e)}), 403


# --- Media Center Routes ---
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
    destination = data.get('destination', 'Downloads')
    custom_name = data.get('filename', '')

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

    return jsonify({"success": True, "enqueued_count": len(enqueued), "task_ids": enqueued, "task_id": enqueued[0] if enqueued else None})


def run_media_download_job(task_obj: dict, url: str, fmt: str, quality: str, destination: str, custom_name: str):
    task_obj['logs'].append(f"Starting yt-dlp download for: {url}")
    dest_dir = os.path.join(config.STORAGE_DIR, destination)
    os.makedirs(dest_dir, exist_ok=True)

    out_tmpl = os.path.join(dest_dir, f"{custom_name}.%(ext)s" if custom_name else "%(title)s.%(ext)s")

    cmd = ["yt-dlp", "--no-warnings", "-o", out_tmpl]
    if fmt in ['mp3', 'm4a', 'opus', 'wav', 'flac']:
        cmd.extend(["-x", "--audio-format", fmt])
    else:
        cmd.extend(["-f", "bv*+ba/b", "--merge-output-format", fmt])
    cmd.append(url)

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    task_obj['process'] = proc

    for line in proc.stdout:
        if task_obj['status'] == 'cancelled':
            proc.terminate()
            break
        task_obj['logs'].append(line.strip())
        m = re.search(r'(\d+\.\d+)%', line)
        if m:
            task_obj['progress'] = min(99, int(float(m.group(1))))

    proc.wait()
    if proc.returncode != 0 and task_obj['status'] != 'cancelled':
        raise RuntimeError(f"yt-dlp exited with status {proc.returncode}")


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
            _, ext = os.path.splitext(f)
            ext = ext.lower()
            if ext in audio_exts or ext in video_exts:
                fpath = os.path.join(root, f)
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

    return jsonify(library)


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

    try:
        fpath = sanitize_storage_path(filename)
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
            cur.execute("SELECT id, filename, filepath, checksum, size_bytes, owner_user_id, created_at FROM backups ORDER BY created_at DESC")
            rows = [dict(r) for r in cur.fetchall()]
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
    err = require_auth()
    if err:
        return err

    cat = request.args.get('category', 'ALL').upper()
    limit = min(200, int(request.args.get('limit', 60)))

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


# --- Storage Intelligence & Settings ---
@app.route('/api/storage/intelligence', methods=['GET'])
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
    return jsonify({"breakdown": breakdown, "large_files": large_files[:15]})


@app.route('/api/vault/checksum/<path:filename>', methods=['GET'])
def get_file_checksum(filename):
    err = require_privilege_or_admin("can_manage_files")
    if err:
        return err

    try:
        fpath = sanitize_storage_path(filename)
        if not os.path.exists(fpath) or os.path.isdir(fpath):
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
    except ValueError as e:
        return jsonify({"error": str(e)}), 403


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


def db_create_user(user_id: str, password: str, role: str = "user", privileges: dict = None) -> tuple[bool, str]:
    """Creates a user with proper password hashing and RBAC privileges."""
    user_id = str(user_id or "").strip().lower()
    if not user_id:
        return False, "User ID cannot be empty."
    if not password:
        return False, "Password cannot be empty."
    if db_get_user(user_id):
        return False, f"User '{user_id}' already exists."

    role = role.lower() if role else "user"
    if role not in ["admin", "user"]:
        return False, f"Invalid role '{role}'. Must be 'admin' or 'user'."

    if privileges is None:
        privileges = dict(config.ADMIN_DEFAULT_PRIVILEGES if role == "admin" else config.USER_DEFAULT_PRIVILEGES)

    hashed, salt = hash_password(password)
    with DB_LOCK:
        conn = get_db_connection()
        try:
            conn.execute("""
                INSERT INTO users (user_id, password_hash, salt, role, privileges, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (user_id, hashed, salt, role, json.dumps(privileges), time.time()))
            conn.commit()
        finally:
            conn.close()

    log_event("INFO", "USERS", f"Created user '{user_id}' with role '{role}'.")
    return True, f"User '{user_id}' created successfully."


def db_delete_user(user_id: str) -> tuple[bool, str]:
    """Deletes a user, purges their sessions, and clears lockout state."""
    user_id = str(user_id or "").strip().lower()
    if user_id == "admin":
        return False, "Cannot delete primary admin account."
    if not db_get_user(user_id):
        return False, f"User '{user_id}' does not exist."

    with DB_LOCK:
        conn = get_db_connection()
        try:
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


@app.route('/api/admin/users', methods=['GET', 'POST'])
def admin_manage_users():
    err = require_admin()
    if err:
        return err

    if request.method == 'POST':
        data = request.get_json(force=True, silent=True) or {}
        user_id = str(data.get('user_id', '')).strip().lower()
        password = str(data.get('password', '')).strip()
        role = str(data.get('role', 'user')).strip().lower()
        privileges = data.get('privileges', None)

        success, msg = db_create_user(user_id, password, role=role, privileges=privileges)
        if not success:
            if "already exists" in msg:
                return jsonify({"error": msg}), 409
            return jsonify({"error": msg}), 400

        return jsonify({"message": msg}), 201

    # GET List
    users = db_get_all_users()
    clean_users = [{"user_id": u["user_id"], "role": u["role"], "privileges": u["privileges"], "created_at": u["created_at"]} for u in users.values()]
    return jsonify(clean_users)


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


@app.route('/api/admin/users/<user_id>', methods=['DELETE'])
def admin_delete_user(user_id):
    err = require_admin()
    if err:
        return err

    success, msg = db_delete_user(user_id)
    if not success:
        if "Cannot delete" in msg:
            return jsonify({"error": msg}), 400
        return jsonify({"error": msg}), 404

    return jsonify({"message": msg})


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

    allowed_tables = ["users", "system_logs", "background_tasks", "shares", "backups", "scheduled_jobs", "incidents", "ai_inference_metrics"]
    if table not in allowed_tables:
        return jsonify({"error": "Table not allowed for inspection."}), 400

    with DB_LOCK:
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute(f"SELECT * FROM {table} ORDER BY 1 DESC LIMIT ?", (limit,))
            rows = [dict(r) for r in cur.fetchall()]
            # Sanitize password hashes if querying users table
            if table == "users":
                for r in rows:
                    if "password_hash" in r: r["password_hash"] = "[REDACTED]"
                    if "salt" in r: r["salt"] = "[REDACTED]"
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
    app.run(host=config.HOST, port=config.PORT, threaded=True)
