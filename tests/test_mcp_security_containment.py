"""
NexusNode — MCP Security Containment & Multi-Tenant Isolation Test Suite
Validates DEF-07 (Unauthenticated SSE & Session Principal Binding)
and DEF-08 (Cross-Tenant Vault Paths & Shared Timetable Fallbacks).
"""

import os
import sys
import json
import time
import uuid
import tempfile
import shutil
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import config
import app as server_app
from agent.vault_service import VaultService, VaultPathError, VaultAccessError
from timetable_sync import TimetableService


class TestMCPSecurityContainment(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        server_app.app.config['TESTING'] = True
        cls.client = server_app.app.test_client()

        cls.test_dir = tempfile.mkdtemp(prefix="nexus_mcp_sec_")
        cls.orig_storage = config.STORAGE_DIR
        cls.orig_db = config.UNIFIED_DB_FILE

        config.STORAGE_DIR = os.path.join(cls.test_dir, "storage_vault")
        config.BACKUP_DIR = os.path.join(config.STORAGE_DIR, "backups")
        config.UNIFIED_DB_FILE = os.path.join(config.STORAGE_DIR, "test_unified.db")
        config.DB_PATH = config.UNIFIED_DB_FILE
        config.DB_FILE = config.UNIFIED_DB_FILE
        config.AGENT_VAULT_ROOT = os.path.join(config.STORAGE_DIR, "user_files")

        os.makedirs(config.STORAGE_DIR, exist_ok=True)
        os.makedirs(config.BACKUP_DIR, exist_ok=True)
        os.makedirs(config.AGENT_VAULT_ROOT, exist_ok=True)

        server_app.init_unified_db()

        # Mint test agent tokens for User A and User B
        cls.token_a, cls.meta_a = server_app.agent_token_manager.generate_token(
            principal="agent-alice",
            user_id="alice",
            description="Alice Test Token"
        )
        cls.token_b, cls.meta_b = server_app.agent_token_manager.generate_token(
            principal="agent-bob",
            user_id="bob",
            description="Bob Test Token"
        )
        cls.token_admin, cls.meta_admin = server_app.agent_token_manager.generate_token(
            principal="agent-admin",
            user_id="admin",
            description="Admin Test Token"
        )

    @classmethod
    def tearDownClass(cls):
        config.STORAGE_DIR = cls.orig_storage
        config.UNIFIED_DB_FILE = cls.orig_db
        config.DB_PATH = cls.orig_db
        config.DB_FILE = cls.orig_db
        if os.path.exists(cls.test_dir):
            shutil.rmtree(cls.test_dir, ignore_errors=True)

    # =========================================================================
    # DEF-07: SSE Authentication & Session Principal Binding
    # =========================================================================

    def test_01_sse_unauthenticated_rejected(self):
        """Unauthenticated SSE requests to /sse and /api/mcp/sse must return HTTP 401."""
        res1 = self.client.get('/sse')
        self.assertEqual(res1.status_code, 401)
        self.assertIn("WWW-Authenticate", res1.headers)

        res2 = self.client.get('/api/mcp/sse')
        self.assertEqual(res2.status_code, 401)
        self.assertIn("WWW-Authenticate", res2.headers)

    def test_02_sse_invalid_token_rejected(self):
        """SSE requests with an invalid Bearer token must return HTTP 401."""
        headers = {"Authorization": "Bearer invalid_nexus_token_xyz"}
        res = self.client.get('/api/mcp/sse', headers=headers)
        self.assertEqual(res.status_code, 401)
        self.assertIn("invalid_token", res.headers.get("WWW-Authenticate", ""))

    def test_03_messages_unauthenticated_rejected(self):
        """POST /api/mcp/messages without token must return HTTP 401."""
        res = self.client.post('/api/mcp/messages?session_id=mock-123', json={"jsonrpc": "2.0"})
        self.assertEqual(res.status_code, 401)

    def test_04_messages_missing_session_id_rejected(self):
        """POST /api/mcp/messages with valid auth but missing session_id must return HTTP 400."""
        headers = {"Authorization": f"Bearer {self.token_a}"}
        res = self.client.post('/api/mcp/messages', headers=headers, json={"jsonrpc": "2.0"})
        self.assertEqual(res.status_code, 400)

    def test_05_messages_nonexistent_session_id_rejected(self):
        """POST /api/mcp/messages with non-existent session_id must return HTTP 404."""
        headers = {"Authorization": f"Bearer {self.token_a}"}
        res = self.client.post('/api/mcp/messages?session_id=fake-session-999', headers=headers, json={"jsonrpc": "2.0"})
        self.assertEqual(res.status_code, 404)

    def test_06_messages_cross_tenant_session_rejected(self):
        """User B cannot post messages to User A's SSE session (HTTP 403 Forbidden)."""
        # Register a simulated active SSE session owned by Alice
        session_id = f"test-sess-{uuid.uuid4().hex}"
        with server_app.SSE_CLIENTS_LOCK:
            server_app.SSE_CLIENTS[session_id] = {
                "queue": None,
                "user_id": "alice",
                "principal": "agent-alice",
                "created_at": time.time()
            }

        try:
            # Bob attempts to post to Alice's session
            headers_b = {"Authorization": f"Bearer {self.token_b}"}
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "nexus.status", "arguments": {}}
            }
            res = self.client.post(f'/api/mcp/messages?session_id={session_id}', headers=headers_b, json=payload)
            self.assertEqual(res.status_code, 403)
            data = res.get_json()
            self.assertIn("Forbidden", data["error"]["message"])
        finally:
            with server_app.SSE_CLIENTS_LOCK:
                if session_id in server_app.SSE_CLIENTS:
                    del server_app.SSE_CLIENTS[session_id]

    def test_07_public_discovery_endpoints_preserved(self):
        """Public OAuth metadata and server info endpoints must remain accessible without auth."""
        # GET /api/mcp without Accept: text/event-stream returns public metadata
        res = self.client.get('/api/mcp')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data.get("status"), "HEALTHY")
        self.assertTrue(data.get("mcp_enabled"))

        # RFC 9728 Protected Resource Metadata
        res_meta = self.client.get('/.well-known/oauth-protected-resource')
        self.assertEqual(res_meta.status_code, 200)
        self.assertIn("resource", res_meta.get_json())

        # RFC 8414 Authorization Server Metadata
        res_auth = self.client.get('/.well-known/oauth-authorization-server')
        self.assertEqual(res_auth.status_code, 200)
        self.assertIn("token_endpoint", res_auth.get_json())

    # =========================================================================
    # DEF-08: Cross-Tenant Vault Paths & Shared Timetable Fallbacks
    # =========================================================================

    def test_08_vault_cross_tenant_isolation(self):
        """User A creating a file in Vault cannot be seen or read by User B."""
        vault = VaultService(agent_vault_root=config.AGENT_VAULT_ROOT)

        # Alice creates a private file
        res_create = vault.create_file(
            user_id="alice",
            params={"path": "confidential_notes.txt", "content": "Alice's Secret Research"}
        )
        self.assertTrue(res_create.ok, f"Alice create failed: {res_create.error}")

        # Bob attempts to read Alice's file directly
        res_read_b = vault.read_file(
            user_id="bob",
            params={"path": "confidential_notes.txt"}
        )
        self.assertFalse(res_read_b.ok)
        self.assertEqual(res_read_b.error_code, "NOT_FOUND")

        # Bob lists his vault directory — must not see Alice's file
        res_list_b = vault.list_files(user_id="bob")
        self.assertTrue(res_list_b.ok)
        bob_files = [f["name"] for f in res_list_b.data.get("entries", [])]
        self.assertNotIn("confidential_notes.txt", bob_files)

        # Bob searches his vault — must not match Alice's content
        res_search_b = vault.search_vault(user_id="bob", params={"query": "Secret"})
        self.assertTrue(res_search_b.ok)
        self.assertEqual(len(res_search_b.data.get("results", [])), 0)

        # Alice reads her own file — must succeed
        res_read_a = vault.read_file(
            user_id="alice",
            params={"path": "confidential_notes.txt"}
        )
        self.assertTrue(res_read_a.ok)
        self.assertIn("Alice's Secret Research", res_read_a.data.get("text", ""))

    def test_09_vault_path_traversal_blocked(self):
        """Path traversal attempts (e.g. '../bob/file.txt') are strictly blocked."""
        vault = VaultService(agent_vault_root=config.AGENT_VAULT_ROOT)

        res = vault.read_file(user_id="alice", params={"path": "../bob/secret.txt"})
        self.assertFalse(res.ok)
        self.assertIn(res.error_code, ["INVALID_PATH", "ACCESS_DENIED"])

    def test_10_timetable_fallback_isolation(self):
        """Uploading User B's timetable does not overwrite User A's fallback timetable file."""
        conn_factory = lambda: server_app.get_db_connection()
        tt_svc = TimetableService(conn_factory)

        sample_json_a = json.dumps([{"CourseCode": "ALICE101", "CourseName": "CS1", "SessionDate": "2026-10-22", "StartTime": "09:00", "EndTime": "09:55", "SessionType": "Regular"}])
        sample_json_b = json.dumps([{"CourseCode": "BOB202", "CourseName": "CS2", "SessionDate": "2026-10-22", "StartTime": "10:00", "EndTime": "10:55", "SessionType": "Regular"}])

        ok_a, _, _ = tt_svc.upload_timetable("alice", sample_json_a)
        self.assertTrue(ok_a)
        ok_b, _, _ = tt_svc.upload_timetable("bob", sample_json_b)
        self.assertTrue(ok_b)

        path_a = os.path.join(config.STORAGE_DIR, "upes_timetable_alice.json")
        path_b = os.path.join(config.STORAGE_DIR, "upes_timetable_bob.json")

        self.assertTrue(os.path.exists(path_a), "Alice's isolated timetable fallback file must exist")
        self.assertTrue(os.path.exists(path_b), "Bob's isolated timetable fallback file must exist")

        with open(path_a, "r", encoding="utf-8") as f:
            content_a = f.read()
        with open(path_b, "r", encoding="utf-8") as f:
            content_b = f.read()

        self.assertIn("ALICE101", content_a)
        self.assertNotIn("BOB202", content_a)
        self.assertIn("BOB202", content_b)
        self.assertNotIn("ALICE101", content_b)


if __name__ == "__main__":
    unittest.main()
