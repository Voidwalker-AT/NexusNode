"""
Authoritative Gemini Spark & MCP Compliance Test Suite
Validates RFC 9728, RFC 8414, RFC 7636 (PKCE S256), RFC 6749, and MCP Streamable HTTP protocols.
"""

import unittest
import json
import base64
import hashlib
import sqlite3
import os
import secrets
import config
from app import app, get_db_connection, agent_registry, oauth_provider, agent_token_manager
import agent


class TestGeminiSparkCompliance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config['TESTING'] = True
        app.config['MCP_ENABLED'] = True
        app.config['PUBLIC_ISSUER_URL'] = 'https://compliance-test.trycloudflare.com'
        cls.client = app.test_client()

        # Seed test client
        cls.client_id = "test-spark-client"
        cls.client_secret = "test-spark-secret-" + secrets.token_hex(16)
        cls.redirect_uri = "https://oauth-redirect.googleusercontent.com/r/user_bound_compliance_test"
        oauth_provider.register_client(
            client_name="Test Spark Connected App",
            redirect_uris=[cls.redirect_uri],
            client_id=cls.client_id,
            client_secret=cls.client_secret
        )

    def setUp(self):
        self.orig_exposed = getattr(config, "MCP_EXPOSED_TOOLS", None)
        config.MCP_EXPOSED_TOOLS = None

    def tearDown(self):
        config.MCP_EXPOSED_TOOLS = self.orig_exposed

    def test_01_mcp_unauthenticated_challenge(self):
        """HEAD and POST /api/mcp without token must return 401 with standard WWW-Authenticate challenge."""
        resp_head = self.client.head('/api/mcp')
        self.assertEqual(resp_head.status_code, 401)
        self.assertIn("WWW-Authenticate", resp_head.headers)
        self.assertIn(".well-known/oauth-protected-resource/api/mcp", resp_head.headers["WWW-Authenticate"])
        self.assertEqual(resp_head.headers.get("MCP-Protocol-Version"), "2026-07-28")

        resp_post = self.client.post('/api/mcp', json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        self.assertEqual(resp_post.status_code, 401)
        self.assertIn("WWW-Authenticate", resp_post.headers)
        self.assertIn(".well-known/oauth-protected-resource/api/mcp", resp_post.headers["WWW-Authenticate"])

    def test_02_protected_resource_metadata_rfc9728(self):
        """GET /.well-known/oauth-protected-resource/api/mcp must return RFC 9728 metadata."""
        resp = self.client.get('/.well-known/oauth-protected-resource/api/mcp')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data.decode('utf-8'))
        self.assertEqual(data.get("resource"), "https://compliance-test.trycloudflare.com/api/mcp")
        self.assertIn("https://compliance-test.trycloudflare.com", data.get("authorization_servers", []))
        self.assertIn("mcp", data.get("scopes_supported", []))
        self.assertIn("header", data.get("bearer_methods_supported", []))

    def test_03_authorization_server_metadata_rfc8414(self):
        """GET /.well-known/oauth-authorization-server must return standard RFC 8414 metadata."""
        resp = self.client.get('/.well-known/oauth-authorization-server')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data.decode('utf-8'))
        self.assertEqual(data.get("issuer"), "https://compliance-test.trycloudflare.com")
        self.assertEqual(data.get("authorization_endpoint"), "https://compliance-test.trycloudflare.com/oauth/authorize")
        self.assertEqual(data.get("token_endpoint"), "https://compliance-test.trycloudflare.com/oauth/token")
        self.assertIn("client_secret_basic", data.get("token_endpoint_auth_methods_supported", []))
        self.assertIn("client_secret_post", data.get("token_endpoint_auth_methods_supported", []))
        self.assertIn("S256", data.get("code_challenge_methods_supported", []))

    def test_04_full_oauth_pkce_authorization_code_flow(self):
        """Complete OAuth 2.0 PKCE S256 code grant and token exchange."""
        # 1. Generate PKCE verifier and challenge
        verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
        digest = hashlib.sha256(verifier.encode('ascii')).digest()
        challenge = base64.urlsafe_b64encode(digest).decode('ascii').rstrip('=')

        # 2. Create authorization code on server
        raw_code, meta = oauth_provider.create_authorization_code(
            client_id=self.client_id,
            user_id="admin",
            redirect_uri=self.redirect_uri,
            scope="mcp",
            code_challenge=challenge,
            code_challenge_method="S256"
        )
        self.assertTrue(raw_code.startswith("oauth_code_"))

        # 3. Exchange code for tokens using Basic client authentication
        basic_creds = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        resp = self.client.post('/oauth/token', data={
            "grant_type": "authorization_code",
            "code": raw_code,
            "redirect_uri": self.redirect_uri,
            "code_verifier": verifier
        }, headers={"Authorization": f"Basic {basic_creds}"})

        self.assertEqual(resp.status_code, 200)
        tokens = json.loads(resp.data.decode('utf-8'))
        self.assertIn("access_token", tokens)
        self.assertEqual(tokens.get("token_type"), "Bearer")
        self.assertEqual(tokens.get("expires_in"), 3600)
        self.assertIn("refresh_token", tokens)

        # 4. Use access token to execute authenticated MCP initialize request
        access_token = tokens["access_token"]
        init_req = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2026-07-28",
                "capabilities": {},
                "clientInfo": {"name": "Gemini-Spark-Test", "version": "1.0.0"}
            }
        }
        resp_mcp = self.client.post('/api/mcp', json=init_req, headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        })
        self.assertEqual(resp_mcp.status_code, 200)
        init_res = json.loads(resp_mcp.data.decode('utf-8'))
        self.assertEqual(init_res.get("result", {}).get("protocolVersion"), "2026-07-28")

        # 5. List tools
        tools_req = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
        resp_tools = self.client.post('/api/mcp', json=tools_req, headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        })
        self.assertEqual(resp_tools.status_code, 200)
        tools_res = json.loads(resp_tools.data.decode('utf-8'))
        tool_list = tools_res.get("result", {}).get("tools", [])
        tool_names = {t["name"] for t in tool_list}
        expected_tools = {
            "nexus.status", "academic.query", "academic.sync", "academic.analyze",
            "lms.query", "lms.fetch", "lms.prepare", "vault.manage",
            "document.process", "browser.interact", "action.status"
        }
        self.assertEqual(tool_names, expected_tools)

        # 6. Call nexus.status
        call_req = {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "nexus.status", "arguments": {}}
        }
        resp_call = self.client.post('/api/mcp', json=call_req, headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        })
        self.assertEqual(resp_call.status_code, 200)
        call_res = json.loads(resp_call.data.decode('utf-8'))
        self.assertIn("content", call_res.get("result", {}))

    def test_05_single_use_code_enforcement(self):
        """Authorization codes must be single-use and reject replays."""
        raw_code, _ = oauth_provider.create_authorization_code(
            client_id=self.client_id,
            user_id="admin",
            redirect_uri=self.redirect_uri
        )
        basic_creds = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()

        # First exchange succeeds
        resp1 = self.client.post('/oauth/token', data={
            "grant_type": "authorization_code",
            "code": raw_code,
            "redirect_uri": self.redirect_uri
        }, headers={"Authorization": f"Basic {basic_creds}"})
        self.assertEqual(resp1.status_code, 200)

        # Replay attempt must fail with invalid_grant
        resp2 = self.client.post('/oauth/token', data={
            "grant_type": "authorization_code",
            "code": raw_code,
            "redirect_uri": self.redirect_uri
        }, headers={"Authorization": f"Basic {basic_creds}"})
        self.assertEqual(resp2.status_code, 400)
        err = json.loads(resp2.data.decode('utf-8'))
        self.assertEqual(err.get("error"), "invalid_grant")


if __name__ == '__main__':
    unittest.main()
