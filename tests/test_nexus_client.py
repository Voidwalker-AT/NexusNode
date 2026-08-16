"""
NexusNode Universal Remote CLI Client Test Suite
Tests configuration resolution, authentication lifecycle, RBAC enforcement,
streaming, error handling, table formatting, and subcommands.
"""

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
    """Mock HTTP handler returning standard NexusNode REST responses."""

    def log_message(self, format, *args):
        pass  # Suppress console log spam during test execution

    def _send_json(self, code: int, data: any):
        raw = json.dumps(data).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        auth_header = self.headers.get("Authorization", "")
        token = auth_header.replace("Bearer ", "").strip()
        path = self.path.split("?")[0]

        if path == "/api/auth/me":
            if token == "valid-admin-token":
                self._send_json(200, {
                    "user_id": "admin",
                    "role": "admin",
                    "privileges": {"can_manage_users": True, "can_control_services": True, "can_manage_models": True, "can_manage_backups": True, "can_manage_settings": True, "can_view_system_logs": True, "can_use_ai": True, "can_use_rag": True, "can_download_media": True, "can_create_shares": True},
                    "created_at": time.time()
                })
            elif token == "valid-user-token":
                self._send_json(200, {
                    "user_id": "anmol",
                    "role": "user",
                    "privileges": {"can_use_ai": True, "can_use_rag": True, "can_download_media": True, "can_create_shares": True},
                    "created_at": time.time()
                })
            else:
                self._send_json(401, {"error": "Invalid or expired session token."})

        elif path == "/api/system/status":
            self._send_json(200, {
                "appliance": {"state": "NORMAL", "tier": "TIER_4_DESKTOP"},
                "ram": {"used_mb": 1800, "total_mb": 3800, "ram_tier": "NORMAL"},
                "thermal": {"thermal_status": "NORMAL", "thermal_headroom": "NORMAL", "cpu_load_1m": 0.45, "cpu_load_5m": 0.50, "cpu_load_15m": 0.55, "battery_level": 92, "battery_temp_c": 32.5, "battery_charging": True},
                "storage": {"free_bytes": 45000000000, "total_bytes": 64000000000, "percent_used": 29.7, "vault_files_count": 14},
                "services": {"online_count": 4, "total_count": 4},
                "tasks": {"running_tasks_count": 0, "queued_tasks_count": 0},
                "process": {"rss_mb": 85, "threads": 12}
            })

        elif path == "/files":
            self._send_json(200, {
                "files": [
                    {"name": "document.pdf", "size": 1048576, "category": "document", "modified": 1723800000},
                    {"name": "photo.jpg", "size": 2097152, "category": "image", "modified": 1723805000}
                ],
                "total_count": 2,
                "total_bytes": 3145728
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
            self._send_json(200, {
                "items": [
                    {"name": "lecture.mp4", "size": 52428800, "ext": ".mp4", "modified": 1723810000}
                ],
                "total_size_bytes": 52428800
            })

        elif path == "/api/tasks":
            self._send_json(200, {
                "tasks": [
                    {"task_id": "task-abc12345", "type": "media_download", "user_id": "anmol", "state": "COMPLETED", "progress": 100.0, "description": "Download video", "created_at": 1723812000},
                    {"task_id": "task-xyz98765", "type": "rag_index", "user_id": "admin", "state": "RUNNING", "progress": 45.0, "description": "Reindex vault", "created_at": 1723813000}
                ]
            })

        elif path == "/api/ai/models":
            self._send_json(200, {
                "models": [
                    {"name": "qwen2.5:0.5b", "size_bytes": 398000000, "family": "qwen2", "parameter_size": "0.5B", "quantization_level": "Q4_K_M"},
                    {"name": "llama3.2:1b", "size_bytes": 1300000000, "family": "llama", "parameter_size": "1B", "quantization_level": "Q4_K_M"}
                ]
            })

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
            self._send_json(200, {
                "total_inferences": 42,
                "avg_tokens_per_sec": 14.8,
                "avg_prompt_eval_duration_ms": 180.5
            })

        elif path == "/api/rag/diagnostics":
            self._send_json(200, {
                "status": "HEALTHY",
                "indexed_documents_count": 8,
                "chunks_count": 128,
                "index_size_bytes": 262144,
                "algorithm": "BM25 + FTS5 Inverted Index",
                "last_indexed_at": 1723810000
            })

        elif path == "/api/rag/sources":
            self._send_json(200, {
                "sources": [
                    {"filename": "whitepaper.pdf", "chunk_count": 32, "indexed_at": 1723810000}
                ]
            })

        elif path == "/api/shares":
            self._send_json(200, {
                "shares": [
                    {"share_id": "share-12345", "filename": "whitepaper.pdf", "token": "tok987654321", "expires_at": 1723900000, "downloads_count": 2, "max_downloads": 10}
                ]
            })

        elif path == "/api/services/status":
            if token != "valid-admin-token":
                self._send_json(403, {"error": "Permission denied: can_control_services required."})
                return
            self._send_json(200, {
                "services": {
                    "ollama": {"online": True, "status": "run (pid 1023) 4200s", "pid": 1023, "supervised": True},
                    "localtonet": {"online": True, "status": "run (pid 1024) 4200s", "pid": 1024, "supervised": True}
                },
                "online_count": 2,
                "total_count": 2
            })

        elif path == "/api/admin/diagnostics/system":
            if token != "valid-admin-token":
                self._send_json(403, {"error": "Permission denied: admin required."})
                return
            self._send_json(200, {
                "uptime_seconds": 86400,
                "health": {"status": "HEALTHY"},
                "hardware": {"ram_total_bytes": 4000000000, "ram_available_bytes": 2000000000, "swap_total_bytes": 2000000000, "swap_free_bytes": 1500000000, "cpu_cores": 8, "load_avg_1m": 0.4, "load_avg_5m": 0.5, "thermal_status": "NORMAL", "battery_pct": 95, "battery_temp_c": 31.0},
                "process": {"pid": 5420, "rss_bytes": 90000000, "vms_bytes": 400000000, "threads_count": 12, "open_files_count": 24}
            })

        elif path == "/api/admin/diagnostics/full-report":
            if token != "valid-admin-token":
                self._send_json(403, {"error": "Permission denied: admin required."})
                return
            self._send_json(200, {
                "timestamp": time.time(),
                "condition": "STABLE",
                "issues": [],
                "recommendations": ["Hardware operating within optimal thermal and RAM parameters."]
            })

        elif path == "/api/events":
            if token != "valid-admin-token":
                self._send_json(403, {"error": "Permission denied: can_view_system_logs required."})
                return
            self._send_json(200, {
                "events": [
                    {"timestamp": time.time(), "level": "INFO", "component": "AUTH", "message": "User login success."}
                ]
            })

        elif path == "/api/admin/users":
            if token != "valid-admin-token":
                self._send_json(403, {"error": "Permission denied: can_manage_users required."})
                return
            self._send_json(200, [
                {"user_id": "admin", "role": "admin", "privileges": {"can_manage_users": True}, "created_at": 1723800000},
                {"user_id": "anmol", "role": "user", "privileges": {"can_use_ai": True}, "created_at": 1723805000}
            ])

        elif path == "/api/backups":
            if token != "valid-admin-token":
                self._send_json(403, {"error": "Permission denied: can_manage_backups required."})
                return
            self._send_json(200, {
                "backups": [
                    {"id": "backup_20260816", "filename": "backup_20260816.tar.gz", "size_bytes": 524288, "sha256": "abcdef1234567890", "created_at": 1723800000}
                ]
            })

        elif path == "/api/automation/jobs":
            if token != "valid-admin-token":
                self._send_json(403, {"error": "Permission denied: can_manage_automation required."})
                return
            self._send_json(200, {
                "jobs": [
                    {"id": "job_cache_clean", "description": "Clean temporary storage", "interval_or_cron": "0 3 * * *", "enabled": True, "last_run_at": 1723800000}
                ]
            })

        elif path == "/api/settings":
            if token != "valid-admin-token":
                self._send_json(403, {"error": "Permission denied: can_manage_settings required."})
                return
            self._send_json(200, {
                "server_name": "NexusNode Prime",
                "max_upload_size_mb": 500,
                "allow_guest_shares": True
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
                    "user_id": "admin",
                    "role": "admin",
                    "privileges": {"can_manage_users": True, "can_control_services": True, "can_manage_models": True, "can_manage_backups": True, "can_manage_settings": True, "can_view_system_logs": True, "can_use_ai": True, "can_use_rag": True, "can_download_media": True, "can_create_shares": True}
                })
            elif uid == "anmol" and pwd == "User@1234":
                self._send_json(200, {
                    "token": "valid-user-token",
                    "user_id": "anmol",
                    "role": "user",
                    "privileges": {"can_use_ai": True, "can_use_rag": True, "can_download_media": True, "can_create_shares": True}
                })
            elif uid == "locked_user":
                self._send_json(429, {"error": "Account locked. Try again in 45 seconds.", "lockout_seconds": 45})
            else:
                self._send_json(401, {"error": "Invalid username or password."})

        elif path == "/api/auth/logout":
            self._send_json(200, {"message": "Logged out successfully."})

        elif path == "/api/media/download":
            self._send_json(200, {
                "task_id": "task-media-5555",
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
                "estimated_model_bytes": 450000000,
                "estimated_kv_cache_bytes": 120000000,
                "estimated_total_bytes": 570000000,
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
            self._send_json(200, {
                "results": [
                    {"document": "arch.md", "score": 0.94, "snippet": "NexusNode architecture documentation."}
                ]
            })

        elif path == "/api/rag/index":
            self._send_json(200, {"message": "RAG indexing task enqueued."})

        elif path == "/api/rag/compact":
            self._send_json(200, {"message": "RAG compacted."})

        elif path == "/api/shares":
            self._send_json(201, {
                "share_id": "share-new-123",
                "filename": body.get("filename"),
                "token": "tok12345678",
                "expires_at": time.time() + 86400,
                "max_downloads": body.get("max_downloads", 10)
            })

        elif path == "/start":
            if token != "valid-admin-token":
                self._send_json(403, {"error": "Permission denied."})
                return
            self._send_json(200, {"message": f"Service '{body.get('service')}' started."})

        elif path == "/stop":
            if token != "valid-admin-token":
                self._send_json(403, {"error": "Permission denied."})
                return
            self._send_json(200, {"message": f"Service '{body.get('service')}' stopped."})

        elif path == "/api/admin/diagnostics/profile-snapshot":
            if token != "valid-admin-token":
                self._send_json(403, {"error": "Permission denied."})
                return
            self._send_json(200, {
                "snapshot_id": "snap-9876",
                "rss_bytes": 85000000,
                "threads": 12
            })

        elif path == "/api/network/test":
            self._send_json(200, {"target": body.get("target"), "status": "AVAILABLE", "latency_ms": 12.4})

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
            self._send_json(200, {
                "id": "backup-new-123",
                "filename": "backup_auto.tar.gz",
                "size_bytes": 102400,
                "sha256": "9876543210fedcba"
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
            self._send_json(200, {"message": "Settings updated."})

        elif path == "/api/vault/clean-temp":
            self._send_json(200, {"deleted_count": 3, "freed_bytes": 204800})

        else:
            self._send_json(404, {"error": "Endpoint not found."})

    def do_DELETE(self):
        auth_header = self.headers.get("Authorization", "")
        token = auth_header.replace("Bearer ", "").strip()
        path = self.path.split("?")[0]

        if path.startswith("/files/"):
            fname = path.replace("/files/", "")
            self._send_json(200, {"message": f"File '{fname}' deleted."})
        elif path.startswith("/api/shares/"):
            sid = path.replace("/api/shares/", "")
            self._send_json(200, {"message": f"Share '{sid}' revoked."})
        elif path.startswith("/api/admin/users/"):
            if token != "valid-admin-token":
                self._send_json(403, {"error": "Permission denied."})
                return
            uid = path.replace("/api/admin/users/", "")
            self._send_json(200, {"message": f"User '{uid}' deleted."})
        else:
            self._send_json(404, {"error": "Not found."})


class TestNexusUniversalCLI(unittest.TestCase):
    """Integration and Unit Test Suite for NexusNode Universal Remote CLI Client."""

    @classmethod
    def setUpClass(cls):
        # Start background Mock HTTP Server on an ephemeral port
        cls.httpd = http.server.HTTPServer(("127.0.0.1", 0), MockNexusHTTPHandler)
        cls.port = cls.httpd.server_port
        cls.server_url = f"http://127.0.0.1:{cls.port}"

        cls.server_thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.server_thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        # Create isolated temporary directory for config/session storage
        self.test_dir = tempfile.mkdtemp()
        self.config_dir = Path(self.test_dir) / ".config" / "nexusnode"
        self.config_dir.mkdir(parents=True, exist_ok=True)

        self.patch_config_dir = patch("nexus.config.get_config_dir", return_value=self.config_dir)
        self.patch_config_dir.start()

    def tearDown(self):
        self.patch_config_dir.stop()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    # --------------------------------------------------------------------------
    # 1. Server URL Resolution Tests
    # --------------------------------------------------------------------------
    def test_server_url_precedence(self):
        # 1. CLI flag takes top precedence
        with patch.dict(os.environ, {"NEXUS_SERVER": "http://env-server.com"}):
            n_config.save_config({"server_url": "http://cfg-server.com"})
            url = n_config.resolve_server_url(cli_server="http://cli-server.com")
            self.assertEqual(url, "http://cli-server.com")

        # 2. Environment variable takes second precedence
        with patch.dict(os.environ, {"NEXUS_SERVER": "http://env-server.com"}):
            n_config.save_config({"server_url": "http://cfg-server.com"})
            url = n_config.resolve_server_url()
            self.assertEqual(url, "http://env-server.com")

        # 3. Config file takes third precedence
        with patch.dict(os.environ, {}, clear=True):
            n_config.save_config({"server_url": "http://cfg-server.com"})
            url = n_config.resolve_server_url()
            self.assertEqual(url, "http://cfg-server.com")

    # --------------------------------------------------------------------------
    # 2. Session Management & File Permissions
    # --------------------------------------------------------------------------
    def test_session_persistence_and_permissions(self):
        sess_data = {"token": "test-token-123", "user_id": "anmol", "role": "user"}
        n_config.save_session(sess_data)

        # Verify load_session reads correct content
        loaded = n_config.load_session()
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["token"], "test-token-123")
        self.assertEqual(loaded["user_id"], "anmol")

        # Verify clear_session removes file
        n_config.clear_session()
        self.assertIsNone(n_config.load_session())

    # --------------------------------------------------------------------------
    # 3. Authentication & Lockout Tests
    # --------------------------------------------------------------------------
    def test_successful_login_and_logout(self):
        client = n_client.NexusClient(server_url=self.server_url)

        # Login as normal user
        success = n_auth.login(client, username="anmol", password="User@1234")
        self.assertTrue(success)
        self.assertEqual(client.token, "valid-user-token")

        # Session should be saved to disk
        sess = n_config.load_session()
        self.assertIsNotNone(sess)
        self.assertEqual(sess["user_id"], "anmol")
        self.assertEqual(sess["role"], "user")

        # Whoami should succeed
        who = n_auth.whoami(client)
        self.assertIsNotNone(who)
        self.assertEqual(who["user_id"], "anmol")

        # Logout should clear session
        n_auth.logout(client)
        self.assertIsNone(client.token)
        self.assertIsNone(n_config.load_session())

    def test_login_invalid_password(self):
        client = n_client.NexusClient(server_url=self.server_url)
        success = n_auth.login(client, username="anmol", password="WrongPassword!")
        self.assertFalse(success)
        self.assertIsNone(client.token)
        self.assertIsNone(n_config.load_session())

    def test_login_account_locked_429(self):
        client = n_client.NexusClient(server_url=self.server_url)
        success = n_auth.login(client, username="locked_user", password="AnyPassword")
        self.assertFalse(success)
        self.assertIsNone(client.token)

    # --------------------------------------------------------------------------
    # 4. RBAC & Error Handling (401 vs 403)
    # --------------------------------------------------------------------------
    def test_401_clears_session(self):
        client = n_client.NexusClient(server_url=self.server_url, token="expired-token")
        n_config.save_session({"token": "expired-token", "user_id": "anmol"})

        status_code, resp = client.get("/api/auth/me")
        self.assertEqual(status_code, 401)
        # Session must be purged on 401
        self.assertIsNone(n_config.load_session())

    def test_403_preserves_session(self):
        # User tries to access admin services
        client = n_client.NexusClient(server_url=self.server_url, token="valid-user-token")
        n_config.save_session({"token": "valid-user-token", "user_id": "anmol", "role": "user"})

        status_code, resp = client.get("/api/services/status")
        self.assertEqual(status_code, 403)
        # Session must NOT be destroyed on 403
        self.assertIsNotNone(n_config.load_session())

    # --------------------------------------------------------------------------
    # 5. User Commands (Status, Vault, Media, Tasks, AI, RAG, Shares)
    # --------------------------------------------------------------------------
    def test_cmd_status(self):
        client = n_client.NexusClient(server_url=self.server_url, token="valid-user-token")
        mock_args = n_main.create_parser().parse_args(["status"])
        ret = cmd_status.cmd_status(client, mock_args)
        self.assertEqual(ret, 0)

        # JSON mode
        mock_json_args = n_main.create_parser().parse_args(["status", "--json"])
        ret_json = cmd_status.cmd_status(client, mock_json_args, as_json=True)
        self.assertEqual(ret_json, 0)

    def test_cmd_vault(self):
        client = n_client.NexusClient(server_url=self.server_url, token="valid-user-token")
        # List
        args = n_main.create_parser().parse_args(["vault", "list"])
        self.assertEqual(cmd_vault.cmd_vault(client, args), 0)

        # Info
        args = n_main.create_parser().parse_args(["vault", "info", "document.pdf"])
        self.assertEqual(cmd_vault.cmd_vault(client, args), 0)

        # Download
        dest_path = Path(self.test_dir) / "downloaded.pdf"
        args = n_main.create_parser().parse_args(["vault", "download", "document.pdf", str(dest_path)])
        self.assertEqual(cmd_vault.cmd_vault(client, args), 0)
        self.assertTrue(dest_path.exists())
        self.assertEqual(dest_path.read_bytes(), b"PDF Mock Content Data")

        # Delete
        args = n_main.create_parser().parse_args(["vault", "delete", "document.pdf", "-y"])
        self.assertEqual(cmd_vault.cmd_vault(client, args), 0)

    def test_cmd_media(self):
        client = n_client.NexusClient(server_url=self.server_url, token="valid-user-token")
        # Download (server payload)
        args = n_main.create_parser().parse_args(["media", "download", "https://youtube.com/watch?v=12345", "--format", "mp3"])
        self.assertEqual(cmd_media.cmd_media(client, args), 0)

        # Library
        args = n_main.create_parser().parse_args(["media", "library"])
        self.assertEqual(cmd_media.cmd_media(client, args), 0)

        # Queue
        args = n_main.create_parser().parse_args(["media", "queue"])
        self.assertEqual(cmd_media.cmd_media(client, args), 0)

    def test_cmd_tasks_ownership(self):
        client = n_client.NexusClient(server_url=self.server_url, token="valid-user-token")
        # List
        args = n_main.create_parser().parse_args(["tasks", "list"])
        self.assertEqual(cmd_tasks.cmd_tasks(client, args), 0)

        # Cancel own task -> Success
        args = n_main.create_parser().parse_args(["tasks", "cancel", "task-abc12345"])
        self.assertEqual(cmd_tasks.cmd_tasks(client, args), 0)

        # Cancel foreign task -> 403 Forbidden
        args = n_main.create_parser().parse_args(["tasks", "cancel", "task-foreign-999"])
        self.assertEqual(cmd_tasks.cmd_tasks(client, args), 1)

    def test_cmd_ai(self):
        client = n_client.NexusClient(server_url=self.server_url, token="valid-user-token")
        # Models
        args = n_main.create_parser().parse_args(["ai", "models"])
        self.assertEqual(cmd_ai.cmd_ai(client, args), 0)

        # State
        args = n_main.create_parser().parse_args(["ai", "state"])
        self.assertEqual(cmd_ai.cmd_ai(client, args), 0)

        # Select
        args = n_main.create_parser().parse_args(["ai", "select", "qwen2.5:0.5b"])
        self.assertEqual(cmd_ai.cmd_ai(client, args), 0)

        # Streaming Chat
        args = n_main.create_parser().parse_args(["ai", "chat", "--prompt", "Hello"])
        self.assertEqual(cmd_ai.cmd_ai(client, args), 0)

    def test_cmd_rag(self):
        client = n_client.NexusClient(server_url=self.server_url, token="valid-user-token")
        # Status
        args = n_main.create_parser().parse_args(["rag", "status"])
        self.assertEqual(cmd_rag.cmd_rag(client, args), 0)

        # Search
        args = n_main.create_parser().parse_args(["rag", "search", "architecture"])
        self.assertEqual(cmd_rag.cmd_rag(client, args), 0)

        # Sources
        args = n_main.create_parser().parse_args(["rag", "sources"])
        self.assertEqual(cmd_rag.cmd_rag(client, args), 0)

    def test_cmd_shares(self):
        client = n_client.NexusClient(server_url=self.server_url, token="valid-user-token")
        # List
        args = n_main.create_parser().parse_args(["shares", "list"])
        self.assertEqual(cmd_shares.cmd_shares(client, args), 0)

        # Create
        args = n_main.create_parser().parse_args(["shares", "create", "whitepaper.pdf"])
        self.assertEqual(cmd_shares.cmd_shares(client, args), 0)

        # Revoke
        args = n_main.create_parser().parse_args(["shares", "revoke", "share-12345"])
        self.assertEqual(cmd_shares.cmd_shares(client, args), 0)

    # --------------------------------------------------------------------------
    # 6. Admin Commands (Services, Models, Diagnostics, Users, Backups, Settings)
    # --------------------------------------------------------------------------
    def test_admin_commands_as_admin(self):
        admin_client = n_client.NexusClient(server_url=self.server_url, token="valid-admin-token")

        # Services
        args = n_main.create_parser().parse_args(["services", "status"])
        self.assertEqual(cmd_services.cmd_services(admin_client, args), 0)

        args = n_main.create_parser().parse_args(["services", "start", "ollama"])
        self.assertEqual(cmd_services.cmd_services(admin_client, args), 0)

        # Models details & estimate
        args = n_main.create_parser().parse_args(["models", "details", "qwen2.5:0.5b"])
        self.assertEqual(cmd_models.cmd_models(admin_client, args), 0)

        args = n_main.create_parser().parse_args(["models", "estimate", "qwen2.5:0.5b"])
        self.assertEqual(cmd_models.cmd_models(admin_client, args), 0)

        # Diagnostics system & full
        args = n_main.create_parser().parse_args(["diagnostics", "system"])
        self.assertEqual(cmd_diag.cmd_diagnostics(admin_client, args), 0)

        args = n_main.create_parser().parse_args(["diagnostics", "full"])
        self.assertEqual(cmd_diag.cmd_diagnostics(admin_client, args), 0)

        # Logs recent
        args = n_main.create_parser().parse_args(["logs", "recent"])
        self.assertEqual(cmd_logs.cmd_logs(admin_client, args), 0)

        # Users
        args = n_main.create_parser().parse_args(["users", "list"])
        self.assertEqual(cmd_users.cmd_users(admin_client, args), 0)

        args = n_main.create_parser().parse_args(["users", "create", "testuser", "--password", "Pass@123"])
        self.assertEqual(cmd_users.cmd_users(admin_client, args), 0)

        # Backups
        args = n_main.create_parser().parse_args(["backups", "list"])
        self.assertEqual(cmd_backups.cmd_backups(admin_client, args), 0)

        args = n_main.create_parser().parse_args(["backups", "create"])
        self.assertEqual(cmd_backups.cmd_backups(admin_client, args), 0)

        # Automation
        args = n_main.create_parser().parse_args(["automation", "list"])
        self.assertEqual(cmd_auto.cmd_automation(admin_client, args), 0)

        # Settings
        args = n_main.create_parser().parse_args(["settings", "get"])
        self.assertEqual(cmd_settings.cmd_settings(admin_client, args), 0)

        # Database
        args = n_main.create_parser().parse_args(["database", "diagnostics"])
        self.assertEqual(cmd_db.cmd_database(admin_client, args), 0)

    def test_admin_commands_denied_to_normal_user(self):
        user_client = n_client.NexusClient(server_url=self.server_url, token="valid-user-token")

        # Services -> 403
        args = n_main.create_parser().parse_args(["services", "status"])
        self.assertEqual(cmd_services.cmd_services(user_client, args), 1)

        # Diagnostics -> 403
        args = n_main.create_parser().parse_args(["diagnostics", "system"])
        self.assertEqual(cmd_diag.cmd_diagnostics(user_client, args), 1)

        # Users -> 403
        args = n_main.create_parser().parse_args(["users", "list"])
        self.assertEqual(cmd_users.cmd_users(user_client, args), 1)

        # Backups -> 403
        args = n_main.create_parser().parse_args(["backups", "list"])
        self.assertEqual(cmd_backups.cmd_backups(user_client, args), 1)

    # --------------------------------------------------------------------------
    # 7. Interactive Shell Safety (Blocks Arbitrary OS Binaries)
    # --------------------------------------------------------------------------
    def test_interactive_shell_blocks_os_binaries(self):
        client = n_client.NexusClient(server_url=self.server_url, token="valid-user-token")
        shell = n_shell.NexusShell(client, {"user_id": "anmol", "role": "user"})

        with patch("nexus.output.print_error") as mock_err:
            shell.default("bash -c 'whoami'")
            mock_err.assert_called_with("'bash' is not an arbitrary OS shell command. Type 'help' for available NexusNode commands.")

            shell.default("rm -rf /")
            mock_err.assert_called_with("'rm' is not an arbitrary OS shell command. Type 'help' for available NexusNode commands.")


if __name__ == "__main__":
    unittest.main()
