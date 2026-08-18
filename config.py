"""
NexusNode — Central Configuration Module
Provides centralized, environment-aware configuration for 24/7 Termux mobile server appliance.
Engineered specifically for unrooted Android 13 Termux on ~4 GB RAM hardware (TECNO BG6).
"""

import os
import secrets
from dotenv import load_dotenv


# ==============================================================================
# BASE PATHS / ENVIRONMENT
# ==============================================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Load .env BEFORE any environment-backed configuration is read.
ENV_FILE = os.path.join(BASE_DIR, ".env")
load_dotenv(ENV_FILE, override=True)


# ==============================================================================
# AUTHORITATIVE SERVER VERSION
# ==============================================================================

NEXUS_SERVER_VERSION = "2.3.8"
VERSION = NEXUS_SERVER_VERSION


# ==============================================================================
# STORAGE PATHS
# ==============================================================================

STORAGE_DIR = os.environ.get(
    "NEXUS_STORAGE_DIR",
    os.path.join(BASE_DIR, "storage_vault")
)

UNIFIED_DB_FILE = os.path.join(STORAGE_DIR, "nexus_unified.db")
DB_FILE = UNIFIED_DB_FILE
DB_PATH = UNIFIED_DB_FILE
AUDIT_DB_FILE = UNIFIED_DB_FILE

RAG_INDEX_FILE = os.environ.get(
    "NEXUS_RAG_INDEX_FILE",
    os.path.join(STORAGE_DIR, "rag_index.json")
)

RAG_DB_FILE = os.environ.get(
    "NEXUS_RAG_DB_FILE",
    os.path.join(STORAGE_DIR, "rag_vault.db")
)

BACKUP_DIR = os.environ.get(
    "NEXUS_BACKUP_DIR",
    os.path.join(STORAGE_DIR, "backups")
)

CONFIG_FILE = os.path.join(STORAGE_DIR, "server_config.json")

EMERGENCY_LOG_FILE = os.environ.get(
    "NEXUS_EMERGENCY_LOG",
    os.path.join(BASE_DIR, "emergency_fallback.log")
)


# Ensure critical storage directories exist.

os.makedirs(STORAGE_DIR, exist_ok=True)
os.makedirs(BACKUP_DIR, exist_ok=True)


# ==============================================================================
# NETWORK & PORTS
# ==============================================================================

PORT = int(os.environ.get("NEXUS_PORT", 5000))
HOST = os.environ.get("NEXUS_HOST", "0.0.0.0")

SSH_PORT = int(os.environ.get("NEXUS_SSH_PORT", 8022))

OLLAMA_PORT = int(
    os.environ.get("NEXUS_OLLAMA_PORT", 11434)
)

OLLAMA_HOST = os.environ.get(
    "OLLAMA_HOST",
    f"http://127.0.0.1:{OLLAMA_PORT}"
)


# ==============================================================================
# LOCALTONET TUNNEL
# ==============================================================================

DEFAULT_TUNNEL_URL = os.environ.get(
    "LOCALTONET_URL",
    "https://k09oezeyib.localto.net"
)

LOCALTONET_LOG_PATHS = [
    os.path.join(BASE_DIR, "localtonet.log"),
    os.path.expanduser("~/.localtonet/localtonet.log"),
    os.path.expanduser("~/localtonet.log"),
    "/data/data/com.termux/files/home/localtonet.log"
]


# ==============================================================================
# SECURITY, PASSWORDS & CREDENTIALS
# ==============================================================================

SECRET_KEY = os.environ.get(
    "NEXUS_SECRET_KEY",
    secrets.token_hex(32)
)

SESSION_EXPIRY_SECONDS = int(
    os.environ.get(
        "NEXUS_SESSION_TTL",
        7 * 24 * 3600
    )
)

PLAYBACK_TOKEN_TTL_SECONDS = int(
    os.environ.get(
        "NEXUS_PLAYBACK_TOKEN_TTL",
        120
    )
)

PASSWORD_KDF_ITERATIONS = int(
    os.environ.get(
        "NEXUS_PASSWORD_KDF_ITERATIONS",
        100000
    )
)

LOCKOUT_THRESHOLD = int(
    os.environ.get(
        "NEXUS_LOCKOUT_THRESHOLD",
        5
    )
)

LOCKOUT_DURATION_SECONDS = int(
    os.environ.get(
        "NEXUS_LOCKOUT_DURATION",
        600
    )
)


# ==============================================================================
# 4 GB RAM FORMAL MEMORY BUDGET
# ==============================================================================

