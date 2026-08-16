"""
NexusNode Universal Remote CLI Client Test Suite
Comprehensive tests covering authentication, session lifecycle, HTTP 200 / token extraction,
WAF/HTML detection, connect sequence, role-aware shell completion, task lifecycle, and error handling.
"""

import io
import os
import sys
import json
import time
import shutil
import tempfile
import threading
import http.server
import unittest
from pathlib import Path
from unittest.mock import patch

# Ensure root directory is on sys.path
SERVER_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SERVER_ROOT not in sys.path:
    sys.path.insert(0, SERVER_ROOT)

import nexus.config as n_config
import nexus.client as n_client
import nexus.auth as n_auth
import nexus.output as n_output
import nexus.shell as n_shell
import nexus.normalize as n_norm
import nexus.__main__ as n_main
from nexus.commands import (
    status as cmd_status,
    vault as cmd_vault,
    media as cmd_media,
    tasks as cmd_tasks,
    ai as cmd_ai,
    rag as cmd_rag,
    shares as cmd_shares,
    account as cmd_account,
    services as cmd_services,
    models as cmd_models,
    diagnostics as cmd_diag,
    logs as cmd_logs,
    users as cmd_users,
    backups as cmd_backups,
    automation as cmd_auto,
    settings as cmd_settings,
    database as cmd_db,
)


