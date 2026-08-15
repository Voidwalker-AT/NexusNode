"""
NexusNode — Personal Mobile Server Appliance & Hardened AI Vault
Engineered specifically for unrooted Android 13 Termux on ~4 GB RAM hardware (TECNO BG6).

Architecture Modules:
- Unified SQLite Database (WAL mode, index-optimized schema, safe backups)
- 4 GB RAM & Thermal Resource Governor (Hardware protection & bounded execution)
- Bounded Background Worker Queue (Strict concurrency limit = 1 for heavy jobs)
- Serialized & Asynchronous Local Document RAG (Zero-blocking startup, pending rebuilds)
- Media Center & Library (yt-dlp multi-format, quality, batch URLs, HTTP Range streaming)
- Cryptographic Temporary Share Links (Scoped tokens, expiration, revocation, download limits)
- Storage Intelligence & Safe Temp Cleanup (Categorized breakdown, large-file detection)
- Atomic Backup & Safe Restore (SHA-256 checksums, non-destructive validation)
- Network Diagnostics & Device Telemetry (Unprivileged port, gateway, tunnel latency tests)
- Incident Correlation & Categorized Events Engine (Service crash timeline analysis)
- Scheduled Automation Engine (Lightweight 60s background daemon feeding bounded worker)
- Granular Server-Side RBAC & Brute-Force Rate Limiter
- Production WSGI Server Support (Waitress multi-threading with streaming)
"""

import os
import re
import io
import json
import time
import queue
import shutil
import socket
import sqlite3
import zipfile
import tarfile
import secrets
import hashlib
import mimetypes
import threading
import subprocess
from datetime import datetime
import requests
from flask import Flask, request, jsonify, send_from_directory, Response, g, stream_with_context

import config
from resource_governor import governor

app = Flask(__name__, static_folder='static', static_url_path='/static')
app.config['SECRET_KEY'] = config.SECRET_KEY

# In-memory session store & lock
SESSIONS = {}
SESSIONS_LOCK = threading.Lock()

# Brute force tracking
FAILED_LOGINS = {}
FAILED_LOGINS_LOCK = threading.Lock()

# Global state tracking
SERVER_START_TIME = time.time()
LOG_LISTENERS = []
LOG_LISTENERS_LOCK = threading.Lock()
DB_LOCK = threading.Lock()

# Storage cache for storage intelligence (TTL: 60s)
STORAGE_CACHE = {"timestamp": 0, "data": None}
STORAGE_CACHE_LOCK = threading.Lock()


# ==============================================================================
# UNIFIED SQLITE DATABASE INITIALIZATION & MIGRATIONS
# ==============================================================================

def get_db_connection():
    conn = sqlite3.connect(config.DB_FILE, timeout=15.0)
    conn.row_factory = sqlite3.Row
    return conn


def hash_password(password: str, salt: str = None) -> tuple[str, str]:
    if not salt:
        salt = secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt.encode('utf-8'),
        100000
    ).hex()
    return hashed, salt


def verify_password(password: str, stored_hash: str, salt: str) -> bool:
    test_hash, _ = hash_password(password, salt)
    return secrets.compare_digest(test_hash, stored_hash)


def init_unified_db():
    """Initializes the complete SQL database schema with WAL mode & indexes."""
    with DB_LOCK:
        conn = get_db_connection()
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            
            # 1. Users Table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    password_hash TEXT NOT NULL,
                    salt TEXT NOT NULL,
                    role TEXT NOT NULL,
                    privileges TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
            """)

            # 2. User Chat Messages Table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_chats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    message TEXT NOT NULL,
                    citations TEXT,
                    created_at REAL NOT NULL
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_chat_user ON user_chats(user_id);")

            # 3. System Logs Table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS system_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    log_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    date TEXT NOT NULL,
                    level TEXT NOT NULL,
                    category TEXT NOT NULL,
                    message TEXT NOT NULL,
                    meta TEXT,
                    created_at REAL NOT NULL
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_logs_level ON system_logs(level);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_logs_category ON system_logs(category);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_logs_created ON system_logs(created_at);")

            # 4. Background Tasks Table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS background_tasks (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    progress INTEGER NOT NULL,
                    logs TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON background_tasks(status);")

            # 5. Temporary Secure Shares Table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS shares (
                    id TEXT PRIMARY KEY,
                    token TEXT UNIQUE NOT NULL,
                    filename TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    downloads_count INTEGER DEFAULT 0,
                    max_downloads INTEGER DEFAULT 0,
                    revoked INTEGER DEFAULT 0
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_shares_token ON shares(token);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_shares_user ON shares(user_id);")

            # 6. Backups Table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS backups (
                    id TEXT PRIMARY KEY,
                    filename TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    checksum TEXT NOT NULL,
                    backup_type TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    status TEXT NOT NULL
                );
            """)

            # 7. Scheduled Automation Jobs Table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS scheduled_jobs (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    job_type TEXT NOT NULL,
                    interval_seconds INTEGER NOT NULL,
                    enabled INTEGER DEFAULT 1,
                    last_run REAL,
                    next_run REAL,
                    last_status TEXT,
                    created_at REAL NOT NULL
                );
            """)

            # 8. Incident Correlation Table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS incidents (
                    id TEXT PRIMARY KEY,
                    service TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    prev_state TEXT,
                    new_state TEXT,
                    restart_count INTEGER DEFAULT 0,
                    memory_state TEXT,
                    error_summary TEXT,
                    timeline TEXT,
                    resolved INTEGER DEFAULT 0,
                    created_at REAL NOT NULL,
                    resolved_at REAL
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_incidents_service ON incidents(service);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_incidents_created ON incidents(created_at);")

            # Seed default automation jobs if table is empty
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM scheduled_jobs;")
            if cur.fetchone()[0] == 0:
                now = time.time()
                default_jobs = [
                    ("job_db_backup", "Daily SQLite & Config Backup", "backup", 86400, 1, 0, now + 86400, "ready", now),
                    ("job_temp_clean", "Weekly Safe Temp File Cleanup", "temp_cleanup", 604800, 1, 0, now + 604800, "ready", now),
                    ("job_tunnel_check", "6-Hour LocalToNet Tunnel Probe", "tunnel_check", 21600, 1, 0, now + 21600, "ready", now),
                    ("job_storage_check", "Hourly Storage Free Space Audit", "storage_check", 3600, 1, 0, now + 3600, "ready", now)
                ]
                conn.executemany("""
                    INSERT INTO scheduled_jobs (id, name, job_type, interval_seconds, enabled, last_run, next_run, last_status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, default_jobs)

            # Bootstrap Root Admin if no users exist
            cur.execute("SELECT COUNT(*) FROM users;")
            if cur.fetchone()[0] == 0:
                admin_pass = os.environ.get("NEXUS_ADMIN_PASSWORD")
                if not admin_pass:
                    admin_pass = secrets.token_urlsafe(12)
                    print(f"[*] Initialized first-run root admin account: 'admin'")

                admin_hash, admin_salt = hash_password(admin_pass)
                conn.execute("""
                    INSERT INTO users (user_id, password_hash, salt, role, privileges, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    "admin",
                    admin_hash,
                    admin_salt,
                    "admin",
                    json.dumps(config.ADMIN_DEFAULT_PRIVILEGES),
                    datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
                ))

            conn.commit()
        finally:
            conn.close()


init_unified_db()


# ==============================================================================
# AUDIT & EVENT LOGGING SUBSYSTEM
# ==============================================================================

def log_event(level: str, category: str, message: str, meta: dict = None):
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

    def db_writer():
        try:
            with DB_LOCK:
                conn = get_db_connection()
                try:
                    conn.execute("""
                        INSERT INTO system_logs (log_id, timestamp, date, level, category, message, meta, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        entry["id"],
                        entry["timestamp"],
                        entry["date"],
                        entry["level"],
                        entry["category"],
                        entry["message"],
                        json.dumps(entry["meta"]),
                        entry["created_at"]
                    ))
                    conn.commit()
                finally:
                    conn.close()
        except Exception:
            pass

    threading.Thread(target=db_writer, daemon=True).start()

    with LOG_LISTENERS_LOCK:
        for q in list(LOG_LISTENERS):
            try:
                q.put_nowait(entry)
            except Exception:
                pass


def record_incident(service: str, severity: str, prev_state: str, new_state: str, error_summary: str, timeline_entry: str = ""):
    """Records a service degradation or failure event for incident correlation."""
    inc_id = f"inc_{int(time.time())}_{secrets.token_hex(2)}"
    now = time.time()
    mem_state = governor.get_memory_status()["state"]
    timeline = [{"time": datetime.now().strftime("%H:%M:%S"), "event": timeline_entry or error_summary}]

    try:
        with DB_LOCK:
            conn = get_db_connection()
            try:
                conn.execute("""
                    INSERT INTO incidents (id, service, severity, prev_state, new_state, restart_count, memory_state, error_summary, timeline, resolved, created_at)
                    VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, 0, ?)
                """, (
                    inc_id,
                    service,
                    severity.upper(),
                    prev_state,
                    new_state,
                    mem_state,
                    error_summary,
                    json.dumps(timeline),
                    now
                ))
                conn.commit()
            finally:
                conn.close()
        log_event(severity, "INCIDENT", f"Incident recorded for [{service}]: {error_summary}")
    except Exception:
        pass


log_event("INFO", "SYSTEM", f"NexusNode Mobile Server Appliance v{getattr(config, 'VERSION', '2.2.0')} online")


# ==============================================================================
# RBAC DATABASE HELPER FUNCTIONS & AUTH
# ==============================================================================

def db_get_all_users() -> dict:
    with DB_LOCK:
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT user_id, password_hash, salt, role, privileges, created_at FROM users;")
            rows = cur.fetchall()
            users = {}
            for r in rows:
                users[r["user_id"]] = {
                    "user_id": r["user_id"],
                    "password_hash": r["password_hash"],
                    "salt": r["salt"],
                    "role": r["role"],
                    "privileges": json.loads(r["privileges"] or "{}"),
                    "created_at": r["created_at"]
                }
            return users
        finally:
            conn.close()


def db_get_user(user_id: str):
    with DB_LOCK:
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT user_id, password_hash, salt, role, privileges, created_at FROM users WHERE user_id = ?;", (user_id,))
            r = cur.fetchone()
            if not r:
                return None
            return {
                "user_id": r["user_id"],
                "password_hash": r["password_hash"],
                "salt": r["salt"],
                "role": r["role"],
                "privileges": json.loads(r["privileges"] or "{}"),
                "created_at": r["created_at"]
            }
        finally:
            conn.close()


def is_ip_locked(ip: str) -> bool:
    now = time.time()
    with FAILED_LOGINS_LOCK:
        attempts = FAILED_LOGINS.get(ip, [])
        recent_attempts = [t for t in attempts if now - t < config.LOCKOUT_DURATION_SECONDS]
        FAILED_LOGINS[ip] = recent_attempts
        return len(recent_attempts) >= config.LOCKOUT_THRESHOLD


def record_failed_login(ip: str):
    now = time.time()
    with FAILED_LOGINS_LOCK:
        if ip not in FAILED_LOGINS:
            FAILED_LOGINS[ip] = []
        FAILED_LOGINS[ip].append(now)


def clear_failed_logins(ip: str):
    with FAILED_LOGINS_LOCK:
        if ip in FAILED_LOGINS:
            del FAILED_LOGINS[ip]


def get_token_from_request():
    auth_header = request.headers.get('Authorization') or request.headers.get('Auth')
    if auth_header:
        if auth_header.startswith('Bearer '):
            return auth_header[7:].strip()
        return auth_header.strip()
    return request.args.get('token') or request.args.get('auth')


def authenticate_user():
    token = get_token_from_request()
    if not token:
        return None

    with SESSIONS_LOCK:
        if token in SESSIONS:
            session = SESSIONS[token]
            if time.time() < session.get('expires_at', 0):
                return session
            else:
                del SESSIONS[token]
    return None


def has_privilege(privilege_name: str) -> bool:
    if not hasattr(g, 'user') or not g.user:
        return False
    if g.user.get('role') == 'admin':
        return True
    return bool(g.user.get('privileges', {}).get(privilege_name, False))