BUDGET_ANDROID_SYSTEM_MB = 1500
BUDGET_CORE_SERVER_MB = 180
BUDGET_RAG_INDEX_MB = 30
BUDGET_OLLAMA_MODEL_MB = 1200
BUDGET_HEAVY_TASK_MB = 250
BUDGET_SAFETY_HEADROOM_MB = 640


# ==============================================================================
# 4 GB RAM RESOURCE GOVERNOR THRESHOLDS
# ==============================================================================

RAM_NORMAL_THRESHOLD_MB = int(
    os.environ.get(
        "NEXUS_RAM_NORMAL_MB",
        1000
    )
)

RAM_PRESSURE_THRESHOLD_MB = int(
    os.environ.get(
        "NEXUS_RAM_PRESSURE_MB",
        600
    )
)


# ==============================================================================
# THERMAL THRESHOLDS
# ==============================================================================

THERMAL_WARM_C = int(
    os.environ.get(
        "NEXUS_THERMAL_WARM_C",
        42
    )
)

THERMAL_THROTTLED_C = int(
    os.environ.get(
        "NEXUS_THERMAL_THROTTLED_C",
        48
    )
)

THERMAL_CRITICAL_C = int(
    os.environ.get(
        "NEXUS_THERMAL_CRITICAL_C",
        55
    )
)


# ==============================================================================
# BACKGROUND TASK WORKER CONCURRENCY
# ==============================================================================

MAX_HEAVY_CONCURRENCY = int(
    os.environ.get(
        "NEXUS_MAX_HEAVY_CONCURRENCY",
        1
    )
)

SUBPROCESS_TIMEOUT_SECONDS = int(
    os.environ.get(
        "NEXUS_TASK_TIMEOUT",
        3600
    )
)


# ==============================================================================
# CANONICAL STORAGE PATHS & VAULT CATEGORIES
# ==============================================================================

MEDIA_CATEGORIES = [
    "downloads",
    "music",
    "videos",
    "podcasts",
    "documents",
    "other"
]

MEDIA_CATEGORY_LABELS = {
    "downloads": "Downloads",
    "music": "Music",
    "videos": "Videos",
    "podcasts": "Podcasts",
    "documents": "Documents",
    "other": "Other"
}

for cat in MEDIA_CATEGORIES:
    os.makedirs(
        os.path.join(STORAGE_DIR, cat),
        exist_ok=True
    )


# ==============================================================================
# RAG & MEMORY PROTECTION
# ==============================================================================

RAG_MAX_FILE_SIZE_BYTES = int(
    os.environ.get(
        "NEXUS_RAG_MAX_FILE_SIZE",
        5 * 1024 * 1024
    )
)

RAG_MAX_CHUNKS = int(
    os.environ.get(
        "NEXUS_RAG_MAX_CHUNKS",
        2500
    )
)

RAG_DEFAULT_SOURCES = [
    "docs",
    "notes",
    "code"
]

for src in RAG_DEFAULT_SOURCES:
    os.makedirs(
        os.path.join(STORAGE_DIR, src),
        exist_ok=True
    )

RAG_EXCLUDE_DIRS = [
    "backups",
    "music",
    "videos",
    "podcasts",
    "downloads",
    "Music",
    "Videos",
    "Podcasts",
    "Downloads",
    ".tmp",
    ".git",
    "__pycache__",
    "node_modules",
    ".ssh",
    ".localtonet"
]

RAG_EXCLUDE_EXTENSIONS = [
    ".mp3",
    ".mp4",
    ".mkv",
    ".webm",
    ".wav",
    ".opus",
    ".m4a",
    ".flac",
    ".zip",
    ".tar",
    ".gz",
    ".7z",
    ".bz2",
    ".xz",
    ".db",
    ".db-wal",
    ".db-shm",
    ".bin",
    ".gguf",
    ".ragindex",
    ".exe",
    ".so",
    ".dll",
    ".dylib"
]

RAG_SUPPORTED_TEXT_EXTENSIONS = [
    "txt",
    "md",
    "py",
    "json",
    "sh",
    "csv",
    "html",
    "css",
    "js",
    "ts",
    "env",
    "yml",
    "yaml",
    "rst",
    "log"
]


# ==============================================================================
# OLLAMA MANAGEMENT & KEEP-ALIVE POLICY
# ==============================================================================

OLLAMA_AUTO_START = (
    os.environ.get(
        "NEXUS_OLLAMA_AUTO_START",
        "false"
    ).lower() == "true"
)

