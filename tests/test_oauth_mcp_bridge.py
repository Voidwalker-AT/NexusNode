import unittest
import json
import base64
import hashlib
import secrets
import time
import urllib.parse
import config
from app import app, oauth_provider, agent_token_manager, get_db_connection
from agent.oauth_provider import OAuthProvider

class TestOAuthToMcpBridge(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.client_id = "test-gemini-bridge-client"
        self.client_secret = "test-secret-bridge-999"
        self.redirect_uri = "https://oauth-redirect.googleusercontent.com/test-bridge"
        
        oauth_provider.register_client(
            client_id=self.client_id,
            client_secret=self.client_secret,
            client_name="Test Gemini Bridge",
            redirect_uris=[self.redirect_uri]
        )
        self.orig_exposed = getattr(config, "MCP_EXPOSED_TOOLS", None)
        config.MCP_EXPOSED_TOOLS = None

    def tearDown(self):
        config.MCP_EXPOSED_TOOLS = self.orig_exposed

    def _get_oauth_access_token(self):
        verifier = secrets.token_urlsafe(32)
        v_bytes = verifier.encode('ascii')
        challenge = base64.urlsafe_b64encode(hashlib.sha256(v_bytes).digest()).decode('ascii').rstrip('=')
        
        auth_code, _ = oauth_provider.create_authorization_code(
            client_id=self.client_id,
            redirect_uri=self.redirect_uri,
            user_id="admin",
            scope="mcp",
            code_challenge=challenge,
            code_challenge_method="S256"
        )
        
        basic_auth = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        post_body = urllib.parse.urlencode({
            "grant_type": "authorization_code",
            "code": auth_code,
            "redirect_uri": self.redirect_uri,
            "code_verifier": verifier
        })
        token_resp = self.client.post("/oauth/token", data=post_body, content_type="application/x-www-form-urlencoded", headers={
            "Authorization": f"Basic {basic_auth}"
        })
        self.assertEqual(token_resp.status_code, 200)
        token_data = json.loads(token_resp.data.decode())
        return token_data["access_token"]

    def test_full_legacy_gemini_handshake_2024_11_05(self):
        access_token = self._get_oauth_access_token()
        
        # 1. Initialize with 2024-11-05
        mcp_req = {
            "jsonrpc": "2.0",
            "id": "gemini-init-1",
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "clientInfo": {"name": "Google-Gemini", "version": "1.0"},
                "capabilities": {}
            }
        }
        mcp_resp = self.client.post("/api/mcp", json=mcp_req, headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json, text/event-stream"
        })
        self.assertEqual(mcp_resp.status_code, 200)
        resp_data = json.loads(mcp_resp.data.decode())
        self.assertEqual(resp_data["result"]["protocolVersion"], "2024-11-05")
        self.assertIn("serverInfo", resp_data["result"])
        
        # 2. notifications/initialized
        notif_req = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
            "params": {}
        }
        notif_resp = self.client.post("/api/mcp", json=notif_req, headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json"
        })
        self.assertEqual(notif_resp.status_code, 204)
        
        # 3. tools/list
        list_req = {"jsonrpc": "2.0", "id": "gemini-list-2", "method": "tools/list", "params": {}}
        list_resp = self.client.post("/api/mcp", json=list_req, headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json"
        })
        self.assertEqual(list_resp.status_code, 200)
        list_data = json.loads(list_resp.data.decode())
        self.assertIn("tools", list_data["result"])
        tool_names = set(t["name"] for t in list_data["result"]["tools"])
        expected_tools = {
            "nexus.status", "academic.query", "academic.sync", "academic.analyze",
            "lms.query", "lms.fetch", "lms.prepare", "vault.manage",
            "document.process", "browser.interact", "action.status"
        }
        self.assertEqual(tool_names, expected_tools)

        # 4. tools/call nexus.status
        call_req = {
            "jsonrpc": "2.0",
            "id": "gemini-call-3",
            "method": "tools/call",
            "params": {
                "name": "nexus.status",
                "arguments": {}
            }
        }
        call_resp = self.client.post("/api/mcp", json=call_req, headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json"
        })
        self.assertEqual(call_resp.status_code, 200)
        call_data = json.loads(call_resp.data.decode())
        self.assertIn("content", call_data["result"])
        self.assertFalse(call_data["result"]["isError"])

    def test_modern_2026_07_28_negotiation(self):
        access_token = self._get_oauth_access_token()
        mcp_req = {
            "jsonrpc": "2.0",
            "id": "modern-1",
            "method": "initialize",
            "params": {
                "protocolVersion": "2026-07-28",
                "clientInfo": {"name": "Modern-MCP-Client", "version": "2.0"}
            }
        }
        mcp_resp = self.client.post("/api/mcp", json=mcp_req, headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json"
        })
        self.assertEqual(mcp_resp.status_code, 200)
        resp_data = json.loads(mcp_resp.data.decode())
        self.assertEqual(resp_data["result"]["protocolVersion"], "2026-07-28")

    def test_case_insensitive_bearer_header(self):
        access_token = self._get_oauth_access_token()
        mcp_req = {"jsonrpc": "2.0", "id": "case-1", "method": "initialize", "params": {"protocolVersion": "2024-11-05"}}
        mcp_resp = self.client.post("/api/mcp", json=mcp_req, headers={
            "Authorization": f"bearer {access_token}",
            "Accept": "application/json"
        })
        self.assertEqual(mcp_resp.status_code, 200)
        resp_data = json.loads(mcp_resp.data.decode())
        self.assertEqual(resp_data["result"]["protocolVersion"], "2024-11-05")

    def test_agent_token_authenticates(self):
        raw_ag_tok, _ = agent_token_manager.generate_token(principal="spark-agent", description="Test permanent token")
        mcp_req = {"jsonrpc": "2.0", "id": "ag-1", "method": "initialize", "params": {"protocolVersion": "2024-11-05"}}
        mcp_resp = self.client.post("/api/mcp", json=mcp_req, headers={
            "Authorization": f"Bearer {raw_ag_tok}",
            "Accept": "application/json"
        })
        self.assertEqual(mcp_resp.status_code, 200)

    def test_invalid_token_returns_401(self):
        mcp_req = {"jsonrpc": "2.0", "id": "inv-1", "method": "initialize", "params": {}}
        mcp_resp = self.client.post("/api/mcp", json=mcp_req, headers={
            "Authorization": "Bearer nexus_oat_invalidbogustoken12345",
            "Accept": "application/json"
        })
        self.assertEqual(mcp_resp.status_code, 401)
        self.assertIn("WWW-Authenticate", mcp_resp.headers)

    def test_revoked_oauth_token_returns_401(self):
        access_token = self._get_oauth_access_token()
        meta = oauth_provider.verify_access_token(access_token)
        self.assertIsNotNone(meta)
        oauth_provider.revoke_token(meta["token_id"])
        
        mcp_req = {"jsonrpc": "2.0", "id": "rev-1", "method": "initialize", "params": {}}
        mcp_resp = self.client.post("/api/mcp", json=mcp_req, headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json"
        })
        self.assertEqual(mcp_resp.status_code, 401)

    def test_persistence_across_provider_instance_restart(self):
        access_token = self._get_oauth_access_token()
        fresh_provider = OAuthProvider(get_db_connection)
        meta = fresh_provider.verify_access_token(access_token)
        self.assertIsNotNone(meta)
        self.assertEqual(meta["principal"], "spark-agent")

if __name__ == "__main__":
    unittest.main()