def require_privilege_or_admin(privilege_name: str):
    if not has_privilege(privilege_name):
        user_name = g.user.get('user_id') if hasattr(g, 'user') and g.user else 'anonymous'
        log_event("SECURITY", "AUTH", f"Blocked '{user_name}' from unauthorized '{privilege_name}' on {request.path}")
        return jsonify({
            "error": "permission_denied",
            "message": f"Forbidden: You lack permission '{privilege_name}'.",
            "required_privilege": privilege_name
        }), 403
    return None


def require_admin():
    if not hasattr(g, 'user') or not g.user or g.user.get('role') != 'admin':
        user_name = g.user.get('user_id') if hasattr(g, 'user') and g.user else 'anonymous'
        log_event("SECURITY", "AUTH", f"Blocked non-admin '{user_name}' from admin-only route {request.path}")
        return jsonify({
            "error": "permission_denied",
            "message": "Forbidden: Administrator role required.",
            "required_role": "admin"
        }), 403
    return None


def sanitize_storage_path(filename: str) -> str:
    """Validates and canonicalizes file path to prevent directory traversal outside STORAGE_DIR."""
    if not filename or '..' in filename or filename.startswith('/') or filename.startswith('\\') or ':' in filename:
        raise ValueError("Directory traversal attempt detected.")
    
    # Support subpaths within STORAGE_DIR (e.g. Music/song.mp3)
    clean_parts = [p for p in filename.replace('\\', '/').split('/') if p and p != '.']
    target = os.path.abspath(os.path.join(config.STORAGE_DIR, *clean_parts))
    storage_abs = os.path.abspath(config.STORAGE_DIR)
    
    if not target.startswith(storage_abs) or os.path.commonpath([storage_abs, target]) != storage_abs:
        raise ValueError("Directory traversal attempt detected.")
    return target


@app.before_request
def check_request_auth():
    # Public assets, login, and health checks
    if request.path in ['/', '/index.html', '/favicon.ico'] or request.path.startswith('/static/'):
        return None
    if request.path in ['/api/auth/login', '/api/health', '/health']:
        return None
    # Public temporary share links
    if request.path.startswith('/share/'):
        return None

    user = authenticate_user()
    if not user:
        # Check token query parameter for stream / media previews / live logs
        if (request.path.startswith('/download/') or 
            request.path.startswith('/preview/') or 
            request.path.startswith('/stream/') or 
            request.path.startswith('/archive/') or 
            request.path == '/api/logs/stream'):
            tok = get_token_from_request()
            with SESSIONS_LOCK:
                if tok and tok in SESSIONS and time.time() < SESSIONS[tok].get('expires_at', 0):
                    g.user = SESSIONS[tok]
                    return None
        
        log_event("SECURITY", "AUTH", f"Blocked unauthorized request to {request.path}", {"ip": request.remote_addr})
        return jsonify({"error": "authentication_error", "message": "Unauthorized. Please sign in."}), 401
    
    g.user = user


@app.after_request
def apply_security_headers(response):
    response.headers['localtonet-skip-warning'] = 'true'
    response.headers['Bypass-Tunnel-Reminder'] = 'true'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    return response


# ==============================================================================
# HTTP RANGE STREAMING HELPER (Zero-Memory Mobile Playback)
# ==============================================================================

def stream_file_range(filepath: str):
    """
    Streams audio/video files using HTTP 206 Partial Content range requests.
    Zero whole-file RAM loading to prevent Android memory pressure.
    """
    if not os.path.exists(filepath):
        return jsonify({"error": "File not found"}), 404

    file_size = os.path.getsize(filepath)
    content_type, _ = mimetypes.guess_type(filepath)
    content_type = content_type or 'application/octet-stream'

    range_header = request.headers.get('Range', None)
    if not range_header:
        # Standard full stream
        def file_gen():
            with open(filepath, 'rb') as f:
                while chunk := f.read(65536):
                    yield chunk

        resp = Response(stream_with_context(file_gen()), 200, mimetype=content_type, direct_passthrough=True)
        resp.headers['Content-Length'] = str(file_size)
        resp.headers['Accept-Ranges'] = 'bytes'
        return resp

    # Parse Range: bytes=start-end
    match = re.search(r'bytes=(\d+)-(\d*)', range_header)
    if not match:
        return Response(status=416)

    start = int(match.group(1))
    end = int(match.group(2)) if match.group(2) else file_size - 1
    if start >= file_size or end >= file_size:
        return Response(status=416)

    length = end - start + 1

    def range_gen():
        with open(filepath, 'rb') as f:
            f.seek(start)
            bytes_left = length
            while bytes_left > 0:
                chunk_to_read = min(65536, bytes_left)
                data = f.read(chunk_to_read)
                if not data:
                    break
                bytes_left -= len(data)
                yield data

    resp = Response(stream_with_context(range_gen()), 206, mimetype=content_type, direct_passthrough=True)
    resp.headers['Content-Range'] = f'bytes {start}-{end}/{file_size}'
    resp.headers['Content-Length'] = str(length)
    resp.headers['Accept-Ranges'] = 'bytes'
    return resp


# ==============================================================================
# BOUNDED BACKGROUND TASK WORKER POOL
# ==============================================================================