OLLAMA_AUTO_RESTART = (
    os.environ.get(
        "NEXUS_OLLAMA_AUTO_RESTART",
        "false"
    ).lower() == "true"
)

OLLAMA_KEEP_ALIVE_NORMAL = os.environ.get(
    "NEXUS_OLLAMA_KEEP_ALIVE_NORMAL",
    "5m"
)

OLLAMA_KEEP_ALIVE_PRESSURE = os.environ.get(
    "NEXUS_OLLAMA_KEEP_ALIVE_PRESSURE",
    "0"
)

OLLAMA_KEEP_ALIVE_CRITICAL = os.environ.get(
    "NEXUS_OLLAMA_KEEP_ALIVE_CRITICAL",
    "0"
)


# ==============================================================================
# MODEL CONTEXT LIMITS BY GOVERNOR STATE
# ==============================================================================

CONTEXT_SIZE_NORMAL = int(
    os.environ.get(
        "NEXUS_CTX_NORMAL",
        2048
    )
)

CONTEXT_SIZE_PRESSURE = int(
    os.environ.get(
        "NEXUS_CTX_PRESSURE",
        1024
    )
)

CONTEXT_SIZE_CRITICAL = int(
    os.environ.get(
        "NEXUS_CTX_CRITICAL",
        512
    )
)


# ==============================================================================
# LOGGING & BOUNDED RETENTION
# ==============================================================================

LOG_QUEUE_MAX_SIZE = int(
    os.environ.get(
        "NEXUS_LOG_QUEUE_MAX",
        1000
    )
)

MAX_DB_LOGS_RETENTION = int(
    os.environ.get(
        "NEXUS_MAX_LOGS_RETENTION",
        10000
    )
)

MAX_TASK_HISTORY_RETENTION = int(
    os.environ.get(
        "NEXUS_MAX_TASKS_RETENTION",
        500
    )
)

MAX_INFERENCE_METRICS_RETENTION = int(
    os.environ.get(
        "NEXUS_MAX_METRICS_RETENTION",
        1000
    )
)

LOG_BROADCAST_QUEUE_SIZE = 100


# ==============================================================================
# TELEMETRY SNAPSHOT CACHE & NETWORK PROBES
# ==============================================================================

TELEMETRY_CACHE_TTL_SECONDS = float(
    os.environ.get(
        "NEXUS_TELEMETRY_TTL",
        2.5
    )
)

TUNNEL_HEALTH_PROBE_TTL_SECONDS = float(
    os.environ.get(
        "NEXUS_TUNNEL_PROBE_TTL",
        30.0
    )
)


# ==============================================================================
# GOOGLE CALENDAR & UPES TIMETABLE SYNCHRONIZATION
# ==============================================================================

GOOGLE_CLIENT_ID = os.environ.get(
    "GOOGLE_CLIENT_ID",
    ""
).strip()

GOOGLE_CLIENT_SECRET = os.environ.get(
    "GOOGLE_CLIENT_SECRET",
    ""
).strip()

GOOGLE_REDIRECT_URI = os.environ.get(
    "GOOGLE_REDIRECT_URI",
    "http://localhost:5000/api/auth/google/callback"
).strip()

GOOGLE_AUTH_URI = (
    "https://accounts.google.com/o/oauth2/v2/auth"
)

GOOGLE_TOKEN_URI = (
    "https://oauth2.googleapis.com/token"
)

GOOGLE_CALENDAR_API_BASE = (
    "https://www.googleapis.com/calendar/v3"
)

GOOGLE_CALENDAR_SCOPE = (
    "https://www.googleapis.com/auth/calendar.events "
    "https://www.googleapis.com/auth/calendar.readonly"
)

TIMETABLE_TIMEZONE = os.environ.get(
    "TIMETABLE_TIMEZONE",
    "Asia/Kolkata"
)

TIMETABLE_SYNC_INTERVAL_SECONDS = int(
    os.environ.get(
        "TIMETABLE_SYNC_INTERVAL_SECONDS",
        3 * 3600
    )
)

UPES_TIMETABLE_JSON_PATH = os.environ.get(
    "UPES_TIMETABLE_JSON_PATH",
    os.path.join(
        STORAGE_DIR,
        "upes_timetable.json"
    )
)

TIMETABLE_MAX_UPLOAD_BYTES = int(
    os.environ.get(
        "NEXUS_TIMETABLE_MAX_UPLOAD",
        2 * 1024 * 1024
    )
)

