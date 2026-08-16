"""
NexusNode — Central Configuration Module
Provides centralized, environment-aware configuration for 24/7 Termux mobile server appliance.
Engineered specifically for unrooted Android 13 Termux on ~4 GB RAM hardware (TECNO BG6).
"""

import os
import secrets

# Authoritative Server Version
NEXUS_SERVER_VERSION = "2.3.8"
VERSION = NEXUS_SERVER_VERSION

# Base Paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STORAGE_DIR = os.environ.get("NEXUS_STORAGE_DIR", os.path.join(BASE_DIR, "storage_vault"))
UNIFIED_DB_FILE = os.path.join(STORAGE_DIR, "nexus_unified.db")
DB_FILE = UNIFIED_DB_FILE
DB_PATH = UNIFIED_DB_FILE
AUDIT_DB_FILE = UNIFIED_DB_FILE
RAG_INDEX_FILE = os.environ.get("NEXUS_RAG_INDEX_FILE", os.path.join(STORAGE_DIR, "rag_index.json"))
RAG_DB_FILE = os.environ.get("NEXUS_RAG_DB_FILE", os.path.join(STORAGE_DIR, "rag_vault.db"))
BACKUP_DIR = os.environ.get("NEXUS_BACKUP_DIR", os.path.join(STORAGE_DIR, "backups"))
CONFIG_FILE = os.path.join(STORAGE_DIR, "server_config.json")
EMERGENCY_LOG_FILE = os.environ.get("NEXUS_EMERGENCY_LOG", os.path.join(BASE_DIR, "emergency_fallback.log"))

# Ensure critical storage directories exist
os.makedirs(STORAGE_DIR, exist_ok=True)
os.makedirs(BACKUP_DIR, exist_ok=True)

# Network & Ports
PORT = int(os.environ.get("NEXUS_PORT", 5000))
HOST = os.environ.get("NEXUS_HOST", "0.0.0.0")
SSH_PORT = int(os.environ.get("NEXUS_SSH_PORT", 8022))
OLLAMA_PORT = int(os.environ.get("NEXUS_OLLAMA_PORT", 11434))
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", f"http://127.0.0.1:{OLLAMA_PORT}")

# LocalToNet Tunnel
DEFAULT_TUNNEL_URL = os.environ.get("LOCALTONET_URL", "https://k09oezeyib.localto.net")
LOCALTONET_LOG_PATHS = [
    os.path.join(BASE_DIR, "localtonet.log"),
    os.path.expanduser("~/.localtonet/localtonet.log"),
    os.path.expanduser("~/localtonet.log"),
    "/data/data/com.termux/files/home/localtonet.log"
]

# Security, Passwords & Credentials
SECRET_KEY = os.environ.get("NEXUS_SECRET_KEY", secrets.token_hex(32))
SESSION_EXPIRY_SECONDS = int(os.environ.get("NEXUS_SESSION_TTL", 7 * 24 * 3600))  # 7 days
PLAYBACK_TOKEN_TTL_SECONDS = int(os.environ.get("NEXUS_PLAYBACK_TOKEN_TTL", 120))  # 120 seconds
PASSWORD_KDF_ITERATIONS = int(os.environ.get("NEXUS_PASSWORD_KDF_ITERATIONS", 100000))
LOCKOUT_THRESHOLD = int(os.environ.get("NEXUS_LOCKOUT_THRESHOLD", 5))
LOCKOUT_DURATION_SECONDS = int(os.environ.get("NEXUS_LOCKOUT_DURATION", 600))  # 10 minutes

# 4 GB RAM Formal Memory Budget (in Megabytes)
# Target total RAM ~ 3800 MB physical
BUDGET_ANDROID_SYSTEM_MB = 1500     # Android OS, SurfaceFlinger, System Services, Radio, ZRAM
BUDGET_CORE_SERVER_MB = 180         # NexusNode Python WSGI process, SQLite cache, SSE
BUDGET_RAG_INDEX_MB = 30           # SQLite FTS5 database page cache & working memory
BUDGET_OLLAMA_MODEL_MB = 1200      # Ollama Engine + active quantized model (Qwen 0.5B/1.5B)
BUDGET_HEAVY_TASK_MB = 250         # yt-dlp / ffmpeg / backup zip worker subprocess
BUDGET_SAFETY_HEADROOM_MB = 640    # Unallocated buffer preventing Android LMK intervention

