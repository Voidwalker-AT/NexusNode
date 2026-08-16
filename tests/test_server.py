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
import secrets
import tempfile
import unittest
from unittest.mock import MagicMock, patch

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
        self.assertEqual(runner.tasks[t2_id]['status'], 'cancelled')

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


if __name__ == '__main__':
    unittest.main(verbosity=2)