TIMETABLE_MAX_SESSIONS = int(
    os.environ.get(
        "NEXUS_TIMETABLE_MAX_SESSIONS",
        500
    )
)

TIMETABLE_LOCK_TIMEOUT_SECONDS = int(
    os.environ.get(
        "NEXUS_TIMETABLE_LOCK_TIMEOUT",
        300
    )
)


# ==============================================================================
# PERMISSIONS REGISTRY
# ==============================================================================

ALL_PRIVILEGES = [
    "can_upload_files",
    "can_manage_files",
    "can_create_shares",
    "can_download_media",
    "can_use_ai",
    "can_use_rag",
    "can_control_services",
    "can_manage_models",
    "can_view_system_logs",
    "can_manage_users",
    "can_manage_backups",
    "can_manage_automation",
    "can_manage_settings",
    "can_sync_timetable"
]


PRIVILEGE_METADATA = {
    "can_upload_files": {
        "name": "can_upload_files",
        "label": "Upload Files",
        "description": "Upload files into user-accessible Vault directories",
        "category": "Storage & Vault",
        "default_user": True,
        "default_admin": True
    },

    "can_manage_files": {
        "name": "can_manage_files",
        "label": "Manage Files",
        "description": "Rename, move, and delete files inside the Vault",
        "category": "Storage & Vault",
        "default_user": True,
        "default_admin": True
    },

    "can_create_shares": {
        "name": "can_create_shares",
        "label": "Temporary Share Links",
        "description": "Generate time-limited, signed public sharing URLs",
        "category": "Storage & Vault",
        "default_user": True,
        "default_admin": True
    },

    "can_download_media": {
        "name": "can_download_media",
        "label": "Media Downloads",
        "description": "Queue yt-dlp media downloads and stream active jobs",
        "category": "Media",
        "default_user": True,
        "default_admin": True
    },

    "can_use_ai": {
        "name": "can_use_ai",
        "label": "AI Chat & Inference",
        "description": "Access local Ollama LLM chat and streaming generation",
        "category": "Artificial Intelligence",
        "default_user": True,
        "default_admin": True
    },

    "can_use_rag": {
        "name": "can_use_rag",
        "label": "RAG Knowledge Base",
        "description": "Query indexed document vault with hybrid lexical search",
        "category": "Artificial Intelligence",
        "default_user": True,
        "default_admin": True
    },

    "can_control_services": {
        "name": "can_control_services",
        "label": "Service Supervision",
        "description": "Start, stop, and restart background daemon processes",
        "category": "System Control",
        "default_user": False,
        "default_admin": True
    },

    "can_manage_models": {
        "name": "can_manage_models",
        "label": "Ollama Model Management",
        "description": "Pull, delete, and switch quantized Ollama models",
        "category": "System Control",
        "default_user": False,
        "default_admin": True
    },

    "can_view_system_logs": {
        "name": "can_view_system_logs",
        "label": "View Audit Logs",
        "description": "Inspect live system log streams and filter historical events",
        "category": "System Control",
        "default_user": False,
        "default_admin": True
    },

    "can_manage_users": {
        "name": "can_manage_users",
        "label": "User Administration",
        "description": "Create, edit, suspend, and delete user accounts and roles",
        "category": "Administration",
        "default_user": False,
        "default_admin": True
    },

    "can_manage_backups": {
        "name": "can_manage_backups",
        "label": "Backup & Recovery",
        "description": "Create, download, and restore system snapshots and databases",
        "category": "Administration",
        "default_user": False,
        "default_admin": True
    },

    "can_manage_automation": {
        "name": "can_manage_automation",
        "label": "Automation Scheduler",
        "description": "Create, configure, and trigger scheduled system tasks",
        "category": "Administration",
        "default_user": False,
        "default_admin": True
    },

    "can_manage_settings": {
        "name": "can_manage_settings",
        "label": "Appliance Settings",
        "description": "Modify core ports, hostname, and resource governor thresholds",
        "category": "Administration",
        "default_user": False,
        "default_admin": True
    },

    "can_sync_timetable": {
        "name": "can_sync_timetable",
        "label": "Timetable Sync",
        "description": "Upload timetable data and synchronize with Google Calendar",
        "category": "Maintenance",
        "default_user": True,
        "default_admin": True
    }
}


ADMIN_DEFAULT_PRIVILEGES = {
    p: True for p in ALL_PRIVILEGES
}

USER_DEFAULT_PRIVILEGES = {
    p: PRIVILEGE_METADATA[p]["default_user"]
    for p in ALL_PRIVILEGES
}