# 4 GB RAM Resource Governor Thresholds (in Megabytes)
RAM_NORMAL_THRESHOLD_MB = int(os.environ.get("NEXUS_RAM_NORMAL_MB", 1000))
RAM_PRESSURE_THRESHOLD_MB = int(os.environ.get("NEXUS_RAM_PRESSURE_MB", 600))

# Thermal Thresholds (in Celsius)
THERMAL_WARM_C = int(os.environ.get("NEXUS_THERMAL_WARM_C", 42))
THERMAL_THROTTLED_C = int(os.environ.get("NEXUS_THERMAL_THROTTLED_C", 48))
THERMAL_CRITICAL_C = int(os.environ.get("NEXUS_THERMAL_CRITICAL_C", 55))

# Background Task Worker Concurrency (Optimized for 4 GB RAM)
MAX_HEAVY_CONCURRENCY = int(os.environ.get("NEXUS_MAX_HEAVY_CONCURRENCY", 1))
SUBPROCESS_TIMEOUT_SECONDS = int(os.environ.get("NEXUS_TASK_TIMEOUT", 3600))

# Canonical Storage Paths & Vault Categories (Canonical Lowercase Internal)
MEDIA_CATEGORIES = ["downloads", "music", "videos", "podcasts", "documents", "other"]
MEDIA_CATEGORY_LABELS = {
    "downloads": "Downloads",
    "music": "Music",
    "videos": "Videos",
    "podcasts": "Podcasts",
    "documents": "Documents",
    "other": "Other"
}
for cat in MEDIA_CATEGORIES:
    os.makedirs(os.path.join(STORAGE_DIR, cat), exist_ok=True)

# RAG & Memory Protection (SQLite FTS5 Inverted Index)
RAG_MAX_FILE_SIZE_BYTES = int(os.environ.get("NEXUS_RAG_MAX_FILE_SIZE", 5 * 1024 * 1024))  # 5 MB
RAG_MAX_CHUNKS = int(os.environ.get("NEXUS_RAG_MAX_CHUNKS", 2500))
RAG_DEFAULT_SOURCES = ["docs", "notes", "code"]
for src in RAG_DEFAULT_SOURCES:
    os.makedirs(os.path.join(STORAGE_DIR, src), exist_ok=True)

RAG_EXCLUDE_DIRS = [
    "backups", "music", "videos", "podcasts", "downloads", "Music", "Videos", "Podcasts", "Downloads",
    ".tmp", ".git", "__pycache__", "node_modules", ".ssh", ".localtonet"
]
RAG_EXCLUDE_EXTENSIONS = [
    ".mp3", ".mp4", ".mkv", ".webm", ".wav", ".opus", ".m4a", ".flac",
    ".zip", ".tar", ".gz", ".7z", ".bz2", ".xz",
    ".db", ".db-wal", ".db-shm", ".bin", ".gguf", ".ragindex",
    ".exe", ".so", ".dll", ".dylib"
]
RAG_SUPPORTED_TEXT_EXTENSIONS = [
    "txt", "md", "py", "json", "sh", "csv", "html", "css", "js", "ts", "env", "yml", "yaml", "rst", "log"
]

# Ollama Management & Keep-Alive Policy
OLLAMA_AUTO_START = os.environ.get("NEXUS_OLLAMA_AUTO_START", "false").lower() == "true"
OLLAMA_AUTO_RESTART = os.environ.get("NEXUS_OLLAMA_AUTO_RESTART", "false").lower() == "true"
OLLAMA_KEEP_ALIVE_NORMAL = os.environ.get("NEXUS_OLLAMA_KEEP_ALIVE_NORMAL", "5m")
OLLAMA_KEEP_ALIVE_PRESSURE = os.environ.get("NEXUS_OLLAMA_KEEP_ALIVE_PRESSURE", "0")
OLLAMA_KEEP_ALIVE_CRITICAL = os.environ.get("NEXUS_OLLAMA_KEEP_ALIVE_CRITICAL", "0")