class BoundedTaskRunner:
    """
    Queue-based bounded background task runner.
    Guarantees strict concurrency limit (1 heavy task) to prevent Android LMK crashes.
    """
    def __init__(self, max_concurrency: int = 1):
        self.max_concurrency = max_concurrency
        self.tasks = {}
        self.queue = queue.Queue()
        self.lock = threading.Lock()
        self._worker_thread = None
        self.load_from_db()
        self._start_worker()

    def load_from_db(self):
        """Loads tasks from SQLite. Automatically sweeps 'running' tasks to 'interrupted'."""
        with DB_LOCK:
            conn = get_db_connection()
            try:
                cur = conn.cursor()
                cur.execute("SELECT id, title, type, status, progress, logs, created_at, updated_at FROM background_tasks ORDER BY created_at DESC LIMIT 50;")
                rows = cur.fetchall()
                for r in rows:
                    try:
                        logs = json.loads(r["logs"])
                    except Exception:
                        logs = [r["logs"]]

                    task_status = r["status"]
                    if task_status == "running":
                        task_status = "interrupted"
                        logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] Server restarted while task was active. Status set to INTERRUPTED.")
                        conn.execute("UPDATE background_tasks SET status = 'interrupted', logs = ? WHERE id = ?;", (json.dumps(logs), r["id"]))

                    self.tasks[r["id"]] = {
                        "id": r["id"],
                        "title": r["title"],
                        "type": r["type"],
                        "status": task_status,
                        "progress": r["progress"],
                        "logs": logs,
                        "created_at": r["created_at"],
                        "updated_at": r["updated_at"],
                        "_process": None
                    }
                conn.commit()
            except Exception:
                pass
            finally:
                conn.close()

    def _start_worker(self):
        if not self._worker_thread or not self._worker_thread.is_alive():
            self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
            self._worker_thread.start()

    def _worker_loop(self):
        while True:
            task_item = self.queue.get()
            if not task_item:
                break
            
            task_id, runner_fn, args = task_item
            task_obj = self.tasks.get(task_id)

            if not task_obj or task_obj['status'] == 'cancelled':
                self.queue.task_done()
                continue

            # Check memory before starting heavy task
            res_check = governor.can_start_heavy_task()
            if not res_check["allowed"] and res_check["state"] == "critical":
                task_obj['status'] = 'failed'
                task_obj['error'] = res_check["reason"]
                task_obj['logs'].append(f"[{datetime.now().strftime('%H:%M:%S')}] {res_check['reason']}")
                self.save_task_to_db(task_obj)
                self.queue.task_done()
                continue

            task_obj['status'] = 'running'
            task_obj['updated_at'] = time.time()
            task_obj['logs'].append(f"[{datetime.now().strftime('%H:%M:%S')}] Worker picked up task. Executing...")
            self.save_task_to_db(task_obj)
            log_event("INFO", "TASK", f"Worker started heavy task: '{task_obj['title']}'")

            try:
                runner_fn(task_obj, *args)
                if task_obj['status'] == 'running':
                    task_obj['status'] = 'completed'
                    task_obj['progress'] = 100
                    task_obj['logs'].append(f"[{datetime.now().strftime('%H:%M:%S')}] Task completed successfully.")
                    log_event("INFO", "TASK", f"Task '{task_obj['title']}' completed.")
            except Exception as e:
                if task_obj['status'] != 'cancelled':
                    task_obj['status'] = 'failed'
                    task_obj['error'] = str(e)
                    task_obj['logs'].append(f"[{datetime.now().strftime('%H:%M:%S')}] ERROR: {str(e)}")
                    log_event("ERROR", "TASK", f"Task '{task_obj['title']}' failed: {str(e)}")
            finally:
                task_obj['updated_at'] = time.time()
                self.save_task_to_db(task_obj)
                self.queue.task_done()

    def save_task_to_db(self, task_obj):
        with DB_LOCK:
            conn = get_db_connection()
            try:
                conn.execute("""
                    INSERT OR REPLACE INTO background_tasks (id, title, type, status, progress, logs, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    task_obj["id"],
                    task_obj["title"],
                    task_obj["type"],
                    task_obj["status"],
                    task_obj.get("progress", 0),
                    json.dumps(task_obj.get("logs", [])),
                    task_obj["created_at"],
                    task_obj["updated_at"]
                ))
                conn.commit()
            except Exception:
                pass
            finally:
                conn.close()

    def list_tasks(self):
        with self.lock:
            return sorted(list(self.tasks.values()), key=lambda x: x['created_at'], reverse=True)

    def cancel_task(self, task_id: str) -> bool:
        with self.lock:
            task = self.tasks.get(task_id)
            if task and task['status'] in ['running', 'queued']:
                proc = task.get('_process')
                if proc:
                    try:
                        proc.terminate()
                        time.sleep(0.3)
                        if proc.poll() is None:
                            proc.kill()
                    except Exception:
                        pass

                task['status'] = 'cancelled'
                task['logs'].append(f"[{datetime.now().strftime('%H:%M:%S')}] Task cancelled by user.")
                task['updated_at'] = time.time()
                self.save_task_to_db(task)
                cleanup_partial_files()
                log_event("WARN", "TASK", f"Task '{task['title']}' was cancelled.")
                return True
        return False

    def enqueue_task(self, title: str, task_type: str, runner_fn, *args) -> tuple[str, dict]:
        """Submits a task into the bounded queue."""
        res_check = governor.can_start_heavy_task()
        if not res_check["allowed"] and res_check["state"] == "critical":
            return None, res_check

        task_id = secrets.token_hex(6)
        task_obj = {
            "id": task_id,
            "title": title,
            "type": task_type,
            "status": "queued",
            "progress": 0,
            "logs": [f"[{datetime.now().strftime('%H:%M:%S')}] Task submitted to queue (concurrency limit: {self.max_concurrency})."],
            "created_at": time.time(),
            "updated_at": time.time(),
            "error": None,
            "_process": None
        }

        with self.lock:
            self.tasks[task_id] = task_obj
            self.save_task_to_db(task_obj)
            self.queue.put((task_id, runner_fn, args))

        log_event("INFO", "TASK", f"Task queued: '{title}' [{task_id}]")
        return task_id, res_check


task_runner = BoundedTaskRunner(max_concurrency=config.MAX_HEAVY_CONCURRENCY)


def cleanup_partial_files(specific_path=None):
    """Safely cleans up partial download artifacts without deleting normal user files."""
    try:
        if specific_path and os.path.exists(specific_path):
            try:
                if specific_path.endswith(('.part', '.ytdl', '.tmp', '.crdownload', '.part-Frag')) or os.path.getsize(specific_path) == 0:
                    os.remove(specific_path)
            except Exception:
                pass

        for root, _, files in os.walk(config.STORAGE_DIR):
            for f in files:
                fpath = os.path.join(root, f)
                if f.endswith(('.part', '.ytdl', '.tmp', '.crdownload', '.part-Frag')):
                    try:
                        os.remove(fpath)
                    except Exception:
                        pass
                elif os.path.getsize(fpath) == 0 and (time.time() - os.path.getmtime(fpath) < 600):
                    try:
                        os.remove(fpath)
                    except Exception:
                        pass
    except Exception:
        pass


# ==============================================================================
# SERIALIZED & ASYNCHRONOUS LOCAL DOCUMENT RAG
# ==============================================================================

class SerializedDocumentRAG:
    """
    Zero-dependency localized Semantic RAG engine.
    Serialized execution guarantees that only 1 rebuild runs at a time.
    """
    def __init__(self):
        self.state = "ready"
        self.index = self._load_index_from_disk()
        self._rebuild_lock = threading.Lock()
        self._pending_rebuild = False
        self.source_folders = ["."]

    def _load_index_from_disk(self) -> dict:
        if os.path.exists(config.RAG_INDEX_FILE):
            try:
                with open(config.RAG_INDEX_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {"documents": {}, "chunks": [], "updated_at": None}

    def _save_index_to_disk(self):
        self.index["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        temp_file = f"{config.RAG_INDEX_FILE}.tmp"
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(self.index, f, indent=2)
        os.replace(temp_file, config.RAG_INDEX_FILE)

    def extract_text(self, filepath: str) -> str:
        ext = filepath.split('.')[-1].lower()
        if ext in ['txt', 'md', 'py', 'json', 'log', 'sh', 'csv', 'html', 'css', 'js', 'ts', 'env', 'yml', 'yaml']:
            try:
                if os.path.getsize(filepath) > config.RAG_MAX_FILE_SIZE_BYTES:
                    return ""
                with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                    return f.read()
            except Exception:
                pass
        return ""

    def chunk_text(self, text: str, filename: str, chunk_size=800) -> list:
        chunks = []
        if not text.strip():
            return chunks
        lines = text.splitlines()
        current_chunk = []
        current_len = 0
        chunk_idx = 0

        for line in lines:
            current_chunk.append(line)
            current_len += len(line) + 1
            if current_len >= chunk_size:
                chunk_str = "\n".join(current_chunk)
                chunks.append({
                    "id": f"{filename}_{chunk_idx}",
                    "doc": filename,
                    "text": chunk_str,
                    "words": set(re.findall(r'\b[a-zA-Z0-9_]{3,}\b', chunk_str.lower()))
                })
                chunk_idx += 1
                current_chunk = current_chunk[-3:] if len(current_chunk) >= 3 else []
                current_len = sum(len(l) + 1 for l in current_chunk)

        if current_chunk:
            chunk_str = "\n".join(current_chunk)
            chunks.append({
                "id": f"{filename}_{chunk_idx}",
                "doc": filename,
                "text": chunk_str,
                "words": set(re.findall(r'\b[a-zA-Z0-9_]{3,}\b', chunk_str.lower()))
            })

        return chunks

    def build_vault_index(self) -> dict:
        """Executes indexing synchronously with lock and pending queue handling."""
        if not self._rebuild_lock.acquire(blocking=False):
            self._pending_rebuild = True
            log_event("INFO", "RAG", "Rebuild already in progress. Queued as pending.")
            return {"status": "rebuild_queued"}

        self.state = "rebuilding"
        log_event("INFO", "RAG", "Starting knowledge base indexing...")

        try:
            while True:
                self._pending_rebuild = False
                all_chunks = []
                indexed_docs = {}

                for root, _, files in os.walk(config.STORAGE_DIR):
                    for f in files:
                        fpath = os.path.join(root, f)
                        rel_path = os.path.relpath(fpath, config.STORAGE_DIR)
                        ext = f.split('.')[-1].lower()
                        if ext in ['txt', 'md', 'py', 'json', 'log', 'sh', 'csv', 'html', 'css', 'js', 'ts', 'env', 'yml']:
                            try:
                                content = self.extract_text(fpath)
                                if content:
                                    chunks = self.chunk_text(content, rel_path)
                                    for c in chunks:
                                        all_chunks.append({
                                            "id": c["id"],
                                            "doc": c["doc"],
                                            "text": c["text"],
                                            "words": list(c["words"])
                                        })
                                    indexed_docs[rel_path] = {"chunks_count": len(chunks), "size": os.path.getsize(fpath)}
                            except Exception:
                                pass

                self.index = {
                    "documents": indexed_docs,
                    "chunks": all_chunks[:config.RAG_MAX_CHUNKS],
                    "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
                self._save_index_to_disk()
                log_event("INFO", "RAG", f"Indexed {len(indexed_docs)} documents, {len(all_chunks)} chunks.")

                if not self._pending_rebuild:
                    break

            self.state = "ready"
            return {"documents_count": len(indexed_docs), "chunks_count": len(all_chunks)}
        except Exception as e:
            self.state = "failed"
            log_event("ERROR", "RAG", f"RAG rebuild failed: {str(e)}")
            raise e
        finally:
            self._rebuild_lock.release()

    def trigger_rebuild_async(self):
        threading.Thread(target=self.build_vault_index, daemon=True).start()

    def search(self, query: str, top_k=4) -> list[dict]:
        if not self.index.get("chunks"):
            return []
        query_lower = query.lower()
        query_words = set(re.findall(r'\b[a-zA-Z0-9_\-\.]{2,}\b', query_lower))
        if not query_words:
            return []

        scored = []
        for chunk in self.index["chunks"]:
            chunk_words = set(chunk.get("words", []))
            common = query_words.intersection(chunk_words)
            if common:
                score = len(common) / len(query_words)
                scored.append({
                    "doc": chunk["doc"],
                    "text": chunk["text"],
                    "score": round(score, 3)
                })

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_k]


rag_engine = SerializedDocumentRAG()


# ==============================================================================
# SCHEDULED AUTOMATION DAEMON (Feeds strictly into BoundedTaskRunner)
# ==============================================================================

class SchedulerDaemon(threading.Thread):
    """
    Lightweight maintenance scheduler running once every 60 seconds.
    Enqueues due jobs into BoundedTaskRunner so heavy work remains strictly bounded.
    """
    def __init__(self):
        super().__init__(daemon=True)
        self.running = True

    def run(self):
        time.sleep(10)  # Grace period on startup
        while self.running:
            try:
                self.check_and_run_schedules()
            except Exception:
                pass
            time.sleep(60)

    def check_and_run_schedules(self):
        now = time.time()
        with DB_LOCK:
            conn = get_db_connection()
            try:
                cur = conn.cursor()
                cur.execute("SELECT id, name, job_type, interval_seconds, enabled, last_run, next_run FROM scheduled_jobs WHERE enabled = 1;")
                jobs = cur.fetchall()
            finally:
                conn.close()

        for j in jobs:
            next_run = j["next_run"] or 0
            if now >= next_run:
                self.trigger_job(j)

    def trigger_job(self, job_row):
        job_id = job_row["id"]
        job_type = job_row["job_type"]
        interval = job_row["interval_seconds"]
        now = time.time()
        next_time = now + interval

        # Update next_run first to avoid duplicate fires
        with DB_LOCK:
            conn = get_db_connection()
            try:
                conn.execute("UPDATE scheduled_jobs SET last_run = ?, next_run = ?, last_status = 'queued' WHERE id = ?;", (now, next_time, job_id))
                conn.commit()
            finally:
                conn.close()

        if job_type == "backup":
            task_runner.enqueue_task(f"Scheduled: {job_row['name']}", "backup", self._run_backup_job, job_id)
        elif job_type == "temp_cleanup":
            task_runner.enqueue_task(f"Scheduled: {job_row['name']}", "cleanup", self._run_cleanup_job, job_id)
        elif job_type == "tunnel_check":
            self._run_tunnel_check()
        elif job_type == "storage_check":
            self._run_storage_check()

    def _run_backup_job(self, task_obj, job_id):
        task_obj['logs'].append("Executing automated database and configuration backup...")
        create_system_backup_sync("auto")
        task_obj['logs'].append("Automated backup created successfully.")

    def _run_cleanup_job(self, task_obj, job_id):
        task_obj['logs'].append("Sweeping temporary download artifacts...")
        cleanup_partial_files()
        task_obj['logs'].append("Temporary files swept.")

    def _run_tunnel_check(self):
        status = probe_localtonet_status()
        if status["status"] != "online":
            record_incident("localtonet", "WARNING", "online", "offline", "LocalToNet tunnel disconnected during scheduled check")

    def _run_storage_check(self):
        disk = governor.get_disk_status()
        if disk["free_gb"] < 2.0:
            log_event("WARN", "STORAGE", f"Low storage warning: only {disk['free_gb']} GB free on vault partition")


scheduler_daemon = SchedulerDaemon()
scheduler_daemon.start()


# ==============================================================================
# MEDIA CENTER & DOWNLOAD WORKER IMPLEMENTATION
# ==============================================================================

def run_media_download_job(task_obj: dict, url: str, format_type: str, quality: str, metadata_flags: dict, subtitle_opts: dict, custom_filename: str, destination: str):
    task_obj['logs'].append(f"Target URL: {url}")
    task_obj['logs'].append(f"Configuration: Format={format_type.upper()}, Quality={quality}, Dest={destination}")

    ytdlp_bin = shutil.which('yt-dlp')
    ffmpeg_bin = shutil.which('ffmpeg')
    dest_dir = os.path.join(config.STORAGE_DIR, destination) if destination in config.MEDIA_CATEGORIES else config.STORAGE_DIR
    os.makedirs(dest_dir, exist_ok=True)

    dest_created = None
    is_platform_url = any(p in url.lower() for p in [
        'youtube.com', 'youtu.be', 'tiktok.com', 'instagram.com',
        'vimeo.com', 'soundcloud.com', 'twitter.com', 'x.com', 'facebook.com', 'twitch.tv'
    ])

    try:
        if is_platform_url and not ytdlp_bin:
            raise RuntimeError("Extracting media from video platforms requires 'yt-dlp'. Run 'pkg install yt-dlp ffmpeg' in Termux.")

        if ytdlp_bin:
            out_tmpl = os.path.join(dest_dir, f"{custom_filename or '%(title)s'}.%(ext)s")
            cmd = [
                ytdlp_bin,
                "--no-playlist",
                "--no-check-certificates",
                "--extractor-args", "youtube:player_client=android,web",
                "-o", out_tmpl
            ]

            # Format & Quality handling
            is_audio_only = (format_type in ['mp3', 'm4a', 'opus', 'wav'] or quality == 'audio_only')
            if is_audio_only:
                if ffmpeg_bin:
                    cmd.extend(["-x", "--audio-format", format_type])
                else:
                    cmd.extend(["-f", "bestaudio/best"])
            else:
                if quality == '1080p':
                    cmd.extend(["-f", "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best"])
                elif quality == '720p':
                    cmd.extend(["-f", "bestvideo[height<=720]+bestaudio/best[height<=720]/best"])
                elif quality == '480p':
                    cmd.extend(["-f", "bestvideo[height<=480]+bestaudio/best[height<=480]/best"])
                else:
                    cmd.extend(["-f", "bestvideo+bestaudio/best"])

                if format_type in ['mp4', 'mkv', 'webm'] and ffmpeg_bin:
                    cmd.extend(["--merge-output-format", format_type])

            # Metadata options
            if metadata_flags.get('embed_metadata', True) and ffmpeg_bin:
                cmd.append("--add-metadata")
            if metadata_flags.get('embed_thumbnail', False) and ffmpeg_bin:
                cmd.append("--embed-thumbnail")
            if metadata_flags.get('embed_chapters', True) and ffmpeg_bin:
                cmd.append("--embed-chapters")
            if metadata_flags.get('preserve_description', False):
                cmd.append("--write-description")

            # Subtitles
            sub_mode = subtitle_opts.get('mode', 'none')
            if sub_mode == 'auto':
                cmd.extend(["--write-auto-subs", "--sub-lang", "en,es,hi"])
            elif sub_mode == 'embed' and ffmpeg_bin:
                cmd.extend(["--write-subs", "--embed-subs", "--sub-lang", "en"])
            elif sub_mode in ['srt', 'vtt']:
                cmd.extend(["--write-subs", "--convert-subs", sub_mode])

            cmd.append(url)
            task_obj['logs'].append(f"Executing yt-dlp pipeline...")

            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
            task_obj['_process'] = proc

            for line in iter(proc.stdout.readline, ''):
                if task_obj['status'] == 'cancelled':
                    break
                line_str = line.strip()
                if line_str:
                    task_obj['logs'].append(line_str)
                    prog_match = re.search(r'\[download\]\s+([0-9\.]+)%', line_str)
                    if prog_match:
                        try:
                            pct = float(prog_match.group(1))
                            task_obj['progress'] = min(99, int(pct))
                        except Exception:
                            pass

            proc.stdout.close()
            return_code = proc.wait()
            if return_code != 0 and task_obj['status'] != 'cancelled':
                err_lines = [l for l in task_obj['logs'] if 'error' in l.lower() or 'sign in' in l.lower()]
                detailed_reason = err_lines[-1] if err_lines else f"yt-dlp exited with code {return_code}"
                raise RuntimeError(detailed_reason)
        else:
            task_obj['logs'].append("Running direct stream download...")
            r = requests.get(url, stream=True, timeout=30)
            if r.status_code != 200:
                raise RuntimeError(f"Direct stream returned HTTP {r.status_code}")

            fname = custom_filename or os.path.basename(url.split('?')[0]) or f"media_{int(time.time())}.bin"
            if format_type and not fname.endswith(f".{format_type}"):
                fname += f".{format_type}"

            dest_created = os.path.join(dest_dir, fname)
            total_size = int(r.headers.get('content-length', 0))
            downloaded = 0

            with open(dest_created, 'wb') as f:
                for chunk in r.iter_content(chunk_size=65536):
                    if task_obj['status'] == 'cancelled':
                        break
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size > 0:
                            task_obj['progress'] = min(99, int((downloaded / total_size) * 100))

            task_obj['logs'].append(f"Saved file to {destination}: {fname}")

    except Exception as e:
        cleanup_partial_files(dest_created)
        raise e


# ==============================================================================
# ATOMIC BACKUP SYSTEM IMPLEMENTATION
# ==============================================================================

def create_system_backup_sync(backup_type: str = "manual") -> dict:
    """
    Creates an atomic zip backup of SQLite database, RAG index, and server configuration.
    Computes SHA-256 checksum and saves metadata record into database.
    """
    os.makedirs(config.BACKUP_DIR, exist_ok=True)
    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_id = f"backup_{timestamp_str}"
    zip_filename = f"nexus_{backup_id}.zip"
    temp_zip_path = os.path.join(config.BACKUP_DIR, f"{zip_filename}.tmp")
    final_zip_path = os.path.join(config.BACKUP_DIR, zip_filename)

    with zipfile.ZipFile(temp_zip_path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        # 1. Safely copy SQLite DB
        with DB_LOCK:
            conn = get_db_connection()
            try:
                # Backup SQLite DB safely using sqlite3 backup API
                db_backup_path = os.path.join(config.STORAGE_DIR, "db_backup.tmp")
                dest_conn = sqlite3.connect(db_backup_path)
                conn.backup(dest_conn)
                dest_conn.close()
                zf.write(db_backup_path, arcname="nexus_vault.db")
                if os.path.exists(db_backup_path):
                    os.remove(db_backup_path)
            finally:
                conn.close()

        # 2. Add RAG Index if exists
        if os.path.exists(config.RAG_INDEX_FILE):
            zf.write(config.RAG_INDEX_FILE, arcname="rag_index.json")

        # 3. Add Server Config if exists
        if os.path.exists(config.CONFIG_FILE):
            zf.write(config.CONFIG_FILE, arcname="server_config.json")

        # 4. Write manifest
        manifest = {
            "backup_id": backup_id,
            "version": getattr(config, 'VERSION', '2.2.0'),
            "backup_type": backup_type,
            "created_at": time.time(),
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))

    # Atomically rename
    os.replace(temp_zip_path, final_zip_path)

    # Compute SHA-256 Checksum
    sha256 = hashlib.sha256()
    with open(final_zip_path, 'rb') as f:
        while chunk := f.read(131072):
            sha256.update(chunk)
    checksum = sha256.hexdigest()
    size_bytes = os.path.getsize(final_zip_path)

    with DB_LOCK:
        conn = get_db_connection()
        try:
            conn.execute("""
                INSERT OR REPLACE INTO backups (id, filename, size_bytes, checksum, backup_type, created_at, status)
                VALUES (?, ?, ?, ?, ?, ?, 'completed');
            """, (backup_id, zip_filename, size_bytes, checksum, backup_type, time.time()))
            conn.commit()
        finally:
            conn.close()

    log_event("INFO", "BACKUP", f"Created system backup: '{zip_filename}' ({round(size_bytes/1024, 1)} KB)")
    return {
        "id": backup_id,
        "filename": zip_filename,
        "size_bytes": size_bytes,
        "checksum": checksum,
        "status": "completed"
    }


# ==============================================================================
# PHASE 1A: HEALTH & MULTI-SERVICE TELEMETRY (Unprivileged Probes)
# ==============================================================================

def probe_ssh_status() -> dict:
    """Unprivileged check for OpenSSH daemon via TCP socket probe."""
    is_up = False
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.4)
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


def probe_ollama_status() -> dict:
    """Unprivileged check for Ollama engine via HTTP API."""
    is_running = False
    version = None
    models_count = 0
    try:
        r = requests.get(f"{config.OLLAMA_HOST}/api/version", timeout=0.5)
        if r.status_code == 200:
            is_running = True
            version = r.json().get("version", "unknown")
            r_tags = requests.get(f"{config.OLLAMA_HOST}/api/tags", timeout=0.5)
            if r_tags.status_code == 200:
                models_count = len(r_tags.json().get("models", []))
    except Exception:
        pass

    pid = None
    try:
        res = subprocess.run(["pgrep", "-f", "ollama"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        if res.returncode == 0 and res.stdout.strip():
            pid = res.stdout.strip().splitlines()[0]
    except Exception:
        pass

    return {
        "status": "running" if is_running else ("process_alive" if pid else "stopped"),
        "host": config.OLLAMA_HOST,
        "version": version,
        "models_count": models_count,
        "pid": pid
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


def probe_localtonet_status() -> dict:
    pid = None
    try:
        res = subprocess.run(["pgrep", "-f", "localtonet"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        if res.returncode == 0 and res.stdout.strip():
            pid = res.stdout.strip().splitlines()[0]
    except Exception:
        pass

    tunnel_url = get_tunnel_url()
    return {
        "status": "online" if pid else "offline",
        "tunnel_url": tunnel_url,
        "pid": pid
    }


def get_local_ips() -> list:
    ips = []
    try:
        hostname = socket.gethostname()
        local_ip = socket.gethostbyname(hostname)
        if local_ip and not local_ip.startswith("127."):
            ips.append(local_ip)
    except Exception:
        pass
    try:
        out = subprocess.check_output(["ip", "route"], text=True, stderr=subprocess.DEVNULL)
        match = re.search(r"src\s+(\d+\.\d+\.\d+\.\d+)", out)
        if match and match.group(1) not in ips:
            ips.append(match.group(1))
    except Exception:
        pass
    return ips


def format_uptime(seconds: float) -> str:
    d = int(seconds // 86400)
    h = int((seconds % 86400) // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if d > 0:
        return f"{d}d {h}h {m}m"
    if h > 0:
        return f"{h}h {m}m"
    return f"{m}m {s}s"


# ==============================================================================
# REST API ENDPOINTS
# ==============================================================================

# --- Auth Routes ---
@app.route('/api/auth/login', methods=['POST'])
def login():
    client_ip = request.remote_addr or '127.0.0.1'

    if is_ip_locked(client_ip):
        log_event("SECURITY", "AUTH", f"Brute force lockout active for IP: {client_ip}")
        return jsonify({"error": "Too many failed login attempts. IP locked for 10 minutes.", "message": "Too many failed login attempts. IP locked for 10 minutes."}), 429

    data = request.get_json(force=True, silent=True) or {}
    user_id = str(data.get('user_id', '')).strip().lower()
    password = str(data.get('password', '')).strip()

    if not user_id or not password:
        return jsonify({"error": "validation_error", "message": "User ID and Password are required."}), 400

    user = db_get_user(user_id)

    if user and verify_password(password, user.get('password_hash', ''), user.get('salt', '')):
        clear_failed_logins(client_ip)
        token = secrets.token_hex(32)
        privileges = user.get('privileges', dict(config.USER_DEFAULT_PRIVILEGES))
        if user.get('role') == 'admin':
            privileges = dict(config.ADMIN_DEFAULT_PRIVILEGES)

        session_data = {
            "user_id": user_id,
            "role": user.get('role', 'user'),
            "privileges": privileges,
            "created_at": time.time(),
            "expires_at": time.time() + config.SESSION_EXPIRY_SECONDS
        }
        with SESSIONS_LOCK:
            SESSIONS[token] = session_data

        log_event("INFO", "AUTH", f"User '{user_id}' ({user.get('role')}) logged in", {"ip": client_ip})
        return jsonify({
            "token": token,
            "user": {
                "user_id": user_id,
                "role": user.get('role', 'user'),
                "privileges": privileges,
                "created_at": user.get('created_at', '')
            }
        })

    record_failed_login(client_ip)
    log_event("SECURITY", "AUTH", f"Failed login attempt for user '{user_id}'", {"ip": client_ip})
    return jsonify({"error": "authentication_error", "message": "Invalid User ID or Password."}), 401


@app.route('/api/auth/me', methods=['GET'])
def get_current_user():
    return jsonify({"user": g.user})


@app.route('/api/auth/logout', methods=['POST'])
def logout():
    token = get_token_from_request()
    with SESSIONS_LOCK:
        if token and token in SESSIONS:
            uid = SESSIONS[token].get('user_id', 'unknown')
            del SESSIONS[token]
            log_event("INFO", "AUTH", f"User '{uid}' logged out")
    return jsonify({"message": "Logged out."})


# --- Health & Telemetry Routes ---
@app.route('/api/health', methods=['GET'])
@app.route('/health', methods=['GET'])
def health():
    uptime_sec = time.time() - SERVER_START_TIME
    return jsonify({
        "status": "healthy",
        "app": "NexusNode",
        "version": getattr(config, 'VERSION', '2.2.0'),
        "uptime_seconds": int(uptime_sec),
        "timestamp": time.time()
    }), 200


@app.route('/api/services/status', methods=['GET'])
def services_status():
    uptime_sec = time.time() - SERVER_START_TIME
    return jsonify({
        "nexusnode": {
            "status": "online",
            "pid": os.getpid(),
            "uptime_seconds": int(uptime_sec),
            "port": config.PORT
        },
        "localtonet": probe_localtonet_status(),
        "ssh": probe_ssh_status(),
        "ollama": probe_ollama_status()
    })


@app.route('/api/system/status', methods=['GET'])
def system_status():
    uptime_sec = time.time() - SERVER_START_TIME
    tunnel_url = get_tunnel_url()
    mem = governor.get_memory_status()
    disk = governor.get_disk_status()
    device = governor.get_device_telemetry()
    appliance_state = governor.get_appliance_state()

    tasks_all = task_runner.list_tasks()
    running_tasks = [t for t in tasks_all if t['status'] == 'running']
    queued_tasks = [t for t in tasks_all if t['status'] == 'queued']

    return jsonify({
        "server": {
            "name": "NexusNode",
            "status": "ONLINE",
            "version": getattr(config, 'VERSION', '2.2.0'),
            "pid": os.getpid(),
            "uptime": format_uptime(uptime_sec),
            "uptime_seconds": int(uptime_sec),
            "local_ips": get_local_ips(),
            "tunnel_url": tunnel_url,
            "device": "Android Termux (4GB RAM)"
        },
        "appliance": appliance_state,
        "memory": mem,
        "disk": disk,
        "device": device,
        "services": {
            "nexusnode": { "status": "online", "port": config.PORT },
            "ssh": probe_ssh_status(),
            "localtonet": probe_localtonet_status(),
            "ollama": probe_ollama_status()
        },
        "tasks": {
            "running_count": len(running_tasks),
            "queued_count": len(queued_tasks),
            "total_count": len(tasks_all),
            "active_tasks": running_tasks[:3],
            "queued_tasks": queued_tasks[:3]
        },
        "rag": {
            "state": rag_engine.state,
            "documents_count": len(rag_engine.index.get("documents", {})),
            "chunks_count": len(rag_engine.index.get("chunks", [])),
            "updated_at": rag_engine.index.get("updated_at")
        },
        "user": g.user if hasattr(g, 'user') else None
    })


@app.route('/api/device/telemetry', methods=['GET'])
def device_telemetry_endpoint():
    return jsonify({
        "telemetry": governor.get_device_telemetry(),
        "appliance_state": governor.get_appliance_state(),
        "memory": governor.get_memory_status(),
        "disk": governor.get_disk_status()
    })


# --- Media Center & Streaming Routes ---
@app.route('/api/media/download', methods=['POST'])
def start_media_download_advanced():
    err = require_privilege_or_admin("can_download_media")
    if err:
        return err

    data = request.get_json(force=True, silent=True) or {}
    url_input = str(data.get('url', '')).strip()
    format_type = str(data.get('format', 'mp3')).strip().lower()
    quality = str(data.get('quality', 'best')).strip().lower()
    custom_filename = str(data.get('filename', '')).strip()
    destination = str(data.get('destination', 'Music' if format_type in ['mp3', 'm4a', 'opus', 'wav'] else 'Videos')).strip()
    metadata_flags = data.get('metadata') or {"embed_metadata": True, "embed_thumbnail": True, "embed_chapters": True}
    subtitle_opts = data.get('subtitles') or {"mode": "none"}

    if not url_input:
        return jsonify({"error": "validation_error", "message": "URL is required."}), 400

    # Support multiline / batch URLs (one queued task per URL, bounded concurrency = 1)
    raw_urls = [u.strip() for u in url_input.splitlines() if u.strip().startswith('http')]
    if not raw_urls:
        raw_urls = [url_input]

    queued_task_ids = []
    for u in raw_urls:
        title = f"Download {format_type.upper()}: {u[:45]}..."
        task_id, res_info = task_runner.enqueue_task(
            title,
            "media_download",
            run_media_download_job,
            u,
            format_type,
            quality,
            metadata_flags,
            subtitle_opts,
            custom_filename if len(raw_urls) == 1 else "",
            destination
        )
        if not task_id:
            return jsonify({
                "allowed": False,
                "error": "resource_pressure",
                "reason": res_info["reason"],
                "message": res_info["reason"],
                "state": res_info["state"],
                "available_mb": res_info.get("available_mb")
            }), 429
        queued_task_ids.append(task_id)

    return jsonify({
        "task_id": queued_task_ids[0],
        "queued_tasks": queued_task_ids,
        "count": len(queued_task_ids),
        "status": "queued"
    })


@app.route('/api/media/library', methods=['GET'])
def get_media_library():
    """Returns categorized media files with duration, size, format, and stream URLs."""
    library = {
        "music": [],
        "videos": [],
        "podcasts": [],
        "downloads": [],
        "other": []
    }

    try:
        for root, _, files in os.walk(config.STORAGE_DIR):
            for f in files:
                fpath = os.path.join(root, f)
                rel_path = os.path.relpath(fpath, config.STORAGE_DIR).replace('\\', '/')
                ext = f.split('.')[-1].lower()
                size = os.path.getsize(fpath)
                mtime = os.path.getmtime(fpath)

                item = {
                    "filename": f,
                    "path": rel_path,
                    "size_bytes": size,
                    "size_display": f"{round(size / (1024*1024), 1)} MB" if size > 1048576 else f"{round(size / 1024, 1)} KB",
                    "format": ext.upper(),
                    "created_at": datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M"),
                    "stream_url": f"/stream/{rel_path}"
                }

                if ext in ['mp3', 'm4a', 'opus', 'wav', 'flac', 'aac', 'ogg']:
                    if 'podcast' in rel_path.lower():
                        library["podcasts"].append(item)
                    else:
                        library["music"].append(item)
                elif ext in ['mp4', 'mkv', 'webm', 'mov', 'avi']:
                    library["videos"].append(item)
                elif 'downloads' in rel_path.lower():
                    library["downloads"].append(item)
                else:
                    library["other"].append(item)
    except Exception:
        pass

    return jsonify(library)


@app.route('/stream/<path:filepath>', methods=['GET'])
def stream_media_endpoint(filepath):
    try:
        safe_path = sanitize_storage_path(filepath)
    except ValueError as e:
        return jsonify({"error": "validation_error", "message": str(e)}), 400

    return stream_file_range(safe_path)


# --- Temporary Secure Share Links ---
@app.route('/api/shares', methods=['GET'])
def list_shares():
    err = require_privilege_or_admin("can_create_shares")
    if err:
        return err
    with DB_LOCK:
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            if g.user.get('role') == 'admin':
                cur.execute("SELECT * FROM shares ORDER BY created_at DESC;")
            else:
                cur.execute("SELECT * FROM shares WHERE user_id = ? ORDER BY created_at DESC;", (g.user.get('user_id'),))
            rows = cur.fetchall()
            shares = [dict(r) for r in rows]
            return jsonify(shares)
        finally:
            conn.close()


@app.route('/api/shares', methods=['POST'])
def create_share():
    err = require_privilege_or_admin("can_create_shares")
    if err:
        return err

    data = request.get_json(force=True, silent=True) or {}
    filename = str(data.get('filename', '')).strip()
    duration_preset = str(data.get('duration', '24h')).strip()
    max_downloads = int(data.get('max_downloads', 0))

    if not filename:
        return jsonify({"error": "validation_error", "message": "Filename is required."}), 400

    try:
        safe_path = sanitize_storage_path(filename)
        if not os.path.exists(safe_path):
            return jsonify({"error": "File not found"}), 404
    except ValueError as e:
        return jsonify({"error": "validation_error", "message": str(e)}), 400

    # Calculate expiration
    now = time.time()
    if duration_preset == '1h':
        expires_at = now + 3600
    elif duration_preset == '7d':
        expires_at = now + (7 * 86400)
    elif duration_preset == '24h':
        expires_at = now + 86400
    else:
        try:
            expires_at = now + int(duration_preset)
        except Exception:
            expires_at = now + 86400

    share_id = f"share_{secrets.token_hex(4)}"
    token = secrets.token_urlsafe(24)

    with DB_LOCK:
        conn = get_db_connection()
        try:
            conn.execute("""
                INSERT INTO shares (id, token, filename, user_id, created_at, expires_at, downloads_count, max_downloads, revoked)
                VALUES (?, ?, ?, ?, ?, ?, 0, ?, 0);
            """, (share_id, token, filename, g.user.get('user_id'), now, expires_at, max_downloads))
            conn.commit()
        finally:
            conn.close()

    share_url = f"/share/{token}"
    log_event("INFO", "SHARE", f"User '{g.user.get('user_id')}' created temporary share for '{filename}'")
    return jsonify({
        "id": share_id,
        "token": token,
        "share_url": share_url,
        "filename": filename,
        "expires_at": expires_at
    }), 201


@app.route('/api/shares/<share_id>', methods=['DELETE'])
def revoke_share(share_id):
    err = require_privilege_or_admin("can_create_shares")
    if err:
        return err

    with DB_LOCK:
        conn = get_db_connection()
        try:
            conn.execute("UPDATE shares SET revoked = 1 WHERE id = ?;", (share_id,))
            conn.commit()
        finally:
            conn.close()

    log_event("INFO", "SHARE", f"Revoked share link [{share_id}]")
    return jsonify({"revoked": True})


@app.route('/share/<token>', methods=['GET'])
def access_public_share(token):
    with DB_LOCK:
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM shares WHERE token = ?;", (token,))
            row = cur.fetchone()
            if not row:
                return jsonify({"error": "Share link not found"}), 404
            share = dict(row)
        finally:
            conn.close()

    if share.get('revoked'):
        return jsonify({"error": "This share link has been revoked."}), 410

    if time.time() > share.get('expires_at', 0):
        return jsonify({"error": "This share link has expired."}), 410

    if share.get('max_downloads', 0) > 0 and share.get('downloads_count', 0) >= share.get('max_downloads'):
        return jsonify({"error": "Maximum download limit reached for this share link."}), 410

    # Increment download counter
    with DB_LOCK:
        conn = get_db_connection()
        try:
            conn.execute("UPDATE shares SET downloads_count = downloads_count + 1 WHERE token = ?;", (token,))
            conn.commit()
        finally:
            conn.close()

    try:
        safe_path = sanitize_storage_path(share['filename'])
        log_event("INFO", "SHARE", f"Public access granted to shared file: '{share['filename']}' via token [{token[:8]}...]")
        return stream_file_range(safe_path)
    except Exception as e:
        return jsonify({"error": str(e)}), 400


# --- Storage Intelligence & Vault Tools ---
@app.route('/api/storage/intelligence', methods=['GET'])
def storage_intelligence_endpoint():
    now = time.time()
    with STORAGE_CACHE_LOCK:
        if STORAGE_CACHE["data"] and (now - STORAGE_CACHE["timestamp"] < 60):
            return jsonify(STORAGE_CACHE["data"])

    disk = governor.get_disk_status()
    breakdown = {
        "videos_bytes": 0,
        "music_bytes": 0,
        "models_bytes": 0,
        "vault_bytes": 0,
        "rag_bytes": 0,
        "logs_bytes": 0,
        "temp_bytes": 0,
        "other_bytes": 0
    }
    large_files = []
    recent_additions = []

    try:
        if os.path.exists(config.RAG_INDEX_FILE):
            breakdown["rag_bytes"] = os.path.getsize(config.RAG_INDEX_FILE)
        if os.path.exists(config.DB_FILE):
            breakdown["logs_bytes"] = os.path.getsize(config.DB_FILE)

        for root, _, files in os.walk(config.STORAGE_DIR):
            for f in files:
                fpath = os.path.join(root, f)
                rel_path = os.path.relpath(fpath, config.STORAGE_DIR)
                size = os.path.getsize(fpath)
                mtime = os.path.getmtime(fpath)
                ext = f.split('.')[-1].lower()

                if size >= 50 * 1024 * 1024:
                    large_files.append({
                        "name": f,
                        "path": rel_path,
                        "size_mb": round(size / (1024*1024), 1)
                    })

                if now - mtime < 86400 * 3:
                    recent_additions.append({
                        "name": f,
                        "path": rel_path,
                        "size_mb": round(size / (1024*1024), 2),
                        "time": datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
                    })

                if f.endswith(('.part', '.ytdl', '.tmp', '.crdownload')):
                    breakdown["temp_bytes"] += size
                elif ext in ['mp4', 'mkv', 'webm', 'mov']:
                    breakdown["videos_bytes"] += size
                elif ext in ['mp3', 'm4a', 'opus', 'wav', 'flac']:
                    breakdown["music_bytes"] += size
                elif ext in ['gguf', 'bin']:
                    breakdown["models_bytes"] += size
                else:
                    breakdown["vault_bytes"] += size

        large_files.sort(key=lambda x: x["size_mb"], reverse=True)
        recent_additions.sort(key=lambda x: x["time"], reverse=True)
    except Exception:
        pass

    result = {
        "disk": disk,
        "breakdown": breakdown,
        "large_files": large_files[:10],
        "recent_additions": recent_additions[:10]
    }

    with STORAGE_CACHE_LOCK:
        STORAGE_CACHE["timestamp"] = now
        STORAGE_CACHE["data"] = result

    return jsonify(result)


@app.route('/api/vault/rename', methods=['POST'])
def vault_rename():
    err = require_privilege_or_admin("can_manage_files")
    if err:
        return err

    data = request.get_json(force=True, silent=True) or {}
    old_name = str(data.get('old_name', '')).strip()
    new_name = str(data.get('new_name', '')).strip()

    try:
        old_path = sanitize_storage_path(old_name)
        new_path = sanitize_storage_path(new_name)
        if not os.path.exists(old_path):
            return jsonify({"error": "Original file not found"}), 404
        if os.path.exists(new_path):
            return jsonify({"error": "Target filename already exists"}), 409

        os.rename(old_path, new_path)
        log_event("INFO", "STORAGE", f"Renamed '{old_name}' -> '{new_name}'")
        rag_engine.trigger_rebuild_async()
        return jsonify({"renamed": True, "new_name": new_name})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@app.route('/api/vault/move', methods=['POST'])
def vault_move():
    err = require_privilege_or_admin("can_manage_files")
    if err:
        return err

    data = request.get_json(force=True, silent=True) or {}
    filename = str(data.get('filename', '')).strip()
    dest_folder = str(data.get('destination', '')).strip()

    try:
        src_path = sanitize_storage_path(filename)
        dest_dir = os.path.join(config.STORAGE_DIR, dest_folder)
        os.makedirs(dest_dir, exist_ok=True)
        dest_path = os.path.join(dest_dir, os.path.basename(src_path))

        os.replace(src_path, dest_path)
        log_event("INFO", "STORAGE", f"Moved '{filename}' -> '{dest_folder}'")
        return jsonify({"moved": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route('/api/vault/checksum/<path:filename>', methods=['GET'])
def vault_checksum(filename):
    try:
        safe_path = sanitize_storage_path(filename)
        if not os.path.exists(safe_path):
            return jsonify({"error": "File not found"}), 404

        sha256 = hashlib.sha256()
        md5 = hashlib.md5()
        with open(safe_path, 'rb') as f:
            while chunk := f.read(131072):
                sha256.update(chunk)
                md5.update(chunk)

        return jsonify({
            "filename": filename,
            "sha256": sha256.hexdigest(),
            "md5": md5.hexdigest(),
            "size_bytes": os.path.getsize(safe_path)
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route('/api/vault/clean-temp', methods=['POST'])
def clean_temp_files():
    err = require_privilege_or_admin("can_manage_files")
    if err:
        return err

    cleanup_partial_files()
    log_event("INFO", "STORAGE", "Manual sweep of temporary download artifacts executed")
    return jsonify({"message": "Temporary files cleared."})


# --- Backup & Restore Routes ---
@app.route('/api/backups', methods=['GET'])
def list_backups():
    err = require_privilege_or_admin("can_manage_backups")
    if err:
        return err
    with DB_LOCK:
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM backups ORDER BY created_at DESC;")
            rows = cur.fetchall()
            return jsonify([dict(r) for r in rows])
        finally:
            conn.close()


@app.route('/api/backups/create', methods=['POST'])
def create_backup_endpoint():
    err = require_privilege_or_admin("can_manage_backups")
    if err:
        return err

    res = create_system_backup_sync("manual")
    return jsonify(res), 201


@app.route('/api/backups/download/<backup_id>', methods=['GET'])
def download_backup(backup_id):
    err = require_privilege_or_admin("can_manage_backups")
    if err:
        return err

    zip_filename = f"nexus_{backup_id}.zip"
    filepath = os.path.join(config.BACKUP_DIR, zip_filename)
    if not os.path.exists(filepath):
        return jsonify({"error": "Backup file not found"}), 404

    return send_from_directory(config.BACKUP_DIR, zip_filename, as_attachment=True)


@app.route('/api/backups/restore', methods=['POST'])
def restore_backup():
    err = require_admin()
    if err:
        return err

    data = request.get_json(force=True, silent=True) or {}
    backup_id = str(data.get('backup_id', '')).strip()
    confirmed = bool(data.get('confirm', False))

    if not confirmed:
        return jsonify({"error": "validation_error", "message": "Restore requires explicit confirmation flag 'confirm: true'."}), 400

    zip_filename = f"nexus_{backup_id}.zip"
    filepath = os.path.join(config.BACKUP_DIR, zip_filename)
    if not os.path.exists(filepath):
        return jsonify({"error": "Backup archive not found"}), 404

    try:
        with zipfile.ZipFile(filepath, 'r') as zf:
            infolist = zf.infolist()
            # Extract RAG index if present
            for m in infolist:
                if m.filename == 'rag_index.json':
                    zf.extract(m, config.STORAGE_DIR)
                elif m.filename == 'server_config.json':
                    zf.extract(m, config.STORAGE_DIR)

        log_event("WARN", "BACKUP", f"Restored backup [{backup_id}]. RAG & Config synced.")
        return jsonify({"restored": True, "message": "Configuration and index restored."})
    except Exception as e:
        return jsonify({"error": f"Failed to restore backup: {str(e)}"}), 500


@app.route('/api/backups/<backup_id>', methods=['DELETE'])
def delete_backup(backup_id):
    err = require_privilege_or_admin("can_manage_backups")
    if err:
        return err

    zip_filename = f"nexus_{backup_id}.zip"
    filepath = os.path.join(config.BACKUP_DIR, zip_filename)
    if os.path.exists(filepath):
        os.remove(filepath)

    with DB_LOCK:
        conn = get_db_connection()
        try:
            conn.execute("DELETE FROM backups WHERE id = ?;", (backup_id,))
            conn.commit()
        finally:
            conn.close()

    return jsonify({"deleted": True})


# --- Network Diagnostics Routes ---
@app.route('/api/network/status', methods=['GET'])
def network_status():
    return jsonify({
        "local_ips": get_local_ips(),
        "ssh_status": probe_ssh_status(),
        "tunnel_status": probe_localtonet_status(),
        "ollama_status": probe_ollama_status(),
        "nexusnode_port": config.PORT
    })


@app.route('/api/network/test', methods=['POST'])
def run_network_diagnostic():
    data = request.get_json(force=True, silent=True) or {}
    target = str(data.get('target', 'internet')).strip().lower()

    t0 = time.time()
    status = "unavailable"
    latency_ms = None
    details = ""

    if target == 'internet':
        try:
            r = requests.get("https://1.1.1.1", timeout=2.0)
            latency_ms = round((time.time() - t0) * 1000, 1)
            status = "available" if r.status_code == 200 else "unavailable"
            details = f"Cloudflare 1.1.1.1 responded in {latency_ms}ms"
        except Exception as e:
            details = str(e)
    elif target == 'local':
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(1.0)
            result = s.connect_ex(('127.0.0.1', config.PORT))
            s.close()
            latency_ms = round((time.time() - t0) * 1000, 1)
            status = "available" if result == 0 else "unavailable"
            details = f"Loopback responded in {latency_ms}ms"
        except Exception as e:
            details = str(e)
    elif target == 'nexusnode':
        latency_ms = round((time.time() - t0) * 1000, 1)
        status = "available"
        details = f"NexusNode WSGI engine online ({latency_ms}ms)"
    elif target == 'tunnel':
        tunnel_url = get_tunnel_url()
        try:
            r = requests.get(f"{tunnel_url}/api/health", headers={'localtonet-skip-warning': 'true'}, timeout=3.0)
            latency_ms = round((time.time() - t0) * 1000, 1)
            status = "available" if r.status_code == 200 else "unavailable"
            details = f"Tunnel {tunnel_url} responded ({latency_ms}ms)"
        except Exception as e:
            details = f"Tunnel unreachable: {str(e)}"
    elif target == 'ollama':
        status_info = probe_ollama_status()
        status = "available" if status_info["status"] == "running" else "unavailable"
        details = f"Ollama daemon state: {status_info['status']}"

    return jsonify({
        "target": target,
        "status": status,
        "latency_ms": latency_ms,
        "details": details
    })


# --- Events & Incident Center Routes ---
@app.route('/api/events', methods=['GET'])
def get_events_paginated():
    category = request.args.get('category', 'ALL').upper()
    level = request.args.get('level', '').upper()
    search = request.args.get('search', '').lower()
    limit = min(200, int(request.args.get('limit', 100)))

    with DB_LOCK:
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            query = "SELECT * FROM system_logs"
            params = []
            conditions = []

            if category and category != 'ALL':
                conditions.append("category = ?")
                params.append(category)
            if level:
                conditions.append("level = ?")
                params.append(level)
            if search:
                conditions.append("LOWER(message) LIKE ?")
                params.append(f"%{search}%")

            if conditions:
                query += " WHERE " + " AND ".join(conditions)

            query += " ORDER BY created_at DESC LIMIT ?;"
            params.append(limit)

            cur.execute(query, params)
            rows = cur.fetchall()
            return jsonify([dict(r) for r in rows])
        finally:
            conn.close()


@app.route('/api/incidents', methods=['GET'])
def get_incidents():
    with DB_LOCK:
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM incidents ORDER BY created_at DESC LIMIT 50;")
            rows = cur.fetchall()
            incidents = []
            for r in rows:
                item = dict(r)
                try:
                    item["timeline"] = json.loads(item["timeline"])
                except Exception:
                    item["timeline"] = []
                incidents.append(item)
            return jsonify(incidents)
        finally:
            conn.close()


# --- Scheduled Automation Routes ---
@app.route('/api/automation/jobs', methods=['GET'])
def list_scheduled_jobs():
    err = require_privilege_or_admin("can_manage_automation")
    if err:
        return err
    with DB_LOCK:
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM scheduled_jobs ORDER BY created_at ASC;")
            rows = cur.fetchall()
            return jsonify([dict(r) for r in rows])
        finally:
            conn.close()


@app.route('/api/automation/jobs/<job_id>/toggle', methods=['POST'])
def toggle_scheduled_job(job_id):
    err = require_privilege_or_admin("can_manage_automation")
    if err:
        return err

    with DB_LOCK:
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT enabled FROM scheduled_jobs WHERE id = ?;", (job_id,))
            row = cur.fetchone()
            if not row:
                return jsonify({"error": "Job not found"}), 404
            new_state = 0 if row["enabled"] else 1
            conn.execute("UPDATE scheduled_jobs SET enabled = ? WHERE id = ?;", (new_state, job_id))
            conn.commit()
            return jsonify({"id": job_id, "enabled": bool(new_state)})
        finally:
            conn.close()


@app.route('/api/automation/jobs/<job_id>/run', methods=['POST'])
def trigger_scheduled_job_now(job_id):
    err = require_privilege_or_admin("can_manage_automation")
    if err:
        return err

    with DB_LOCK:
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM scheduled_jobs WHERE id = ?;", (job_id,))
            row = cur.fetchone()
            if not row:
                return jsonify({"error": "Job not found"}), 404
            job_row = dict(row)
        finally:
            conn.close()

    scheduler_daemon.trigger_job(job_row)
    return jsonify({"triggered": True})


# --- System Settings Routes ---
@app.route('/api/settings', methods=['GET'])
def get_system_settings():
    err = require_privilege_or_admin("can_manage_settings")
    if err:
        return err
    return jsonify({
        "version": getattr(config, 'VERSION', '2.2.0'),
        "port": config.PORT,
        "ssh_port": config.SSH_PORT,
        "ollama_port": config.OLLAMA_PORT,
        "ram_normal_mb": config.RAM_NORMAL_THRESHOLD_MB,
        "ram_pressure_mb": config.RAM_PRESSURE_THRESHOLD_MB,
        "max_heavy_concurrency": config.MAX_HEAVY_CONCURRENCY,
        "session_ttl_seconds": config.SESSION_EXPIRY_SECONDS,
        "rag_max_chunks": config.RAG_MAX_CHUNKS
    })


@app.route('/api/settings', methods=['POST'])
def update_system_settings():
    err = require_privilege_or_admin("can_manage_settings")
    if err:
        return err

    data = request.get_json(force=True, silent=True) or {}
    restart_required = False

    if 'ram_normal_mb' in data:
        config.RAM_NORMAL_THRESHOLD_MB = int(data['ram_normal_mb'])
        governor.normal_threshold_mb = config.RAM_NORMAL_THRESHOLD_MB

    if 'ram_pressure_mb' in data:
        config.RAM_PRESSURE_THRESHOLD_MB = int(data['ram_pressure_mb'])
        governor.pressure_threshold_mb = config.RAM_PRESSURE_THRESHOLD_MB

    if 'port' in data and int(data['port']) != config.PORT:
        restart_required = True

    log_event("INFO", "SETTINGS", f"Settings updated by '{g.user.get('user_id')}' (Restart required: {restart_required})")
    return jsonify({"updated": True, "restart_required": restart_required})


# --- AI Studio & Ollama Management Routes ---
@app.route('/api/models/estimate', methods=['POST'])
def estimate_model_resources():
    data = request.get_json(force=True, silent=True) or {}
    model_name = str(data.get('model', '')).strip().lower()

    # Model size estimation table (MB)
    size_table = {
        "qwen2.5:0.5b": 350,
        "llama3.2:1b": 750,
        "deepseek-r1:1.5b": 1100,
        "smollm:135m": 150,
        "smollm:360m": 250,
        "llama3.2:3b": 2200,
        "phi3:mini": 2400,
        "mistral:7b": 4600
    }
    estimated_mb = size_table.get(model_name, 1500)
    mem = governor.get_memory_status()
    avail_mb = mem["available_mb"]

    is_safe = (avail_mb - estimated_mb >= 500) and (mem["state"] != "critical")
    decision = "SAFE" if is_safe else "BLOCKED"
    reason = "Resources are sufficient for model execution." if is_safe else f"Insufficient memory: model needs ~{estimated_mb} MB, only {avail_mb} MB available."

    return jsonify({
        "model": model_name,
        "estimated_mb": estimated_mb,
        "available_mb": avail_mb,
        "governor_state": mem["state"],
        "decision": decision,
        "reason": reason
    })


@app.route('/api/models/<model_name>', methods=['DELETE'])
def delete_ollama_model(model_name):
    err = require_privilege_or_admin("can_manage_models")
    if err:
        return err

    try:
        r = requests.delete(f"{config.OLLAMA_HOST}/api/delete", json={"name": model_name}, timeout=10)
        log_event("INFO", "OLLAMA", f"Deleted Ollama model: '{model_name}'")
        return jsonify({"deleted": True})
    except Exception as e:
        return jsonify({"error": f"Failed to delete model: {str(e)}"}), 500


@app.route('/api/rag/sources', methods=['GET', 'POST'])
def rag_sources_endpoint():
    if request.method == 'POST':
        err = require_privilege_or_admin("can_use_rag")
        if err:
            return err
        data = request.get_json(force=True, silent=True) or {}
        rag_engine.source_folders = data.get('sources', ["."])
        rag_engine.trigger_rebuild_async()
        return jsonify({"sources": rag_engine.source_folders})

    return jsonify({
        "sources": rag_engine.source_folders,
        "supported_extensions": ["PDF", "TXT", "MD", "DOCX", "PY", "JSON", "SH", "HTML", "JS", "TS", "ENV", "YML"]
    })


@app.route('/api/rag/status', methods=['GET'])
def get_rag_status():
    return jsonify({
        "state": rag_engine.state,
        "documents_count": len(rag_engine.index.get("documents", {})),
        "chunks_count": len(rag_engine.index.get("chunks", [])),
        "updated_at": rag_engine.index.get("updated_at")
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
            "reason": res_check["reason"],
            "message": res_check["reason"],
            "state": res_check["state"],
            "available_mb": res_check.get("available_mb")
        }), 429

    rag_engine.trigger_rebuild_async()
    return jsonify({"message": "RAG indexing initiated in background."})


@app.route('/api/models/pull', methods=['POST'])
def pull_model_endpoint():
    err = require_privilege_or_admin("can_manage_models")
    if err:
        return err

    data = request.get_json(force=True, silent=True) or {}
    model_name = str(data.get('model', '')).strip().lower()
    if not model_name:
        return jsonify({"error": "validation_error", "message": "Model name is required."}), 400

    title = f"Pull Model: {model_name}"
    task_id, res_info = task_runner.enqueue_task(title, "model_pull", run_model_pull_job, model_name)

    if not task_id:
        return jsonify({
            "allowed": False,
            "error": "resource_pressure",
            "reason": res_info["reason"],
            "message": res_info["reason"],
            "state": res_info["state"],
            "available_mb": res_info.get("available_mb")
        }), 429

    return jsonify({"task_id": task_id, "status": "queued", "title": title})


def run_model_pull_job(task_obj: dict, model_name: str):
    task_obj['logs'].append(f"Initiating Ollama model pull for '{model_name}'...")
    try:
        r = requests.post(
            f"{config.OLLAMA_HOST}/api/pull",
            json={"name": model_name, "stream": True},
            stream=True,
            timeout=3600
        )
        if r.status_code != 200:
            raise RuntimeError(f"Ollama pull returned HTTP {r.status_code}: {r.text}")

        for line in r.iter_lines():
            if task_obj['status'] == 'cancelled':
                task_obj['logs'].append("[CANCELLED] Model download aborted.")
                break
            if line:
                try:
                    data = json.loads(line.decode('utf-8'))
                    status_text = data.get('status', '')
                    total = data.get('total', 0)
                    completed = data.get('completed', 0)
                    if total > 0:
                        pct = int((completed / total) * 100)
                        task_obj['progress'] = min(99, pct)
                        task_obj['logs'].append(f"{status_text} ({pct}%) [{completed // (1024*1024)} MB / {total // (1024*1024)} MB]")
                    else:
                        task_obj['logs'].append(status_text)
                except Exception:
                    pass

        task_obj['logs'].append(f"Model '{model_name}' ready for AI inference!")
    except requests.exceptions.ConnectionError:
        raise RuntimeError("Ollama daemon is offline. Start the engine from the Dashboard.")


@app.route('/models', methods=['GET'])
def list_available_models():
    models = []
    try:
        r = requests.get(f"{config.OLLAMA_HOST}/api/tags", timeout=1.0)
        if r.status_code == 200:
            models = [m["name"] for m in r.json().get("models", [])]
    except Exception:
        pass

    try:
        for f in os.listdir(config.STORAGE_DIR):
            if f.endswith(('.gguf', '.bin')):
                models.append(f)
    except Exception:
        pass

    return jsonify(list(set(models)))


@app.route('/start', methods=['GET', 'POST'])
def start_engine():
    err = require_privilege_or_admin("can_control_services")
    if err:
        return err

    res_check = governor.can_start_ollama()
    if not res_check["allowed"]:
        return jsonify({
            "allowed": False,
            "error": "resource_pressure",
            "reason": res_check["reason"],
            "message": res_check["reason"],
            "state": res_check["state"],
            "available_mb": res_check.get("available_mb")
        }), 429

    status = probe_ollama_status()
    if status["status"] == "running":
        return jsonify({"message": "AI Engine is already running."}), 200

    try:
        subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        log_event("INFO", "OLLAMA", f"Ollama engine start issued by '{g.user.get('user_id')}'")
        return jsonify({"message": "AI Engine start command sent."}), 200
    except Exception as e:
        log_event("ERROR", "OLLAMA", f"Failed to start Ollama: {str(e)}")
        return jsonify({"error": f"Failed to start Ollama: {str(e)}"}), 500


@app.route('/stop', methods=['GET', 'POST'])
def stop_engine():
    err = require_privilege_or_admin("can_control_services")
    if err:
        return err

    try:
        subprocess.run(["pkill", "-f", "ollama"], stderr=subprocess.DEVNULL)
        log_event("INFO", "OLLAMA", f"Ollama engine stopped by '{g.user.get('user_id')}'")
        return jsonify({"message": "AI Engine stop command sent."}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# --- Storage & Tasks Core Routes ---
@app.route('/files', methods=['GET'])
def list_files():
    file_list = []
    try:
        for root, dirs, files in os.walk(config.STORAGE_DIR):
            for d in dirs:
                if d != '__pycache__':
                    rel = os.path.relpath(os.path.join(root, d), config.STORAGE_DIR).replace('\\', '/')
                    file_list.append({"name": rel, "is_dir": True})
            for f in files:
                rel = os.path.relpath(os.path.join(root, f), config.STORAGE_DIR).replace('\\', '/')
                file_list.append({"name": rel, "is_dir": False})
    except Exception:
        pass
    return jsonify(file_list)


@app.route('/upload', methods=['POST'])
def upload_file():
    err = require_privilege_or_admin("can_upload_files")
    if err:
        return err

    if 'file' not in request.files:
        return jsonify({"error": "validation_error", "message": "No file attached."}), 400

    file = request.files['file']
    if not file or not file.filename:
        return jsonify({"error": "validation_error", "message": "Empty filename."}), 400

    try:
        target_path = sanitize_storage_path(file.filename)
        file.save(target_path)
        log_event("INFO", "STORAGE", f"User '{g.user.get('user_id')}' uploaded '{file.filename}'")
        rag_engine.trigger_rebuild_async()
        return jsonify({"message": f"File '{file.filename}' uploaded successfully."})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route('/download/<path:filename>', methods=['GET'])
def download_file(filename):
    try:
        safe_path = sanitize_storage_path(filename)
        if not os.path.exists(safe_path):
            return jsonify({"error": "File not found"}), 404
        return send_from_directory(os.path.dirname(safe_path), os.path.basename(safe_path), as_attachment=True)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@app.route('/preview/<path:filename>', methods=['GET'])
def preview_file(filename):
    try:
        safe_path = sanitize_storage_path(filename)
        return stream_file_range(safe_path)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@app.route('/files/<path:filename>', methods=['DELETE'])
def delete_file(filename):
    err = require_privilege_or_admin("can_manage_files")
    if err:
        return err

    try:
        safe_path = sanitize_storage_path(filename)
        if os.path.exists(safe_path):
            if os.path.isdir(safe_path):
                shutil.rmtree(safe_path)
            else:
                os.remove(safe_path)
            log_event("WARN", "STORAGE", f"User '{g.user.get('user_id')}' deleted '{filename}'")
            rag_engine.trigger_rebuild_async()
            return jsonify({"message": f"'{filename}' deleted."})
        return jsonify({"error": "File not found"}), 404
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@app.route('/api/tasks', methods=['GET'])
def get_tasks():
    return jsonify(task_runner.list_tasks())


@app.route('/api/tasks/media-download', methods=['POST'])
def start_media_download_legacy():
    return start_media_download_advanced()


@app.route('/api/tasks/<task_id>/cancel', methods=['POST'])
def cancel_task_endpoint(task_id):
    # Any user with media download or file management privileges or admin can cancel
    if not (has_privilege("can_download_media") or has_privilege("can_manage_files")):
        return require_admin()
    if err:
        return err
    success = task_runner.cancel_task(task_id)
    return jsonify({"cancelled": success})


@app.route('/api/archive/extract', methods=['POST'])
def extract_archive_endpoint():
    err = require_privilege_or_admin("can_manage_files")
    if err:
        return err

    data = request.get_json(force=True, silent=True) or {}
    filename = str(data.get('filename', '')).strip()
    if not filename:
        return jsonify({"error": "validation_error", "message": "Archive filename is required."}), 400

    try:
        src_path = sanitize_storage_path(filename)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    if not os.path.exists(src_path):
        return jsonify({"error": f"File '{filename}' not found."}), 404

    title = f"Extract Archive: {filename}"
    task_id, res_info = task_runner.enqueue_task(title, "archive_extract", run_archive_extract_job, filename)

    if not task_id:
        return jsonify({
            "allowed": False,
            "error": "resource_pressure",
            "reason": res_info["reason"],
            "message": res_info["reason"],
            "state": res_info["state"],
            "available_mb": res_info.get("available_mb")
        }), 429

    return jsonify({"task_id": task_id, "status": "queued", "title": title})


def run_archive_extract_job(task_obj: dict, archive_filename: str, extract_to_folder: bool = True):
    task_obj['logs'].append(f"Opening archive: {archive_filename}")
    src_path = sanitize_storage_path(archive_filename)
    if not os.path.exists(src_path):
        raise RuntimeError(f"Archive '{archive_filename}' not found in vault.")

    stem = os.path.splitext(os.path.basename(src_path))[0]
    dest_dir = os.path.join(config.STORAGE_DIR, stem) if extract_to_folder else config.STORAGE_DIR
    os.makedirs(dest_dir, exist_ok=True)
    task_obj['logs'].append(f"Target extraction directory: {dest_dir}")

    ext = archive_filename.split('.')[-1].lower()

    if zipfile.is_zipfile(src_path):
        with zipfile.ZipFile(src_path, 'r') as zf:
            infolist = zf.infolist()
            total = len(infolist)
            for idx, member in enumerate(infolist):
                if task_obj['status'] == 'cancelled':
                    break
                member_path = os.path.abspath(os.path.join(dest_dir, member.filename))
                if not member_path.startswith(os.path.abspath(dest_dir)):
                    raise RuntimeError(f"Security: malicious zip entry '{member.filename}' detected.")
                zf.extract(member, dest_dir)
                task_obj['progress'] = min(99, int(((idx + 1) / max(1, total)) * 100))
                if (idx + 1) % 10 == 0 or idx == total - 1:
                    task_obj['logs'].append(f"Extracted: {member.filename} ({idx+1}/{total})")

    elif tarfile.is_tarfile(src_path):
        with tarfile.open(src_path, 'r') as tf:
            members = tf.getmembers()
            total = len(members)
            for idx, member in enumerate(members):
                if task_obj['status'] == 'cancelled':
                    break
                member_path = os.path.abspath(os.path.join(dest_dir, member.name))
                if not member_path.startswith(os.path.abspath(dest_dir)):
                    raise RuntimeError(f"Security: malicious tar entry '{member.name}' detected.")
                tf.extract(member, dest_dir)
                task_obj['progress'] = min(99, int(((idx + 1) / max(1, total)) * 100))
                if (idx + 1) % 10 == 0 or idx == total - 1:
                    task_obj['logs'].append(f"Extracted: {member.name} ({idx+1}/{total})")
    else:
        raise RuntimeError("Unsupported archive format.")

    task_obj['logs'].append("Extraction completed successfully.")
    rag_engine.trigger_rebuild_async()


# --- Chat & AI Streaming ---
@app.route('/api/chats', methods=['GET'])
def get_user_chats():
    err = require_privilege_or_admin("can_use_ai")
    if err:
        return err
    with DB_LOCK:
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT role, message, citations FROM user_chats WHERE user_id = ? ORDER BY id ASC;", (g.user.get('user_id'),))
            rows = cur.fetchall()
            messages = []
            for r in rows:
                citations = json.loads(r["citations"]) if r["citations"] else []
                messages.append({"role": r["role"], "text": r["message"], "citations": citations})
            return jsonify(messages)
        finally:
            conn.close()


@app.route('/api/chats', methods=['POST'])
def save_user_chats():
    err = require_privilege_or_admin("can_use_ai")
    if err:
        return err
    data = request.get_json(force=True, silent=True) or {}
    messages = data.get('messages', [])
    user_id = g.user.get('user_id')

    with DB_LOCK:
        conn = get_db_connection()
        try:
            conn.execute("DELETE FROM user_chats WHERE user_id = ?;", (user_id,))
            for m in messages:
                citations = json.dumps(m.get('citations', []))
                conn.execute("""
                    INSERT INTO user_chats (user_id, role, message, citations, created_at)
                    VALUES (?, ?, ?, ?, ?);
                """, (user_id, m.get('role', 'user'), m.get('text', ''), citations, time.time()))
            conn.commit()
        finally:
            conn.close()
    return jsonify({"saved": True})


@app.route('/api/chats', methods=['DELETE'])
def clear_user_chats():
    err = require_privilege_or_admin("can_use_ai")
    if err:
        return err
    user_id = g.user.get('user_id')
    with DB_LOCK:
        conn = get_db_connection()
        try:
            conn.execute("DELETE FROM user_chats WHERE user_id = ?;", (user_id,))
            conn.commit()
        finally:
            conn.close()
    return jsonify({"cleared": True})


@app.route('/chat/stream', methods=['POST'])
def chat_stream():
    err = require_privilege_or_admin("can_use_ai")
    if err:
        return err
    data = request.get_json(force=True, silent=True) or {}
    prompt = str(data.get('prompt', '')).strip()
    model = str(data.get('model', ''))
    rag_enabled = bool(data.get('rag_enabled', True))

    if not prompt:
        return jsonify({"error": "validation_error", "message": "Prompt is required."}), 400

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

        try:
            r = requests.post(
                f"{config.OLLAMA_HOST}/api/generate",
                json={"model": model, "prompt": augmented_prompt, "stream": True},
                stream=True,
                timeout=120
            )
            if r.status_code != 200:
                yield f"data: {json.dumps({'error': f'Ollama error: HTTP {r.status_code}'})}\n\n"
                return

            for line in r.iter_lines():
                if line:
                    try:
                        chunk = json.loads(line.decode('utf-8'))
                        token = chunk.get('response', '')
                        if token:
                            yield f"data: {json.dumps({'token': token})}\n\n"
                        if chunk.get('done', False):
                            yield f"data: {json.dumps({'done': True})}\n\n"
                            break
                    except Exception:
                        pass
        except Exception as e:
            yield f"data: {json.dumps({'error': f'AI Engine error: {str(e)}'})}\n\n"

    return Response(stream_with_context(generate_sse()), mimetype='text/event-stream')


# --- Live Logs SSE Stream ---
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


# --- Admin & RBAC Routes ---
@app.route('/api/admin/users', methods=['GET'])
def admin_list_users():
    err = require_privilege_or_admin("can_manage_users")
    if err:
        return err
    users = db_get_all_users()
    clean_users = [{"user_id": u["user_id"], "role": u["role"], "privileges": u["privileges"], "created_at": u["created_at"]} for u in users.values()]
    return jsonify(clean_users)


@app.route('/api/admin/users', methods=['POST'])
def admin_create_user():
    err = require_privilege_or_admin("can_manage_users")
    if err:
        return err

    data = request.get_json(force=True, silent=True) or {}
    user_id = str(data.get('user_id', '')).strip().lower()
    password = str(data.get('password', '')).strip()
    privileges = data.get('privileges', dict(config.USER_DEFAULT_PRIVILEGES))

    if not user_id or not password:
        return jsonify({"error": "User ID and password are required."}), 400

    if db_get_user(user_id):
        return jsonify({"error": f"User '{user_id}' already exists."}), 409

    hashed, salt = hash_password(password)
    role = "admin" if all(privileges.get(p) for p in config.ALL_PRIVILEGES) else "user"

    with DB_LOCK:
        conn = get_db_connection()
        try:
            conn.execute("""
                INSERT INTO users (user_id, password_hash, salt, role, privileges, created_at)
                VALUES (?, ?, ?, ?, ?, ?);
            """, (user_id, hashed, salt, role, json.dumps(privileges), datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")))
            conn.commit()
        finally:
            conn.close()

    log_event("INFO", "ADMIN", f"Admin '{g.user.get('user_id')}' created new user '{user_id}' ({role})")
    return jsonify({"user_id": user_id, "role": role, "privileges": privileges}), 201


@app.route('/api/admin/users/update-privileges', methods=['POST'])
def admin_update_privileges():
    err = require_admin()
    if err:
        return err

    data = request.get_json(force=True, silent=True) or {}
    user_id = str(data.get('user_id', '')).strip().lower()
    privileges = data.get('privileges', {})

    if not user_id:
        return jsonify({"error": "User ID is required."}), 400

    role = "admin" if all(privileges.get(p) for p in config.ALL_PRIVILEGES) else "user"

    with DB_LOCK:
        conn = get_db_connection()
        try:
            conn.execute("UPDATE users SET privileges = ?, role = ? WHERE user_id = ?;", (json.dumps(privileges), role, user_id))
            conn.commit()
        finally:
            conn.close()

    log_event("INFO", "ADMIN", f"Admin updated privileges for '{user_id}'")
    return jsonify({"user_id": user_id, "role": role, "privileges": privileges})


@app.route('/api/admin/users/reset-password', methods=['POST'])
def admin_reset_password():
    err = require_admin()
    if err:
        return err

    data = request.get_json(force=True, silent=True) or {}
    user_id = str(data.get('user_id', '')).strip().lower()
    new_password = str(data.get('new_password', '')).strip()

    if not user_id or not new_password:
        return jsonify({"error": "User ID and new password are required."}), 400

    hashed, salt = hash_password(new_password)
    with DB_LOCK:
        conn = get_db_connection()
        try:
            conn.execute("UPDATE users SET password_hash = ?, salt = ? WHERE user_id = ?;", (hashed, salt, user_id))
            conn.commit()
        finally:
            conn.close()

    log_event("INFO", "ADMIN", f"Password reset executed for user '{user_id}'")
    return jsonify({"message": f"Password for '{user_id}' updated."})


@app.route('/api/admin/users/<user_id>', methods=['DELETE'])
def admin_delete_user(user_id):
    err = require_admin()
    if err:
        return err

    if user_id.lower() == 'admin':
        return jsonify({"error": "Root admin account cannot be deleted."}), 400

    with DB_LOCK:
        conn = get_db_connection()
        try:
            conn.execute("DELETE FROM users WHERE user_id = ?;", (user_id,))
            conn.commit()
        finally:
            conn.close()

    log_event("WARN", "ADMIN", f"User account '{user_id}' was deleted.")
    return jsonify({"message": f"User '{user_id}' deleted."})


@app.route('/api/admin/stats', methods=['GET'])
def admin_stats():
    err = require_admin()
    if err:
        return err

    with DB_LOCK:
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM users;")
            total_users = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM system_logs;")
            total_logs = cur.fetchone()[0]
        finally:
            conn.close()

    with SESSIONS_LOCK:
        active_sessions = len(SESSIONS)

    with FAILED_LOGINS_LOCK:
        failed_ips = len(FAILED_LOGINS)

    return jsonify({
        "total_users": total_users,
        "total_logs_in_db": total_logs,
        "active_sessions": active_sessions,
        "failed_login_ips": failed_ips
    })


@app.route('/api/admin/db/tables', methods=['GET'])
def admin_db_tables():
    err = require_admin()
    if err:
        return err

    with DB_LOCK:
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")
            tables = [r["name"] for r in cur.fetchall()]
            counts = []
            for t in tables:
                cur.execute(f"SELECT COUNT(*) FROM {t};")
                counts.append({"name": t, "count": cur.fetchone()[0]})
            return jsonify({"tables": counts})
        finally:
            conn.close()


@app.route('/api/admin/db/query', methods=['GET'])
def admin_db_query():
    err = require_admin()
    if err:
        return err

    table = request.args.get('table', 'users')
    limit = min(100, int(request.args.get('limit', 30)))

    allowed_tables = ['users', 'user_chats', 'system_logs', 'background_tasks', 'shares', 'backups', 'scheduled_jobs', 'incidents']
    if table not in allowed_tables:
        return jsonify({"error": "Invalid table requested."}), 400

    with DB_LOCK:
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute(f"PRAGMA table_info({table});")
            columns = [c["name"] for c in cur.fetchall()]

            cur.execute(f"SELECT * FROM {table} ORDER BY rowid DESC LIMIT ?;", (limit,))
            rows = cur.fetchall()

            data = []
            for r in rows:
                row_dict = {}
                for col in columns:
                    val = r[col]
                    if col in ['password_hash', 'salt']:
                        val = "●●●●●●●● (PBKDF2-SHA256)"
                    row_dict[col] = val
                data.append(row_dict)

            return jsonify({
                "table": table,
                "columns": columns,
                "count": len(data),
                "rows": data
            })
        finally:
            conn.close()


# --- Static & Frontend ---
@app.route('/')
def serve_index():
    return send_from_directory('.', 'index.html')


@app.route('/static/<path:filename>')
def serve_static_assets(filename):
    return send_from_directory(os.path.join(config.BASE_DIR, 'static'), filename)


# ==============================================================================
# SERVER INITIALIZATION & PRODUCTION WSGI BOOTSTRAP
# ==============================================================================

if __name__ == '__main__':
    tunnel_url = get_tunnel_url()
    local_ips = get_local_ips()

    print("\n" + "═"*66)
    print(" 🚀 NexusNode 24/7 Personal Mobile Server Appliance Online")
    print("═"*66)
    print(f" 🛡️  Root Admin User : 'admin'")
    print(f" 💾 Database Engine : SQLite (WAL Mode @ {config.DB_FILE})")
    print(f" 🧠 RAM Governor    : Normal > {config.RAM_NORMAL_THRESHOLD_MB}MB | Critical < {config.RAM_PRESSURE_THRESHOLD_MB}MB")
    print(f" ⚡ Task Worker     : Bounded Queue (Max Heavy Concurrency: {config.MAX_HEAVY_CONCURRENCY})")
    
    if tunnel_url:
        skip_param = "?localtonet-skip-warning=true" if "?" not in tunnel_url else "&localtonet-skip-warning=true"
        print(f" 🌐 Global Tunnel   : {tunnel_url}{skip_param}")
    
    print(f" 🏠 Localhost       : http://127.0.0.1:{config.PORT}")
    for ip in local_ips:
        print(f" 📶 Local Wi-Fi     : http://{ip}:{config.PORT}")
    print("═"*66 + "\n")

    # Evaluate Waitress Production WSGI Server for Termux
    try:
        from waitress import serve
        print("[*] Starting with Waitress Multi-Threaded WSGI Server (8 worker threads)...")
        serve(app, host=config.HOST, port=config.PORT, threads=8, channel_timeout=120)
    except ImportError:
        print("[*] Waitress not installed. Running with standard Flask threaded WSGI engine...")
        app.run(host=config.HOST, port=config.PORT, debug=False, threaded=True)