class MockNexusHTTPHandler(http.server.BaseHTTPRequestHandler):
    """Mock HTTP handler returning standard authoritative NexusNode REST responses."""

    def log_message(self, format, *args):
        pass  # Suppress console log spam during test execution

    def _send_json(self, code: int, data: any):
        raw = json.dumps(data).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _send_html(self, code: int, html_str: str):
        raw = html_str.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        auth_header = self.headers.get("Authorization", "")
        token = auth_header.replace("Bearer ", "").strip()
        path = self.path.split("?")[0]

        if path == "/api/health":
            self._send_json(200, {
                "status": "HEALTHY",
                "service": "NexusNode Mobile Appliance",
                "device": "TECNO BG6",
                "version": "2.3.2"
            })

        elif path == "/api/auth/me":
            if token == "valid-admin-token":
                self._send_json(200, {
                    "user": {
                        "user_id": "admin",
                        "username": "admin",
                        "role": "admin",
                        "privileges": {"can_manage_users": True, "can_control_services": True, "can_manage_models": True, "can_manage_backups": True, "can_manage_settings": True, "can_view_system_logs": True, "can_use_ai": True, "can_use_rag": True, "can_download_media": True, "can_create_shares": True}
                    },
                    "created_at": time.time()
                })
            elif token == "valid-user-token":
                self._send_json(200, {
                    "user": {
                        "user_id": "anmol",
                        "username": "anmol",
                        "role": "user",
                        "privileges": {"can_use_ai": True, "can_use_rag": True, "can_download_media": True, "can_create_shares": True}
                    },
                    "created_at": time.time()
                })
            else:
                self._send_json(401, {"error": "Invalid or expired session token."})

        elif path == "/api/system/status":
            # Authoritative schema matching app.py
            self._send_json(200, {
                "server": {
                    "name": "NexusNode Mobile Appliance",
                    "version": "2.3.2",
                    "device": "TECNO BG6 (Android 13 / Termux)",
                    "uptime": "1h 23m 45s",
                    "uptime_seconds": 5025
                },
                "appliance": {"state": "NORMAL", "tier": "TIER_1_PHONE"},
                "memory": {
                    "used_mb": 1800,
                    "total_mb": 3800,
                    "available_mb": 2000,
                    "ram_percent": 47.4,
                    "swap_percent": 0.0,
                    "swap_used_mb": 0,
                    "swap_total_mb": 2048
                },
                "disk": {
                    "free_gb": 41.6,
                    "total_gb": 64.0,
                    "used_gb": 22.4,
                    "percent": 35.0
                },
                "battery": {"level": 92, "status": "CHARGING"},
                "thermal": {"temp_c": 32.5, "status": "NORMAL"},
                "cpu": {"percent": 12.5},
                "services": {
                    "nexusnode": {"status": "online", "running": True, "port": 5000, "pid": 1021},
                    "localtonet": {"status": "running", "state": "TUNNEL_CONNECTED", "running": True, "connected": True, "url": "https://sample.localto.net", "pid": 1024},
                    "ssh": {"status": "online", "running": True, "port": 8022, "pid": 1022},
                    "ollama": {"status": "running", "running": True, "online": True, "selected_model": "qwen2.5:0.5b", "loaded_model": "qwen2.5:0.5b", "pid": 1023}
                },
                "tasks": {
                    "active_count": 1,
                    "active_tasks": [{"task_id": "task-run123", "status": "RUNNING"}]
                },
                "rag": {"documents_count": 8, "chunks_count": 128, "state": "READY"}
            })

        elif path == "/files":
            self._send_json(200, {
                "files": [
                    {"name": "Documents", "path": "Documents", "is_dir": True, "size": 0, "category": "folder", "modified": "2024-08-16T14:50:00Z"},
                    {"name": "document.pdf", "path": "document.pdf", "is_dir": False, "size": 1048576, "category": "document", "modified": "2024-08-16T14:50:00Z"},
                    {"name": "photo.jpg", "path": "photo.jpg", "is_dir": False, "size": 2097152, "category": "image", "modified": "2024-08-16T16:13:20Z"}
                ],
                "current_path": ""
            })

        elif path.startswith("/api/vault/checksum/"):
            filename = path.replace("/api/vault/checksum/", "")
            self._send_json(200, {
                "filename": filename,
                "path": f"storage_vault/{filename}",
                "size_bytes": 1048576,
                "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                "modified_time": 1723800000
            })

        elif path == "/api/media/library":
            self._send_json(200, [
                {"name": "lecture.mp4", "size": 52428800, "category": "video", "format": "mp4", "modified": 1723810000}
            ])

        elif path == "/api/tasks":
            # Authoritative top-level JSON array
            self._send_json(200, [
                {"task_id": "task-abc12345", "type": "media_download", "owner_user_id": "anmol", "status": "COMPLETED", "stage": "COMPLETED", "progress": 100.0, "title": "Download video", "created_at": 1723812000},
                {"task_id": "task-run123", "type": "media_download", "owner_user_id": "admin", "status": "RUNNING", "stage": "RUNNING", "progress": 82.0, "speed_bps": 1258291, "eta_seconds": 13, "title": "Example Video", "created_at": 1723813000},
                {"task_id": "task-que123", "type": "media_download", "owner_user_id": "admin", "status": "QUEUED", "stage": "QUEUED", "progress": 0.0, "title": "Another Video", "created_at": 1723813100},
                {"task_id": "task-post123", "type": "media_download", "owner_user_id": "admin", "status": "RUNNING", "stage": "POST_PROCESSING", "progress": 95.0, "title": "Post Process Video", "created_at": 1723813200},
                {"task_id": "task-ver123", "type": "media_download", "owner_user_id": "admin", "status": "RUNNING", "stage": "VERIFYING", "progress": 99.0, "title": "Verifying Video", "created_at": 1723813300},
                {"task_id": "task-can123", "type": "media_download", "owner_user_id": "admin", "status": "CANCELLED", "stage": "CANCELLED", "progress": 0.0, "title": "Cancelled Video", "created_at": 1723813400},
                {"task_id": "task-contra1", "type": "media_download", "owner_user_id": "admin", "status": "COMPLETED", "stage": "QUEUED", "progress": 100.0, "title": "Contradictory Task", "created_at": 1723813500}
            ])

        elif path.startswith("/api/tasks/task-run123"):
            self._send_json(200, {
                "task_id": "task-run123",
                "task_type": "media_download",
                "owner_user_id": "admin",
                "status": "RUNNING",
                "stage": "RUNNING",
                "progress": 82.0,
                "speed_bps": 1258291,
                "eta_seconds": 13,
                "title": "Example Video",
                "created_at": 1723813000
            })

        elif path == "/api/ai/models":
            # Authoritative top-level JSON array from Ollama registry
            self._send_json(200, [
                {"name": "qwen2.5:0.5b", "size_bytes": 398000000, "family": "qwen2", "parameter_size": "0.5B", "quantization_level": "Q4_K_M"},
                {"name": "llama3.2:1b", "size_bytes": 1300000000, "family": "llama", "parameter_size": "1B", "quantization_level": "Q4_K_M"}
            ])

        elif path.startswith("/api/ai/models/"):
            model_name = path.replace("/api/ai/models/", "")
            self._send_json(200, {
                "name": model_name,
                "size_bytes": 398000000,
                "family": "qwen2",
                "parameter_size": "0.5B",
                "quantization_level": "Q4_K_M",
                "estimated_ram_bytes": 850000000,
                "modified_at": 1723800000
            })

        elif path == "/api/ai/state":
            self._send_json(200, {
                "service_online": True,
                "engine": "running",
                "selected_model": "qwen2.5:0.5b",
                "loaded_model": "qwen2.5:0.5b",
                "keep_alive": "5m",
                "context_size": 2048,
                "size_vram_bytes": 450000000
            })

        elif path == "/api/ai/metrics":
            self._send_json(200, [
                {"gen_tokens_per_sec": 14.8, "prompt_eval_ms": 180.5, "created_at": 1723800000}
            ])

        elif path == "/api/rag/diagnostics":
            self._send_json(200, {
                "backend": "SQLite FTS5 (BM25 Ranking)",
                "database_file": "nexus_vault.db",
                "database_size_kb": 256.0,
                "document_count": 8,
                "chunk_count": 128,
                "avg_chunk_tokens": 120.5,
                "largest_document": "docs/whitepaper.pdf",
                "last_rebuild_time": "2024-08-16 17:36:40",
                "state": "READY"
            })

        elif path == "/api/rag/sources":
            self._send_json(200, {
                "sources": ["storage_vault/Documents", "storage_vault/Notes"],
                "supported_extensions": [".txt", ".pdf", ".md", ".json"]
            })

        elif path == "/api/services/status":
            self._send_json(200, {
                "nexusnode": {"status": "online", "running": True, "port": 5000, "pid": 1021},
                "localtonet": {"status": "running", "state": "TUNNEL_CONNECTED", "running": True, "connected": True, "url": "https://sample.localto.net", "pid": 1024},
                "ssh": {"status": "online", "running": True, "port": 8022, "pid": 1022},
                "sshd": {"status": "online", "running": True, "port": 8022, "pid": 1022},
                "ollama": {"status": "running", "running": True, "online": True, "selected_model": "qwen2.5:0.5b", "loaded_model": "qwen2.5:0.5b", "pid": 1023}
            })

        elif path == "/api/shares":
            self._send_json(200, [
                {"id": "share-12345", "token": "tok9876543210fedcba", "filename": "whitepaper.pdf", "expires_at": 1723886400, "downloads_count": 2, "max_downloads": 10, "revoked": 0}
            ])

        elif path == "/api/admin/diagnostics/system":
            if token != "valid-admin-token":
                self._send_json(403, {"error": "Permission denied."})
                return
            self._send_json(200, {
                "device": {"model": "TECNO BG6", "android_version": "Android 13 (aarch64)", "python_version": "3.10.12", "nexus_version": "2.3.2"},
                "nexusnode_process": {"pid": 1021, "rss_mb": 85, "vms_mb": 240, "threads": 12, "open_files": 45},
                "memory": {"used_mb": 1800, "total_mb": 3800, "available_mb": 2000, "ram_percent": 47.4, "swap_used_mb": 0, "swap_total_mb": 2048},
                "disk": {"used_gb": 22.4, "total_gb": 64.0, "free_gb": 41.6, "percent": 35.0},
                "device_telemetry": {"cpu_cores": 8, "load_avg_1m": "0.45", "load_avg_5m": "0.50", "load_avg_15m": "0.55", "cpu_temperature_c": 32.5, "battery_percent": 92, "battery_temp_c": 32.5},
                "health": {"status": "HEALTHY"}
            })

        elif path == "/api/admin/diagnostics/full-report":
            if token != "valid-admin-token":
                self._send_json(403, {"error": "Permission denied."})
                return
            self._send_json(200, {
                "timestamp": 1723800000,
                "condition": "STABLE",
                "issues": [],
                "recommendations": ["Routine cache sweep recommended in 48 hours."]
            })

        elif path == "/api/network/test":
            self._send_json(200, {
                "gateway_reachable": True,
                "dns_working": True,
                "public_ip": "104.28.19.42",
                "ping_ms": 14
            })

        elif path == "/api/events":
            if token != "valid-admin-token":
                self._send_json(403, {"error": "Permission denied: can_view_system_logs required."})
                return
            self._send_json(200, [
                {"id": 1, "timestamp": 1723800000, "level": "INFO", "category": "SYS", "message": "Appliance initialized and ready."}
            ])

        elif path == "/api/admin/users":
            if token != "valid-admin-token":
                self._send_json(403, {"error": "Permission denied: can_manage_users required."})
                return
            self._send_json(200, [
                {"user_id": "admin", "username": "admin", "role": "admin", "privileges": {"can_manage_users": True}, "created_at": 1723800000},
                {"user_id": "anmol", "username": "anmol", "role": "user", "privileges": {"can_use_ai": True}, "created_at": 1723805000}
            ])

        elif path == "/api/backups":
            if token != "valid-admin-token":
                self._send_json(403, {"error": "Permission denied: can_manage_backups required."})
                return
            self._send_json(200, [
                {"id": "backup_20240816", "filename": "backup_20240816.tar.gz", "size_bytes": 204800, "checksum": "9876543210fedcba", "created_at": 1723800000}
            ])

        elif path == "/api/automation/jobs":
            if token != "valid-admin-token":
                self._send_json(403, {"error": "Permission denied: can_manage_automation required."})
                return
            self._send_json(200, [
                {"id": "job_cache_clean", "name": "Clean temporary storage", "interval_seconds": 3600, "enabled": 1, "schedule": "Every 3600s", "last_run": 1723800000}
            ])

        elif path == "/api/settings":
            if token != "valid-admin-token":
                self._send_json(403, {"error": "Permission denied: can_manage_settings required."})
                return
            self._send_json(200, {
                "ram_normal_mb": 2200,
                "ram_pressure_mb": 1400,
                "thermal_warm_c": 45.0,
                "thermal_throttled_c": 50.0,
                "thermal_critical_c": 55.0
            })

        elif path == "/api/admin/db/diagnostics":
            if token != "valid-admin-token":
                self._send_json(403, {"error": "Permission denied."})
                return
            self._send_json(200, {
                "db_file": "/data/data/com.termux/files/home/server/nexus_vault.db",
                "db_size_kb": 128.5,
                "wal_size_kb": 32.0,
                "shm_size_kb": 16.0,
                "table_counts": {"users": 2, "system_logs": 45, "shares": 1}
            })

        elif path == "/api/admin/db/query":
            if token != "valid-admin-token":
                self._send_json(403, {"error": "Permission denied."})
                return
            self._send_json(200, {
                "table": "users",
                "count": 2,
                "rows": [{"user_id": "admin", "role": "admin"}, {"user_id": "anmol", "role": "user"}]
            })

        elif path.startswith("/download/"):
            raw_content = b"PDF Mock Content Data"
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(raw_content)))
            self.end_headers()
            self.wfile.write(raw_content)

        elif path.startswith("/api/backups/download/"):
            raw_content = b"GZIP Backup Content"
            self.send_response(200)
            self.send_header("Content-Type", "application/gzip")
            self.send_header("Content-Length", str(len(raw_content)))
            self.end_headers()
            self.wfile.write(raw_content)

        else:
            self._send_json(404, {"error": f"Path '{path}' not found."})

    def do_POST(self):
        auth_header = self.headers.get("Authorization", "")
        token = auth_header.replace("Bearer ", "").strip()
        length = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(length) if length > 0 else b"{}"
        try:
            body = json.loads(raw_body.decode("utf-8"))
        except Exception:
            body = {}

        path = self.path.split("?")[0]

        if path == "/api/auth/login":
            uid = str(body.get("user_id", "")).lower()
            pwd = body.get("password", "")
            if uid == "admin" and pwd == "Admin@1234":
                self._send_json(200, {
                    "token": "valid-admin-token",
                    "user": {
                        "user_id": "admin",
                        "username": "admin",
                        "role": "admin",
                        "privileges": {"can_manage_users": True, "can_control_services": True, "can_manage_models": True, "can_manage_backups": True, "can_manage_settings": True, "can_view_system_logs": True, "can_use_ai": True, "can_use_rag": True, "can_download_media": True, "can_create_shares": True}
                    }
                })
            elif uid == "anmol" and pwd == "User@1234":
                self._send_json(200, {
                    "token": "valid-user-token",
                    "user": {
                        "user_id": "anmol",
                        "username": "anmol",
                        "role": "user",
                        "privileges": {"can_use_ai": True, "can_use_rag": True, "can_download_media": True, "can_create_shares": True}
                    }
                })
            elif uid == "locked_user":
                self._send_json(429, {"error": "account_locked", "message": "Account locked.", "lockout_seconds": 45, "remaining_seconds": 45})
            elif uid == "waf_user":
                self._send_html(200, "<html><head><title>LocalToNet WAF Interstitial</title></head><body>LocalToNet Security Check</body></html>")
            elif uid == "html_user":
                self._send_html(200, "<html><head><title>Error</title></head><body>General Gateway HTML</body></html>")
            elif uid == "server_err_user":
                self._send_json(500, {"error": "internal_error", "message": "Internal Server Error"})
            elif uid == "forbidden_user":
                self._send_json(403, {"error": "forbidden", "message": "Access Forbidden."})
            else:
                self._send_json(401, {"error": "invalid_credentials", "message": "Invalid username or password."})

        elif path == "/api/auth/logout":
            self._send_json(200, {"message": "Logged out successfully."})

        elif path == "/api/media/download":
            self._send_json(200, {
                "success": True,
                "task_id": "task-media-5555",
                "task_ids": ["task-media-5555"],
                "status": "QUEUED",
                "url": body.get("url"),
                "format": body.get("format", "mp4")
            })

        elif path.startswith("/api/tasks/") and path.endswith("/cancel"):
            task_id = path.replace("/api/tasks/", "").replace("/cancel", "")
            if task_id == "task-foreign-999" and token == "valid-user-token":
                self._send_json(403, {"error": "Permission denied: Cannot cancel tasks owned by another user."})
            else:
                self._send_json(200, {"message": f"Task '{task_id}' cancelled."})

        elif path == "/api/ai/models/select":
            self._send_json(200, {"message": f"Model '{body.get('model')}' selected.", "selected_model": body.get("model")})

        elif path == "/api/models/estimate":
            self._send_json(200, {
                "model": body.get("model"),
                "model_size_mb": 400,
                "total_ram_required_mb": 650,
                "allowed": True,
                "budget_status": {"allowed": True}
            })

        elif path == "/chat/stream":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            chunks = [
                json.dumps({"message": {"content": "Hello "}}),
                json.dumps({"message": {"content": "from NexusNode "}}),
                json.dumps({"message": {"content": "AI!\n"}})
            ]
            for c in chunks:
                self.wfile.write(f"data: {c}\n\n".encode("utf-8"))
                self.wfile.flush()

        elif path == "/api/rag/sources":
            self._send_json(200, {"sources": body.get("sources", []), "results": [{"score": 0.95, "source_file": "doc.txt", "snippet": "Sample text snippet"}]})

        elif path == "/api/rag/index":
            self._send_json(200, {"message": "RAG reindexing task initiated on server."})

        elif path == "/api/rag/compact":
            self._send_json(200, {"message": "Compacted."})

        elif path == "/start":
            self._send_json(200, {"service": body.get("service"), "status": "started"})

        elif path == "/stop":
            self._send_json(200, {"service": body.get("service"), "status": "stopped"})

        elif path == "/api/shares":
            self._send_json(201, {
                "share_id": "share-new-1234",
                "filename": body.get("filename"),
                "token": "tok_abcdef123456",
                "expires_at": time.time() + 86400,
                "max_downloads": body.get("max_downloads", 10)
            })

        elif path == "/api/admin/users":
            if token != "valid-admin-token":
                self._send_json(403, {"error": "Permission denied."})
                return
            self._send_json(201, {"message": f"User '{body.get('user_id')}' created successfully."})

        elif path == "/api/admin/users/update-privileges":
            if token != "valid-admin-token":
                self._send_json(403, {"error": "Permission denied."})
                return
            self._send_json(200, {"message": "Privileges updated."})

        elif path == "/api/backups/create":
            if token != "valid-admin-token":
                self._send_json(403, {"error": "Permission denied."})
                return
            # HTTP 201 with task_id
            self._send_json(201, {
                "task_id": "task-backup-123",
                "status": "queued"
            })

        elif path == "/api/backups/restore":
            if token != "valid-admin-token":
                self._send_json(403, {"error": "Permission denied."})
                return
            self._send_json(200, {"message": f"Backup '{body.get('backup_id')}' restored."})

        elif path.startswith("/api/automation/jobs/") and path.endswith("/run"):
            if token != "valid-admin-token":
                self._send_json(403, {"error": "Permission denied."})
                return
            self._send_json(200, {"message": "Job executed."})

        elif path.startswith("/api/automation/jobs/") and path.endswith("/toggle"):
            if token != "valid-admin-token":
                self._send_json(403, {"error": "Permission denied."})
                return
            self._send_json(200, {"enabled": True})

        elif path == "/api/settings":
            if token != "valid-admin-token":
                self._send_json(403, {"error": "Permission denied."})
                return
            self._send_json(200, {"updated": True, "ram_normal_mb": body.get("ram_normal_mb", 2200)})

        elif path == "/api/vault/clean-temp":
            self._send_json(200, {"deleted_count": 3, "freed_bytes": 204800})

        else:
            self._send_json(404, {"error": "Endpoint not found."})

    def do_DELETE(self):
        auth_header = self.headers.get("Authorization", "")
        token = auth_header.replace("Bearer ", "").strip()
        path = self.path.split("?")[0]

        if path.startswith("/files/"):
            filename = path.replace("/files/", "")
            self._send_json(200, {"message": f"File '{filename}' deleted from vault."})
        elif path.startswith("/api/shares/"):
            share_id = path.replace("/api/shares/", "")
            self._send_json(200, {"message": f"Share '{share_id}' revoked."})
        elif path.startswith("/api/admin/users/"):
            if token != "valid-admin-token":
                self._send_json(403, {"error": "Permission denied."})
                return
            uid = path.replace("/api/admin/users/", "")
            self._send_json(200, {"message": f"User '{uid}' deleted."})
        else:
            self._send_json(404, {"error": "Not found."})