# Model Context Limits by Governor State
CONTEXT_SIZE_NORMAL = int(os.environ.get("NEXUS_CTX_NORMAL", 2048))
CONTEXT_SIZE_PRESSURE = int(os.environ.get("NEXUS_CTX_PRESSURE", 1024))
CONTEXT_SIZE_CRITICAL = int(os.environ.get("NEXUS_CTX_CRITICAL", 512))

# Logging & Bounded Retention
LOG_QUEUE_MAX_SIZE = int(os.environ.get("NEXUS_LOG_QUEUE_MAX", 1000))
MAX_DB_LOGS_RETENTION = int(os.environ.get("NEXUS_MAX_LOGS_RETENTION", 10000))
MAX_TASK_HISTORY_RETENTION = int(os.environ.get("NEXUS_MAX_TASKS_RETENTION", 500))
MAX_INFERENCE_METRICS_RETENTION = int(os.environ.get("NEXUS_MAX_METRICS_RETENTION", 1000))
LOG_BROADCAST_QUEUE_SIZE = 100

# Telemetry Snapshot Cache & Network Probes
TELEMETRY_CACHE_TTL_SECONDS = float(os.environ.get("NEXUS_TELEMETRY_TTL", 2.5))
TUNNEL_HEALTH_PROBE_TTL_SECONDS = float(os.environ.get("NEXUS_TUNNEL_PROBE_TTL", 30.0))

# Permissions Registry (Authoritative Single Source of Truth)
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
    "can_manage_settings"
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
        "description": "Rename, move, and delete user-accessible Vault files",
        "category": "Storage & Vault",
        "default_user": True,
        "default_admin": True
    },
    "can_create_shares": {
        "name": "can_create_shares",
        "label": "Create File Shares",
        "description": "Generate temporary cryptographic public download links",
        "category": "Storage & Vault",
        "default_user": False,
        "default_admin": True
    },
    "can_download_media": {
        "name": "can_download_media",
        "label": "Download Media",
        "description": "Enqueue background audio/video media extraction downloads",
        "category": "Media Center",
        "default_user": True,
        "default_admin": True
    },
    "can_use_ai": {
        "name": "can_use_ai",
        "label": "AI Studio Inference",
        "description": "Execute conversational LLM inference and model chat",
        "category": "AI & Inference",
        "default_user": True,
        "default_admin": True
    },
    "can_use_rag": {
        "name": "can_use_rag",
        "label": "RAG Knowledge Search",
        "description": "Search inverted index knowledge base and document chunks",
        "category": "AI & Inference",
        "default_user": True,
        "default_admin": True
    },
    "can_control_services": {
        "name": "can_control_services",
        "label": "Control Services",
        "description": "Start, stop, and restart daemon services (OpenSSH, LocalToNet, Ollama)",
        "category": "System & Daemons",
        "default_user": False,
        "default_admin": True
    },
    "can_manage_models": {
        "name": "can_manage_models",
        "label": "Manage LLM Models",
        "description": "Pull, delete, and inspect Ollama quantization models",
        "category": "AI & Inference",
        "default_user": False,
        "default_admin": True
    },
    "can_view_system_logs": {
        "name": "can_view_system_logs",
        "label": "View Audit Logs",
        "description": "Inspect raw system event and audit log streams",
        "category": "Monitoring & Logs",
        "default_user": False,
        "default_admin": True
    },
    "can_manage_users": {
        "name": "can_manage_users",
        "label": "User & Role Governance",
        "description": "Create, edit, disable, and delete user accounts and RBAC roles",
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
    }
}

ADMIN_DEFAULT_PRIVILEGES = {p: True for p in ALL_PRIVILEGES}
USER_DEFAULT_PRIVILEGES = {
    p: PRIVILEGE_METADATA[p]["default_user"] for p in ALL_PRIVILEGES
}
