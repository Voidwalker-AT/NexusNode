"""
NexusNode — Central Configuration Module
Provides centralized, environment-aware configuration for 24/7 Termux mobile server appliance.
"""

import os
import secrets

VERSION = "2.2.0"

# Base Paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STORAGE_DIR = os.environ.get("NEXUS_STORAGE_DIR", os.path.join(BASE_DIR, "storage_vault"))
DB_FILE = os.environ.get("NEXUS_DB_FILE", os.path.join(STORAGE_DIR, "nexus_vault.db"))
RAG_INDEX_FILE = os.environ.get("NEXUS_RAG_INDEX_FILE", os.path.join(STORAGE_DIR, "rag_index.json"))
BACKUP_DIR = os.environ.get("NEXUS_BACKUP_DIR", os.path.join(STORAGE_DIR, "backups"))
CONFIG_FILE = os.path.join(STORAGE_DIR, "server_config.json")

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

# Security & Secrets
SECRET_KEY = os.environ.get("NEXUS_SECRET_KEY", secrets.token_hex(32))
SESSION_EXPIRY_SECONDS = int(os.environ.get("NEXUS_SESSION_TTL", 7 * 24 * 3600))  # 7 days
LOCKOUT_THRESHOLD = int(os.environ.get("NEXUS_LOCKOUT_THRESHOLD", 5))
LOCKOUT_DURATION_SECONDS = int(os.environ.get("NEXUS_LOCKOUT_DURATION", 600))  # 10 minutes

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

# Media Center & Vault Categories
MEDIA_CATEGORIES = ["Music", "Videos", "Podcasts", "Downloads", "Other"]
for cat in ["Music", "Videos", "Podcasts", "Downloads"]:
    os.makedirs(os.path.join(STORAGE_DIR, cat), exist_ok=True)

# RAG & Memory Protection
RAG_MAX_FILE_SIZE_BYTES = int(os.environ.get("NEXUS_RAG_MAX_FILE_SIZE", 5 * 1024 * 1024))  # 5 MB
RAG_MAX_CHUNKS = int(os.environ.get("NEXUS_RAG_MAX_CHUNKS", 1500))

# Ollama Management
OLLAMA_AUTO_START = os.environ.get("NEXUS_OLLAMA_AUTO_START", "false").lower() == "true"
OLLAMA_AUTO_RESTART = os.environ.get("NEXUS_OLLAMA_AUTO_RESTART", "false").lower() == "true"

# Logging & Retention
MAX_DB_LOGS_RETENTION = int(os.environ.get("NEXUS_MAX_LOGS_RETENTION", 5000))
LOG_BROADCAST_QUEUE_SIZE = 100

# Permissions Registry
ALL_PRIVILEGES = [
    "can_view_logs",
    "can_delete_files",
    "can_upload_files",
    "can_manage_engine",
    "can_run_tasks",
    "can_use_rag",
    "can_manage_users",
    "can_create_shares",
    "can_manage_backups",
    "can_manage_automation",
    "can_manage_settings"
]

ADMIN_DEFAULT_PRIVILEGES = {p: True for p in ALL_PRIVILEGES}
USER_DEFAULT_PRIVILEGES = {
    "can_view_logs": False,
    "can_delete_files": False,
    "can_upload_files": True,
    "can_manage_engine": False,
    "can_run_tasks": True,
    "can_use_rag": True,
    "can_manage_users": False,
    "can_create_shares": True,
    "can_manage_backups": False,
    "can_manage_automation": False,
    "can_manage_settings": False
}
