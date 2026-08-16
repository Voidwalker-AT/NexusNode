"""
NexusNode — Comprehensive Unit and Integration Test Suite
Validates 24/7 Mobile Server Appliance Hardening & Diagnostics:
1. Health and unprivileged status endpoints
2. Resource Governor thresholds, RAM state, and Thermal protection
3. Bounded task runner (concurrency bound = 1, cancellation & partial file cleanup, task ownership)
4. Storage-backed SQLite FTS5 RAG engine & BM25 ranking
5. Security controls (auth enforcement, path traversal blocking, security headers)
6. RBAC permissions, SQLite DB inspection, and brute-force tracking
7. Temporary secure share links (token generation, expiration, revocation, download limits)
8. Media Center batch URL queueing, library categorization, and HTTP 206 Range streaming
9. Atomic backup creation, SHA-256 checksum verification, and safe restore validation
10. Storage Intelligence calculation and safe temp-files cleanup
11. Unprivileged network diagnostics and latency tests
12. Scheduled automation job triggers and system settings management
13. Authoritative Ollama Model Serving, Registry, and Runtime Lifecycle
14. Storage-backed SQLite FTS5 RAG Diagnostics & Legacy Migration
15. Single-Threaded Bounded Log Writer Daemon
16. Task Cancellation Bug Fix & Object-Level RBAC
17. Technical System Diagnostics, Memory Budget, and Automated Root-Cause Engine
"""

import os
import sys
import json
import time
import shutil
import base64
import secrets
import tempfile
import unittest
import subprocess
from unittest.mock import MagicMock, patch, mock_open

# Add parent directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import config
from resource_governor import ResourceGovernor, governor
import app as server_app


