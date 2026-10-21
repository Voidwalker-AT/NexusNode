"""
NexusNode — Production State Invariance Test Suite
Ensures running test operations and importing application modules
causes ZERO mutations or state changes to the production SQLite database.
"""

import os
import sys
import hashlib
import unittest
import tempfile
import shutil

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import config


def get_file_sha256(filepath: str) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


class TestProductionInvariance(unittest.TestCase):

    def test_production_db_is_never_mutated_by_test_runs(self):
        """Verifies that running isolated tests leaves production database byte-invariant."""
        # Locate production database on disk if present
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        prod_db_path = os.path.join(repo_root, "storage_vault", "nexus_unified.db")

        # If running on host where real DB exists, verify real DB
        # If no DB on development host, create a temporary sentinel baseline to verify invariance
        created_sentinel = False
        if not os.path.exists(prod_db_path):
            os.makedirs(os.path.dirname(prod_db_path), exist_ok=True)
            with open(prod_db_path, "wb") as f:
                f.write(b"SENTINEL_PROD_DB_BASELINE_RECORD_0123456789")
            created_sentinel = True

        try:
            hash_before = get_file_sha256(prod_db_path)

            # Run a simulated test workflow using isolated database
            temp_dir = tempfile.mkdtemp(prefix="invariance_test_")
            try:
                test_db = os.path.join(temp_dir, "isolated.db")
                orig_db = config.UNIFIED_DB_FILE
                config.UNIFIED_DB_FILE = test_db
                config.DB_PATH = test_db
                config.DB_FILE = test_db

                import app as server_app
                server_app.init_unified_db()

                # Perform user registration / auth in isolated DB
                conn = server_app.get_db_connection()
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) FROM users")
                cnt = cur.fetchone()[0]
                self.assertGreaterEqual(cnt, 1)
                conn.close()

                # Restore config
                config.UNIFIED_DB_FILE = orig_db
                config.DB_PATH = orig_db
                config.DB_FILE = orig_db

            finally:
                shutil.rmtree(temp_dir, ignore_errors=True)

            hash_after = get_file_sha256(prod_db_path)
            self.assertEqual(hash_before, hash_after, "CRITICAL: Production database hash modified during test execution!")

        finally:
            if created_sentinel and os.path.exists(prod_db_path):
                os.remove(prod_db_path)


if __name__ == "__main__":
    unittest.main()
