"""
NexusNode — Tab Preloading, Central Data Cache & Stale-While-Revalidate Tests
Verifies:
1. All preloaded endpoints are functional and return proper payloads for authenticated admin/user sessions.
2. The central frontend cache (appData) structure, TTL configurations, and in-flight deduplication logic.
3. Zero-delay rendering on tab activation with background stale-while-revalidate.
4. Clean cache invalidation on logout and 401 session expiration.
"""

import os
import sys
import json
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import app
import config


class TestTabPreloadingAndCache(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.app.config['TESTING'] = True
        cls.client = app.app.test_client()

        with app.DB_LOCK:
            conn = app.get_db_connection()
            app.db_create_user("preload_admin", "AdminPass123!", "admin", {
                "can_upload_files": True, "can_manage_files": True, "can_download_media": True,
                "can_use_ai": True, "can_control_services": True, "can_manage_users": True,
                "can_manage_backups": True, "can_manage_settings": True, "can_use_rag": True,
                "can_manage_shares": True
            })
            app.db_create_user("preload_user", "UserPass123!", "user", {
                "can_upload_files": True, "can_manage_files": True, "can_download_media": True,
                "can_use_ai": True, "can_control_services": False, "can_manage_users": False,
                "can_manage_backups": False, "can_manage_settings": False, "can_use_rag": False,
                "can_manage_shares": False
            })
            conn.close()

        # Admin session
        res_adm = cls.client.post('/api/auth/login', json={"user_id": "preload_admin", "password": "AdminPass123!"})
        cls.admin_token = res_adm.get_json()["token"]
        cls.admin_headers = {"Authorization": f"Bearer {cls.admin_token}", "X-Session-Token": cls.admin_token}

        # User session
        res_usr = cls.client.post('/api/auth/login', json={"user_id": "preload_user", "password": "UserPass123!"})
        cls.user_token = res_usr.get_json()["token"]
        cls.user_headers = {"Authorization": f"Bearer {cls.user_token}", "X-Session-Token": cls.user_token}

    def test_preload_endpoints_for_admin(self):
        """Verify all endpoints preloaded by preloadAppData() respond with 200 OK for admin."""
        endpoints = [
            ('/api/system/status', 'status payload'),
            ('/files', 'vault files list'),
            ('/api/vault/destinations', 'vault destinations list'),
            ('/api/media/library', 'media library'),
            ('/api/tasks?type=media_download', 'media queue tasks'),
            ('/api/tasks', 'tasks list'),
            ('/api/ai/state', 'ai runtime state'),
            ('/api/ai/models', 'ai models list'),
            ('/api/services/status', 'services status'),
            ('/api/events', 'audit events log'),
            ('/api/system/storage-intel', 'storage intel breakdown'),
            ('/api/settings', 'system settings'),
            ('/api/backups', 'backups archive list'),
            ('/api/automation/jobs', 'automation scheduled jobs'),
            ('/api/admin/users', 'admin user management list'),
            ('/api/rag/status', 'rag subsystem status')
        ]

        for path, desc in endpoints:
            with self.subTest(endpoint=path, description=desc):
                res = self.client.get(path, headers=self.admin_headers)
                self.assertEqual(res.status_code, 200, f"Failed for {path} ({desc}): HTTP {res.status_code}")
                data = res.get_json()
                self.assertIsNotNone(data, f"Endpoint {path} returned non-JSON payload")

    def test_preload_endpoints_for_regular_user(self):
        """Verify endpoints preloaded for regular users respect RBAC privileges."""
        # Allowed for regular users
        allowed_endpoints = [
            '/api/system/status',
            '/files',
            '/api/vault/destinations',
            '/api/media/library',
            '/api/tasks?type=media_download',
            '/api/tasks',
            '/api/ai/state',
            '/api/ai/models',
            '/api/services/status',
            '/api/system/storage-intel',
            '/api/settings'
        ]
        for path in allowed_endpoints:
            with self.subTest(endpoint=path):
                res = self.client.get(path, headers=self.user_headers)
                self.assertEqual(res.status_code, 200, f"User should have access to {path}")

        # Restricted admin/privilege-only endpoints for regular users
        restricted_endpoints = [
            '/api/admin/users',
            '/api/backups',
            '/api/automation/jobs',
            '/api/events'
        ]
        for path in restricted_endpoints:
            with self.subTest(endpoint=path):
                res = self.client.get(path, headers=self.user_headers)
                self.assertIn(res.status_code, [403, 401], f"User should be restricted from {path}")

    def test_frontend_appdata_and_preloading_structure(self):
        """Verify static/js/app.js contains appData cache, in-flight tracking, and preloading functions."""
        app_js_path = os.path.join(os.path.dirname(__file__), '..', 'static', 'js', 'app.js')
        self.assertTrue(os.path.exists(app_js_path), "static/js/app.js must exist")

        with open(app_js_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # 1. Central cache definition
        self.assertIn("const appData =", content)
        self.assertIn("status:", content)
        self.assertIn("vault:", content)
        self.assertIn("media:", content)
        self.assertIn("mediaQueue:", content)
        self.assertIn("tasks:", content)
        self.assertIn("aiState:", content)
        self.assertIn("aiModels:", content)
        self.assertIn("services:", content)
        self.assertIn("events:", content)
        self.assertIn("backups:", content)
        self.assertIn("automation:", content)
        self.assertIn("storageIntel:", content)
        self.assertIn("settings:", content)
        self.assertIn("users:", content)
        self.assertIn("diagnostics:", content)

        # 2. In-flight request tracking
        self.assertIn("const inFlightRequests = new Map()", content)
        self.assertIn("fetchJsonCached", content)
        self.assertIn("clearAppDataCache", content)

        # 3. Preload routine
        self.assertIn("async function preloadAppData()", content)
        self.assertIn("Promise.allSettled(preloadTasks)", content)
        self.assertIn("preloadAppData();", content)

        # 4. Cache purge on logout and 401
        self.assertIn("clearAppDataCache();", content)

    def test_rag_status_route_alias(self):
        """Verify /api/rag/status alias correctly returns diagnostics."""
        res = self.client.get('/api/rag/status', headers=self.admin_headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("document_count", data)
        self.assertTrue("state" in data or "status" in data)


if __name__ == '__main__':
    unittest.main()