class TestNexusUniversalCLI(unittest.TestCase):
    """Authoritative test suite for the Universal Remote CLI frontend."""

    @classmethod
    def setUpClass(cls):
        cls.server = http.server.HTTPServer(("127.0.0.1", 0), MockNexusHTTPHandler)
        cls.port = cls.server.server_port
        cls.server_url = f"http://127.0.0.1:{cls.port}"
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="nexus_cli_test_")
        self.orig_config_dir_fn = n_config.get_config_dir
        n_config.get_config_dir = lambda: Path(self.test_dir)
        n_config.clear_session()

    def tearDown(self):
        n_config.get_config_dir = self.orig_config_dir_fn
        shutil.rmtree(self.test_dir, ignore_errors=True)

    # --------------------------------------------------------------------------
    # 1. HTTP 200 Login Success & Token/User Extraction
    # --------------------------------------------------------------------------
    def test_http_200_login_success(self):
        client = n_client.NexusClient(server_url=self.server_url)
        success = n_auth.login(client, username="admin", password="Admin@1234")
        self.assertTrue(success)
        self.assertEqual(client.token, "valid-admin-token")

    def test_login_token_extraction(self):
        client = n_client.NexusClient(server_url=self.server_url)
        success = n_auth.login(client, username="anmol", password="User@1234")
        self.assertTrue(success)
        self.assertEqual(client.token, "valid-user-token")

    def test_login_user_extraction(self):
        client = n_client.NexusClient(server_url=self.server_url)
        n_auth.login(client, username="admin", password="Admin@1234")
        sess = n_config.load_session()
        self.assertIsNotNone(sess)
        self.assertEqual(sess["user_id"], "admin")
        self.assertEqual(sess["role"], "admin")
        self.assertTrue(sess["privileges"].get("can_manage_users"))

    # --------------------------------------------------------------------------
    # 2. CLI Arguments & URL Normalization
    # --------------------------------------------------------------------------
    def test_cli_user_argument(self):
        client = n_client.NexusClient(server_url=self.server_url)
        with patch("getpass.getpass", return_value="Admin@1234"), patch("builtins.input") as mock_input:
            success = n_auth.login(client, username="admin")
            self.assertTrue(success)
            mock_input.assert_not_called()

    def test_server_url_normalization(self):
        self.assertEqual(n_config.normalize_server_url("https://nexus.localto.net/"), "https://nexus.localto.net")
        self.assertEqual(n_config.normalize_server_url("nexus.localto.net"), "https://nexus.localto.net")
        self.assertEqual(n_config.normalize_server_url("127.0.0.1:5000/"), "http://127.0.0.1:5000")

    def test_server_url_prompt(self):
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value="https://my-node.localto.net"):
            resolved = n_config.resolve_server_url(prompt_if_missing=True)
            self.assertEqual(resolved, "https://my-node.localto.net")

    # --------------------------------------------------------------------------
    # 3. HTML / WAF & Error Handling (401, 403, 429, 500)
    # --------------------------------------------------------------------------
    def test_html_200_response(self):
        client = n_client.NexusClient(server_url=self.server_url)
        with patch("nexus.output.print_error") as mock_err:
            success = n_auth.login(client, username="html_user", password="AnyPassword")
            self.assertFalse(success)
            self.assertTrue(any("HTML" in str(call) for call in mock_err.call_args_list))

    def test_html_waf_response(self):
        client = n_client.NexusClient(server_url=self.server_url)
        with patch("nexus.output.print_error") as mock_err:
            success = n_auth.login(client, username="waf_user", password="AnyPassword")
            self.assertFalse(success)
            self.assertTrue(any("WAF" in str(call) or "HTML" in str(call) for call in mock_err.call_args_list))

    def test_401(self):
        client = n_client.NexusClient(server_url=self.server_url)
        with patch("nexus.output.print_error") as mock_err:
            success = n_auth.login(client, username="admin", password="WrongPassword")
            self.assertFalse(success)
            mock_err.assert_called_with("Invalid username or password.")

    def test_403(self):
        client = n_client.NexusClient(server_url=self.server_url)
        with patch("nexus.output.print_error") as mock_err:
            success = n_auth.login(client, username="forbidden_user", password="AnyPassword")
            self.assertFalse(success)
            mock_err.assert_called_with("Access Forbidden.")

    def test_429(self):
        client = n_client.NexusClient(server_url=self.server_url)
        with patch("nexus.output.print_error") as mock_err:
            success = n_auth.login(client, username="locked_user", password="AnyPassword")
            self.assertFalse(success)
            mock_err.assert_called_with("Account locked. Retry in 45 seconds.")

    def test_500(self):
        client = n_client.NexusClient(server_url=self.server_url)
        with patch("nexus.output.print_error") as mock_err:
            success = n_auth.login(client, username="server_err_user", password="AnyPassword")
            self.assertFalse(success)
            mock_err.assert_called_with("Internal Server Error")

    # --------------------------------------------------------------------------
    # 4. Session Persistence, Connect & Disconnect Commands
    # --------------------------------------------------------------------------
    def test_session_persistence(self):
        client = n_client.NexusClient(server_url=self.server_url)
        n_auth.login(client, username="admin", password="Admin@1234")
        sess = n_config.load_session()
        self.assertEqual(sess["token"], "valid-admin-token")

        # New client instance automatically restores session
        new_client = n_client.NexusClient(server_url=self.server_url)
        self.assertEqual(new_client.token, "valid-admin-token")

    def test_connect_command(self):
        client = n_client.NexusClient(server_url=self.server_url)
        with patch("getpass.getpass", return_value="Admin@1234"):
            success = n_auth.connect_sequence(client, server_url=self.server_url, username="admin")
            self.assertTrue(success)

    def test_disconnect_command(self):
        client = n_client.NexusClient(server_url=self.server_url, token="valid-admin-token")
        n_config.save_session({"token": "valid-admin-token", "server_url": self.server_url})
        n_auth.logout(client)
        self.assertIsNone(client.token)
        self.assertIsNone(n_config.load_session())

    def test_whoami(self):
        client = n_client.NexusClient(server_url=self.server_url, token="valid-admin-token")
        info = n_auth.whoami(client, as_json=False)
        self.assertIsNotNone(info)
        self.assertEqual(info["user_id"], "admin")
        self.assertEqual(info["role"], "admin")

    # --------------------------------------------------------------------------
    # 5. Interactive Shell, Role-Aware Help & Autocompletion
    # --------------------------------------------------------------------------
    def test_interactive_shell(self):
        client = n_client.NexusClient(server_url=self.server_url, token="valid-admin-token")
        shell = n_shell.NexusShell(client, {"user_id": "admin", "role": "admin"})
        self.assertEqual(shell.prompt, "nexus> ")
        self.assertTrue(shell.do_exit(""))

    def test_help(self):
        client = n_client.NexusClient(server_url=self.server_url, token="valid-user-token")
        shell_user = n_shell.NexusShell(client, {"user_id": "anmol", "role": "user"})

        stdout_backup = sys.stdout
        sys.stdout = io.StringIO()
        try:
            shell_user.do_help("")
            out = sys.stdout.getvalue()
            self.assertIn("SYSTEM:", out)
            self.assertIn("STORAGE:", out)
            self.assertNotIn("ADMINISTRATION:", out)
        finally:
            sys.stdout = stdout_backup

        shell_admin = n_shell.NexusShell(client, {"user_id": "admin", "role": "admin"})
        sys.stdout = io.StringIO()
        try:
            shell_admin.do_help("")
            out_admin = sys.stdout.getvalue()
            self.assertIn("ADMINISTRATION:", out_admin)
        finally:
            sys.stdout = stdout_backup

    def test_tab_completion(self):
        client = n_client.NexusClient(server_url=self.server_url, token="valid-admin-token")
        shell = n_shell.NexusShell(client, {"user_id": "admin", "role": "admin"})
        names = shell.get_names()
        self.assertIn("do_services", names)
        self.assertIn("do_diagnostics", names)

        ai_completions = shell.complete_ai("m", "ai m", 3, 4)
        self.assertIn("models", ai_completions)
        self.assertIn("metrics", ai_completions)

        vault_completions = shell.complete_vault("l", "vault l", 6, 7)
        self.assertIn("list", vault_completions)

        # Normal user does not get admin commands
        user_shell = n_shell.NexusShell(client, {"user_id": "anmol", "role": "user"})
        user_names = user_shell.get_names()
        self.assertNotIn("do_services", user_names)

    def test_interactive_shell_blocks_os_binaries(self):
        client = n_client.NexusClient(server_url=self.server_url, token="valid-user-token")
        shell = n_shell.NexusShell(client, {"user_id": "anmol", "role": "user"})

        with patch("nexus.output.print_error") as mock_err:
            shell.default("bash -c 'whoami'")
            mock_err.assert_called_with("'bash' is not an OS shell command. Type 'help' for available NexusNode commands.")

            shell.default("rm -rf /")
            mock_err.assert_called_with("'rm' is not an OS shell command. Type 'help' for available NexusNode commands.")

    # --------------------------------------------------------------------------
    # 6. Status Command Live API Contract Tests
    # --------------------------------------------------------------------------
    def test_status_real_schema(self):
        client = n_client.NexusClient(server_url=self.server_url, token="valid-admin-token")
        args = n_main.create_parser().parse_args(["status"])
        stdout_backup = sys.stdout
        sys.stdout = io.StringIO()
        try:
            ret = cmd_status.cmd_status(client, args)
            self.assertEqual(ret, 0)
            out = sys.stdout.getvalue()
            self.assertIn("1800 MB / 3800 MB (47.4%)", out)
            self.assertIn("41.6 GB free of 64.0 GB (35.0% used)", out)
            self.assertIn("92% (CHARGING)", out)
            self.assertIn("32.5 °C", out)
            self.assertIn("4 / 4 services active", out)
            self.assertIn("1 active", out)
        finally:
            sys.stdout = stdout_backup

    def test_status_missing_field_does_not_default_to_zero(self):
        client = n_client.NexusClient(server_url=self.server_url, token="valid-admin-token")
        empty_status = {"server": {"name": "NexusNode"}}
        with patch.object(client, "get", return_value=(200, empty_status)):
            args = n_main.create_parser().parse_args(["status"])
            stdout_backup = sys.stdout
            sys.stdout = io.StringIO()
            try:
                ret = cmd_status.cmd_status(client, args)
                self.assertEqual(ret, 0)
                out = sys.stdout.getvalue()
                self.assertIn("RAM Usage:           UNAVAILABLE", out)
                self.assertNotIn("0 MB / 1 MB", out)
                self.assertIn("Vault Storage:       UNAVAILABLE", out)
                self.assertNotIn("0 B free of 0 B", out)
            finally:
                sys.stdout = stdout_backup

    def test_json_status_real_data(self):
        client = n_client.NexusClient(server_url=self.server_url, token="valid-admin-token")
        args = n_main.create_parser().parse_args(["status", "--json"])
        with patch("nexus.output.print_json") as mock_json:
            ret = cmd_status.cmd_status(client, args, as_json=True)
            self.assertEqual(ret, 0)
            mock_json.assert_called()
            call_arg = mock_json.call_args[0][0]
            self.assertEqual(call_arg["memory"]["used_mb"], 1800)
            self.assertEqual(call_arg["disk"]["total_gb"], 64.0)

    # --------------------------------------------------------------------------
    # 7. AI Models & State Contract Tests (Array & HTTP 200)
    # --------------------------------------------------------------------------
    def test_ai_models_http_200_array_response(self):
        client = n_client.NexusClient(server_url=self.server_url, token="valid-admin-token")
        args = n_main.create_parser().parse_args(["ai", "models"])
        stdout_backup = sys.stdout
        sys.stdout = io.StringIO()
        try:
            ret = cmd_ai.cmd_ai_models(client, args)
            self.assertEqual(ret, 0)
            out = sys.stdout.getvalue()
            self.assertIn("qwen2.5:0.5b", out)
            self.assertIn("llama3.2:1b", out)
            self.assertNotIn("Failed to fetch AI models", out)
        finally:
            sys.stdout = stdout_backup

    def test_ai_models_wrapped_response(self):
        client = n_client.NexusClient(server_url=self.server_url, token="valid-admin-token")
        wrapped = {"models": [{"name": "mistral:7b", "size_bytes": 4100000000, "family": "mistral", "parameter_size": "7B", "quantization_level": "Q4_0"}]}
        with patch.object(client, "get", return_value=(200, wrapped)):
            args = n_main.create_parser().parse_args(["ai", "models"])
            stdout_backup = sys.stdout
            sys.stdout = io.StringIO()
            try:
                ret = cmd_ai.cmd_ai_models(client, args)
                self.assertEqual(ret, 0)
                out = sys.stdout.getvalue()
                self.assertIn("mistral:7b", out)
            finally:
                sys.stdout = stdout_backup

    def test_ai_state(self):
        client = n_client.NexusClient(server_url=self.server_url, token="valid-admin-token")
        args = n_main.create_parser().parse_args(["ai", "state"])
        stdout_backup = sys.stdout
        sys.stdout = io.StringIO()
        try:
            ret = cmd_ai.cmd_ai_state(client, args)
            self.assertEqual(ret, 0)
            out = sys.stdout.getvalue()
            self.assertIn("Selected Model:     qwen2.5:0.5b", out)
            self.assertIn("Loaded Model:       qwen2.5:0.5b", out)
        finally:
            sys.stdout = stdout_backup

    # --------------------------------------------------------------------------
    # 8. Tasks & Media Lifecycle Tests (Separate STATUS & STAGE, Contradiction Warning)
    # --------------------------------------------------------------------------
    def test_task_status_stage_separation(self):
        client = n_client.NexusClient(server_url=self.server_url, token="valid-admin-token")
        args = n_main.create_parser().parse_args(["tasks", "list"])
        stdout_backup = sys.stdout
        sys.stdout = io.StringIO()
        try:
            ret = cmd_tasks.cmd_tasks_list(client, args)
            self.assertEqual(ret, 0)
            out = sys.stdout.getvalue()
            self.assertIn("STATUS", out)
            self.assertIn("STAGE", out)
            self.assertIn("SPEED", out)
            self.assertIn("ETA", out)
            self.assertIn("POST_PROCESSING", out)
            self.assertIn("VERIFYING", out)
            self.assertIn("1.2 MB/s", out)
        finally:
            sys.stdout = stdout_backup

    def test_task_state_contradiction_warning(self):
        client = n_client.NexusClient(server_url=self.server_url, token="valid-admin-token")
        args = n_main.create_parser().parse_args(["tasks", "list"])
        stdout_backup = sys.stdout
        stderr_backup = sys.stderr
        sys.stdout = io.StringIO()
        sys.stderr = io.StringIO()
        try:
            ret = cmd_tasks.cmd_tasks_list(client, args)
            self.assertEqual(ret, 0)
            err_out = sys.stderr.getvalue()
            self.assertIn("Task 'task-contra1'", err_out)
            self.assertIn("STATUS=COMPLETED", err_out)
            self.assertIn("STAGE=QUEUED", err_out)
        finally:
            sys.stdout = stdout_backup
            sys.stderr = stderr_backup

    def test_media_queue_uses_task_records(self):
        client = n_client.NexusClient(server_url=self.server_url, token="valid-admin-token")
        args = n_main.create_parser().parse_args(["media", "queue"])
        stdout_backup = sys.stdout
        sys.stdout = io.StringIO()
        try:
            ret = cmd_media.cmd_media_queue(client, args)
            self.assertEqual(ret, 0)
            out = n_output.strip_ansi(sys.stdout.getvalue())
            self.assertIn("ACTIVE", out)
            self.assertIn("Download: Example Video", out)
            self.assertIn("1.2 MB/s", out)
            self.assertIn("ETA:             13s", out)
            self.assertIn("QUEUED", out)
            self.assertIn("Download: Another Video", out)
        finally:
            sys.stdout = stdout_backup

    def test_media_download_task_id(self):
        client = n_client.NexusClient(server_url=self.server_url, token="valid-admin-token")
        args = n_main.create_parser().parse_args(["media", "download", "https://youtube.com/watch?v=123", "--format", "mp4"])
        stdout_backup = sys.stdout
        sys.stdout = io.StringIO()
        try:
            ret = cmd_media.cmd_media_download(client, args)
            self.assertEqual(ret, 0)
            out = n_output.strip_ansi(sys.stdout.getvalue())
            self.assertIn("Task ID:     task-media-5555", out)
            self.assertIn("Status:      QUEUED", out)
        finally:
            sys.stdout = stdout_backup

    # --------------------------------------------------------------------------
    # 9. Vault, RAG, Backups, and Admin Endpoints
    # --------------------------------------------------------------------------
    def test_vault_folder_metadata(self):
        client = n_client.NexusClient(server_url=self.server_url, token="valid-user-token")
        args = n_main.create_parser().parse_args(["vault", "list"])
        stdout_backup = sys.stdout
        sys.stdout = io.StringIO()
        try:
            ret = cmd_vault.cmd_vault_list(client, args)
            self.assertEqual(ret, 0)
            out = sys.stdout.getvalue()
            self.assertIn("2 files, 1 folders | 3.0 MB", out)
            self.assertIn("FOLDER", out)
            self.assertIn("1.0 MB", out)
            self.assertIn("2.0 MB", out)
        finally:
            sys.stdout = stdout_backup

    def test_rag_status_real_schema(self):
        client = n_client.NexusClient(server_url=self.server_url, token="valid-user-token")
        args = n_main.create_parser().parse_args(["rag", "status"])
        stdout_backup = sys.stdout
        sys.stdout = io.StringIO()
        try:
            ret = cmd_rag.cmd_rag_status(client, args)
            self.assertEqual(ret, 0)
            out = sys.stdout.getvalue()
            self.assertIn("Indexed Documents:   8", out)
            self.assertIn("Total Chunks:        128", out)
            self.assertIn("Index Size on Disk:  256.0 KB", out)
            self.assertIn("Algorithm:           SQLite FTS5 (BM25 Ranking)", out)
            self.assertIn("Last Reindex Time:   2024-08-16 17:36:40", out)
        finally:
            sys.stdout = stdout_backup

    def test_backups_list_and_create_201(self):
        client = n_client.NexusClient(server_url=self.server_url, token="valid-admin-token")
        args_list = n_main.create_parser().parse_args(["backups", "list"])
        stdout_backup = sys.stdout
        sys.stdout = io.StringIO()
        try:
            ret = cmd_backups.cmd_backups_list(client, args_list)
            self.assertEqual(ret, 0)
            out = sys.stdout.getvalue()
            self.assertIn("backup_20240816", out)
            self.assertIn("200.0 KB", out)
        finally:
            sys.stdout = stdout_backup

        args_create = n_main.create_parser().parse_args(["backups", "create"])
        sys.stdout = io.StringIO()
        try:
            ret = cmd_backups.cmd_backups_create(client, args_create)
            self.assertEqual(ret, 0)
            out = sys.stdout.getvalue()
            self.assertIn("Task ID:     task-backup-123", out)
        finally:
            sys.stdout = stdout_backup

    def test_logs_array_response(self):
        client = n_client.NexusClient(server_url=self.server_url, token="valid-admin-token")
        args = n_main.create_parser().parse_args(["logs", "recent"])
        stdout_backup = sys.stdout
        sys.stdout = io.StringIO()
        try:
            ret = cmd_logs.cmd_logs_recent(client, args)
            self.assertEqual(ret, 0)
            out = sys.stdout.getvalue()
            self.assertIn("Appliance initialized and ready.", out)
        finally:
            sys.stdout = stdout_backup

    def test_automation_array_response(self):
        client = n_client.NexusClient(server_url=self.server_url, token="valid-admin-token")
        args = n_main.create_parser().parse_args(["automation", "list"])
        stdout_backup = sys.stdout
        sys.stdout = io.StringIO()
        try:
            ret = cmd_auto.cmd_auto_list(client, args)
            self.assertEqual(ret, 0)
            out = sys.stdout.getvalue()
            self.assertIn("job_cache_clean", out)
            self.assertIn("Every 3600s", out)
        finally:
            sys.stdout = stdout_backup

    def test_normalization_helpers(self):
        self.assertEqual(n_norm.normalize_list([1, 2, 3]), [1, 2, 3])
        self.assertEqual(n_norm.normalize_list({"items": [4, 5]}), [4, 5])
        self.assertEqual(n_norm.normalize_list({"custom": [7, 8]}, preferred_key="custom"), [7, 8])
        self.assertEqual(n_norm.normalize_list("invalid"), [])

        task = n_norm.normalize_task({"id": "t1", "status": "COMPLETED", "stage": "QUEUED", "progress": 100})
        self.assertTrue(task["has_contradiction"])
        self.assertEqual(task["task_id"], "t1")
        self.assertEqual(task["progress"], 100.0)

    def test_color_enabled_tty(self):
        n_output.set_color_enabled(True)
        self.assertTrue(n_output.is_color_enabled())
        colored_text = n_output.cyan("nexus")
        self.assertIn("\033[96m", colored_text)
        self.assertIn("\033[0m", colored_text)

    def test_color_disabled_non_tty(self):
        n_output.set_color_enabled(False)
        self.assertFalse(n_output.is_color_enabled())
        plain_text = n_output.cyan("nexus")
        self.assertEqual(plain_text, "nexus")
        self.assertNotIn("\033[", plain_text)

    def test_no_color_flag(self):
        args1 = n_main.create_parser().parse_args(["--no-color", "status"])
        self.assertTrue(getattr(args1, "no_color", False))
        args2 = n_main.create_parser().parse_args(["status", "--no-color"])
        self.assertTrue(getattr(args2, "no_color", False))

    def test_json_disables_colors(self):
        n_output.set_color_enabled(True)
        args1 = n_main.create_parser().parse_args(["--json", "status"])
        self.assertTrue(getattr(args1, "json", False))
        args2 = n_main.create_parser().parse_args(["status", "--json"])
        self.assertTrue(getattr(args2, "json", False))

    def test_task_status_colors(self):
        n_output.set_color_enabled(True)
        c_comp = n_output.colorize_status("COMPLETED")
        self.assertIn("\033[92m", c_comp)  # Green

        c_run = n_output.colorize_status("RUNNING")
        self.assertIn("\033[92m", c_run)  # Green

        c_que = n_output.colorize_status("QUEUED")
        self.assertIn("\033[93m", c_que)  # Yellow

        c_fail = n_output.colorize_status("FAILED")
        self.assertIn("\033[91m", c_fail)  # Red

        c_canc = n_output.colorize_status("CANCELLED")
        self.assertIn("\033[91m", c_canc)  # Red

    def test_service_status_colors(self):
        n_output.set_color_enabled(True)
        client = n_client.NexusClient(server_url=self.server_url, token="valid-admin-token")
        args = n_main.create_parser().parse_args(["services", "status"])
        stdout_backup = sys.stdout
        sys.stdout = io.StringIO()
        try:
            ret = cmd_services.cmd_services_status(client, args)
            self.assertEqual(ret, 0)
            out = sys.stdout.getvalue()
            self.assertIn("MANAGED SYSTEM SERVICES", out)
            self.assertIn("ollama", out)
        finally:
            sys.stdout = stdout_backup
            n_output.set_color_enabled(False)

    def test_error_colors(self):
        n_output.set_color_enabled(True)
        stderr_backup = sys.stderr
        sys.stderr = io.StringIO()
        try:
            n_output.print_error("Failed to connect to backend")
            err_out = sys.stderr.getvalue()
            self.assertIn("[ERROR]", err_out)
            self.assertIn("\033[91m", err_out)
        finally:
            sys.stderr = stderr_backup
            n_output.set_color_enabled(False)

    def test_ai_colors(self):
        n_output.set_color_enabled(True)
        client = n_client.NexusClient(server_url=self.server_url, token="valid-admin-token")
        args = n_main.create_parser().parse_args(["ai", "state"])
        stdout_backup = sys.stdout
        sys.stdout = io.StringIO()
        try:
            ret = cmd_ai.cmd_ai_state(client, args)
            self.assertEqual(ret, 0)
            out = sys.stdout.getvalue()
            self.assertIn("AI RUNTIME STATE", out)
            self.assertIn("qwen2.5:0.5b", out)
        finally:
            sys.stdout = stdout_backup
            n_output.set_color_enabled(False)

    def test_table_visible_len_alignment(self):
        n_output.set_color_enabled(True)
        colored_cell = n_output.green("ACTIVE")
        self.assertEqual(n_output.visible_len(colored_cell), 6)
        self.assertEqual(n_output.strip_ansi(colored_cell), "ACTIVE")

        stdout_backup = sys.stdout
        sys.stdout = io.StringIO()
        try:
            n_output.print_table(["COL1", "COL2"], [["val1", colored_cell]])
            table_out = sys.stdout.getvalue()
            self.assertIn("COL1", table_out)
            self.assertIn("COL2", table_out)
        finally:
            sys.stdout = stdout_backup
            n_output.set_color_enabled(False)


if __name__ == "__main__":
    unittest.main()
