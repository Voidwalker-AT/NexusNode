"""
Regression tests for NexusNode startup initialization order.

Catches the NameError: name 'hash_password' is not defined regression
where init_unified_db() was called at module import time before
hash_password() was defined.
"""

import os
import sys
import json
import time
import types
import shutil
import sqlite3
import hashlib
import secrets
import tempfile
import unittest
import importlib

# Ensure the project root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config


class TestAppModuleStartup(unittest.TestCase):
    """Tests that the app module imports without NameError or other startup regressions."""

    def test_app_module_imports_cleanly(self):
        """
        Regression test: importing app.py must NOT raise NameError.
        This catches the exact bug where init_unified_db() calls hash_password()
        at import time before hash_password() is defined.
        """
        try:
            import app
        except NameError as e:
            self.fail(
                f"app.py raised NameError during import (startup order regression): {e}"
            )
        except Exception:
            # Other errors (e.g. missing DB path) are not the startup-order bug
            pass

    def test_hash_password_is_callable(self):
        """hash_password must be importable and callable from the app module."""
        import app
        self.assertTrue(callable(app.hash_password))

    def test_verify_password_is_callable(self):
        """verify_password must be importable and callable from the app module."""
        import app
        self.assertTrue(callable(app.verify_password))

    def test_init_unified_db_is_callable(self):
        """init_unified_db must be importable and callable from the app module."""
        import app
        self.assertTrue(callable(app.init_unified_db))


class TestInitUnifiedDbStartup(unittest.TestCase):
    """Tests init_unified_db works on fresh and existing databases."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="nexus_startup_test_")
        self.db_path = os.path.join(self.test_dir, "test_nexus.db")
        self.rag_path = os.path.join(self.test_dir, "test_rag.db")
        self.storage_dir = os.path.join(self.test_dir, "storage_vault")
        os.makedirs(self.storage_dir, exist_ok=True)

        # Override config paths for isolated testing
        self._orig_db = config.UNIFIED_DB_FILE
        self._orig_rag = config.RAG_DB_FILE
        self._orig_storage = config.STORAGE_DIR
        config.UNIFIED_DB_FILE = self.db_path
        config.RAG_DB_FILE = self.rag_path
        config.STORAGE_DIR = self.storage_dir

    def tearDown(self):
        config.UNIFIED_DB_FILE = self._orig_db
        config.RAG_DB_FILE = self._orig_rag
        config.STORAGE_DIR = self._orig_storage
        try:
            shutil.rmtree(self.test_dir, ignore_errors=True)
        except Exception:
            pass

    def test_init_unified_db_with_fresh_database(self):
        """init_unified_db must create all tables on a fresh database without error."""
        import app

        # Ensure no database exists yet
        self.assertFalse(os.path.exists(self.db_path))

        # Run initialization — must NOT raise NameError or any other error
        app.init_unified_db()

        # Verify database was created
        self.assertTrue(os.path.exists(self.db_path))

        # Verify core tables exist
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;")
        tables = sorted([row[0] for row in cur.fetchall()])
        conn.close()

        for required in ["users", "system_logs", "background_tasks", "shares",
                         "backups", "scheduled_jobs", "incidents"]:
            self.assertIn(required, tables, f"Missing required table: {required}")

    def test_init_unified_db_existing_database(self):
        """init_unified_db must be idempotent — running twice on existing DB must not error."""
        import app

        app.init_unified_db()
        # Run again on existing DB — must not crash
        app.init_unified_db()

        # Verify admin still exists and there's exactly one
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM users WHERE user_id = 'admin';")
        count = cur.fetchone()[0]
        conn.close()
        self.assertEqual(count, 1, "Admin account should exist exactly once after double init")

    def test_admin_seed_uses_current_password_kdf(self):
        """Default admin password must be hashed with PBKDF2, not legacy SHA-256."""
        import app

        app.init_unified_db()

        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT password_hash, salt FROM users WHERE user_id = 'admin';")
        row = cur.fetchone()
        conn.close()

        self.assertIsNotNone(row, "Admin user must exist after init")
        pwd_hash = row[0]
        self.assertTrue(
            pwd_hash.startswith("pbkdf2_sha256$"),
            f"Admin password must use PBKDF2 format, got: {pwd_hash[:30]}..."
        )

        # Verify it can be verified
        is_valid, needs_upgrade = app.verify_password("Admin@1234", pwd_hash)
        self.assertTrue(is_valid, "Admin default password must verify correctly")
        self.assertFalse(needs_upgrade, "Fresh PBKDF2 hash should NOT need upgrade")

    def test_init_with_legacy_sha256_admin_does_not_crash(self):
        """
        If the database already has an admin with legacy SHA-256 hash,
        init_unified_db must not crash (admin already exists, seed is skipped).
        """
        import app

        # Manually create a database with a legacy SHA-256 admin
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user',
                is_disabled INTEGER NOT NULL DEFAULT 0,
                privileges TEXT NOT NULL DEFAULT '{}',
                created_at REAL NOT NULL,
                failed_attempts INTEGER NOT NULL DEFAULT 0,
                locked_until REAL NOT NULL DEFAULT 0.0
            );
        """)
        legacy_salt = secrets.token_hex(16)
        legacy_hash = hashlib.sha256(("Admin@1234" + legacy_salt).encode()).hexdigest()
        conn.execute(
            "INSERT INTO users (user_id, password_hash, salt, role, privileges, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            ("admin", legacy_hash, legacy_salt, "admin", "{}", time.time())
        )
        conn.commit()
        conn.close()

        # init_unified_db must not crash when admin already exists with legacy hash
        app.init_unified_db()

        # Legacy admin hash must still be intact
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT password_hash FROM users WHERE user_id = 'admin';")
        stored_hash = cur.fetchone()[0]
        conn.close()

        # It should still be the legacy hash (init doesn't overwrite existing)
        self.assertEqual(stored_hash, legacy_hash)

        # Legacy hash must verify and flag for upgrade
        is_valid, needs_upgrade = app.verify_password("Admin@1234", stored_hash, legacy_salt)
        self.assertTrue(is_valid, "Legacy SHA-256 password must still verify")
        self.assertTrue(needs_upgrade, "Legacy hash must flag needs_upgrade=True")


if __name__ == "__main__":
    unittest.main()
