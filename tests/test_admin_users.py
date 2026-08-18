"""
NexusNode — Comprehensive Admin User Governance & RBAC Test Suite
Tests complete lifecycle of user creation, RBAC modification, enable/disable,
password reset, session revocation, self-service password update, account deletion,
and multi-tier RBAC boundary enforcement.
"""

import os
import sys
import json
import time
import shutil
import sqlite3
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
import app


class TestAdminUserGovernance(unittest.TestCase):
    """Full-coverage test suite for authoritative user management and RBAC security."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="nexus_admin_user_test_")
        self.db_path = os.path.join(self.test_dir, "test_admin_users.db")
        self.rag_path = os.path.join(self.test_dir, "test_rag.db")
        self.storage_dir = os.path.join(self.test_dir, "storage_vault")
        os.makedirs(self.storage_dir, exist_ok=True)

        self._orig_db = config.UNIFIED_DB_FILE
        self._orig_rag = config.RAG_DB_FILE
        self._orig_storage = config.STORAGE_DIR
        config.UNIFIED_DB_FILE = self.db_path
        config.RAG_DB_FILE = self.rag_path
        config.STORAGE_DIR = self.storage_dir

        app.init_unified_db()

        self.client = app.app.test_client()
        app.SESSIONS.clear()
        app.FAILED_LOGINS.clear()

        # Create admin session
        admin_user = app.db_get_user("admin")
        self.admin_token = app.create_user_session(admin_user)
        self.admin_headers = {
            "Authorization": f"Bearer {self.admin_token}",
            "Content-Type": "application/json"
        }

    def tearDown(self):
        config.UNIFIED_DB_FILE = self._orig_db
        config.RAG_DB_FILE = self._orig_rag
        config.STORAGE_DIR = self._orig_storage
        app.SESSIONS.clear()
        app.FAILED_LOGINS.clear()
        try:
            shutil.rmtree(self.test_dir, ignore_errors=True)
        except Exception:
            pass

    # 1. User Creation & Validation Tests
    def test_create_user_success(self):
        """Admin can successfully create a new user with PBKDF2 hash."""
        payload = {
            "user_id": "operator_bob",
            "password": "SecurePassword123",
            "confirm_password": "SecurePassword123",
            "role": "user",
            "privileges": {
                "can_upload_files": True,
                "can_download_media": True
            }
        }
        res = self.client.post("/api/admin/users", headers=self.admin_headers, data=json.dumps(payload))
        self.assertEqual(res.status_code, 201)
        data = res.get_json()
        self.assertEqual(data.get("user_id"), "operator_bob")

        # Verify user is persisted in DB with PBKDF2
        user = app.db_get_user("operator_bob")
        self.assertIsNotNone(user)
        self.assertEqual(user["role"], "user")
        self.assertTrue(user["password_hash"].startswith("pbkdf2_sha256$"))
        self.assertTrue(user["privileges"].get("can_upload_files"))
        self.assertTrue(user["privileges"].get("can_download_media"))

    def test_create_duplicate_user_rejected(self):
        """Creating an existing user returns 409 Conflict."""
        payload = {
            "user_id": "duplicate_user",
            "password": "Password123",
            "role": "user"
        }
        res1 = self.client.post("/api/admin/users", headers=self.admin_headers, data=json.dumps(payload))
        self.assertEqual(res1.status_code, 201)

        res2 = self.client.post("/api/admin/users", headers=self.admin_headers, data=json.dumps(payload))
        self.assertEqual(res2.status_code, 409)

    def test_create_user_validation_failures(self):
        """Rejects empty IDs, invalid characters, short passwords, and password mismatches."""
        # Empty user ID
        res = self.client.post("/api/admin/users", headers=self.admin_headers, data=json.dumps({
            "user_id": "",
            "password": "Password123"
        }))
        self.assertEqual(res.status_code, 400)

        # Invalid characters in user ID
        res = self.client.post("/api/admin/users", headers=self.admin_headers, data=json.dumps({
            "user_id": "bad user@name!",
            "password": "Password123"
        }))
        self.assertEqual(res.status_code, 400)

        # Short password (< 6 chars)
        res = self.client.post("/api/admin/users", headers=self.admin_headers, data=json.dumps({
            "user_id": "valid_user",
            "password": "123"
        }))
        self.assertEqual(res.status_code, 400)

        # Password confirmation mismatch
        res = self.client.post("/api/admin/users", headers=self.admin_headers, data=json.dumps({
            "user_id": "valid_user",
            "password": "Password123",
            "confirm_password": "DifferentPassword456"
        }))
        self.assertEqual(res.status_code, 400)

    # 2. User Authentication & Login
    def test_user_authentication_flow(self):
        """Newly created user can authenticate and retrieve session token."""
        app.db_create_user("operator_alice", "AlicePass123", role="user")
        login_res = self.client.post("/api/auth/login", data=json.dumps({
            "user_id": "operator_alice",
            "password": "AlicePass123"
        }), headers={"Content-Type": "application/json"})
        self.assertEqual(login_res.status_code, 200)
        data = login_res.get_json()
        self.assertIn("token", data)
        self.assertEqual(data["user"]["user_id"], "operator_alice")
        self.assertEqual(data["user"]["role"], "user")

    # 3. User Listing & Single Get
    def test_get_users_list_and_single_user(self):
        """Admin can list all registered users and fetch individual user record."""
        app.db_create_user("charlie_user", "CharliePass123", role="user")
        res = self.client.get("/api/admin/users", headers=self.admin_headers)
        self.assertEqual(res.status_code, 200)
        users = res.get_json()
        self.assertIsInstance(users, list)
        user_ids = [u["user_id"] for u in users]
        self.assertIn("admin", user_ids)
        self.assertIn("charlie_user", user_ids)

        # Fetch single user
        res_single = self.client.get("/api/admin/users/charlie_user", headers=self.admin_headers)
        self.assertEqual(res_single.status_code, 200)
        s_data = res_single.get_json()
        self.assertEqual(s_data["user_id"], "charlie_user")
        self.assertEqual(s_data["status"], "ACTIVE")

    # 4. Role & Privilege Updates
    def test_edit_user_role_and_privileges(self):
        """Admin can modify user role and grant/revoke individual privileges."""
        app.db_create_user("dave_user", "DavePassword123", role="user")
        patch_res = self.client.patch("/api/admin/users/dave_user", headers=self.admin_headers, data=json.dumps({
            "role": "admin",
            "privileges": {
                "can_control_services": True,
                "can_manage_models": True
            }
        }))
        self.assertEqual(patch_res.status_code, 200)

        # Verify updated in DB
        user = app.db_get_user("dave_user")
        self.assertEqual(user["role"], "admin")
        self.assertTrue(user["privileges"].get("can_control_services"))
        self.assertTrue(user["privileges"].get("can_manage_models"))

    # 5. Account Disable & Enable Lifecycle
    def test_disable_and_reenable_user(self):
        """Disabled user cannot log in and active sessions are dropped; re-enabling restores access."""
        app.db_create_user("eve_user", "EvePassword123", role="user")

        # Log in as eve
        login_res = self.client.post("/api/auth/login", data=json.dumps({
            "user_id": "eve_user",
            "password": "EvePassword123"
        }), headers={"Content-Type": "application/json"})
        eve_token = login_res.get_json()["token"]

        # Eve can access /api/auth/me
        me_res = self.client.get("/api/auth/me", headers={"Authorization": f"Bearer {eve_token}"})
        self.assertEqual(me_res.status_code, 200)

        # Admin disables eve
        dis_res = self.client.patch("/api/admin/users/eve_user", headers=self.admin_headers, data=json.dumps({
            "is_disabled": True
        }))
        self.assertEqual(dis_res.status_code, 200)

        # Active session must now receive 401 (session dropped) or 403
        me_after = self.client.get("/api/auth/me", headers={"Authorization": f"Bearer {eve_token}"})
        self.assertIn(me_after.status_code, [401, 403])

        # New login attempt by disabled user must fail with 403
        login_disabled = self.client.post("/api/auth/login", data=json.dumps({
            "user_id": "eve_user",
            "password": "EvePassword123"
        }), headers={"Content-Type": "application/json"})
        self.assertEqual(login_disabled.status_code, 403)

        # Admin re-enables eve
        en_res = self.client.patch("/api/admin/users/eve_user", headers=self.admin_headers, data=json.dumps({
            "is_disabled": False
        }))
        self.assertEqual(en_res.status_code, 200)

        # Eve can log in again
        login_restored = self.client.post("/api/auth/login", data=json.dumps({
            "user_id": "eve_user",
            "password": "EvePassword123"
        }), headers={"Content-Type": "application/json"})
        self.assertEqual(login_restored.status_code, 200)

    # 6. Admin Password Reset
    def test_admin_password_reset(self):
        """Admin resets user password; old password fails, new password succeeds, active sessions revoked."""
        app.db_create_user("frank_user", "OldPassword123", role="user")

        # Initial login
        log1 = self.client.post("/api/auth/login", data=json.dumps({
            "user_id": "frank_user",
            "password": "OldPassword123"
        }), headers={"Content-Type": "application/json"})
        frank_token = log1.get_json()["token"]

        # Admin resets password
        reset_res = self.client.post("/api/admin/users/frank_user/password", headers=self.admin_headers, data=json.dumps({
            "password": "BrandNewPassword789"
        }))
        self.assertEqual(reset_res.status_code, 200)

        # Old session token is revoked
        auth_check = self.client.get("/api/auth/me", headers={"Authorization": f"Bearer {frank_token}"})
        self.assertEqual(auth_check.status_code, 401)

        # Old password fails
        log_old = self.client.post("/api/auth/login", data=json.dumps({
            "user_id": "frank_user",
            "password": "OldPassword123"
        }), headers={"Content-Type": "application/json"})
        self.assertEqual(log_old.status_code, 401)

        # New password works
        log_new = self.client.post("/api/auth/login", data=json.dumps({
            "user_id": "frank_user",
            "password": "BrandNewPassword789"
        }), headers={"Content-Type": "application/json"})
        self.assertEqual(log_new.status_code, 200)

    # 7. Self-Service Password Update
    def test_self_service_password_change(self):
        """User can update own password with valid current password; old sessions revoked."""
        app.db_create_user("grace_user", "GracePass123", role="user")
        log1 = self.client.post("/api/auth/login", data=json.dumps({
            "user_id": "grace_user",
            "password": "GracePass123"
        }), headers={"Content-Type": "application/json"})
        g_token1 = log1.get_json()["token"]

        # Another session
        log2 = self.client.post("/api/auth/login", data=json.dumps({
            "user_id": "grace_user",
            "password": "GracePass123"
        }), headers={"Content-Type": "application/json"})
        g_token2 = log2.get_json()["token"]

        # Wrong current password fails
        bad_change = self.client.post("/api/account/password", headers={"Authorization": f"Bearer {g_token1}", "Content-Type": "application/json"}, data=json.dumps({
            "current_password": "WrongPassword",
            "new_password": "NewGracePassword456"
        }))
        self.assertEqual(bad_change.status_code, 401)

        # Valid password change
        good_change = self.client.post("/api/account/password", headers={"Authorization": f"Bearer {g_token1}", "Content-Type": "application/json"}, data=json.dumps({
            "current_password": "GracePass123",
            "new_password": "NewGracePassword456"
        }))
        self.assertEqual(good_change.status_code, 200)

        # Current session g_token1 remains valid, other session g_token2 is revoked
        res_current = self.client.get("/api/auth/me", headers={"Authorization": f"Bearer {g_token1}"})
        self.assertEqual(res_current.status_code, 200)
        res_other = self.client.get("/api/auth/me", headers={"Authorization": f"Bearer {g_token2}"})
        self.assertEqual(res_other.status_code, 401)

    # 8. Session Revocation
    def test_admin_revoke_user_sessions(self):
        """Admin can revoke all active sessions for a target user."""
        app.db_create_user("heidi_user", "HeidiPass123", role="user")
        log = self.client.post("/api/auth/login", data=json.dumps({
            "user_id": "heidi_user",
            "password": "HeidiPass123"
        }), headers={"Content-Type": "application/json"})
        h_token = log.get_json()["token"]

        # Verify active
        self.assertEqual(self.client.get("/api/auth/me", headers={"Authorization": f"Bearer {h_token}"}).status_code, 200)

        # Admin revokes sessions
        rev_res = self.client.post("/api/admin/users/heidi_user/sessions/revoke", headers=self.admin_headers, data=json.dumps({}))
        self.assertEqual(rev_res.status_code, 200)

        # Token is immediately rejected with 401
        self.assertEqual(self.client.get("/api/auth/me", headers={"Authorization": f"Bearer {h_token}"}).status_code, 401)

    # 9. User Deletion & Cleanup
    def test_delete_user_and_cascade(self):
        """Deleting user purges record, active sessions, and cascades related records."""
        app.db_create_user("ivan_user", "IvanPass123", role="user")
        log = self.client.post("/api/auth/login", data=json.dumps({
            "user_id": "ivan_user",
            "password": "IvanPass123"
        }), headers={"Content-Type": "application/json"})
        ivan_token = log.get_json()["token"]

        # Add a share link and chat for ivan
        with app.DB_LOCK:
            conn = app.get_db_connection()
            conn.execute("INSERT INTO shares (id, token, filename, user_id, owner_user_id, created_at, expires_at) VALUES ('s1', 'tok1', 'f.txt', 'ivan_user', 'ivan_user', ?, ?)", (time.time(), time.time() + 3600))
            conn.execute("INSERT INTO user_chats (id, session_id, user_id, title, created_at, updated_at) VALUES ('c1', 'sess1', 'ivan_user', 'Chat', ?, ?)", (time.time(), time.time()))
            conn.commit()
            conn.close()

        # Admin deletes ivan
        del_res = self.client.delete("/api/admin/users/ivan_user", headers=self.admin_headers)
        self.assertEqual(del_res.status_code, 200)

        # Verify user is gone from DB
        self.assertIsNone(app.db_get_user("ivan_user"))

        # Verify sessions purged
        self.assertEqual(self.client.get("/api/auth/me", headers={"Authorization": f"Bearer {ivan_token}"}).status_code, 401)

        # Verify associated records cleaned up
        conn = app.get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM shares WHERE user_id = 'ivan_user'")
        self.assertEqual(cur.fetchone()[0], 0)
        cur.execute("SELECT COUNT(*) FROM user_chats WHERE user_id = 'ivan_user'")
        self.assertEqual(cur.fetchone()[0], 0)
        conn.close()

    # 10. Primary Admin & Self-Deletion Protection
    def test_primary_admin_protections(self):
        """Primary admin cannot be deleted, disabled, or demoted; caller cannot self-delete."""
        # Cannot delete primary admin
        res_del = self.client.delete("/api/admin/users/admin", headers=self.admin_headers)
        self.assertEqual(res_del.status_code, 400)

        # Cannot disable primary admin
        res_dis = self.client.patch("/api/admin/users/admin", headers=self.admin_headers, data=json.dumps({
            "is_disabled": True
        }))
        self.assertEqual(res_dis.status_code, 400)

        # Cannot demote primary admin
        res_dem = self.client.patch("/api/admin/users/admin", headers=self.admin_headers, data=json.dumps({
            "role": "user"
        }))
        self.assertEqual(res_dem.status_code, 400)

    # 11. Multi-Tier RBAC Boundary Enforcement
    def test_rbac_boundary_denial(self):
        """Anonymous gets 401; regular user gets 403 on admin routes."""
        app.db_create_user("regular_judy", "JudyPass123", role="user")
        log = self.client.post("/api/auth/login", data=json.dumps({
            "user_id": "regular_judy",
            "password": "JudyPass123"
        }), headers={"Content-Type": "application/json"})
        judy_token = log.get_json()["token"]
        judy_headers = {"Authorization": f"Bearer {judy_token}", "Content-Type": "application/json"}

        admin_routes = [
            ("GET", "/api/admin/users"),
            ("POST", "/api/admin/users"),
            ("GET", "/api/admin/users/admin"),
            ("PATCH", "/api/admin/users/admin"),
            ("DELETE", "/api/admin/users/some_user"),
            ("POST", "/api/admin/users/some_user/password"),
            ("POST", "/api/admin/users/some_user/sessions/revoke"),
            ("POST", "/api/admin/users/update-privileges")
        ]

        for method, endpoint in admin_routes:
            # Anonymous check (401)
            anon_func = getattr(self.client, method.lower())
            res_anon = anon_func(endpoint, data=json.dumps({}))
            self.assertEqual(res_anon.status_code, 401, f"Expected 401 for anonymous on {method} {endpoint}")

            # Regular user check (403)
            user_func = getattr(self.client, method.lower())
            res_user = user_func(endpoint, headers=judy_headers, data=json.dumps({}))
            self.assertEqual(res_user.status_code, 403, f"Expected 403 for regular user on {method} {endpoint}")


if __name__ == "__main__":
    unittest.main()
