"""
NexusNode — Production Hardening, RBAC, Storage Safety & Playback Security Tests
Comprehensive test suite verifying all hardened subsystems using Python stdlib unittest.
"""

import hashlib
import os
import shutil
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch

import app
import config


class TestPBKDF2PasswordSecurity(unittest.TestCase):
    """Verify PBKDF2 hashing, verification, iterations, and transparent migration."""

    def test_hash_format(self):
        pwd = "SecurePassword123!"
        hashed, salt = app.hash_password(pwd)
        parts = hashed.split("$")
        self.assertEqual(len(parts), 4, f"Hash format must have 4 parts: {hashed}")
        self.assertEqual(parts[0], "pbkdf2_sha256")
        self.assertTrue(parts[1].isdigit())
        self.assertGreaterEqual(int(parts[1]), 10000)
        self.assertEqual(len(parts[2]), 32)  # 16-byte hex salt
        self.assertEqual(len(parts[3]), 64)  # 32-byte SHA256 hex digest

    def test_verify_correct_password(self):
        pwd = "CorrectHorseBatteryStaple"
        hashed, salt = app.hash_password(pwd)
        valid, needs_upgrade = app.verify_password(pwd, hashed)
        self.assertTrue(valid)
        self.assertFalse(needs_upgrade)

    def test_verify_wrong_password(self):
        pwd = "CorrectPassword123"
        hashed, salt = app.hash_password(pwd)
        valid, needs_upgrade = app.verify_password("WrongPassword123", hashed)
        self.assertFalse(valid)
        self.assertFalse(needs_upgrade)

    def test_legacy_sha256_verification_and_upgrade_flag(self):
        pwd = "LegacyPassword123"
        legacy_salt = "0123456789abcdef"
        legacy_hash = hashlib.sha256((pwd + legacy_salt).encode("utf-8")).hexdigest()
        
        valid, needs_upgrade = app.verify_password(pwd, legacy_hash, salt=legacy_salt)
        self.assertTrue(valid)
        self.assertTrue(needs_upgrade)

        # Wrong password against legacy hash
        valid_wrong, _ = app.verify_password("WrongLegacyPwd", legacy_hash, salt=legacy_salt)
        self.assertFalse(valid_wrong)


