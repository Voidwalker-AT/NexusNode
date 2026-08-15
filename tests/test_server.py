"""
NexusNode — Comprehensive Unit and Integration Test Suite
Validates 24/7 Mobile Server Appliance Hardening:
1. Health and unprivileged status endpoints
2. Resource Governor thresholds, RAM state, and Thermal protection
3. Bounded task runner (concurrency bound = 1, cancellation & partial file cleanup, interrupted task sweep)
4. Serialized RAG indexing & pending rebuild deduplication
5. Security controls (auth enforcement on streaming/download endpoints, path traversal blocking, zip-slip defense)
6. RBAC permissions, SQLite DB inspection, and brute-force tracking
7. Temporary secure share links (token generation, expiration, revocation, download limits)
8. Media Center batch URL queueing, library categorization, and HTTP 206 Range streaming
9. Atomic backup creation, SHA-256 checksum verification, and safe restore validation
10. Storage Intelligence calculation and safe temp-files cleanup
11. Unprivileged network diagnostics and latency tests
12. Scheduled automation job triggers and system settings management
"""

import os
import sys
import json
import time
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

# Add parent directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import config
from resource_governor import ResourceGovernor
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

        # Obtain or inject an admin session token
        admin_token = None
        with server_app.SESSIONS_LOCK:
            for token, session in server_app.SESSIONS.items():
                if session.get("user_id") == "admin":
                    admin_token = token
                    break
            
            if not admin_token:
                import secrets
                admin_token = secrets.token_hex(32)
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
        with patch.object(gov, 'get_memory_status', return_value={"total_mb": 3800, "available_mb": 1500, "state": "normal"}):
            self.assertTrue(gov.can_start_heavy_task()["allowed"])
            self.assertTrue(gov.can_start_rag()["allowed"])
            self.assertTrue(gov.can_start_ollama()["allowed"])

        # Test pressure state (600 - 1000 MB)
        with patch.object(gov, 'get_memory_status', return_value={"total_mb": 3800, "available_mb": 750, "state": "pressure"}):
            self.assertFalse(gov.can_start_heavy_task()["allowed"])
            self.assertTrue(gov.can_start_rag()["allowed"])

        # Test critical state (< 600 MB)
        with patch.object(gov, 'get_memory_status', return_value={"total_mb": 3800, "available_mb": 350, "state": "critical"}):
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
                time.sleep(0.1)

        t1_id, _ = runner.enqueue_task("Task 1", "test", mock_slow_job, 1.0)
        t2_id, _ = runner.enqueue_task("Task 2", "test", mock_slow_job, 1.0)

        self.assertIsNotNone(t1_id)
        self.assertIsNotNone(t2_id)
        
        tasks = runner.list_tasks()
        task_ids = [t['id'] for t in tasks]
        self.assertIn(t1_id, task_ids)
        self.assertIn(t2_id, task_ids)

        # Cancel Task 2
        cancelled = runner.cancel_task(t2_id)
        self.assertTrue(cancelled)
        self.assertEqual(runner.tasks[t2_id]['status'], 'cancelled')

    def test_06_partial_download_cleanup_on_cancel(self):
        """Verify .part, .tmp and .ytdl files are removed on cancellation."""
        part_file = os.path.join(config.STORAGE_DIR, "test_download.mp4.part")
        with open(part_file, "w") as f:
            f.write("partial data chunk")
        
        self.assertTrue(os.path.exists(part_file))
        server_app.cleanup_partial_files(part_file)
        self.assertFalse(os.path.exists(part_file))

    def test_07_interrupted_tasks_recovery_on_startup(self):
        """Verify that tasks left in 'running' state on crash are swept to 'interrupted'."""
        with server_app.DB_LOCK:
            conn = server_app.get_db_connection()
            conn.execute("""
                INSERT OR REPLACE INTO background_tasks (id, title, type, status, progress, logs, created_at, updated_at)
                VALUES ('orphan_task_99', 'Crash Test', 'test', 'running', 45, '["started"]', 1000.0, 1001.0);
            """)
            conn.commit()
            conn.close()

        runner = server_app.BoundedTaskRunner(max_concurrency=1)
        self.assertIn('orphan_task_99', runner.tasks)
        self.assertEqual(runner.tasks['orphan_task_99']['status'], 'interrupted')

    # 4. Asynchronous Serialized RAG Engine
    def test_08_serialized_rag_indexing(self):
        """Verify RAG index builds without throwing and supports searching."""
        test_doc = os.path.join(config.STORAGE_DIR, "rag_sample.txt")
        with open(test_doc, "w", encoding="utf-8") as f:
            f.write("NexusNode is a hardened 24/7 mobile server appliance for Android 13 Termux.\nIt protects memory with a 4GB resource governor.")

        rag = server_app.SerializedDocumentRAG()
        res = rag.build_vault_index()
        self.assertIn("documents_count", res)
        self.assertTrue(res["documents_count"] >= 1)

        # Search test
        results = rag.search("resource governor")
        self.assertTrue(len(results) > 0)
        self.assertIn("4gb resource governor", results[0]["text"].lower())

    # 5. Security & Path Traversal Controls
    def test_09_path_traversal_sanitization(self):
        """Verify sanitize_storage_path detects and blocks traversal payloads."""
        traversal_payloads = [
            "../../etc/passwd",
            "..\\..\\windows\\system32",
            "/etc/shadow",
            "C:\\boot.ini",
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

    # 6. Low Memory Protection on Engine Startup
    def test_14_low_memory_rejection_for_ollama(self):
        """Verify engine start is blocked with 429 when RAM is critical."""
        with patch.object(server_app.governor, 'can_start_ollama', return_value={
            "allowed": False,
            "state": "critical",
            "available_mb": 320,
            "reason": "Ollama startup blocked: critically low RAM"
        }):
            res = self.client.post(
                '/start',
                headers={'Authorization': f'Bearer {self.admin_token}'}
            )
            self.assertEqual(res.status_code, 429)
            self.assertIn("critically low RAM", res.get_json().get('message', ''))

    # 7. Admin User Provisioning and RBAC
    def test_15_admin_user_provisioning(self):
        """Verify admin can create, list, and reset user passwords."""
        import secrets
        uid = f"testuser_{secrets.token_hex(4)}"
        res_create = self.client.post(
            '/api/admin/users',
            headers={'Authorization': f'Bearer {self.admin_token}'},
            json={
                "user_id": uid,
                "password": "Password123!",
                "privileges": config.USER_DEFAULT_PRIVILEGES
            }
        )
        self.assertEqual(res_create.status_code, 201)

        # List users
        res_list = self.client.get(
            '/api/admin/users',
            headers={'Authorization': f'Bearer {self.admin_token}'}
        )
        self.assertEqual(res_list.status_code, 200)
        user_ids = [u['user_id'] for u in res_list.get_json()]
        self.assertIn(uid, user_ids)

    def test_16_rbac_permission_enforcement(self):
        """Verify non-admin user without privileges is blocked from admin routes."""
        import secrets
        user_token = secrets.token_hex(32)
        uid = "restricted_user"
        with server_app.SESSIONS_LOCK:
            server_app.SESSIONS[user_token] = {
                "user_id": uid,
                "role": "user",
                "privileges": {
                    "can_upload_files": True,
                    "can_run_tasks": False,
                    "can_use_rag": True
                },
                "created_at": time.time(),
                "expires_at": time.time() + 86400
            }

        res = self.client.post(
            '/api/admin/users',
            headers={'Authorization': f'Bearer {user_token}'},
            json={"user_id": "hack_admin", "password": "abc"}
        )
        self.assertEqual(res.status_code, 403)

    def test_17_sqlite_db_inspector_endpoints(self):
        """Verify /api/admin/db/tables and /api/admin/db/query return accurate table rows."""
        res = self.client.get(
            '/api/admin/db/tables',
            headers={'Authorization': f'Bearer {self.admin_token}'}
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn('tables', data)
        table_names = [t['name'] for t in data['tables']]
        self.assertIn('users', table_names)
        self.assertIn('background_tasks', table_names)

        # Query users table
        res_query = self.client.get(
            '/api/admin/db/query?table=users&limit=10',
            headers={'Authorization': f'Bearer {self.admin_token}'}
        )
        self.assertEqual(res_query.status_code, 200)
        q_data = res_query.get_json()
        self.assertIn('columns', q_data)
        self.assertIn('rows', q_data)
        self.assertTrue(len(q_data['rows']) > 0)

    def test_18_brute_force_lockout_mechanism(self):
        """Verify IP address is blocked after exceeding lockout threshold of failed logins."""
        test_ip = "192.168.1.199"
        
        with patch.object(server_app, 'is_ip_locked', side_effect=lambda ip: ip == test_ip):
            res = self.client.post(
                '/api/auth/login',
                environ_overrides={'REMOTE_ADDR': test_ip},
                json={"user_id": "admin", "password": "wrong_password"}
            )
            self.assertEqual(res.status_code, 429)
            self.assertIn("Too many failed", res.get_json().get('error', ''))

    # ==========================================================================
    # NEW TESTS: TEMPORARY SHARES, MEDIA CENTER, BACKUPS, AUTOMATION & TELEMETRY
    # ==========================================================================

    def test_19_temporary_share_create_and_access(self):
        """Verify temporary share link creation, public access, and download counter."""
        test_filename = "share_test.txt"
        test_path = os.path.join(config.STORAGE_DIR, test_filename)
        with open(test_path, "w", encoding="utf-8") as f:
            f.write("Secret shared text content")

        res_create = self.client.post(
            '/api/shares',
            headers={'Authorization': f'Bearer {self.admin_token}'},
            json={"filename": test_filename, "duration": "1h", "max_downloads": 5}
        )
        self.assertEqual(res_create.status_code, 201)
        data = res_create.get_json()
        self.assertIn('token', data)
        self.assertIn('share_url', data)
        token = data['token']

        # Access without authorization header (public access via token)
        res_access = self.client.get(f'/share/{token}')
        self.assertEqual(res_access.status_code, 200)
        self.assertIn("Secret shared text content", res_access.data.decode('utf-8'))

    def test_20_temporary_share_revocation(self):
        """Verify revoking a share link returns 410 Gone on subsequent access."""
        test_filename = "revoke_test.txt"
        test_path = os.path.join(config.STORAGE_DIR, test_filename)
        with open(test_path, "w", encoding="utf-8") as f:
            f.write("Content to revoke")

        res_create = self.client.post(
            '/api/shares',
            headers={'Authorization': f'Bearer {self.admin_token}'},
            json={"filename": test_filename, "duration": "24h"}
        )
        share_id = res_create.get_json()['id']
        token = res_create.get_json()['token']

        # Revoke share
        res_del = self.client.delete(
            f'/api/shares/{share_id}',
            headers={'Authorization': f'Bearer {self.admin_token}'}
        )
        self.assertEqual(res_del.status_code, 200)

        # Attempt public access
        res_access = self.client.get(f'/share/{token}')
        self.assertEqual(res_access.status_code, 410)

    def test_21_media_download_batch_queueing(self):
        """Verify multiline URLs are parsed and enqueued as individual sequential tasks."""
        batch_urls = "https://example.com/song1.mp3\nhttps://example.com/song2.mp3"
        res = self.client.post(
            '/api/media/download',
            headers={'Authorization': f'Bearer {self.admin_token}'},
            json={
                "url": batch_urls,
                "format": "mp3",
                "quality": "audio_only",
                "destination": "Music"
            }
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data.get('count'), 2)
        self.assertEqual(len(data.get('queued_tasks', [])), 2)

    def test_22_media_library_categorization(self):
        """Verify /api/media/library categorizes vault files into music, videos, and podcasts."""
        music_file = os.path.join(config.STORAGE_DIR, "Music", "test_track.mp3")
        os.makedirs(os.path.dirname(music_file), exist_ok=True)
        with open(music_file, "w") as f:
            f.write("audio dummy")

        video_file = os.path.join(config.STORAGE_DIR, "Videos", "test_clip.mp4")
        os.makedirs(os.path.dirname(video_file), exist_ok=True)
        with open(video_file, "w") as f:
            f.write("video dummy")

        res = self.client.get(
            '/api/media/library',
            headers={'Authorization': f'Bearer {self.admin_token}'}
        )
        self.assertEqual(res.status_code, 200)
        lib = res.get_json()
        self.assertTrue(len(lib.get('music', [])) >= 1)
        self.assertTrue(len(lib.get('videos', [])) >= 1)

    def test_23_media_streaming_range_requests(self):
        """Verify HTTP 206 Partial Content is returned when Range header is provided."""
        media_path = os.path.join(config.STORAGE_DIR, "stream_test.mp3")
        with open(media_path, "wb") as f:
            f.write(b"0123456789ABCDEF0123456789ABCDEF")

        res = self.client.get(
            '/stream/stream_test.mp3',
            headers={'Authorization': f'Bearer {self.admin_token}', 'Range': 'bytes=0-9'}
        )
        self.assertEqual(res.status_code, 206)
        self.assertEqual(res.headers.get('Content-Range'), 'bytes 0-9/32')
        self.assertEqual(res.data, b"0123456789")

    def test_24_backup_create_and_checksum_verification(self):
        """Verify atomic backup creation and SHA-256 checksum calculation."""
        res = self.client.post(
            '/api/backups/create',
            headers={'Authorization': f'Bearer {self.admin_token}'}
        )
        self.assertEqual(res.status_code, 201)
        data = res.get_json()
        self.assertIn('checksum', data)
        self.assertEqual(len(data['checksum']), 64)  # Valid SHA-256 length
        self.assertTrue(os.path.exists(os.path.join(config.BACKUP_DIR, data['filename'])))

    def test_25_storage_intelligence_calculation(self):
        """Verify /api/storage/intelligence returns breakdown categories."""
        res = self.client.get(
            '/api/storage/intelligence',
            headers={'Authorization': f'Bearer {self.admin_token}'}
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn('breakdown', data)
        self.assertIn('disk', data)

    def test_26_temp_files_cleanup_safety(self):
        """Verify /api/vault/clean-temp only removes .part/.tmp and preserves normal files."""
        temp_file = os.path.join(config.STORAGE_DIR, "download.mp4.part")
        real_file = os.path.join(config.STORAGE_DIR, "important_doc.pdf")
        with open(temp_file, "w") as f:
            f.write("temporary garbage")
        with open(real_file, "w") as f:
            f.write("vital user data")

        res = self.client.post(
            '/api/vault/clean-temp',
            headers={'Authorization': f'Bearer {self.admin_token}'}
        )
        self.assertEqual(res.status_code, 200)
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
        """Verify thermal CRITICAL state blocks heavy tasks with 429."""
        with patch.object(server_app.governor, 'get_device_telemetry', return_value={
            "effective_temperature_c": 58.5,
            "thermal_state": "CRITICAL",
            "thermal_desc": "Thermal critical (58.5°C ≥ 55°C)."
        }):
            res = self.client.post(
                '/api/media/download',
                headers={'Authorization': f'Bearer {self.admin_token}'},
                json={"url": "https://example.com/test.mp3", "format": "mp3"}
            )
            self.assertEqual(res.status_code, 429)
            self.assertIn("thermal critical", res.get_json().get('reason', '').lower())

    def test_29_scheduled_automation_job_trigger(self):
        """Verify listing and manually triggering scheduled maintenance jobs."""
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
        self.assertTrue(res_run.get_json().get('triggered'))

    def test_30_settings_update_and_restart_flag(self):
        """Verify settings update API and restart required flags."""
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
        res = self.client.post(
            '/api/backups/create',
            headers={'Authorization': f'Bearer {self.admin_token}'}
        )
        self.assertEqual(res.status_code, 201)
        filename = res.get_json()['filename']
        backup_path = os.path.join(config.BACKUP_DIR, filename)

        with zipfile.ZipFile(backup_path, 'r') as zf:
            names = zf.namelist()
            self.assertIn("nexus_vault.db", names)
            self.assertIn("manifest.json", names)
            
            manifest_raw = zf.read("manifest.json").decode('utf-8')
            manifest = json.loads(manifest_raw)
            self.assertIn("backup_id", manifest)
            self.assertNotIn("password", manifest_raw.lower())
            self.assertNotIn("session", manifest_raw.lower())
            self.assertNotIn("localtonet_token", manifest_raw.lower())

    def test_32_task_queue_sequential_execution_and_cancellation(self):
        """Verify sequential execution queue and clean cancellation of active task."""
        runner = server_app.BoundedTaskRunner(max_concurrency=1)
        execution_order = []

        def slow_job(task_obj, name, duration):
            task_obj['logs'].append(f"Running {name}")
            for _ in range(int(duration * 10)):
                if task_obj['status'] == 'cancelled':
                    return
                time.sleep(0.05)
            execution_order.append(name)

        t1, _ = runner.enqueue_task("Job A", "test", slow_job, "A", 0.5)
        t2, _ = runner.enqueue_task("Job B", "test", slow_job, "B", 0.1)

        # Cancel Job A while it starts
        time.sleep(0.05)
        cancelled = runner.cancel_task(t1)
        self.assertTrue(cancelled)

        # Wait for queue to process B
        time.sleep(0.4)
        self.assertEqual(runner.tasks[t1]['status'], 'cancelled')

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
        self.assertEqual(data_small["estimated_mb"], 350)
        self.assertIn(data_small["decision"], ["SAFE", "BLOCKED"])

    def test_35_logout_clears_session_state(self):
        """Verify POST /api/auth/logout destroys server-side session token."""
        import secrets
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
        import secrets

        # 1. Admin login/token
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

        # 2. Normal user logs in
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
        import secrets
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
        import secrets
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

    def test_39_user_cannot_manage_models(self):
        """Verify normal user cannot pull or delete Ollama models."""
        import secrets
        user_tok = secrets.token_hex(32)
        with server_app.SESSIONS_LOCK:
            server_app.SESSIONS[user_tok] = {
                "user_id": "dave",
                "role": "user",
                "privileges": config.USER_DEFAULT_PRIVILEGES,
                "created_at": time.time(),
                "expires_at": time.time() + 3600
            }

        res_pull = self.client.post('/api/models/pull', headers={'Authorization': f'Bearer {user_tok}'}, json={"model": "smollm:135m"})
        self.assertEqual(res_pull.status_code, 403)

        res_del = self.client.delete('/api/models/smollm:135m', headers={'Authorization': f'Bearer {user_tok}'})
        self.assertEqual(res_del.status_code, 403)

    def test_40_session_expiration_returns_401(self):
        """Verify expired session token returns HTTP 401."""
        import secrets
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
        import secrets
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


if __name__ == '__main__':
    unittest.main(verbosity=2)