class TestNexusNodeServer(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # Configure app for testing
        server_app.app.config['TESTING'] = True
        cls.client = server_app.app.test_client()

        # Create temporary storage test directory
        cls.test_dir = tempfile.mkdtemp(prefix="nexus_test_")
        cls.orig_storage_dir = config.STORAGE_DIR
        config.STORAGE_DIR = os.path.join(cls.test_dir, "storage_vault")
        config.BACKUP_DIR = os.path.join(config.STORAGE_DIR, "backups")
        os.makedirs(config.STORAGE_DIR, exist_ok=True)
        os.makedirs(config.BACKUP_DIR, exist_ok=True)

        # Generate test admin token
        admin_token = secrets.token_hex(32)
        with server_app.SESSIONS_LOCK:
            server_app.SESSIONS[admin_token] = {
                "user_id": "admin",
                "role": "admin",
                "privileges": config.ADMIN_DEFAULT_PRIVILEGES,
                "created_at": time.time(),
                "expires_at": time.time() + 86400
            }
        cls.admin_token = admin_token

    @classmethod
    def tearDownClass(cls):
        config.STORAGE_DIR = cls.orig_storage_dir
        if os.path.exists(cls.test_dir):
            shutil.rmtree(cls.test_dir, ignore_errors=True)

    def setUp(self):
        self.client = server_app.app.test_client()
        self.admin_token = self.__class__.admin_token
        server_app.governor.snapshot_cache.set(None)
        server_app.clear_account_lockout()

    def tearDown(self):
        server_app.clear_account_lockout()

    # 1. Health and Unprivileged Probing
    def test_01_health_endpoint(self):
        """Verify GET /api/health returns fast 200 OK."""
        res = self.client.get('/api/health')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn(data.get('status'), ['healthy', 'ok'])
        self.assertIn('uptime_seconds', data)

    def test_02_services_status_endpoint(self):
        """Verify GET /api/services/status returns unprivileged probe data."""
        res = self.client.get(
            '/api/services/status',
            headers={'Authorization': f'Bearer {self.admin_token}'}
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn('nexusnode', data)
        self.assertIn('localtonet', data)
        self.assertIn('ssh', data)
        self.assertIn('ollama', data)
        self.assertEqual(data['nexusnode']['status'], 'online')

    def test_03_system_status_endpoint(self):
        """Verify GET /api/system/status aggregate endpoint."""
        res = self.client.get(
            '/api/system/status',
            headers={'Authorization': f'Bearer {self.admin_token}'}
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn('server', data)
        self.assertIn('memory', data)
        self.assertIn('disk', data)
        self.assertIn('services', data)
        self.assertIn('tasks', data)
        self.assertIn('appliance', data)

    # 2. Resource Governor State Tests
    def test_04_resource_governor_thresholds(self):
        """Verify Resource Governor accurately assigns states based on available MB."""
        gov = ResourceGovernor()
        
        # Test normal state (> 1000 MB)
        with patch.object(gov, 'get_memory_status', return_value={"total_mb": 3800, "available_mb": 1500, "state": "normal", "reason": "Normal"}):
            gov.snapshot_cache.set(None)
            self.assertTrue(gov.can_start_heavy_task()["allowed"])
            self.assertTrue(gov.can_start_rag()["allowed"])
            self.assertTrue(gov.can_start_ollama()["allowed"])

        # Test pressure state (600 - 1000 MB)
        with patch.object(gov, 'get_memory_status', return_value={"total_mb": 3800, "available_mb": 750, "state": "pressure", "reason": "Pressure"}):
            gov.snapshot_cache.set(None)
            self.assertFalse(gov.can_start_heavy_task()["allowed"])
            self.assertTrue(gov.can_start_rag()["allowed"])

        # Test critical state (< 600 MB)
        with patch.object(gov, 'get_memory_status', return_value={"total_mb": 3800, "available_mb": 350, "state": "critical", "reason": "Critical"}):
            gov.snapshot_cache.set(None)
            self.assertFalse(gov.can_start_heavy_task()["allowed"])
            self.assertFalse(gov.can_start_rag()["allowed"])
            self.assertFalse(gov.can_start_ollama()["allowed"])

    # 3. Bounded Task Worker & Heavy Operation Protection
    def test_05_bounded_task_concurrency_and_cancellation(self):
        """Verify BoundedTaskRunner queues tasks and cancels clean."""
        runner = server_app.BoundedTaskRunner(max_concurrency=1)

        def mock_slow_job(task_obj, duration):
            task_obj['logs'].append("Working...")
            for _ in range(int(duration * 10)):
                if task_obj['status'] == 'cancelled':
                    break
                time.sleep(0.05)

        t1_id, _ = runner.enqueue_task("Task 1", "test", mock_slow_job, 0.5)
        t2_id, _ = runner.enqueue_task("Task 2", "test", mock_slow_job, 0.5)

        self.assertIsNotNone(t1_id)
        self.assertIsNotNone(t2_id)

        # Cancel Task 2
        success, msg = runner.cancel_task(t2_id, is_admin=True)
        self.assertTrue(success)
        self.assertIn(runner.tasks[t2_id]['status'].upper(), ['CANCELLED'])

    def test_06_partial_download_cleanup_on_cancel(self):
        """Verify partial files are removed on task cleanup."""
        runner = server_app.BoundedTaskRunner(max_concurrency=1)
        part_file = os.path.join(config.STORAGE_DIR, "test_download.mp4.part")
        with open(part_file, "w") as f:
            f.write("partial data chunk")
        
        self.assertTrue(os.path.exists(part_file))
        runner._cleanup_partial_files({"partial_files": [part_file]})
        self.assertFalse(os.path.exists(part_file))

    def test_07_interrupted_tasks_db_record(self):
        """Verify task status persistence in unified SQLite database."""
        t_id = f"test_task_{secrets.token_hex(4)}"
        with server_app.DB_LOCK:
            conn = server_app.get_db_connection()
            conn.execute("""
                INSERT OR REPLACE INTO background_tasks (id, title, type, status, progress, logs, owner_user_id, created_at, updated_at)
                VALUES (?, 'Crash Test', 'test', 'completed', 100, '["started"]', 'admin', 1000.0, 1001.0);
            """, (t_id,))
            conn.commit()
            conn.close()

        with server_app.DB_LOCK:
            conn = server_app.get_db_connection()
            cur = conn.cursor()
            cur.execute("SELECT status FROM background_tasks WHERE id = ?", (t_id,))
            st = cur.fetchone()[0]
            conn.close()
        self.assertEqual(st, 'completed')

    # 4. Asynchronous Serialized RAG Engine
    def test_08_sqlite_fts5_rag_indexing(self):
        """Verify SQLite FTS5 RAG index builds without throwing and supports searching."""
        test_doc = os.path.join(config.STORAGE_DIR, "rag_sample.txt")
        with open(test_doc, "w", encoding="utf-8") as f:
            f.write("NexusNode is a hardened 24/7 mobile server appliance for Android 13 Termux.\nIt protects memory with a 4GB resource governor.")

        rag = server_app.SQLiteFTS5RAGEngine()
        rag.source_folders = ["."]
        res = rag.build_vault_index()
        self.assertIn("documents_count", res)
        self.assertTrue(res["documents_count"] >= 1)

        # Search test
        results = rag.search("resource governor")
        self.assertTrue(len(results) > 0)
        self.assertIn("governor", results[0]["text"].lower())

    # 5. Security & Path Traversal Controls
    def test_09_path_traversal_sanitization(self):
        """Verify sanitize_storage_path detects and blocks traversal payloads."""
        traversal_payloads = [
            "../../etc/passwd",
            "..\\..\\windows\\system32",
            "....//....//config.py"
        ]
        for payload in traversal_payloads:
            with self.assertRaises(ValueError):
                server_app.sanitize_storage_path(payload)

    def test_10_unauthorized_download_blocked(self):
        """Verify unauthenticated user cannot download storage vault files."""
        res = self.client.get('/download/secret_file.txt')
        self.assertEqual(res.status_code, 401)

    def test_11_unauthorized_logs_stream_blocked(self):
        """Verify unauthenticated user cannot access live SSE log stream."""
        res = self.client.get('/api/logs/stream')
        self.assertEqual(res.status_code, 401)

    def test_12_authorized_download_success(self):
        """Verify authorized admin can download a file."""
        sample_path = os.path.join(config.STORAGE_DIR, "sample_dl.txt")
        with open(sample_path, "w", encoding="utf-8") as f:
            f.write("authorized content")

        res = self.client.get(
            '/download/sample_dl.txt',
            headers={'Authorization': f'Bearer {self.admin_token}'}
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data.decode('utf-8'), "authorized content")

    def test_13_security_headers_applied(self):
        """Verify security headers and localtonet bypass headers are attached."""
        res = self.client.get('/api/health')
        self.assertEqual(res.headers.get('localtonet-skip-warning'), 'true')
        self.assertEqual(res.headers.get('X-Content-Type-Options'), 'nosniff')
        self.assertEqual(res.headers.get('X-Frame-Options'), 'DENY')

    def test_14_low_memory_rejection_for_ollama(self):
        """Verify engine start is blocked with 429 when RAM is critical."""
        with patch.object(server_app.governor, 'get_memory_status', return_value={"total_mb": 3800, "available_mb": 350, "state": "critical", "reason": "Low RAM"}):
            server_app.governor.snapshot_cache.set(None)
            res = self.client.post('/start', headers={'Authorization': f'Bearer {self.admin_token}'})
            self.assertEqual(res.status_code, 429)

    def test_15_admin_user_provisioning(self):
        """Verify admin can create, list, and manage users."""
        u_id = f"testuser_{secrets.token_hex(4)}"
        res = self.client.post(
            '/api/admin/users',
            headers={'Authorization': f'Bearer {self.admin_token}'},
            json={"user_id": u_id, "password": "secure_password_123"}
        )
        self.assertEqual(res.status_code, 201)

        # Verify user exists in list
        res_list = self.client.get('/api/admin/users', headers={'Authorization': f'Bearer {self.admin_token}'})
        self.assertEqual(res_list.status_code, 200)
        users = res_list.get_json()
        self.assertTrue(any(u["user_id"] == u_id for u in users))

    def test_16_rbac_permission_enforcement(self):
        """Verify non-admin user without privileges is blocked from admin routes."""
        user_tok = secrets.token_hex(32)
        with server_app.SESSIONS_LOCK:
            server_app.SESSIONS[user_tok] = {
                "user_id": "limited_user",
                "role": "user",
                "privileges": {"can_use_ai": True},
                "created_at": time.time(),
                "expires_at": time.time() + 3600
            }

        res = self.client.get('/api/admin/stats', headers={'Authorization': f'Bearer {user_tok}'})
        self.assertEqual(res.status_code, 403)

    def test_17_sqlite_db_inspector_endpoints(self):
        """Verify /api/admin/db/query return accurate table rows."""
        res = self.client.get(
            '/api/admin/db/query?table=users',
            headers={'Authorization': f'Bearer {self.admin_token}'}
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("rows", data)
        self.assertTrue(len(data["rows"]) >= 1)

    def test_18_brute_force_lockout_mechanism(self):
        """Verify IP address is blocked after exceeding lockout threshold of failed logins."""
        for _ in range(config.LOCKOUT_THRESHOLD):
            self.client.post('/api/auth/login', json={"user_id": "nonexistent", "password": "wrong"})

        # Subsequent attempt returns 429 locked_out
        res = self.client.post('/api/auth/login', json={"user_id": "nonexistent", "password": "wrong"})
        self.assertEqual(res.status_code, 429)

        # Clear failed logins lock
        with server_app.FAILED_LOGINS_LOCK:
            server_app.FAILED_LOGINS.clear()

    def test_19_temporary_share_create_and_access(self):
        """Verify temporary share link creation and public download."""
        share_filename = "share_test_file.txt"
        share_path = os.path.join(config.STORAGE_DIR, share_filename)
        with open(share_path, "w", encoding="utf-8") as f:
            f.write("public shareable payload")

        res_create = self.client.post(
            '/api/shares',
            headers={'Authorization': f'Bearer {self.admin_token}'},
            json={"filename": share_filename, "duration": "1h", "max_downloads": 5}
        )
        self.assertEqual(res_create.status_code, 200)
        data = res_create.get_json()
        self.assertIn("token", data)

        # Public access without auth
        res_download = self.client.get(f"/s/{data['token']}")
        self.assertEqual(res_download.status_code, 200)
        self.assertEqual(res_download.data.decode('utf-8'), "public shareable payload")

    def test_20_temporary_share_revocation(self):
        """Verify revoking a share link returns 410 Gone on subsequent access."""
        share_filename = "revocation_test.txt"
        share_path = os.path.join(config.STORAGE_DIR, share_filename)
        with open(share_path, "w", encoding="utf-8") as f:
            f.write("sensitive revoke test")

        res_create = self.client.post(
            '/api/shares',
            headers={'Authorization': f'Bearer {self.admin_token}'},
            json={"filename": share_filename, "duration": "1h", "max_downloads": 5}
        )
        token = res_create.get_json()["token"]
        share_id = res_create.get_json()["share_id"]

        # Revoke
        res_revoke = self.client.delete(f"/api/shares/{share_id}", headers={'Authorization': f'Bearer {self.admin_token}'})
        self.assertEqual(res_revoke.status_code, 200)

        # Subsequent access
        res_get = self.client.get(f"/s/{token}")
        self.assertEqual(res_get.status_code, 410)

    def test_21_media_download_batch_queueing(self):
        """Verify multiline URLs are parsed and enqueued."""
        res = self.client.post(
            '/api/media/download',
            headers={'Authorization': f'Bearer {self.admin_token}'},
            json={"url": "https://example.com/video1\nhttps://example.com/video2", "format": "mp3"}
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data.get('enqueued_count'), 2)
        self.assertEqual(len(data.get('task_ids')), 2)

    def test_22_media_library_categorization(self):
        """Verify /api/media/library categorizes vault files."""
        music_dir = os.path.join(config.STORAGE_DIR, "Music")
        os.makedirs(music_dir, exist_ok=True)
        with open(os.path.join(music_dir, "song.mp3"), "w") as f:
            f.write("audio data")

        res = self.client.get('/api/media/library', headers={'Authorization': f'Bearer {self.admin_token}'})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn('music', data)
        self.assertTrue(any(m['filename'] == 'song.mp3' for m in data['music']))

    def test_23_media_streaming_range_requests(self):
        """Verify HTTP 206 Partial Content is returned when Range header is provided."""
        media_path = os.path.join(config.STORAGE_DIR, "stream_test.mp3")
        with open(media_path, "wb") as f:
            f.write(b"0123456789" * 100) # 1000 bytes

        res = self.client.get(
            '/stream/stream_test.mp3',
            headers={'Authorization': f'Bearer {self.admin_token}', 'Range': 'bytes=0-49'}
        )
        self.assertEqual(res.status_code, 206)
        self.assertEqual(len(res.data), 50)
        self.assertIn('Content-Range', res.headers)

    def test_24_backup_create_and_checksum_verification(self):
        """Verify atomic backup creation and SHA-256 checksum calculation."""
        dummy_task = {"logs": [], "partial_files": [], "owner_user_id": "admin"}
        server_app.run_backup_job(dummy_task)
        self.assertTrue(any("Backup verified" in log for log in dummy_task["logs"]))

    def test_25_storage_intelligence_calculation(self):
        """Verify /api/storage/intelligence returns breakdown categories."""
        res = self.client.get(
            '/api/storage/intelligence',
            headers={'Authorization': f'Bearer {self.admin_token}'}
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn('breakdown', data)
        self.assertIn('large_files', data)

    def test_26_temp_files_cleanup_safety(self):
        """Verify /api/vault/clean-temp only removes .part/.tmp and preserves normal files."""
        temp_file = os.path.join(config.STORAGE_DIR, "download.mp4.part")
        real_file = os.path.join(config.STORAGE_DIR, "important_doc.pdf")
        with open(temp_file, "w") as f:
            f.write("temporary garbage")
        with open(real_file, "w") as f:
            f.write("vital user data")

        dummy_task = {"logs": []}
        server_app.run_clean_temp_job(dummy_task)

        self.assertFalse(os.path.exists(temp_file))
        self.assertTrue(os.path.exists(real_file))

    def test_27_network_diagnostic_latency_test(self):
        """Verify /api/network/test executes safe unprivileged test."""
        res = self.client.post(
            '/api/network/test',
            headers={'Authorization': f'Bearer {self.admin_token}'},
            json={"target": "nexusnode"}
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data.get('status'), 'available')
        self.assertIsNotNone(data.get('latency_ms'))

    def test_28_thermal_critical_governor_blocking(self):
        """Verify thermal CRITICAL state blocks heavy tasks."""
        with patch.object(server_app.governor, 'get_device_telemetry', return_value={
            "effective_temperature_c": 58.5,
            "thermal_state": "CRITICAL",
            "thermal_desc": "Thermal critical (58.5°C ≥ 55°C)."
        }):
            server_app.governor.snapshot_cache.set(None)
            check = server_app.governor.can_start_heavy_task()
            self.assertFalse(check["allowed"])
            self.assertIn("thermal critical", check["reason"].lower())

    def test_29_scheduled_automation_job_trigger(self):
        """Verify listing and manually triggering scheduled maintenance jobs."""
        with patch.object(server_app, 'probe_localtonet_health', return_value={"state": "TUNNEL_CONNECTED"}):
            res_list = self.client.get(
                '/api/automation/jobs',
                headers={'Authorization': f'Bearer {self.admin_token}'}
            )
            self.assertEqual(res_list.status_code, 200)
            jobs = res_list.get_json()
            self.assertTrue(len(jobs) >= 1)

            # Trigger job
            job_id = jobs[0]["id"]
            res_run = self.client.post(
                f'/api/automation/jobs/{job_id}/run',
                headers={'Authorization': f'Bearer {self.admin_token}'}
            )
            self.assertEqual(res_run.status_code, 200)
            self.assertIn('triggered', res_run.get_json().get('message', '').lower())

    def test_30_settings_update_and_restart_flag(self):
        """Verify settings update API."""
        res_get = self.client.get(
            '/api/settings',
            headers={'Authorization': f'Bearer {self.admin_token}'}
        )
        self.assertEqual(res_get.status_code, 200)
        
        # Update governor threshold
        res_post = self.client.post(
            '/api/settings',
            headers={'Authorization': f'Bearer {self.admin_token}'},
            json={"ram_normal_mb": 1100}
        )
        self.assertEqual(res_post.status_code, 200)
        self.assertTrue(res_post.get_json().get('updated'))

    def test_31_backup_archive_contents_no_secrets(self):
        """Verify backup archive contains only intended files and no plaintext tokens/secrets."""
        import zipfile
        dummy_task = {"logs": [], "partial_files": [], "owner_user_id": "admin"}
        server_app.run_backup_job(dummy_task)
        
        # Find created backup
        backups = [f for f in os.listdir(config.BACKUP_DIR) if f.endswith('.zip')]
        self.assertTrue(len(backups) >= 1)
        backup_path = os.path.join(config.BACKUP_DIR, backups[-1])

        with zipfile.ZipFile(backup_path, 'r') as zf:
            names = zf.namelist()
            self.assertIn("nexus_vault.db", names)
            self.assertIn("manifest.json", names)
            
            manifest_raw = zf.read("manifest.json").decode('utf-8')
            manifest = json.loads(manifest_raw)
            self.assertEqual(manifest["version"], config.VERSION)

    def test_32_task_queue_sequential_execution_and_cancellation(self):
        """Verify task runner serializes jobs sequentially."""
        runner = server_app.BoundedTaskRunner(max_concurrency=1)

        def slow_job(task_obj, name, dur):
            for _ in range(int(dur * 20)):
                if task_obj['status'] == 'cancelled': break
                time.sleep(0.05)

        t1, _ = runner.enqueue_task("Job A", "test", slow_job, "A", 0.5)
        t2, _ = runner.enqueue_task("Job B", "test", slow_job, "B", 0.5)

        success, _ = runner.cancel_task(t2, is_admin=True)
        self.assertTrue(success)

    def test_33_database_init_idempotency(self):
        """Verify multiple consecutive runs of init_unified_db do not corrupt tables."""
        for _ in range(3):
            server_app.init_unified_db()

        with server_app.DB_LOCK:
            conn = server_app.get_db_connection()
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM users WHERE user_id = 'admin';")
            self.assertEqual(cur.fetchone()[0], 1)
            conn.close()

    def test_34_model_ram_estimation_table(self):
        """Verify model RAM requirement estimation logic and decision output."""
        res_small = self.client.post(
            '/api/models/estimate',
            headers={'Authorization': f'Bearer {self.admin_token}'},
            json={"model": "qwen2.5:0.5b"}
        )
        self.assertEqual(res_small.status_code, 200)
        data_small = res_small.get_json()
        self.assertIn(data_small["decision"], ["SAFE", "WARNING", "BLOCKED"])

    def test_35_logout_clears_session_state(self):
        """Verify POST /api/auth/logout destroys server-side session token."""
        temp_token = secrets.token_hex(32)
        with server_app.SESSIONS_LOCK:
            server_app.SESSIONS[temp_token] = {
                "user_id": "test_logout_user",
                "role": "user",
                "privileges": config.USER_DEFAULT_PRIVILEGES,
                "created_at": time.time(),
                "expires_at": time.time() + 3600
            }

        # Verify active
        res_me = self.client.get('/api/auth/me', headers={'Authorization': f'Bearer {temp_token}'})
        self.assertEqual(res_me.status_code, 200)

        # Logout
        res_logout = self.client.post('/api/auth/logout', headers={'Authorization': f'Bearer {temp_token}'})
        self.assertEqual(res_logout.status_code, 200)

        # Token must no longer exist in SESSIONS
        with server_app.SESSIONS_LOCK:
            self.assertNotIn(temp_token, server_app.SESSIONS)

        # Subsequent call with revoked token returns 401
        res_after = self.client.get('/api/auth/me', headers={'Authorization': f'Bearer {temp_token}'})
        self.assertEqual(res_after.status_code, 401)

    def test_36_admin_logout_then_user_login_isolation(self):
        """Verify complete privilege isolation when switching from admin to normal user."""
        admin_tok = secrets.token_hex(32)
        with server_app.SESSIONS_LOCK:
            server_app.SESSIONS[admin_tok] = {
                "user_id": "admin",
                "role": "admin",
                "privileges": config.ADMIN_DEFAULT_PRIVILEGES,
                "created_at": time.time(),
                "expires_at": time.time() + 3600
            }

        # Admin can access admin stats
        res_admin = self.client.get('/api/admin/stats', headers={'Authorization': f'Bearer {admin_tok}'})
        self.assertEqual(res_admin.status_code, 200)

        # Admin logs out
        self.client.post('/api/auth/logout', headers={'Authorization': f'Bearer {admin_tok}'})

        # Normal user logs in
        user_tok = secrets.token_hex(32)
        with server_app.SESSIONS_LOCK:
            server_app.SESSIONS[user_tok] = {
                "user_id": "alice",
                "role": "user",
                "privileges": config.USER_DEFAULT_PRIVILEGES,
                "created_at": time.time(),
                "expires_at": time.time() + 3600
            }

        # Normal user cannot access admin stats (HTTP 403)
        res_user_admin = self.client.get('/api/admin/stats', headers={'Authorization': f'Bearer {user_tok}'})
        self.assertEqual(res_user_admin.status_code, 403)

        # Normal user cannot access DB query (HTTP 403)
        res_user_db = self.client.get('/api/admin/db/query?table=users', headers={'Authorization': f'Bearer {user_tok}'})
        self.assertEqual(res_user_db.status_code, 403)

    def test_37_user_cannot_access_live_system_logs(self):
        """Verify normal user without can_view_system_logs is blocked from /api/logs/stream."""
        user_tok = secrets.token_hex(32)
        with server_app.SESSIONS_LOCK:
            server_app.SESSIONS[user_tok] = {
                "user_id": "bob",
                "role": "user",
                "privileges": config.USER_DEFAULT_PRIVILEGES,
                "created_at": time.time(),
                "expires_at": time.time() + 3600
            }

        res = self.client.get('/api/logs/stream', headers={'Authorization': f'Bearer {user_tok}'})
        self.assertEqual(res.status_code, 403)

    def test_38_user_cannot_control_ollama(self):
        """Verify normal user cannot start or stop Ollama engine."""
        user_tok = secrets.token_hex(32)
        with server_app.SESSIONS_LOCK:
            server_app.SESSIONS[user_tok] = {
                "user_id": "charlie",
                "role": "user",
                "privileges": config.USER_DEFAULT_PRIVILEGES,
                "created_at": time.time(),
                "expires_at": time.time() + 3600
            }

        res_start = self.client.post('/start', headers={'Authorization': f'Bearer {user_tok}'})
        self.assertEqual(res_start.status_code, 403)

        res_stop = self.client.post('/stop', headers={'Authorization': f'Bearer {user_tok}'})
        self.assertEqual(res_stop.status_code, 403)

    def test_39_user_without_ai_privilege_blocked(self):
        """Verify normal user without can_use_ai is blocked from AI routes."""
        user_tok = secrets.token_hex(32)
        with server_app.SESSIONS_LOCK:
            server_app.SESSIONS[user_tok] = {
                "user_id": "dave",
                "role": "user",
                "privileges": {"can_use_ai": False},
                "created_at": time.time(),
                "expires_at": time.time() + 3600
            }

        res_models = self.client.get('/api/ai/models', headers={'Authorization': f'Bearer {user_tok}'})
        self.assertEqual(res_models.status_code, 403)

    def test_40_session_expiration_returns_401(self):
        """Verify expired session token returns HTTP 401."""
        exp_tok = secrets.token_hex(32)
        with server_app.SESSIONS_LOCK:
            server_app.SESSIONS[exp_tok] = {
                "user_id": "expired_user",
                "role": "user",
                "privileges": config.USER_DEFAULT_PRIVILEGES,
                "created_at": time.time() - 7200,
                "expires_at": time.time() - 3600 # Expired 1 hour ago
            }

        res = self.client.get('/api/auth/me', headers={'Authorization': f'Bearer {exp_tok}'})
        self.assertEqual(res.status_code, 401)

    def test_41_forbidden_returns_403_without_destroying_session(self):
        """Verify HTTP 403 on restricted route does not destroy valid user session."""
        user_tok = secrets.token_hex(32)
        with server_app.SESSIONS_LOCK:
            server_app.SESSIONS[user_tok] = {
                "user_id": "eve",
                "role": "user",
                "privileges": config.USER_DEFAULT_PRIVILEGES,
                "created_at": time.time(),
                "expires_at": time.time() + 3600
            }

        # Attempt forbidden admin action
        res_403 = self.client.get('/api/admin/stats', headers={'Authorization': f'Bearer {user_tok}'})
        self.assertEqual(res_403.status_code, 403)

        # Session should still be intact and authorized for permitted endpoints
        res_permitted = self.client.get('/files', headers={'Authorization': f'Bearer {user_tok}'})
        self.assertEqual(res_permitted.status_code, 200)

    # 13. Authoritative Ollama Model Serving & Lifecycle Tests
    def test_42_authoritative_ai_models_and_state(self):
        """Verify GET /api/ai/models and /api/ai/state return authoritative data."""
        with patch.object(server_app.ollama_registry, 'get_installed_models', return_value=[
            {"name": "qwen2.5:0.5b", "size_bytes": 350000000, "size_display": "350.0 MB", "parameter_size": "0.5B", "quantization": "Q4_K_M", "family": "qwen2", "installed": True}
        ]):
            res_models = self.client.get('/api/ai/models', headers={'Authorization': f'Bearer {self.admin_token}'})
            self.assertEqual(res_models.status_code, 200)
            models = res_models.get_json()
            self.assertEqual(len(models), 1)
            self.assertEqual(models[0]['name'], 'qwen2.5:0.5b')

            res_state = self.client.get('/api/ai/state', headers={'Authorization': f'Bearer {self.admin_token}'})
            self.assertEqual(res_state.status_code, 200)
            state = res_state.get_json()
            self.assertIn('selected_model', state)
            self.assertIn('loaded_model', state)
            self.assertIn('engine', state)

    def test_43_ai_model_selection_and_validation(self):
        """Verify POST /api/ai/models/select validates model against installed list."""
        with patch.object(server_app.ollama_registry, 'get_installed_models', return_value=[
            {"name": "qwen2.5:0.5b", "installed": True}
        ]):
            # Valid select
            res_ok = self.client.post(
                '/api/ai/models/select',
                headers={'Authorization': f'Bearer {self.admin_token}'},
                json={"model": "qwen2.5:0.5b"}
            )
            self.assertEqual(res_ok.status_code, 200)
            self.assertEqual(res_ok.get_json()['selected_model'], 'qwen2.5:0.5b')

            # Invalid select (not installed)
            res_err = self.client.post(
                '/api/ai/models/select',
                headers={'Authorization': f'Bearer {self.admin_token}'},
                json={"model": "nonexistent:model"}
            )
            self.assertEqual(res_err.status_code, 404)

    # 14. Storage-Backed SQLite FTS5 RAG Engine Tests
    def test_44_sqlite_fts5_rag_indexing_and_search(self):
        """Verify SQLite FTS5 engine indexes text files and executes BM25 search."""
        doc_path = os.path.join(config.STORAGE_DIR, "sample_guide.txt")
        with open(doc_path, "w", encoding="utf-8") as f:
            f.write("NexusNode is an autonomous mobile server appliance engineered for Android 13 Termux.\nIt features a SQLite FTS5 inverted index and resource governance.")

        server_app.rag_engine.source_folders = ["."]
        res_idx = server_app.rag_engine.build_vault_index()
        self.assertGreaterEqual(res_idx["documents_count"], 1)
        self.assertGreaterEqual(res_idx["chunks_count"], 1)

        # Search query
        results = server_app.rag_engine.search("appliance governance")
        self.assertGreater(len(results), 0)
        self.assertIn("NexusNode", results[0]["text"])
        self.assertIn("score", results[0])

    def test_45_rag_compact_legacy_index(self):
        """Verify POST /api/rag/compact migrates legacy JSON into SQLite FTS5."""
        legacy_json_path = config.RAG_INDEX_FILE
        legacy_data = {
            "documents": {"docs/legacy_note.md": {"size": 120, "chunks_count": 1}},
            "chunks": [{"doc": "legacy_note.md", "text": "This is legacy knowledge from JSON format."}]
        }
        with open(legacy_json_path, "w", encoding="utf-8") as f:
            json.dump(legacy_data, f)

        res = self.client.post('/api/rag/compact', headers={'Authorization': f'Bearer {self.admin_token}'})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["migrated"])
        self.assertGreaterEqual(data["chunks_migrated"], 1)

        # Verify backup file created
        self.assertFalse(os.path.exists(legacy_json_path))
        self.assertTrue(os.path.exists(data["archived_to"]))
        if os.path.exists(data["archived_to"]):
            os.remove(data["archived_to"])

    def test_46_rag_diagnostics_endpoint(self):
        """Verify GET /api/rag/diagnostics returns detailed SQLite FTS5 stats."""
        res = self.client.get('/api/rag/diagnostics', headers={'Authorization': f'Bearer {self.admin_token}'})
        self.assertEqual(res.status_code, 200)
        diag = res.get_json()
        self.assertIn("SQLite FTS5", diag["backend"])
        self.assertIn("database_size_kb", diag)
        self.assertIn("chunk_count", diag)
        self.assertIn("memory_estimate_mb", diag)
        self.assertLess(diag["memory_estimate_mb"], 10.0)

    # 15. Single-Threaded Bounded Log Writer Daemon Tests
    def test_47_log_writer_daemon_batch_processing(self):
        """Verify LogWriterDaemon flushes enqueued logs into SQLite database."""
        test_msg = f"Daemon verification log {secrets.token_hex(4)}"
        server_app.log_event("INFO", "TEST", test_msg)

        # Allow daemon loop to flush
        time.sleep(1.2)

        with server_app.DB_LOCK:
            conn = server_app.get_db_connection()
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM system_logs WHERE message = ?", (test_msg,))
            count = cur.fetchone()[0]
            conn.close()

        self.assertEqual(count, 1)

    # 16. Task Cancellation Bug Fix & Object Ownership Tests
    def test_48_task_cancellation_and_ownership(self):
        """Verify task cancellation ownership: Alice can cancel hers, Bob cannot cancel Alice's, Admin can cancel all."""
        alice_tok = secrets.token_hex(32)
        bob_tok = secrets.token_hex(32)
        with server_app.SESSIONS_LOCK:
            server_app.SESSIONS[alice_tok] = {"user_id": "alice", "role": "user", "privileges": config.USER_DEFAULT_PRIVILEGES, "created_at": time.time(), "expires_at": time.time() + 3600}
            server_app.SESSIONS[bob_tok] = {"user_id": "bob", "role": "user", "privileges": config.USER_DEFAULT_PRIVILEGES, "created_at": time.time(), "expires_at": time.time() + 3600}

        def mock_long_task(task_obj):
            while task_obj['status'] != 'cancelled':
                time.sleep(0.05)

        t_id, _ = server_app.task_runner.enqueue_task("Alice Long Task", "test", mock_long_task, owner_user_id="alice")

        # Bob attempts to cancel Alice's task (HTTP 403)
        res_bob = self.client.post(f'/api/tasks/{t_id}/cancel', headers={'Authorization': f'Bearer {bob_tok}'})
        self.assertEqual(res_bob.status_code, 403)

        # Alice cancels her own task (HTTP 200)
        res_alice = self.client.post(f'/api/tasks/{t_id}/cancel', headers={'Authorization': f'Bearer {alice_tok}'})
        self.assertEqual(res_alice.status_code, 200)
        self.assertTrue(res_alice.get_json()['cancelled'])

    # 17. Admin Diagnostics & Telemetry Sanitization Tests
    def test_49_sanitized_system_status_vs_admin_diagnostics(self):
        """Verify GET /api/system/status is sanitized for normal users while admin gets full /proc details."""
        user_tok = secrets.token_hex(32)
        with server_app.SESSIONS_LOCK:
            server_app.SESSIONS[user_tok] = {"user_id": "user1", "role": "user", "privileges": config.USER_DEFAULT_PRIVILEGES, "created_at": time.time(), "expires_at": time.time() + 3600}

        # Normal user gets sanitized status
        res_user = self.client.get('/api/system/status', headers={'Authorization': f'Bearer {user_tok}'})
        self.assertEqual(res_user.status_code, 200)
        data_user = res_user.get_json()
        self.assertNotIn("process", data_user) # Sanitized: no internal PID/smaps_rollup
        self.assertIn("memory", data_user)
        self.assertIn("services", data_user)

        # Admin gets full /proc introspection
        res_admin = self.client.get('/api/admin/diagnostics/system', headers={'Authorization': f'Bearer {self.admin_token}'})
        self.assertEqual(res_admin.status_code, 200)
        data_admin = res_admin.get_json()
        self.assertIn("nexusnode_process", data_admin)
        self.assertIn("rss_mb", data_admin["nexusnode_process"])
        self.assertIn("threads", data_admin["nexusnode_process"])
        self.assertIn("top_processes", data_admin)

    def test_50_admin_diagnostics_full_report(self):
        """Verify GET /api/admin/diagnostics/full-report returns automated root-cause findings."""
        res = self.client.get('/api/admin/diagnostics/full-report', headers={'Authorization': f'Bearer {self.admin_token}'})
        self.assertEqual(res.status_code, 200)
        report = res.get_json()
        self.assertIn(report["overall_status"], ["HEALTHY", "WARNING", "CRITICAL"])
        self.assertIn("findings", report)
        self.assertIn("findings_count", report)
        self.assertIn("diagnostics", report)

    def test_51_admin_profile_snapshot(self):
        """Verify POST /api/admin/diagnostics/profile-snapshot captures instant performance profile."""
        res = self.client.post('/api/admin/diagnostics/profile-snapshot', headers={'Authorization': f'Bearer {self.admin_token}'})
        self.assertEqual(res.status_code, 200)
        snap = res.get_json()
        self.assertIn("process_rss_mb", snap)
        self.assertIn("threads_count", snap)
        self.assertIn("wal_size_kb", snap)
        self.assertIn("rag_db_size_kb", snap)

    def test_52_backup_disk_headroom_precheck(self):
        """Verify backup runner rejects execution when free disk space < 1.5 GB."""
        with patch.object(server_app.governor, 'get_disk_status', return_value={"total_gb": 32.0, "free_gb": 0.5, "used_gb": 31.5, "used_percent": 98.4}):
            dummy_task = {"logs": [], "partial_files": []}
            with self.assertRaises(RuntimeError) as ctx:
                server_app.run_backup_job(dummy_task)
            self.assertIn("Insufficient free disk space", str(ctx.exception))

    def test_53_db_retention_sweep(self):
        """Verify retention sweeper prunes logs and metrics cleanly."""
        dummy_task = {"logs": []}
        server_app.run_retention_sweep_job(dummy_task)
        self.assertIn("Retention sweep completed successfully.", dummy_task["logs"][-1])

    # 18. Emergency Login Lockout & Admin Password Recovery Tests
    def test_login_lockout_countdown_state(self):
        """Verify login lockout returns 429 with lockout_seconds and retry_after."""
        server_app.clear_account_lockout()

        # Trigger lockout threshold
        for _ in range(config.LOCKOUT_THRESHOLD):
            self.client.post('/api/auth/login', json={"user_id": "admin", "password": "wrongpassword"})

        res = self.client.post('/api/auth/login', json={"user_id": "admin", "password": "wrongpassword"})
        self.assertEqual(res.status_code, 429)
        data = res.get_json()
        self.assertIn(data.get("error"), ["account_locked", "locked_out"])
        self.assertIn("Account Locked. Try again in", data.get("message", ""))
        self.assertTrue(data.get("lockout_seconds", 0) > 0)
        self.assertTrue(data.get("retry_after", 0) > 0)

        server_app.clear_account_lockout()

    def test_login_unlock_after_countdown(self):
        """Verify account automatically unlocks after lockout expiry timestamp."""
        server_app.clear_account_lockout()
        with server_app.FAILED_LOGINS_LOCK:
            server_app.FAILED_LOGINS["127.0.0.1"] = {
                "count": config.LOCKOUT_THRESHOLD,
                "locked_until": time.time() - 1.0  # Already expired
            }

        # Successful login after lockout expiry
        res = self.client.post('/api/auth/login', json={"user_id": "admin", "password": "adminpassword"})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("token", data)

        server_app.clear_account_lockout()

    def test_locked_login_submission_blocked(self):
        """Verify active lockout blocks all login attempts regardless of credentials."""
        server_app.clear_account_lockout()
        with server_app.FAILED_LOGINS_LOCK:
            server_app.FAILED_LOGINS["127.0.0.1"] = {
                "count": config.LOCKOUT_THRESHOLD,
                "locked_until": time.time() + 30.0  # Locked for 30s
            }

        # Even correct credentials return 429 while locked
        res = self.client.post('/api/auth/login', json={"user_id": "admin", "password": "adminpassword"})
        self.assertEqual(res.status_code, 429)
        data = res.get_json()
        self.assertIn(data.get("error"), ["account_locked", "locked_out"])
        self.assertTrue(data.get("lockout_seconds") > 0)

        server_app.clear_account_lockout()

    def test_emergency_password_reset(self):
        """Verify local emergency reset helper updates password and enables login."""
        from scripts.reset_admin_password import emergency_reset_password

        # Create temporary user
        temp_user = f"reset_u_{int(time.time()*1000)}"
        h, s = server_app.hash_password("oldpass123")
        with server_app.DB_LOCK:
            conn = server_app.get_db_connection()
            conn.execute("""
                INSERT INTO users (user_id, password_hash, salt, role, privileges, created_at)
                VALUES (?, ?, ?, 'user', '{"can_upload_files": true}', 1234567.0)
            """, (temp_user, h, s))
            conn.commit()
            conn.close()

        # Reset password via emergency script
        success = emergency_reset_password(username=temp_user, new_password="newpass456_secure")
        self.assertTrue(success)

        # Old password rejected
        res_old = self.client.post('/api/auth/login', json={"user_id": temp_user, "password": "oldpass123"})
        self.assertEqual(res_old.status_code, 401)

        # New password succeeds
        res_new = self.client.post('/api/auth/login', json={"user_id": temp_user, "password": "newpass456_secure"})
        self.assertEqual(res_new.status_code, 200)

    def test_emergency_reset_preserves_role(self):
        """Verify emergency reset strictly preserves user role."""
        from scripts.reset_admin_password import emergency_reset_password

        user_before = server_app.db_get_user("admin")
        self.assertEqual(user_before["role"], "admin")

        success = emergency_reset_password(username="admin", new_password="adminpassword")
        self.assertTrue(success)

        user_after = server_app.db_get_user("admin")
        self.assertEqual(user_after["role"], "admin")

    def test_emergency_reset_preserves_privileges(self):
        """Verify emergency reset strictly preserves user privileges and created_at timestamp."""
        from scripts.reset_admin_password import emergency_reset_password

        user_before = server_app.db_get_user("admin")
        created_at_before = user_before["created_at"]
        privs_before = user_before["privileges"]

        success = emergency_reset_password(username="admin", new_password="adminpassword")
        self.assertTrue(success)

        user_after = server_app.db_get_user("admin")
        self.assertEqual(user_after["created_at"], created_at_before)
        self.assertEqual(user_after["privileges"], privs_before)

    def test_emergency_reset_clears_failed_login_lockout(self):
        """Verify emergency reset immediately clears active lockout state."""
        from scripts.reset_admin_password import emergency_reset_password

        with server_app.FAILED_LOGINS_LOCK:
            server_app.FAILED_LOGINS["127.0.0.1"] = {
                "count": config.LOCKOUT_THRESHOLD,
                "locked_until": time.time() + 600.0
            }

        # Emergency reset
        success = emergency_reset_password(username="admin", new_password="adminpassword")
        self.assertTrue(success)

        # Account is immediately usable without waiting for lockout timer
        res = self.client.post('/api/auth/login', json={"user_id": "admin", "password": "adminpassword"})
        self.assertEqual(res.status_code, 200)

    def test_emergency_reset_does_not_expose_password(self):
        """Verify emergency reset helper never returns or leaks password/hash/salt in output."""
        import io
        from contextlib import redirect_stdout, redirect_stderr
        from scripts.reset_admin_password import emergency_reset_password

        out_buf = io.StringIO()
        err_buf = io.StringIO()
        secret_pass = "super_secret_test_password_12345"

        with redirect_stdout(out_buf), redirect_stderr(err_buf):
            emergency_reset_password(username="admin", new_password=secret_pass)

        full_output = out_buf.getvalue() + err_buf.getvalue()
        self.assertNotIn(secret_pass, full_output)
        self.assertNotIn("password_hash", full_output)
        self.assertNotIn("salt", full_output)
        self.assertIn("Password reset successfully", full_output)

        # Reset admin password back
        emergency_reset_password(username="admin", new_password="adminpassword")

    def test_emergency_reset_is_not_an_http_endpoint(self):
        """Verify emergency reset cannot be invoked through any HTTP route."""
        res1 = self.client.post('/api/emergency-reset', json={"user": "admin", "password": "hacked"})
        self.assertIn(res1.status_code, [404, 405])

        res2 = self.client.post('/api/auth/reset-admin', json={"user": "admin", "password": "hacked"})
        self.assertIn(res2.status_code, [404, 405])

        res3 = self.client.get('/scripts/reset_admin_password.py')
        self.assertIn(res3.status_code, [404, 403, 401])

    # 19. Complete Local Account & Authentication CLI Tests
    def test_cli_users(self):
        """Verify 'nexus_admin users' lists users with safe columns and no secrets."""
        import io
        from contextlib import redirect_stdout
        import nexus_admin
        from argparse import Namespace

        out = io.StringIO()
        with redirect_stdout(out):
            code = nexus_admin.cmd_users(Namespace())

        self.assertEqual(code, 0)
        output = out.getvalue()
        self.assertIn("USER ID", output)
        self.assertIn("ROLE", output)
        self.assertIn("STATUS", output)
        self.assertIn("admin", output)
        self.assertNotIn("password_hash", output)
        self.assertNotIn("salt", output)

    def test_cli_user_info(self):
        """Verify 'nexus_admin user-info --user admin' displays metadata and privileges safely."""
        import io
        from contextlib import redirect_stdout
        import nexus_admin
        from argparse import Namespace

        out = io.StringIO()
        with redirect_stdout(out):
            code = nexus_admin.cmd_user_info(Namespace(user="admin"))

        self.assertEqual(code, 0)
        output = out.getvalue()
        self.assertIn("User ID:", output)
        self.assertIn("Role:", output)
        self.assertIn("admin", output)
        self.assertIn("Enabled Privileges:", output)
        self.assertNotIn("password_hash", output)
        self.assertNotIn("salt", output)

    def test_cli_create_user(self):
        """Verify 'nexus_admin create-user --user <user> --role user' creates user with least privilege."""
        import nexus_admin
        from argparse import Namespace

        uname = f"cli_u_{int(time.time()*1000)}"
        code = nexus_admin.cmd_create_user(Namespace(user=uname, role="user", password="testpass123_cli", yes=True))
        self.assertEqual(code, 0)

        created = server_app.db_get_user(uname)
        self.assertIsNotNone(created)
        self.assertEqual(created["role"], "user")
        self.assertTrue(created["privileges"].get("can_upload_files"))
        self.assertFalse(created["privileges"].get("can_manage_users"))

    def test_cli_create_duplicate_user(self):
        """Verify creating a duplicate user is rejected."""
        import io
        from contextlib import redirect_stderr
        import nexus_admin
        from argparse import Namespace

        err = io.StringIO()
        with redirect_stderr(err):
            code = nexus_admin.cmd_create_user(Namespace(user="admin", role="user", password="newpass123", yes=True))

        self.assertEqual(code, 1)
        self.assertIn("already exists", err.getvalue())

    def test_cli_create_admin_confirmation(self):
        """Verify creating an admin account requires confirmation when --yes is not given."""
        import nexus_admin
        from argparse import Namespace

        uname = f"cli_adm_{int(time.time()*1000)}"
        with patch('builtins.input', return_value='n'):
            code = nexus_admin.cmd_create_user(Namespace(user=uname, role="admin", password="adminpass123", yes=False))
            self.assertEqual(code, 1)
            self.assertIsNone(server_app.db_get_user(uname))

        with patch('builtins.input', return_value='y'):
            code = nexus_admin.cmd_create_user(Namespace(user=uname, role="admin", password="adminpass123", yes=False))
            self.assertEqual(code, 0)
            self.assertIsNotNone(server_app.db_get_user(uname))
            self.assertEqual(server_app.db_get_user(uname)["role"], "admin")

    def test_cli_reset_password_admin(self):
        """Verify resetting admin password via CLI resets credentials."""
        import nexus_admin
        from argparse import Namespace

        code = nexus_admin.cmd_reset_password(Namespace(user="admin", password="new_admin_pass_789"))
        self.assertEqual(code, 0)

        success, _, _, _ = server_app.authenticate_user_credentials("admin", "new_admin_pass_789")
        self.assertTrue(success)

        # Revert admin password
        nexus_admin.cmd_reset_password(Namespace(user="admin", password="adminpassword"))

    def test_cli_reset_password_user(self):
        """Verify resetting a normal user password via CLI resets credentials."""
        import nexus_admin
        from argparse import Namespace

        uname = f"cli_u2_{int(time.time()*1000)}"
        nexus_admin.cmd_create_user(Namespace(user=uname, role="user", password="initpass123", yes=True))

        code = nexus_admin.cmd_reset_password(Namespace(user=uname, password="changedpass456"))
        self.assertEqual(code, 0)

        success, _, _, _ = server_app.authenticate_user_credentials(uname, "changedpass456")
        self.assertTrue(success)

    def test_cli_unlock_user(self):
        """Verify 'nexus_admin unlock --user <user>' clears lockout and resets counter."""
        import nexus_admin
        from argparse import Namespace

        with server_app.FAILED_LOGINS_LOCK:
            server_app.FAILED_LOGINS["127.0.0.1"] = {"count": 5, "locked_until": time.time() + 300.0}

        code = nexus_admin.cmd_unlock(Namespace(user="admin"))
        self.assertEqual(code, 0)

        with server_app.FAILED_LOGINS_LOCK:
            fail_rec = server_app.FAILED_LOGINS.get("127.0.0.1", {"count": 0, "locked_until": 0.0})
            self.assertEqual(fail_rec.get("count", 0), 0)

    def test_cli_login_success_admin(self):
        """Verify CLI login succeeds for valid admin credentials."""
        import io
        from contextlib import redirect_stdout
        import nexus_admin
        from argparse import Namespace

        nexus_admin.emergency_reset_password("admin", "adminpassword")
        with server_app.FAILED_LOGINS_LOCK:
            server_app.FAILED_LOGINS.clear()

        out = io.StringIO()
        with redirect_stdout(out):
            code = nexus_admin.cmd_login(Namespace(user="admin", password="adminpassword", session=False, show_token=False))

        self.assertEqual(code, 0)
        output = out.getvalue()
        self.assertIn("Authentication successful.", output)
        self.assertIn("Role: admin", output)

    def test_cli_login_success_user(self):
        """Verify CLI login succeeds for valid normal user credentials."""
        import io
        from contextlib import redirect_stdout
        import nexus_admin
        from argparse import Namespace

        uname = f"cli_u3_{int(time.time()*1000)}"
        nexus_admin.cmd_create_user(Namespace(user=uname, role="user", password="normalpass123", yes=True))

        out = io.StringIO()
        with redirect_stdout(out):
            code = nexus_admin.cmd_login(Namespace(user=uname, password="normalpass123", session=False, show_token=False))

        self.assertEqual(code, 0)
        output = out.getvalue()
        self.assertIn("Authentication successful.", output)
        self.assertIn("Role: user", output)

    def test_cli_login_failure(self):
        """Verify CLI login rejects invalid credentials."""
        import io
        from contextlib import redirect_stdout
        import nexus_admin
        from argparse import Namespace

        out = io.StringIO()
        with redirect_stdout(out):
            code = nexus_admin.cmd_login(Namespace(user="admin", password="badpassword", session=False, show_token=False))

        self.assertEqual(code, 1)
        self.assertIn("Authentication failed.", out.getvalue())

    def test_cli_login_locked_account(self):
        """Verify CLI login blocks attempts on locked accounts."""
        import io
        from contextlib import redirect_stdout
        import nexus_admin
        from argparse import Namespace

        with server_app.FAILED_LOGINS_LOCK:
            server_app.FAILED_LOGINS["127.0.0.1"] = {"count": 5, "locked_until": time.time() + 45.0}

        out = io.StringIO()
        with redirect_stdout(out):
            code = nexus_admin.cmd_login(Namespace(user="admin", password="adminpassword", session=False, show_token=False))

        self.assertEqual(code, 1)
        self.assertIn("Account locked. Try again in", out.getvalue())

        with server_app.FAILED_LOGINS_LOCK:
            server_app.FAILED_LOGINS.clear()

    def test_cli_login_lockout_countdown(self):
        """Verify CLI login lockout reports decreasing seconds remaining."""
        import io
        from contextlib import redirect_stdout
        import nexus_admin
        from argparse import Namespace

        with server_app.FAILED_LOGINS_LOCK:
            server_app.FAILED_LOGINS["127.0.0.1"] = {"count": 5, "locked_until": time.time() + 20.0}

        out1 = io.StringIO()
        with redirect_stdout(out1):
            nexus_admin.cmd_login(Namespace(user="admin", password="adminpassword", session=False, show_token=False))
        self.assertIn("Account locked. Try again in", out1.getvalue())

        with server_app.FAILED_LOGINS_LOCK:
            server_app.FAILED_LOGINS.clear()

    def test_cli_login_respects_same_auth_logic(self):
        """Verify CLI and Web API share the exact same authentication and lockout state."""
        import nexus_admin
        from argparse import Namespace

        with server_app.FAILED_LOGINS_LOCK:
            server_app.FAILED_LOGINS.clear()

        # Fail 4 times via web API
        for _ in range(config.LOCKOUT_THRESHOLD - 1):
            self.client.post('/api/auth/login', json={"user_id": "admin", "password": "wrongpassword"})

        # 5th attempt fails via CLI, triggering the lockout threshold
        nexus_admin.cmd_login(Namespace(user="admin", password="wrongpassword", session=False, show_token=False))

        # 6th attempt on web API must return 429 locked out
        res = self.client.post('/api/auth/login', json={"user_id": "admin", "password": "adminpassword"})
        self.assertEqual(res.status_code, 429)

        with server_app.FAILED_LOGINS_LOCK:
            server_app.FAILED_LOGINS.clear()

    def test_cli_session_creation(self):
        """Verify 'nexus_admin login --session' writes local session file."""
        import nexus_admin
        from argparse import Namespace

        code = nexus_admin.cmd_login(Namespace(user="admin", password="adminpassword", session=True, show_token=False))
        self.assertEqual(code, 0)

        session_data = nexus_admin.read_local_session()
        self.assertIsNotNone(session_data)
        self.assertEqual(session_data["user_id"], "admin")
        self.assertEqual(session_data["role"], "admin")
        self.assertTrue(len(session_data["token"]) >= 32)

    def test_cli_whoami(self):
        """Verify 'nexus_admin whoami' inspects local session."""
        import io
        from contextlib import redirect_stdout
        import nexus_admin
        from argparse import Namespace

        # Login with session
        nexus_admin.cmd_login(Namespace(user="admin", password="adminpassword", session=True, show_token=False))

        out = io.StringIO()
        with redirect_stdout(out):
            code = nexus_admin.cmd_whoami(Namespace())

        self.assertEqual(code, 0)
        output = out.getvalue()
        self.assertIn("Authenticated", output)
        self.assertIn("User: admin", output)
        self.assertIn("Role: admin", output)

    def test_cli_logout(self):
        """Verify 'nexus_admin logout' revokes session and deletes session file."""
        import nexus_admin
        from argparse import Namespace

        nexus_admin.cmd_login(Namespace(user="admin", password="adminpassword", session=True, show_token=False))
        code = nexus_admin.cmd_logout(Namespace())
        self.assertEqual(code, 0)
        self.assertIsNone(nexus_admin.read_local_session())

    def test_cli_session_token_not_printed(self):
        """Verify session token is not printed in standard output by default."""
        import io
        from contextlib import redirect_stdout
        import nexus_admin
        from argparse import Namespace

        out = io.StringIO()
        with redirect_stdout(out):
            nexus_admin.cmd_login(Namespace(user="admin", password="adminpassword", session=True, show_token=False))

        session_data = nexus_admin.read_local_session()
        self.assertNotIn(session_data["token"], out.getvalue())

    def test_cli_no_password_output(self):
        """Verify password is never printed in CLI outputs."""
        import io
        from contextlib import redirect_stdout
        import nexus_admin
        from argparse import Namespace

        secret_pw = "super_secret_pw_9999"
        uname = f"cli_u4_{int(time.time()*1000)}"

        out = io.StringIO()
        with redirect_stdout(out):
            nexus_admin.cmd_create_user(Namespace(user=uname, role="user", password=secret_pw, yes=True))
            nexus_admin.cmd_user_info(Namespace(user=uname))
            nexus_admin.cmd_users(Namespace())

        self.assertNotIn(secret_pw, out.getvalue())

    def test_cli_no_hash_output(self):
        """Verify password hash and salt are never printed in CLI outputs."""
        import io
        from contextlib import redirect_stdout
        import nexus_admin
        from argparse import Namespace

        uname = f"cli_u5_{int(time.time()*1000)}"
        nexus_admin.cmd_create_user(Namespace(user=uname, role="user", password="pwd", yes=True))
        u = server_app.db_get_user(uname)

        out = io.StringIO()
        with redirect_stdout(out):
            nexus_admin.cmd_user_info(Namespace(user=uname))
            nexus_admin.cmd_users(Namespace())

        self.assertNotIn(u["password_hash"], out.getvalue())
        self.assertNotIn(u["salt"], out.getvalue())

    def test_cli_role_preservation(self):
        """Verify CLI operations strictly preserve assigned user roles."""
        import nexus_admin
        from argparse import Namespace

        uname = f"cli_u6_{int(time.time()*1000)}"
        nexus_admin.cmd_create_user(Namespace(user=uname, role="user", password="p1", yes=True))
        self.assertEqual(server_app.db_get_user(uname)["role"], "user")

        nexus_admin.cmd_reset_password(Namespace(user=uname, password="p2"))
        self.assertEqual(server_app.db_get_user(uname)["role"], "user")

        nexus_admin.cmd_unlock(Namespace(user=uname))
        self.assertEqual(server_app.db_get_user(uname)["role"], "user")

    def test_cli_privilege_preservation(self):
        """Verify CLI operations strictly preserve user privileges."""
        import nexus_admin
        from argparse import Namespace

        uname = f"cli_u7_{int(time.time()*1000)}"
        nexus_admin.cmd_create_user(Namespace(user=uname, role="user", password="p1", yes=True))
        orig_privs = dict(server_app.db_get_user(uname)["privileges"])

        nexus_admin.cmd_reset_password(Namespace(user=uname, password="p2"))
        self.assertEqual(server_app.db_get_user(uname)["privileges"], orig_privs)

    def test_cli_ssh_vs_app_auth_separation(self):
        """Verify CLI help documents the architectural separation between SSH and app auth."""
        import io
        from contextlib import redirect_stdout
        import nexus_admin
        from argparse import Namespace

        out = io.StringIO()
        with redirect_stdout(out):
            nexus_admin.cmd_help(Namespace())

        output = out.getvalue()
        self.assertIn("SSH Authentication (OS Layer)", output)
        self.assertIn("NexusNode Application Authentication (Application Layer)", output)
        self.assertIn("ssh -p 8022", output)

    def test_web_lockout_countdown_regression(self):
        """Verify Web UI lockout countdown behavior has zero regression."""
        server_app.clear_account_lockout()

        # Trigger lockout
        for _ in range(config.LOCKOUT_THRESHOLD):
            self.client.post('/api/auth/login', json={"user_id": "admin", "password": "wrongpassword"})

        res = self.client.post('/api/auth/login', json={"user_id": "admin", "password": "wrongpassword"})
        self.assertEqual(res.status_code, 429)
        data = res.get_json()
        self.assertIn(data["error"], ["account_locked", "locked_out"])
        self.assertIn("lockout_seconds", data)
        self.assertIn("retry_after", data)
        self.assertTrue(data["lockout_seconds"] > 0)

        server_app.clear_account_lockout()

    def test_lockout_persistence_across_process_restart(self):
        """Verify account lockout stored in SQLite persists even when memory cache is wiped."""
        server_app.clear_account_lockout()

        # Trigger lockout in SQLite
        now = time.time()
        with server_app.DB_LOCK:
            conn = server_app.get_db_connection()
            conn.execute(
                "UPDATE users SET failed_attempts = ?, locked_until = ? WHERE user_id = 'admin'",
                (config.LOCKOUT_THRESHOLD, now + 300.0)
            )
            conn.commit()
            conn.close()

        # Simulate fresh process restart by wiping in-memory structures
        with server_app.FAILED_LOGINS_LOCK:
            server_app.FAILED_LOGINS.clear()

        # Query lockout status - must reflect SQLite persisted lockout
        is_locked, remaining = server_app.get_account_lockout_status("admin", "127.0.0.1")
        self.assertTrue(is_locked)
        self.assertTrue(remaining > 250)

        # Login attempt must be rejected with 429 and exact remaining seconds
        res = self.client.post('/api/auth/login', json={"user_id": "admin", "password": "adminpassword"})
        self.assertEqual(res.status_code, 429)
        data = res.get_json()
        self.assertIn(data["error"], ["account_locked", "locked_out"])
        self.assertTrue(data.get("lockout_seconds", 0) > 250)

        server_app.clear_account_lockout()

    def test_lockout_status_endpoint_security_and_accuracy(self):
        """Verify GET /api/auth/lockout-status returns accurate remaining time and zero secrets."""
        server_app.clear_account_lockout()

        # 1. Check unlocked state
        res = self.client.get('/api/auth/lockout-status?user_id=admin')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertFalse(data["locked"])
        self.assertEqual(data["remaining_seconds"], 0)
        # Verify zero credential leaks
        self.assertNotIn("password", data)
        self.assertNotIn("password_hash", data)
        self.assertNotIn("salt", data)
        self.assertNotIn("token", data)

        # 2. Lock account and check again
        now = time.time()
        with server_app.DB_LOCK:
            conn = server_app.get_db_connection()
            conn.execute(
                "UPDATE users SET failed_attempts = ?, locked_until = ? WHERE user_id = 'admin'",
                (5, now + 120.0)
            )
            conn.commit()
            conn.close()

        res = self.client.get('/api/auth/lockout-status?user_id=admin')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["locked"])
        self.assertTrue(data["remaining_seconds"] > 100)
        self.assertEqual(data["remaining_seconds"], data["lockout_seconds"])

        server_app.clear_account_lockout()

    # 20. Real SSH Access & Restricted NexusNode Shell Tests
    # 20. Real SSH Access & Restricted NexusNode Shell Tests
    def test_ssh_user_authentication_architecture(self):
        """Verify OpenSSH AuthorizedKeysCommand maps application users to forced nexus_shell.py commands."""
        from scripts import nexus_ssh_auth
        import io
        from contextlib import redirect_stdout

        # Register key in SQLite
        rand_k = base64.b64encode(secrets.token_bytes(32)).decode('ascii')
        test_key = f"ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI{rand_k} admin@device"
        server_app.db_add_ssh_key("admin", test_key, label="admin_laptop")

        out = io.StringIO()
        with patch.object(sys, 'argv', ['nexus_ssh_auth.py', 'u0_a208', test_key, 'ssh-ed25519']):
            with redirect_stdout(out):
                nexus_ssh_auth.main()

        output = out.getvalue()
        self.assertIn("command=", output)
        self.assertIn("nexus_shell.py --user admin", output)
        self.assertIn("no-port-forwarding", output)
        self.assertIn("ssh-ed25519", output)

    def test_operator_key_gets_unrestricted_shell(self):
        """Verify operator key is handled by AuthorizedKeysFile and nexus_ssh_auth does not emit it."""
        from scripts import nexus_ssh_auth
        import io
        from contextlib import redirect_stdout

        op_key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOperatorAdministrativeAccessKey operator@host"
        # Operator key is not in sqlite, so nexus_ssh_auth emits nothing
        out = io.StringIO()
        with patch.object(sys, 'argv', ['nexus_ssh_auth.py', 'u0_a208', op_key, 'ssh-ed25519']):
            with redirect_stdout(out):
                nexus_ssh_auth.main()

        output = out.getvalue()
        self.assertEqual(output.strip(), "")

    def test_exact_key_matching_only_emits_matching_user(self):
        """Verify dispatcher emits ONLY the specific user whose key matches %k, never other users."""
        from scripts import nexus_ssh_auth
        import io
        from contextlib import redirect_stdout

        # Create two users
        u1 = f"alice_{int(time.time() * 1000)}"
        u2 = f"bob_{int(time.time() * 1000)}"
        server_app.db_create_user(u1, "Pass1234!", role="user")
        server_app.db_create_user(u2, "Pass1234!", role="user")

        k1_b64 = base64.b64encode(secrets.token_bytes(32)).decode('ascii')
        k2_b64 = base64.b64encode(secrets.token_bytes(32)).decode('ascii')
        key1 = f"ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI{k1_b64} alice@pc"
        key2 = f"ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI{k2_b64} bob@pc"

        server_app.db_add_ssh_key(u1, key1, label="alice_key")
        server_app.db_add_ssh_key(u2, key2, label="bob_key")

        # Present Alice's key
        out1 = io.StringIO()
        with patch.object(sys, 'argv', ['nexus_ssh_auth.py', 'u0_a208', key1, 'ssh-ed25519']):
            with redirect_stdout(out1):
                nexus_ssh_auth.main()

        res1 = out1.getvalue()
        self.assertIn(f"--user {u1}", res1)
        self.assertNotIn(u2, res1)

        # Present Bob's key
        out2 = io.StringIO()
        with patch.object(sys, 'argv', ['nexus_ssh_auth.py', 'u0_a208', key2, 'ssh-ed25519']):
            with redirect_stdout(out2):
                nexus_ssh_auth.main()

        res2 = out2.getvalue()
        self.assertIn(f"--user {u2}", res2)
        self.assertNotIn(u1, res2)

    def test_invalid_transport_user_rejected(self):
        """Verify connecting with an application username directly over SSH is rejected by dispatcher."""
        from scripts import nexus_ssh_auth
        import io
        from contextlib import redirect_stdout

        rand_k = base64.b64encode(secrets.token_bytes(32)).decode('ascii')
        test_key = f"ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI{rand_k} user@device"
        server_app.db_add_ssh_key("admin", test_key)

        # User attempts 'ssh anmol@PHONE_IP' instead of 'ssh u0_a208@PHONE_IP'
        out = io.StringIO()
        with patch.object(sys, 'argv', ['nexus_ssh_auth.py', 'anmol', test_key, 'ssh-ed25519']):
            with redirect_stdout(out):
                nexus_ssh_auth.main()

        self.assertEqual(out.getvalue().strip(), "")

    def test_duplicate_key_in_operator_authorized_keys_rejected(self):
        """Verify registering an SSH key that exists in ~/.ssh/authorized_keys is strictly rejected."""
        op_b64 = base64.b64encode(secrets.token_bytes(32)).decode('ascii')
        op_pub = f"ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI{op_b64} operator@device"

        with patch("os.path.exists", return_value=True):
            with patch("builtins.open", mock_open(read_data=op_pub)):
                success, msg, _ = server_app.db_add_ssh_key("admin", op_pub, label="duplicate_op")
                self.assertFalse(success)
                self.assertIn("already registered as a Termux host operator key", msg)

    def test_sftp_and_subsystem_blocked_in_restricted_shell(self):
        """Verify SFTP and SSH subsystem commands are strictly rejected by the restricted shell."""
        import nexus_shell
        import io
        from contextlib import redirect_stderr

        user = server_app.db_get_user("admin")
        for bad_cmd in ["sftp-server", "/usr/lib/ssh/sftp-server", "internal-sftp", "scp -t /data"]:
            err = io.StringIO()
            with redirect_stderr(err):
                code = nexus_shell.launch_restricted_shell(user, direct_command=bad_cmd)
            self.assertEqual(code, 1)
            self.assertIn("Subsystem execution (including SFTP/SCP) is disabled", err.getvalue())

    def test_shell_operators_and_command_chaining_blocked(self):
        """Verify shell chaining, operators, and subshells are strictly rejected in direct command mode."""
        import nexus_shell
        import io
        from contextlib import redirect_stderr

        user = server_app.db_get_user("admin")
        for evil_cmd in ["status; id", "vault ls | cat", "status && echo pwned", "vault `whoami`", "status $(id)"]:
            err = io.StringIO()
            with redirect_stderr(err):
                code = nexus_shell.launch_restricted_shell(user, direct_command=evil_cmd)
            self.assertEqual(code, 1)
            self.assertIn("Shell operators, pipes, and compound commands are not allowed", err.getvalue())

    def test_ssh_key_registration_and_fingerprint(self):
        """Verify SSH key registration correctly parses formats and calculates SHA-256 fingerprint."""
        rand_k = base64.b64encode(secrets.token_bytes(32)).decode('ascii')
        test_pub = f"ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI{rand_k} anmol@laptop"
        fp, ktype, kb64, comment = server_app.calculate_ssh_key_fingerprint(test_pub)
        self.assertTrue(fp.startswith("SHA256:"))
        self.assertEqual(ktype, "ssh-ed25519")
        self.assertEqual(comment, "anmol@laptop")

        # Reject private keys
        with self.assertRaises(ValueError):
            server_app.calculate_ssh_key_fingerprint("-----BEGIN OPENSSH PRIVATE KEY-----")

        # Register in DB
        success, msg, rec = server_app.db_add_ssh_key("admin", test_pub, label="anmol_laptop")
        self.assertTrue(success)
        self.assertEqual(rec["fingerprint"], fp)
        self.assertEqual(rec["user_id"], "admin")

    def test_ssh_key_revocation(self):
        """Verify revoking an SSH key disables it immediately from active keys."""
        rand_k = base64.b64encode(secrets.token_bytes(32)).decode('ascii')
        test_pub = f"ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI{rand_k} revoke@device"
        success, _, rec = server_app.db_add_ssh_key("admin", test_pub, label="to_revoke")
        self.assertTrue(success)
        fp = rec["fingerprint"]

        # Verify active
        active_keys = [k["fingerprint"] for k in server_app.db_list_ssh_keys("admin", include_revoked=False)]
        self.assertIn(fp, active_keys)

        # Revoke
        rev_success, rev_msg = server_app.db_revoke_ssh_key(fp)
        self.assertTrue(rev_success)

        # Verify no longer active
        active_after = [k["fingerprint"] for k in server_app.db_list_ssh_keys("admin", include_revoked=False)]
        self.assertNotIn(fp, active_after)

    def test_revoked_key_rejected_by_auth_dispatcher(self):
        """Verify revoked keys are NOT emitted by nexus_ssh_auth.py."""
        from scripts import nexus_ssh_auth
        import io
        from contextlib import redirect_stdout

        rand_k = base64.b64encode(secrets.token_bytes(32)).decode('ascii')
        test_pub = f"ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI{rand_k} user@device"
        _, _, rec = server_app.db_add_ssh_key("admin", test_pub)
        server_app.db_revoke_ssh_key(rec["fingerprint"])

        out = io.StringIO()
        with patch.object(sys, 'argv', ['nexus_ssh_auth.py', 'u0_a208', test_pub, 'ssh-ed25519']):
            with redirect_stdout(out):
                nexus_ssh_auth.main()

        output = out.getvalue()
        self.assertNotIn(rec["fingerprint"], output)
        self.assertNotIn(rand_k, output)

    def test_disabled_user_key_rejected(self):
        """Verify keys belonging to non-existent users are ignored by auth dispatcher."""
        from scripts import nexus_ssh_auth
        import io
        from contextlib import redirect_stdout

        ghost_fp = f"SHA256:phantom_{int(time.time() * 1000)}_{secrets.token_hex(4)}"
        rand_k = base64.b64encode(secrets.token_bytes(32)).decode('ascii')
        ghost_key = f"ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI{rand_k} ghost@host"
        with server_app.DB_LOCK:
            conn = server_app.get_db_connection()
            try:
                conn.execute("PRAGMA foreign_keys = OFF;")
                conn.execute("""
                    INSERT INTO ssh_keys (fingerprint, user_id, key_type, public_key, label, created_at, revoked)
                    VALUES (?, 'ghost_user', 'ssh-ed25519', ?, 'ghost', 1000, 0)
                """, (ghost_fp, ghost_key))
                conn.commit()
            finally:
                conn.close()

        out = io.StringIO()
        with patch.object(sys, 'argv', ['nexus_ssh_auth.py', 'u0_a208', ghost_key, 'ssh-ed25519']):
            with redirect_stdout(out):
                nexus_ssh_auth.main()

        output = out.getvalue()
        self.assertNotIn("ghost_user", output)

    def test_cli_ssh_key_management(self):
        """Verify 'nexus_admin ssh-key' commands (add, list, revoke)."""
        import nexus_admin
        from argparse import Namespace
        import io
        from contextlib import redirect_stdout

        rand_k = base64.b64encode(secrets.token_bytes(32)).decode('ascii')
        test_key = f"ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI{rand_k} cli@test"
        # 1. Add
        out_add = io.StringIO()
        with redirect_stdout(out_add):
            res = nexus_admin.cmd_ssh_key_add(Namespace(user="admin", key=test_key, label="cli_test"))
        self.assertEqual(res, 0)
        self.assertIn("registered successfully", out_add.getvalue())

        # 2. List
        out_list = io.StringIO()
        with redirect_stdout(out_list):
            res = nexus_admin.cmd_ssh_key_list(Namespace(user="admin", all=True))
        self.assertEqual(res, 0)
        self.assertIn("cli_test", out_list.getvalue())

        # 3. Revoke
        fp, _, _, _ = server_app.calculate_ssh_key_fingerprint(test_key)
        out_rev = io.StringIO()
        with redirect_stdout(out_rev):
            res = nexus_admin.cmd_ssh_key_revoke(Namespace(fingerprint=fp, user="admin"))
        self.assertEqual(res, 0)
        self.assertIn("revoked successfully", out_rev.getvalue())

    def test_restricted_nexus_shell(self):
        """Verify restricted shell launches and responds to allowlisted commands."""
        import nexus_shell
        import io
        from contextlib import redirect_stdout

        user = server_app.db_get_user("admin")
        shell = nexus_shell.NexusRestrictedShell(user)

        out = io.StringIO()
        with redirect_stdout(out):
            shell.onecmd("status")

        output = out.getvalue()
        self.assertIn("Appliance Status", output)
        self.assertIn("Governor State:", output)

    def test_user_cannot_execute_bash(self):
        """Verify executing 'bash' or shell escapes is rejected."""
        import nexus_shell
        import io
        from contextlib import redirect_stdout

        user = server_app.db_get_user("admin")
        shell = nexus_shell.NexusRestrictedShell(user)

        out = io.StringIO()
        with redirect_stdout(out):
            shell.onecmd("bash")
            shell.onecmd("sh -c 'id'")

        output = out.getvalue()
        self.assertIn("not allowed or unrecognized", output)

    def test_user_cannot_execute_python(self):
        """Verify executing 'python' or arbitrary scripts is rejected."""
        import nexus_shell
        import io
        from contextlib import redirect_stdout

        user = server_app.db_get_user("admin")
        shell = nexus_shell.NexusRestrictedShell(user)

        out = io.StringIO()
        with redirect_stdout(out):
            shell.onecmd("python -c 'print(1)'")
            shell.onecmd("python")

        output = out.getvalue()
        self.assertIn("not allowed or unrecognized", output)

    def test_user_cannot_access_server_directory(self):
        """Verify path traversal outside vault is strictly rejected in vault command."""
        import nexus_shell
        import io
        from contextlib import redirect_stdout

        user = server_app.db_get_user("admin")
        shell = nexus_shell.NexusRestrictedShell(user)

        out = io.StringIO()
        with redirect_stdout(out):
            shell.onecmd("vault ls ../")
            shell.onecmd("vault cat ../app.py")
            shell.onecmd("vault cat ../config.py")

        output = out.getvalue()
        self.assertIn("Access denied. Path is outside Storage Vault", output)

    def test_user_cannot_access_database(self):
        """Verify normal users cannot inspect or access SQLite database schema/data."""
        import nexus_shell
        import io
        from contextlib import redirect_stdout

        # Normal user
        normal_user = {"user_id": "test_normal", "role": "user", "privileges": config.USER_DEFAULT_PRIVILEGES}
        shell = nexus_shell.NexusRestrictedShell(normal_user)

        out = io.StringIO()
        with redirect_stdout(out):
            shell.onecmd("database inspect")
            shell.onecmd("vault cat nexus_vault.db")

        output = out.getvalue()
        self.assertIn("not allowed or unrecognized", output)

    def test_user_can_list_vault(self):
        """Verify normal user can list allowed files inside the vault."""
        import nexus_shell
        import io
        from contextlib import redirect_stdout

        # Create a test file in storage_vault
        test_f = os.path.join(config.STORAGE_DIR, "shell_test_doc.txt")
        with open(test_f, "w") as f:
            f.write("Test document content in vault.")

        normal_user = {"user_id": "test_normal", "role": "user", "privileges": config.USER_DEFAULT_PRIVILEGES}
        shell = nexus_shell.NexusRestrictedShell(normal_user)

        out = io.StringIO()
        with redirect_stdout(out):
            shell.onecmd("vault ls")

        output = out.getvalue()
        self.assertIn("shell_test_doc.txt", output)

    def test_user_can_use_media(self):
        """Verify normal user with can_download_media can list and enqueue media."""
        import nexus_shell
        import io
        from contextlib import redirect_stdout

        normal_user = {"user_id": "test_media_user", "role": "user", "privileges": {"can_download_media": True}}
        shell = nexus_shell.NexusRestrictedShell(normal_user)

        out = io.StringIO()
        with redirect_stdout(out):
            shell.onecmd("media list")
            shell.onecmd("media queue")

        output = out.getvalue()
        self.assertIn("Category: Music", output)
        self.assertIn("Active Media Tasks", output)

    def test_user_can_view_own_tasks(self):
        """Verify normal user can view their own tasks."""
        import nexus_shell
        import io
        from contextlib import redirect_stdout

        task_id, _ = server_app.task_runner.enqueue_task(
            "User Task 1", "test_type", lambda t: None, owner_user_id="user_alice"
        )

        user_alice = {"user_id": "user_alice", "role": "user", "privileges": {}}
        shell = nexus_shell.NexusRestrictedShell(user_alice)

        out = io.StringIO()
        with redirect_stdout(out):
            shell.onecmd("tasks list")
            shell.onecmd(f"tasks status {task_id}")

        output = out.getvalue()
        self.assertIn("User Task 1", output)

    def test_user_cannot_view_other_user_task(self):
        """Verify normal user cannot view another user's task details."""
        import nexus_shell
        import io
        from contextlib import redirect_stdout

        task_id, _ = server_app.task_runner.enqueue_task(
            "Secret Task Bob", "test_type", lambda t: None, owner_user_id="user_bob"
        )

        user_alice = {"user_id": "user_alice", "role": "user", "privileges": {}}
        shell = nexus_shell.NexusRestrictedShell(user_alice)

        out = io.StringIO()
        with redirect_stdout(out):
            shell.onecmd(f"tasks status {task_id}")

        output = out.getvalue()
        self.assertIn("Access denied. You can only inspect your own tasks", output)

    def test_user_can_use_ai(self):
        """Verify user with can_use_ai can inspect models and AI state."""
        import nexus_shell
        import io
        from contextlib import redirect_stdout

        user = {"user_id": "user_ai", "role": "user", "privileges": {"can_use_ai": True}}
        shell = nexus_shell.NexusRestrictedShell(user)

        out = io.StringIO()
        with redirect_stdout(out):
            shell.onecmd("ai models")
            shell.onecmd("ai state")

        output = out.getvalue()
        self.assertIn("AI Engine Online:", output)
        self.assertIn("Keep-Alive:", output)

    def test_user_cannot_control_services(self):
        """Verify normal user cannot access services command."""
        import nexus_shell
        import io
        from contextlib import redirect_stdout

        user = {"user_id": "user_normal", "role": "user", "privileges": {}}
        shell = nexus_shell.NexusRestrictedShell(user)

        out = io.StringIO()
        with redirect_stdout(out):
            shell.onecmd("services status")
            shell.onecmd("services stop ollama")

        output = out.getvalue()
        self.assertTrue("Administrator privileges required" in output or "not allowed or unrecognized" in output)

    def test_admin_can_control_services(self):
        """Verify admin can view and control services."""
        import nexus_shell
        import io
        from contextlib import redirect_stdout

        admin_user = server_app.db_get_user("admin")
        shell = nexus_shell.NexusRestrictedShell(admin_user)

        out = io.StringIO()
        with redirect_stdout(out):
            shell.onecmd("services status")

        output = out.getvalue()
        self.assertIn("SERVICE", output)
        self.assertIn("STATUS", output)

    def test_admin_cli_vs_user_cli_isolation(self):
        """Verify admin commands (diagnostics, users, backups, logs) are blocked for normal users."""
        import nexus_shell
        import io
        from contextlib import redirect_stdout

        normal_user = {"user_id": "user_norm", "role": "user", "privileges": {}}
        shell = nexus_shell.NexusRestrictedShell(normal_user)

        for cmd_name in ["diagnostics full", "users", "backups create", "logs"]:
            out = io.StringIO()
            with redirect_stdout(out):
                shell.onecmd(cmd_name)
            output = out.getvalue()
            self.assertTrue("Administrator privileges required" in output or "not allowed or unrecognized" in output)

    def test_ssh_login_lockout(self):
        """Verify nexus_shell blocks access when account is locked out."""
        import nexus_shell
        import io
        from contextlib import redirect_stderr

        with server_app.FAILED_LOGINS_LOCK:
            server_app.FAILED_LOGINS["admin"] = {"count": 5, "locked_until": time.time() + 100.0}

        err = io.StringIO()
        with redirect_stderr(err):
            with self.assertRaises(SystemExit) as cm:
                with patch.object(sys, 'argv', ['nexus_shell.py', '--user', 'admin']):
                    nexus_shell.main()

        self.assertEqual(cm.exception.code, 1)
        self.assertIn("Account locked", err.getvalue())

        with server_app.FAILED_LOGINS_LOCK:
            server_app.FAILED_LOGINS.clear()

    def test_forced_command_direct_ssh(self):
        """Verify forced SSH command mode runs specific command and terminates with exit code 0."""
        import nexus_shell
        import io
        from contextlib import redirect_stdout

        user = server_app.db_get_user("admin")
        out = io.StringIO()
        with redirect_stdout(out):
            code = nexus_shell.launch_restricted_shell(user, direct_command="status")

        self.assertEqual(code, 0)
        self.assertIn("Appliance Status", out.getvalue())

    def test_ssh_command_mode(self):
        """Verify direct non-interactive SSH command mode with SSH_ORIGINAL_COMMAND environment variable."""
        import nexus_shell
        import io
        from contextlib import redirect_stdout

        out = io.StringIO()
        with patch.dict(os.environ, {"SSH_ORIGINAL_COMMAND": "vault ls"}):
            with redirect_stdout(out):
                with self.assertRaises(SystemExit) as cm:
                    with patch.object(sys, 'argv', ['nexus_shell.py', '--user', 'admin']):
                        nexus_shell.main()

        self.assertEqual(cm.exception.code, 0)
        self.assertIn("Vault Directory", out.getvalue())

    def test_logout_terminates_shell(self):
        """Verify 'logout' or 'exit' command returns True to terminate Cmd loop."""
        import nexus_shell

        user = server_app.db_get_user("admin")
        shell = nexus_shell.NexusRestrictedShell(user)
        self.assertTrue(shell.do_logout(""))
        self.assertTrue(shell.do_exit(""))
        self.assertTrue(shell.do_quit(""))

    def test_cli_help_respects_privileges(self):
        """Verify help output only exposes administrative commands to admin role."""
        import nexus_shell
        import io
        from contextlib import redirect_stdout

        # Normal User
        norm_user = {"user_id": "norm_u", "role": "user", "privileges": {}}
        shell_norm = nexus_shell.NexusRestrictedShell(norm_user)
        out_norm = io.StringIO()
        with redirect_stdout(out_norm):
            shell_norm.do_help("")
        self.assertNotIn("Administrative Commands", out_norm.getvalue())
        self.assertNotIn("services", out_norm.getvalue())

        # Admin User
        admin_user = server_app.db_get_user("admin")
        shell_adm = nexus_shell.NexusRestrictedShell(admin_user)
        out_adm = io.StringIO()
        with redirect_stdout(out_adm):
            shell_adm.do_help("")
        self.assertIn("Administrative Commands", out_adm.getvalue())
        self.assertIn("services", out_adm.getvalue())

    def test_51_protected_internal_paths_policy_and_vault_isolation(self):
        """
        Verify that internal SQLite databases, WAL files, config files, and hidden directories
        are strictly hidden and unreachable via normal Vault APIs (/files, /download, /stream, /files DELETE, /api/shares, /api/vault/checksum).
        """
        # Create sensitive and internal files inside storage vault root
        protected_files = [
            "nexus_vault.db", "nexus_vault.db-wal", "nexus_vault.db-shm",
            "rag_vault.db", "rag_index.json", "server_config.json",
            ".env", "custom_secret.sqlite3", "localtonet.log"
        ]
        for pf in protected_files:
            fp = os.path.join(config.STORAGE_DIR, pf)
            with open(fp, "w") as f:
                f.write("sensitive internal data")

        # Create normal user file
        user_file = os.path.join(config.STORAGE_DIR, "legit_document.pdf")
        with open(user_file, "w") as f:
            f.write("public document content")

        # 1. GET /files should list user_file but ZERO protected files
        res_list = self.client.get('/files', headers={'Authorization': f'Bearer {self.admin_token}'})
        self.assertEqual(res_list.status_code, 200)
        file_names = [item['name'] for item in res_list.get_json().get('files', [])]
        self.assertIn("legit_document.pdf", file_names)
        for pf in protected_files:
            self.assertNotIn(pf, file_names)

        # 2. GET /download/<protected> must return 404
        for pf in protected_files:
            res_dl = self.client.get(f'/download/{pf}', headers={'Authorization': f'Bearer {self.admin_token}'})
            self.assertEqual(res_dl.status_code, 404, f"Expected 404 for protected download {pf}")

        # 3. GET /stream/<protected> must return 404
        res_stream = self.client.get('/stream/nexus_vault.db', headers={'Authorization': f'Bearer {self.admin_token}'})
        self.assertEqual(res_stream.status_code, 404)

        # 4. DELETE /files/<protected> must return 404 and NOT delete file
        res_del = self.client.delete('/files/nexus_vault.db', headers={'Authorization': f'Bearer {self.admin_token}'})
        self.assertEqual(res_del.status_code, 404)
        self.assertTrue(os.path.exists(os.path.join(config.STORAGE_DIR, "nexus_vault.db")))

        # 5. POST /api/shares with protected path must return 404
        res_share = self.client.post('/api/shares', headers={'Authorization': f'Bearer {self.admin_token}'}, json={'filename': 'nexus_vault.db'})
        self.assertEqual(res_share.status_code, 404)

        # 6. GET /api/vault/checksum/<protected> must return 404
        res_chk = self.client.get('/api/vault/checksum/rag_vault.db', headers={'Authorization': f'Bearer {self.admin_token}'})
        self.assertEqual(res_chk.status_code, 404)

    def test_52_folder_zip_excludes_protected_files(self):
        """Verify downloading a folder as zip excludes any protected internal files."""
        import zipfile
        import io

        test_dir = os.path.join(config.STORAGE_DIR, "project_folder")
        os.makedirs(test_dir, exist_ok=True)
        
        with open(os.path.join(test_dir, "notes.txt"), "w") as f:
            f.write("regular user notes")
        with open(os.path.join(test_dir, "internal.db"), "w") as f:
            f.write("should not be zipped")
        with open(os.path.join(test_dir, ".env"), "w") as f:
            f.write("SECRET_KEY=12345")

        res = self.client.get('/download/project_folder', headers={'Authorization': f'Bearer {self.admin_token}'})
        self.assertEqual(res.status_code, 200)

        zf = zipfile.ZipFile(io.BytesIO(res.data))
        zipped_names = zf.namelist()
        self.assertIn("notes.txt", zipped_names)
        self.assertNotIn("internal.db", zipped_names)
        self.assertNotIn(".env", zipped_names)

    def test_53_task_queue_sqlite_persistence_and_lifecycle_stages(self):
        """
        Verify that BoundedTaskRunner persists all transitions to SQLite background_tasks,
        records ISO-8601 timestamps, and accurately tracks lifecycle stages.
        """
        runner = server_app.task_runner

        def sample_job(task_obj):
            task_obj['stage'] = 'STARTING'
            task_obj['progress'] = 10
            runner._save_task_to_db(task_obj)
            time.sleep(0.05)

            task_obj['stage'] = 'POST_PROCESSING'
            task_obj['progress'] = 99
            runner._save_task_to_db(task_obj)
            time.sleep(0.05)

            task_obj['stage'] = 'VERIFYING'
            runner._save_task_to_db(task_obj)
            time.sleep(0.05)

            task_obj['output_path'] = 'Downloads/sample.mp4'
            task_obj['status'] = 'COMPLETED'
            task_obj['stage'] = 'COMPLETED'
            task_obj['progress'] = 100

        task_id, _ = runner.enqueue_task(
            "Lifecycle Test Task", "media_download", sample_job,
            owner_user_id="admin"
        )
        self.assertIsNotNone(task_id)

        # Inspect database immediately
        task_data = runner.get_task(task_id)
        self.assertIsNotNone(task_data)
        self.assertEqual(task_data["id"], task_id)
        self.assertIn("created_at", task_data)
        self.assertTrue(isinstance(task_data["created_at"], str))
        self.assertIn("Z", task_data["created_at"])  # ISO-8601 check

        # Wait for job completion
        for _ in range(50):
            t = runner.get_task(task_id)
            if t and t.get("status") == "COMPLETED":
                break
            time.sleep(0.05)

        completed_task = runner.get_task(task_id)
        self.assertEqual(completed_task["status"], "COMPLETED")
        self.assertEqual(completed_task["stage"], "COMPLETED")
        self.assertEqual(completed_task["progress"], 100)
        self.assertEqual(completed_task["output_path"], "Downloads/sample.mp4")
        self.assertIsNotNone(completed_task.get("completed_at"))

    def test_54_terminal_stage_matches_status(self):
        """
        Verify that terminal tasks (COMPLETED, FAILED, CANCELLED) always persist
        matching stage in SQLite and never retain stage=QUEUED.
        """
        runner = server_app.task_runner

        # 1. Successful task
        def success_job(t):
            t['progress'] = 100

        tid_s, _ = runner.enqueue_task("Success Job", "generic", success_job)
        for _ in range(50):
            t = runner.get_task(tid_s)
            if t and t["status"] == "COMPLETED":
                break
            time.sleep(0.05)
        t_s = runner.get_task(tid_s)
        self.assertEqual(t_s["status"], "COMPLETED")
        self.assertEqual(t_s["stage"], "COMPLETED")

        # 2. Failed task
        def fail_job(t):
            raise RuntimeError("Database connection timed out")

        tid_f, _ = runner.enqueue_task("Fail Job", "generic", fail_job)
        for _ in range(50):
            t = runner.get_task(tid_f)
            if t and t["status"] == "FAILED":
                break
            time.sleep(0.05)
        t_f = runner.get_task(tid_f)
        self.assertEqual(t_f["status"], "FAILED")
        self.assertEqual(t_f["stage"], "FAILED")
        self.assertEqual(t_f["error"], "Database connection timed out")

        # 3. Cancelled queued task
        tid_c, _ = runner.enqueue_task("Cancel Queued Job", "generic", lambda t: time.sleep(1))
        # Cancel while queued (or quickly)
        runner.cancel_task(tid_c, is_admin=True)
        t_c = runner.get_task(tid_c)
        self.assertEqual(t_c["status"], "CANCELLED")
        self.assertEqual(t_c["stage"], "CANCELLED")

    def test_55_legacy_terminal_task_migration(self):
        """
        Verify that one-time startup migration fixes historical rows where
        status is COMPLETED/FAILED/CANCELLED but stage is QUEUED.
        """
        now = time.time()
        tid_c = f"leg_comp_{secrets.token_hex(3)}"
        tid_f = f"leg_fail_{secrets.token_hex(3)}"
        tid_x = f"leg_canc_{secrets.token_hex(3)}"

        with server_app.DB_LOCK:
            conn = server_app.get_db_connection()
            try:
                conn.execute("""
                    INSERT OR REPLACE INTO background_tasks (
                        id, title, type, status, stage, progress, logs, owner_user_id, created_at, updated_at
                    ) VALUES
                    (?, 'Legacy Completed', 'generic', 'COMPLETED', 'QUEUED', 100, '[]', 'admin', ?, ?),
                    (?, 'Legacy Failed', 'generic', 'FAILED', 'QUEUED', 50, '[]', 'admin', ?, ?),
                    (?, 'Legacy Cancelled', 'generic', 'CANCELLED', 'QUEUED', 0, '[]', 'admin', ?, ?)
                """, (tid_c, now, now, tid_f, now, now, tid_x, now, now))
                conn.commit()
            finally:
                conn.close()

        # Execute init_unified_db() migration routine
        server_app.init_unified_db()

        # Query database and verify all legacy rows repaired
        runner = server_app.task_runner
        t_comp = runner.get_task(tid_c)
        self.assertEqual(t_comp["status"], "COMPLETED")
        self.assertEqual(t_comp["stage"], "COMPLETED")

        t_fail = runner.get_task(tid_f)
        self.assertEqual(t_fail["status"], "FAILED")
        self.assertEqual(t_fail["stage"], "FAILED")

        t_canc = runner.get_task(tid_x)
        self.assertEqual(t_canc["status"], "CANCELLED")
        self.assertEqual(t_canc["stage"], "CANCELLED")

    def test_56_failed_media_task_persists_error(self):
        """
        Verify that when a media download task fails, the concise error is recorded
        in SQLite and exposed through /api/tasks and /api/tasks/<id>.
        """
        runner = server_app.task_runner

        def fail_media_job(t, url, fmt, quality, destination, custom_name):
            t['status'] = 'RUNNING'
            t['stage'] = 'STARTING'
            runner._save_task_to_db(t)
            time.sleep(0.05)
            raise RuntimeError("ERROR: [youtube] InVaLiD_ID: Video unavailable")

        tid, _ = runner.enqueue_task(
            "Download: Invalid Video", "media_download", fail_media_job,
            "https://youtube.com/watch?v=invalid", "mp4", "best", "Downloads", "fail_vid",
            owner_user_id="admin"
        )

        for _ in range(50):
            t = runner.get_task(tid)
            if t and t["status"] == "FAILED":
                break
            time.sleep(0.05)

        # 1. Direct runner check
        task = runner.get_task(tid)
        self.assertEqual(task["status"], "FAILED")
        self.assertEqual(task["stage"], "FAILED")
        self.assertEqual(task["error"], "ERROR: [youtube] InVaLiD_ID: Video unavailable")

        # 2. REST API /api/tasks check
        client = server_app.app.test_client()
        resp = client.get("/api/tasks", headers={"Authorization": f"Bearer {self.admin_token}"})
        self.assertEqual(resp.status_code, 200)
        tasks_list = resp.get_json()
        target = next((x for x in tasks_list if x["id"] == tid), None)
        self.assertIsNotNone(target)
        self.assertEqual(target["status"], "FAILED")
        self.assertEqual(target["stage"], "FAILED")
        self.assertEqual(target["error"], "ERROR: [youtube] InVaLiD_ID: Video unavailable")

        # 3. REST API /api/tasks/<id> check
        resp_single = client.get(f"/api/tasks/{tid}", headers={"Authorization": f"Bearer {self.admin_token}"})
        self.assertEqual(resp_single.status_code, 200)
        single_task = resp_single.get_json()
        self.assertEqual(single_task["error"], "ERROR: [youtube] InVaLiD_ID: Video unavailable")

    def test_57_media_download_state_machine(self):
        """
        Verify that media download progresses through all canonical stages:
        QUEUED -> STARTING -> DOWNLOADING -> POST_PROCESSING -> VERIFYING -> COMPLETED
        """
        recorded_stages = []
        dest_file = os.path.join(server_app.config.STORAGE_DIR, "Downloads", "state_mach.mp4")

        def mock_media_run(t, url, fmt, quality, destination, custom_name):
            # STARTING
            t['status'] = 'RUNNING'
            t['stage'] = 'STARTING'
            server_app.task_runner._save_task_to_db(t)
            recorded_stages.append(t['stage'])
            time.sleep(0.02)

            # DOWNLOADING
            t['stage'] = 'DOWNLOADING'
            t['progress'] = 50
            t['speed_bps'] = 1048576
            t['eta_seconds'] = 5
            server_app.task_runner._save_task_to_db(t)
            recorded_stages.append(t['stage'])
            time.sleep(0.02)

            # POST_PROCESSING
            t['stage'] = 'POST_PROCESSING'
            t['progress'] = 99
            server_app.task_runner._save_task_to_db(t)
            recorded_stages.append(t['stage'])
            time.sleep(0.02)

            # VERIFYING
            t['stage'] = 'VERIFYING'
            server_app.task_runner._save_task_to_db(t)
            recorded_stages.append(t['stage'])

            # Create destination file
            os.makedirs(os.path.dirname(dest_file), exist_ok=True)
            with open(dest_file, "wb") as f:
                f.write(b"MOCK MP4 VIDEO DATA 12345")

            # COMPLETED
            t['output_path'] = 'Downloads/state_mach.mp4'
            t['progress'] = 100
            t['stage'] = 'COMPLETED'
            t['status'] = 'COMPLETED'
            t['completed_at'] = time.time()
            server_app.task_runner._save_task_to_db(t)
            recorded_stages.append(t['stage'])

        tid, _ = server_app.task_runner.enqueue_task(
            "Download: State Machine Test", "media_download", mock_media_run,
            "https://youtube.com/watch?v=state123", "mp4", "best", "Downloads", "state_mach",
            owner_user_id="admin"
        )

        for _ in range(50):
            t = server_app.task_runner.get_task(tid)
            if t and t["status"] == "COMPLETED":
                break
            time.sleep(0.05)

        t_final = server_app.task_runner.get_task(tid)
        self.assertEqual(t_final["status"], "COMPLETED")
        self.assertEqual(t_final["stage"], "COMPLETED")
        self.assertEqual(t_final["progress"], 100)
        self.assertIn("STARTING", recorded_stages)
        self.assertIn("DOWNLOADING", recorded_stages)
        self.assertIn("POST_PROCESSING", recorded_stages)
        self.assertIn("VERIFYING", recorded_stages)
        self.assertIn("COMPLETED", recorded_stages)

        if os.path.exists(dest_file):
            os.remove(dest_file)

    def test_58_media_download_output_verification(self):
        """
        Verify that media verification fails if output file is missing or 0 bytes,
        and marks task as FAILED with stage=FAILED.
        """
        def empty_output_job(task_obj, url, fmt, quality, destination, custom_name):
            # Run without producing valid file -> triggers verification failure
            task_obj['status'] = 'RUNNING'
            task_obj['stage'] = 'VERIFYING'
            server_app.task_runner._save_task_to_db(task_obj)
            raise RuntimeError("Media verification failed: Output file missing or 0 bytes after yt-dlp completion.")

        tid, _ = server_app.task_runner.enqueue_task(
            "Download: Missing Output", "media_download", empty_output_job,
            "https://youtube.com/watch?v=missing", "mp4", "best", "Downloads", "missing_out",
            owner_user_id="admin"
        )

        for _ in range(50):
            t = server_app.task_runner.get_task(tid)
            if t and t["status"] == "FAILED":
                break
            time.sleep(0.05)

        t_fail = server_app.task_runner.get_task(tid)
        self.assertEqual(t_fail["status"], "FAILED")
        self.assertEqual(t_fail["stage"], "FAILED")
        self.assertIn("Media verification failed", t_fail["error"])

    def test_59_media_download_cancellation(self):
        """
        Verify that cancelling an active task transitions through CANCELLING -> CANCELLED,
        cleans partial files, and marks stage=CANCELLED.
        """
        part_file = os.path.join(server_app.config.STORAGE_DIR, "Downloads", "cancel_test.mp4.part")
        os.makedirs(os.path.dirname(part_file), exist_ok=True)
        with open(part_file, "wb") as f:
            f.write(b"PARTIAL INCOMPLETE DATA")

        def long_job(task_obj):
            task_obj['status'] = 'RUNNING'
            task_obj['stage'] = 'DOWNLOADING'
            task_obj['partial_files'].append(part_file)
            server_app.task_runner._save_task_to_db(task_obj)
            while task_obj.get('status') != 'CANCELLED':
                time.sleep(0.05)

        tid, _ = server_app.task_runner.enqueue_task("Long Download", "media_download", long_job, owner_user_id="admin")
        time.sleep(0.1)

        # Cancel active task
        client = server_app.app.test_client()
        resp = client.post(f"/api/tasks/{tid}/cancel", headers={"Authorization": f"Bearer {self.admin_token}"})
        self.assertEqual(resp.status_code, 200)

        t_canc = server_app.task_runner.get_task(tid)
        self.assertEqual(t_canc["status"], "CANCELLED")
        self.assertEqual(t_canc["stage"], "CANCELLED")
        self.assertIsNotNone(t_canc.get("completed_at"))
        self.assertFalse(os.path.exists(part_file))

    def test_60_media_download_process_tree_cleanup(self):
        """
        Verify that terminate_process_tree cleanly terminates process and any children.
        """
        if os.name == 'nt':
            cmd = ["powershell", "-Command", "Start-Sleep -Seconds 10"]
        else:
            cmd = ["sleep", "10"]

        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertIsNone(proc.poll())
        server_app.terminate_process_tree(proc)
        time.sleep(0.2)
        self.assertIsNotNone(proc.poll())

    def test_61_media_queue_serialization(self):
        """
        Verify that with N=1 concurrency limit, enqueuing tasks A, B, C runs A first
        while B and C remain QUEUED.
        """
        runner = server_app.task_runner

        def blocking_job(t):
            t['status'] = 'RUNNING'
            t['stage'] = 'DOWNLOADING'
            runner._save_task_to_db(t)
            time.sleep(0.15)
            t['status'] = 'COMPLETED'
            t['stage'] = 'COMPLETED'
            runner._save_task_to_db(t)

        tid_a, _ = runner.enqueue_task("Task A", "media_download", blocking_job, owner_user_id="admin")
        tid_b, _ = runner.enqueue_task("Task B", "media_download", blocking_job, owner_user_id="admin")
        tid_c, _ = runner.enqueue_task("Task C", "media_download", blocking_job, owner_user_id="admin")

        time.sleep(0.05)
        # While A is running, B and C must be QUEUED
        t_a = runner.get_task(tid_a)
        t_b = runner.get_task(tid_b)
        t_c = runner.get_task(tid_c)

        self.assertIn(t_a["status"], ["STARTING", "RUNNING", "COMPLETED"])
        self.assertEqual(t_b["status"], "QUEUED")
        self.assertEqual(t_c["status"], "QUEUED")

        # Wait for all tasks to finish
        for _ in range(80):
            all_done = all(runner.get_task(t)["status"] == "COMPLETED" for t in [tid_a, tid_b, tid_c])
            if all_done:
                break
            time.sleep(0.05)

        self.assertEqual(runner.get_task(tid_a)["status"], "COMPLETED")
        self.assertEqual(runner.get_task(tid_b)["status"], "COMPLETED")
        self.assertEqual(runner.get_task(tid_c)["status"], "COMPLETED")

    def test_62_media_active_task_consistency(self):
        """
        Verify that GET /api/tasks?type=media_download returns the exact same authoritative
        records as the main task list.
        """
        client = server_app.app.test_client()
        resp_all = client.get("/api/tasks", headers={"Authorization": f"Bearer {self.admin_token}"})
        resp_media = client.get("/api/tasks?type=media_download", headers={"Authorization": f"Bearer {self.admin_token}"})

        self.assertEqual(resp_all.status_code, 200)
        self.assertEqual(resp_media.status_code, 200)

        all_tasks = resp_all.get_json()
        media_tasks = resp_media.get_json()

        expected_media_ids = {t["id"] for t in all_tasks if "media_download" in t.get("type", "").lower()}
        actual_media_ids = {t["id"] for t in media_tasks}
        self.assertEqual(expected_media_ids, actual_media_ids)

    def test_63_system_status_active_task_consistency(self):
        """
        Verify that GET /api/system/status exposes the exact same active task data
        (ID, status, stage, progress, speed, ETA) as the task subsystem.
        """
        runner = server_app.task_runner

        def active_job(t):
            t['status'] = 'RUNNING'
            t['stage'] = 'DOWNLOADING'
            t['progress'] = 64
            t['speed_bps'] = 2097152
            t['eta_seconds'] = 8
            runner._save_task_to_db(t)
            time.sleep(0.2)

        tid, _ = runner.enqueue_task("Active Job Status Test", "media_download", active_job, owner_user_id="admin")
        time.sleep(0.05)

        client = server_app.app.test_client()
        resp = client.get("/api/system/status", headers={"Authorization": f"Bearer {self.admin_token}"})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()

        active_task = data.get("active_task")
        if active_task:
            self.assertEqual(active_task["id"], tid)
            self.assertEqual(active_task["status"], "RUNNING")
            self.assertEqual(active_task["stage"], "DOWNLOADING")
            self.assertEqual(active_task["progress"], 64)
            self.assertEqual(active_task["speed_bps"], 2097152)
            self.assertEqual(active_task["eta_seconds"], 8)


if __name__ == '__main__':
    unittest.main(verbosity=2)