class TestStorageSafetyAndCanonicalization(unittest.TestCase):
    """Verify canonical storage categories, case migration, and safe destination traversal validation."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="nexus_test_storage_")
        self.orig_storage = config.STORAGE_DIR
        config.STORAGE_DIR = self.test_dir

    def tearDown(self):
        config.STORAGE_DIR = self.orig_storage
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_validate_safe_destination_valid_categories(self):
        for cat in ["downloads", "music", "videos", "podcasts", "documents", "other"]:
            rel = app.validate_safe_destination(cat)
            self.assertEqual(rel, cat)

    def test_validate_safe_destination_canonicalizes_casing(self):
        rel = app.validate_safe_destination("Music/subfolder")
        self.assertEqual(rel, "music/subfolder")

    def test_validate_safe_destination_rejects_directory_traversal(self):
        traversal_attempts = [
            "../etc/passwd",
            "..\\windows\\system32",
            "music/../../shadow",
            "/absolute/root/path",
            "C:\\secret\\file.txt",
            "....//....//etc",
        ]
        for attempt in traversal_attempts:
            with self.assertRaises(ValueError):
                app.validate_safe_destination(attempt)

    def test_validate_safe_destination_rejects_protected_internal_paths(self):
        protected_targets = [
            "backups",
            "rag",
            ".git",
            ".ssh",
            "backups/vault_backup.db",
            "music/.env",
            "downloads/app.db",
            "videos/rag_index.json",
            "documents/localtonet.log",
        ]
        for prot in protected_targets:
            with self.assertRaises(ValueError):
                app.validate_safe_destination(prot)

    def test_migrate_storage_casing_if_needed(self):
        # Create legacy uppercase directories with mock files
        legacy_music = os.path.join(self.test_dir, "Music")
        os.makedirs(legacy_music, exist_ok=True)
        test_file = os.path.join(legacy_music, "track.mp3")
        with open(test_file, "w") as f:
            f.write("mock audio data")

        app.migrate_storage_casing_if_needed()

        canonical_music = os.path.join(self.test_dir, "music")
        self.assertTrue(os.path.exists(canonical_music))
        migrated_file = os.path.join(canonical_music, "track.mp3")
        self.assertTrue(os.path.exists(migrated_file))


class TestPlaybackTokenSecurity(unittest.TestCase):
    """Verify short-lived playback token creation, binding, path isolation, and expiration."""

    def setUp(self):
        app.PLAYBACK_TOKENS.clear()

    def test_create_and_verify_playback_token(self):
        user_id = "admin"
        path = "music/synthwave_groove.mp3"
        token = app.create_playback_token(user_id, path, ttl_seconds=60)
        self.assertTrue(token)
        self.assertGreater(len(token), 20)

        # Verify matching token
        valid, msg = app.verify_playback_token(token, path)
        self.assertTrue(valid)
        self.assertEqual(msg, "Valid")

    def test_reject_token_for_different_path(self):
        user_id = "admin"
        token = app.create_playback_token(user_id, "music/song_a.mp3", ttl_seconds=60)

        valid, msg = app.verify_playback_token(token, "music/song_b.mp3")
        self.assertFalse(valid)
        self.assertIn("not valid for this media path", msg)

    def test_reject_expired_playback_token(self):
        user_id = "admin"
        path = "videos/presentation.mp4"
        # Token with -1s TTL
        token = app.create_playback_token(user_id, path, ttl_seconds=-1)

        valid, msg = app.verify_playback_token(token, path)
        self.assertFalse(valid)
        self.assertIn("expired", msg.lower())

    def test_reject_nonexistent_token(self):
        valid, msg = app.verify_playback_token("invalid_opaque_token_xyz", "music/song.mp3")
        self.assertFalse(valid)
        self.assertIn("invalid", msg.lower())


class TestUserGovernanceAndRBACAPIs(unittest.TestCase):
    """Verify user administration, password resets, session revoking, and status enforcement."""

    def setUp(self):
        self.temp_db_fd, self.temp_db_path = tempfile.mkstemp(prefix="nexus_test_db_", suffix=".db")
        self.orig_db = config.UNIFIED_DB_FILE
        config.UNIFIED_DB_FILE = self.temp_db_path
        config.DB_PATH = self.temp_db_path
        config.AUDIT_DB_FILE = self.temp_db_path
        app.init_unified_db()

        self.client = app.app.test_client()
        self.app_context = app.app.app_context()
        self.app_context.push()

        # Login as admin to get auth token
        resp = self.client.post("/api/auth/login", json={"username": "admin", "password": "Admin@1234"})
        self.assertEqual(resp.status_code, 200)
        self.admin_token = resp.get_json()["token"]
        self.admin_headers = {"Authorization": f"Bearer {self.admin_token}"}

    def tearDown(self):
        self.app_context.pop()
        os.close(self.temp_db_fd)
        config.UNIFIED_DB_FILE = self.orig_db
        config.DB_PATH = self.orig_db
        config.AUDIT_DB_FILE = self.orig_db
        if os.path.exists(self.temp_db_path):
            try:
                os.remove(self.temp_db_path)
            except Exception:
                pass

    def test_get_privileges_metadata(self):
        resp = self.client.get("/api/admin/privileges", headers=self.admin_headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("privileges", data)
        self.assertIn("defaults", data)
        priv_keys = [p["key"] for p in data["privileges"]]
        self.assertIn("can_upload_files", priv_keys)
        self.assertIn("can_manage_users", priv_keys)

    def test_create_and_manage_user_lifecycle(self):
        # 1. Create user
        new_user = {
            "user_id": "operator_bob",
            "password": "InitialPassword123!",
            "role": "user",
            "privileges": {"can_upload_files": True, "can_use_ai": False}
        }
        resp = self.client.post("/api/admin/users", json=new_user, headers=self.admin_headers)
        self.assertEqual(resp.status_code, 201)
        res_data = resp.get_json()
        self.assertEqual(res_data["user_id"], "operator_bob")

        # 2. Login as new user
        user_login = self.client.post("/api/auth/login", json={"username": "operator_bob", "password": "InitialPassword123!"})
        self.assertEqual(user_login.status_code, 200)
        user_token = user_login.get_json()["token"]
        user_headers = {"Authorization": f"Bearer {user_token}"}

        # 3. User self-service change password
        pwd_change = self.client.post("/api/account/password", json={
            "current_password": "InitialPassword123!",
            "new_password": "NewSecretPassword456!"
        }, headers=user_headers)
        self.assertEqual(pwd_change.status_code, 200)

        # 4. Old password fails, new password succeeds
        old_login = self.client.post("/api/auth/login", json={"username": "operator_bob", "password": "InitialPassword123!"})
        self.assertEqual(old_login.status_code, 401)
        new_login = self.client.post("/api/auth/login", json={"username": "operator_bob", "password": "NewSecretPassword456!"})
        self.assertEqual(new_login.status_code, 200)

        # 5. Admin disables user
        patch_resp = self.client.patch("/api/admin/users/operator_bob", json={"is_disabled": True}, headers=self.admin_headers)
        self.assertEqual(patch_resp.status_code, 200)
        self.assertTrue(patch_resp.get_json()["user_id"] == "operator_bob")

        # 6. Disabled user login rejected with 403
        dis_login = self.client.post("/api/auth/login", json={"username": "operator_bob", "password": "NewSecretPassword456!"})
        self.assertEqual(dis_login.status_code, 403)
        self.assertIn("disabled", dis_login.get_json()["error"].lower())

        # 7. Admin password reset
        reset_resp = self.client.post("/api/admin/users/operator_bob/password", json={"password": "AdminResetPassword789!"}, headers=self.admin_headers)
        self.assertEqual(reset_resp.status_code, 200)

        # 8. Admin re-enables user
        enable_resp = self.client.patch("/api/admin/users/operator_bob", json={"is_disabled": False}, headers=self.admin_headers)
        self.assertEqual(enable_resp.status_code, 200)

        # 9. Login with reset password succeeds
        reset_login = self.client.post("/api/auth/login", json={"username": "operator_bob", "password": "AdminResetPassword789!"})
        self.assertEqual(reset_login.status_code, 200)

        # 10. Delete user
        del_resp = self.client.delete("/api/admin/users/operator_bob", headers=self.admin_headers)
        self.assertEqual(del_resp.status_code, 200)

    def test_prevent_primary_admin_deletion_or_disabling(self):
        # Attempt to delete primary admin
        del_resp = self.client.delete("/api/admin/users/admin", headers=self.admin_headers)
        self.assertEqual(del_resp.status_code, 400)
        self.assertIn("cannot delete", del_resp.get_json()["error"].lower())

        # Attempt to disable primary admin
        dis_resp = self.client.patch("/api/admin/users/admin", json={"is_disabled": True}, headers=self.admin_headers)
        self.assertEqual(dis_resp.status_code, 400)
        self.assertIn("cannot disable", dis_resp.get_json()["error"].lower())


class TestLoggingDurabilityAndRetention(unittest.TestCase):
    """Verify log sanitization, retention sweep tracking, and emergency fallback."""

    def test_mask_sensitive_data(self):
        sensitive_log = "User logged in with password=MySecretPass and token=a1b2c3d4e5f6g7h8"
        masked = app.mask_sensitive_data(sensitive_log)
        self.assertNotIn("MySecretPass", masked)
        self.assertIn("[REDACTED_TOKEN]", masked)

    def test_retention_sweep_metrics(self):
        app.run_retention_sweep_job()
        metrics = app.RETENTION_METRICS
        self.assertIn("last_cleanup", metrics)
        self.assertGreater(metrics["last_cleanup"], 0)
        self.assertIn("cleanup_duration_ms", metrics)


if __name__ == "__main__":
    unittest.main()
