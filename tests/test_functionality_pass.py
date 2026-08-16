"""
NexusNode — Functionality & Mobile UX Repair Pass Test Suite
Covers:
1. File Uploads (root, destination folder, path sanitization, failure logging)
2. Dynamic Upload Destinations (RBAC filtering, internal path hiding)
3. Media Streaming & MIME Typing (?auth= query support, 206 Partial Content, accurate MIME types)
4. Photo Viewing & Categorization (jpg/png/webp/gif categorization, inline viewing)
5. AI Engine Start/Stop/State Controls (canonical /api/ai/start & /api/ai/stop, supervisor state)
6. Comprehensive Failure Logging (failed login, upload rejection, delete rejection)
7. Security & Protected Path Invariance (internal files remain hidden and blocked)
"""

import io
import os
import sys
import json
import time
import shutil
import tempfile
import unittest

# Import server application
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import app
import config


class TestFunctionalityRepairPass(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.app.config['TESTING'] = True
        cls.client = app.app.test_client()

        # Create test users and sessions
        with app.DB_LOCK:
            conn = app.get_db_connection()
            # Ensure admin exists
            app.db_create_user("func_admin", "AdminPass123!", "admin", {
                "can_upload_files": True, "can_manage_files": True, "can_download_media": True,
                "can_use_ai": True, "can_control_services": True, "can_manage_users": True,
                "can_manage_backups": True, "can_manage_settings": True, "can_use_rag": True,
                "can_manage_shares": True
            })
            # Ensure regular user exists
            app.db_create_user("func_user", "UserPass123!", "user", {
                "can_upload_files": True, "can_manage_files": True, "can_download_media": True,
                "can_use_ai": True, "can_control_services": False, "can_manage_users": False,
                "can_manage_backups": False, "can_manage_settings": False, "can_use_rag": False,
                "can_manage_shares": False
            })
            conn.close()

        # Login admin
        res_adm = cls.client.post('/api/auth/login', json={"user_id": "func_admin", "password": "AdminPass123!"})
        cls.admin_token = res_adm.get_json()["token"]

        # Login user
        res_usr = cls.client.post('/api/auth/login', json={"user_id": "func_user", "password": "UserPass123!"})
        cls.user_token = res_usr.get_json()["token"]

    def setUp(self):
        self.admin_headers = {"Authorization": f"Bearer {self.admin_token}"}
        self.user_headers = {"Authorization": f"Bearer {self.user_token}"}

    # =========================================================================
    # 1. FILE UPLOAD & DESTINATIONS
    # =========================================================================

    def test_upload_to_root(self):
        """Verify uploading file to Vault Root."""
        data = {
            'file': (io.BytesIO(b"Root test content"), 'test_root_upload.txt'),
            'path': ''
        }
        res = self.client.post('/upload', data=data, headers=self.user_headers, content_type='multipart/form-data')
        self.assertEqual(res.status_code, 200)
        json_data = res.get_json()
        self.assertIn("uploaded successfully", json_data.get("message", ""))

        # Verify file exists on disk
        target = os.path.join(config.STORAGE_DIR, 'test_root_upload.txt')
        self.assertTrue(os.path.exists(target))
        with open(target, 'rb') as f:
            self.assertEqual(f.read(), b"Root test content")
        os.remove(target)

    def test_upload_to_subfolder(self):
        """Verify uploading file to a specific destination folder."""
        data = {
            'file': (io.BytesIO(b"Subfolder test content"), 'sub_upload.txt'),
            'path': 'documents/test_sub'
        }
        res = self.client.post('/upload', data=data, headers=self.user_headers, content_type='multipart/form-data')
        self.assertEqual(res.status_code, 200)

        # Verify file exists in subfolder
        target = os.path.join(config.STORAGE_DIR, 'documents', 'test_sub', 'sub_upload.txt')
        self.assertTrue(os.path.exists(target))
        shutil.rmtree(os.path.join(config.STORAGE_DIR, 'documents', 'test_sub'), ignore_errors=True)

    def test_upload_to_protected_folder_rejected(self):
        """Verify uploading to protected folders like backups is strictly blocked."""
        data = {
            'file': (io.BytesIO(b"backup exploit"), 'exploit.zip'),
            'path': 'backups'
        }
        res = self.client.post('/upload', data=data, headers=self.user_headers, content_type='multipart/form-data')
        self.assertIn(res.status_code, [400, 403])

    def test_upload_destination_listing_rbac(self):
        """Verify dynamic destinations respect user permissions and hide internal paths."""
        # Regular user should see standard writable directories
        res_usr = self.client.get('/api/vault/destinations', headers=self.user_headers)
        self.assertEqual(res_usr.status_code, 200)
        usr_dests = [d["path"] for d in res_usr.get_json()["destinations"]]
        self.assertIn("downloads", usr_dests)
        self.assertIn("documents", usr_dests)
        self.assertIn("media", usr_dests)
        self.assertNotIn("backups", usr_dests)
        self.assertNotIn(".git", usr_dests)

    # =========================================================================
    # 2. PHOTO PREVIEW & CATEGORIZATION
    # =========================================================================

    def test_photos_categorization_in_file_list(self):
        """Verify image files are categorized as 'photos' in /files."""
        test_img = os.path.join(config.STORAGE_DIR, "sample_test.png")
        with open(test_img, "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4")

        try:
            res = self.client.get('/files', headers=self.user_headers)
            self.assertEqual(res.status_code, 200)
            files = res.get_json()["files"]
            img_entry = next((f for f in files if f["name"] == "sample_test.png"), None)
            self.assertIsNotNone(img_entry)
            self.assertEqual(img_entry["category"], "photos")
        finally:
            if os.path.exists(test_img):
                os.remove(test_img)

    def test_inline_photo_download_with_auth(self):
        """Verify image download with inline=true serves image inline with auth."""
        test_img = os.path.join(config.STORAGE_DIR, "photo_inline.jpg")
        with open(test_img, "wb") as f:
            f.write(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00H\x00H\x00\x00\xff\xdb")

        try:
            # Query param auth
            res = self.client.get(f'/download/photo_inline.jpg?auth={self.user_token}&inline=true')
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res.mimetype, 'image/jpeg')
            self.assertNotIn("attachment", res.headers.get("Content-Disposition", ""))
            res.close()
        finally:
            if os.path.exists(test_img):
                os.remove(test_img)

    # =========================================================================
    # 3. MEDIA STREAMING & RANGE PLAYBACK
    # =========================================================================

    def test_stream_media_with_auth_query_and_mime(self):
        """Verify /stream/<path> accepts ?auth=<token> and sets correct MIME type."""
        test_audio = os.path.join(config.STORAGE_DIR, "test_track.mp3")
        with open(test_audio, "wb") as f:
            f.write(b"ID3" + b"\x00" * 1024)

        test_video = os.path.join(config.STORAGE_DIR, "test_clip.webm")
        with open(test_video, "wb") as f:
            f.write(b"\x1a\x45\xdf\xa3" + b"\x00" * 2048)

        try:
            # MP3 stream
            res_mp3 = self.client.get(f'/stream/test_track.mp3?auth={self.user_token}')
            self.assertEqual(res_mp3.status_code, 200)
            self.assertEqual(res_mp3.mimetype, 'audio/mpeg')
            res_mp3.close()

            # WebM stream with HTTP Range request
            headers = {"Range": "bytes=0-100"}
            res_webm = self.client.get(f'/stream/test_clip.webm?auth={self.user_token}', headers=headers)
            self.assertEqual(res_webm.status_code, 206)
            self.assertEqual(res_webm.mimetype, 'video/webm')
            self.assertIn('Content-Range', res_webm.headers)
            self.assertEqual(res_webm.headers.get('Content-Length'), '101')
            res_webm.close()
        finally:
            if os.path.exists(test_audio):
                os.remove(test_audio)
            if os.path.exists(test_video):
                os.remove(test_video)

    # =========================================================================
    # 4. AI ENGINE ON/OFF & CONTROLS
    # =========================================================================

    def test_ai_state_query(self):
        """Verify /api/ai/state returns unified engine status."""
        res = self.client.get('/api/ai/state', headers=self.user_headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("engine", data)
        self.assertIn(data["engine"], ["running", "stopped", "unavailable"])
        self.assertIn("selected_model", data)

    def test_ai_start_and_stop_endpoints_rbac(self):
        """Verify /api/ai/start and /api/ai/stop require service control permissions."""
        # Regular user without can_control_services cannot toggle
        res_usr_start = self.client.post('/api/ai/start', headers=self.user_headers)
        self.assertEqual(res_usr_start.status_code, 403)

        # Admin with can_control_services can invoke endpoint
        res_adm_stop = self.client.post('/api/ai/stop', headers=self.admin_headers)
        self.assertIn(res_adm_stop.status_code, [200, 500])

    # =========================================================================
    # 5. COMPREHENSIVE FAILURE LOGGING
    # =========================================================================

    def test_failed_login_logs_warning(self):
        """Verify failed login attempt is recorded in event logs."""
        unique_bad_user = f"bad_usr_{int(time.time()*1000)}"
        res = self.client.post('/api/auth/login', json={"user_id": unique_bad_user, "password": "WrongPassword"})
        self.assertEqual(res.status_code, 401)

        # Flush queued log batch
        app.log_daemon.flush()

        # Inspect DB logs
        with app.DB_LOCK:
            conn = app.get_db_connection()
            cur = conn.cursor()
            cur.execute("SELECT level, category, message FROM system_logs WHERE message LIKE ? ORDER BY id DESC LIMIT 1",
                        (f"%{unique_bad_user}%",))
            row = cur.fetchone()
            conn.close()

        self.assertIsNotNone(row)
        self.assertEqual(row["level"], "WARN")
        self.assertEqual(row["category"], "AUTH")

    def test_upload_rejection_logs_warning(self):
        """Verify empty upload rejection is recorded in event logs."""
        res = self.client.post('/upload', headers=self.user_headers, data={})
        self.assertEqual(res.status_code, 400)

        # Flush queued log batch
        app.log_daemon.flush()

        # Inspect DB logs
        with app.DB_LOCK:
            conn = app.get_db_connection()
            cur = conn.cursor()
            cur.execute("SELECT level, category, message FROM system_logs WHERE category = 'STORAGE' ORDER BY id DESC LIMIT 5")
            rows = [dict(r) for r in cur.fetchall()]
            conn.close()

        has_upload_warn = any("Upload rejected" in r["message"] or "No file" in r["message"] for r in rows)
        self.assertTrue(has_upload_warn)

    # =========================================================================
    # 6. SECURITY & PROTECTED INTERNAL PATH INVARIANCE
    # =========================================================================

    def test_protected_files_hidden_and_blocked(self):
        """Verify system databases, source files, and keys cannot be downloaded or streamed."""
        protected_targets = [
            'nexusnode.db',
            'nexusnode.db-wal',
            'app.py',
            'config.py',
            '.env',
            '../app.py',
            '..\\config.py',
            'storage_vault/nexusnode.db'
        ]
        for pt in protected_targets:
            with self.subTest(target=pt):
                # Test download
                res_dl = self.client.get(f'/download/{pt}', headers=self.admin_headers)
                self.assertIn(res_dl.status_code, [400, 403, 404])
                res_dl.close()

                # Test stream
                res_st = self.client.get(f'/stream/{pt}', headers=self.admin_headers)
                self.assertIn(res_st.status_code, [400, 403, 404])
                res_st.close()

                # Test delete
                res_del = self.client.delete(f'/files/{pt}', headers=self.admin_headers)
                self.assertIn(res_del.status_code, [400, 403, 404])


if __name__ == '__main__':
    unittest.main()
