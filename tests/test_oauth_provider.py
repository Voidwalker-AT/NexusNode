"""
Unit and Integration Tests for NexusNode MCP OAuth 2.0 Provider
Covers RFC 6749, RFC 7636 (PKCE), RFC 8414 Metadata, and MCP Gateway integration.
"""

import unittest
import json
import time
import base64
import hashlib
import sqlite3
from unittest.mock import patch, MagicMock

import app
import config
from agent.oauth_provider import OAuthProvider, init_oauth_tables, OAuthError, verify_pkce
from agent.policy import RiskClass


import tempfile
import os

class TestOAuthProviderUnit(unittest.TestCase):
    def setUp(self):
        self.temp_db = tempfile.NamedTemporaryFile(delete=False)
        self.temp_db.close()
        self.db_path = self.temp_db.name

        self.provider = OAuthProvider(lambda: sqlite3.connect(self.db_path))

        self.client_id = "test_client_123"
        self.client_secret = "test_secret_abc_456"
        self.redirect_uri = "https://oauth-redirect.googleusercontent.com/r/test-app"
        self.provider.register_client(
            client_id=self.client_id,
            client_secret=self.client_secret,
            client_name="Test Gemini Client",
            redirect_uris=[self.redirect_uri]
        )

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)


    def test_client_registration_and_validation(self):
        self.assertTrue(self.provider.validate_client_credentials(self.client_id, self.client_secret))
        self.assertFalse(self.provider.validate_client_credentials(self.client_id, "wrong_secret"))
        self.assertFalse(self.provider.validate_client_credentials("unknown_client", self.client_secret))

    def test_redirect_uri_validation(self):
        self.assertTrue(self.provider.validate_redirect_uri(self.client_id, self.redirect_uri))
        self.assertFalse(self.provider.validate_redirect_uri(self.client_id, "https://malicious.example.com/callback"))

    def test_pkce_verification(self):
        verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")

        self.assertTrue(verify_pkce(verifier, challenge, "S256"))
        self.assertFalse(verify_pkce("wrong_verifier", challenge, "S256"))
        self.assertTrue(verify_pkce("plain_challenge", "plain_challenge", "plain"))

    def test_authorization_code_lifecycle_and_replay_protection(self):
        raw_code, meta = self.provider.create_authorization_code(
            client_id=self.client_id,
            user_id="admin",
            redirect_uri=self.redirect_uri,
            scope="mcp"
        )
        self.assertTrue(raw_code.startswith("oauth_code_"))

        # Exchange code for token
        tokens = self.provider.exchange_authorization_code(
            client_id=self.client_id,
            code=raw_code,
            redirect_uri=self.redirect_uri
        )
        self.assertIn("access_token", tokens)
        self.assertIn("refresh_token", tokens)
        self.assertEqual(tokens["token_type"], "Bearer")
        self.assertEqual(tokens["expires_in"], 3600)

        # Replay attempt must fail
        with self.assertRaises(OAuthError) as ctx:
            self.provider.exchange_authorization_code(
                client_id=self.client_id,
                code=raw_code,
                redirect_uri=self.redirect_uri
            )
        self.assertEqual(ctx.exception.error, "invalid_grant")

    def test_pkce_enforcement_during_exchange(self):
        verifier = "my_secret_pkce_verifier_string_1234567890"
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")

        raw_code, meta = self.provider.create_authorization_code(
            client_id=self.client_id,
            user_id="admin",
            redirect_uri=self.redirect_uri,
            code_challenge=challenge,
            code_challenge_method="S256"
        )

        # Exchange without verifier must fail
        with self.assertRaises(OAuthError):
            self.provider.exchange_authorization_code(
                client_id=self.client_id,
                code=raw_code,
                redirect_uri=self.redirect_uri,
                code_verifier=None
            )

        # Exchange with correct verifier succeeds
        tokens = self.provider.exchange_authorization_code(
            client_id=self.client_id,
            code=raw_code,
            redirect_uri=self.redirect_uri,
            code_verifier=verifier
        )
        self.assertTrue(tokens["access_token"].startswith("nexus_oat_"))

    def test_access_token_verification_and_mcp_principal_mapping(self):
        raw_code, _ = self.provider.create_authorization_code(
            client_id=self.client_id,
            user_id="admin",
            redirect_uri=self.redirect_uri
        )
        tokens = self.provider.exchange_authorization_code(
            client_id=self.client_id,
            code=raw_code,
            redirect_uri=self.redirect_uri
        )

        # Verify access token
        meta = self.provider.verify_access_token(tokens["access_token"])
        self.assertIsNotNone(meta)
        self.assertEqual(meta["principal"], "spark-agent")
        self.assertIn("upes.attendance.read", meta["capabilities"])
        self.assertIn("lms.courses.read", meta["capabilities"])

    def test_refresh_token_rotation(self):
        raw_code, _ = self.provider.create_authorization_code(
            client_id=self.client_id,
            user_id="admin",
            redirect_uri=self.redirect_uri
        )
        tokens1 = self.provider.exchange_authorization_code(
            client_id=self.client_id,
            code=raw_code,
            redirect_uri=self.redirect_uri
        )

        # Refresh
        tokens2 = self.provider.refresh_access_token(
            client_id=self.client_id,
            refresh_token=tokens1["refresh_token"]
        )
        self.assertNotEqual(tokens1["access_token"], tokens2["access_token"])
        self.assertNotEqual(tokens1["refresh_token"], tokens2["refresh_token"])

        # Old refresh token is revoked
        with self.assertRaises(OAuthError):
            self.provider.refresh_access_token(
                client_id=self.client_id,
                refresh_token=tokens1["refresh_token"]
            )


class TestOAuthAppEndpoints(unittest.TestCase):
    def setUp(self):
        self.app = app.app
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

        self.client_id = "gemini_spark_test_client"
        self.client_secret = "gemini_spark_secret_xyz123"
        self.redirect_uri = "https://oauth-redirect.googleusercontent.com/r/user_bound_custom-mcp-test"

        # Register client
        app.oauth_provider.register_client(
            client_id=self.client_id,
            client_secret=self.client_secret,
            client_name="Gemini Spark",
            redirect_uris=[self.redirect_uri]
        )

    def test_oauth_metadata_endpoint(self):
        resp = self.client.get("/.well-known/oauth-authorization-server")
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertIn("authorization_endpoint", data)
        self.assertIn("token_endpoint", data)
        self.assertIn("response_types_supported", data)
        self.assertIn("code", data["response_types_supported"])
        self.assertIn("S256", data["code_challenge_methods_supported"])

    def test_authorize_requires_authentication(self):
        resp = self.client.get(
            f"/oauth/authorize?client_id={self.client_id}&redirect_uri={self.redirect_uri}&response_type=code"
        )
        # Should redirect to /login
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login", resp.headers["Location"])

    def test_authorize_consent_and_code_generation(self):
        # Authenticate session
        with self.client.session_transaction() as sess:
            sess["user_id"] = "admin"
            sess["role"] = "admin"

        # GET consent page
        resp = self.client.get(
            f"/oauth/authorize?client_id={self.client_id}&redirect_uri={self.redirect_uri}&response_type=code&state=test_state_123"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Gemini Spark", resp.data)

        # POST approve
        post_resp = self.client.post(
            "/oauth/authorize",
            data={
                "client_id": self.client_id,
                "redirect_uri": self.redirect_uri,
                "response_type": "code",
                "state": "test_state_123",
                "action": "approve"
            }
        )
        self.assertEqual(post_resp.status_code, 302)
        loc = post_resp.headers["Location"]
        self.assertTrue(loc.startswith(self.redirect_uri))
        self.assertIn("code=", loc)
        self.assertIn("state=test_state_123", loc)

    def test_end_to_end_oauth_to_mcp_flow(self):
        with self.client.session_transaction() as sess:
            sess["user_id"] = "admin"
            sess["role"] = "admin"

        # 1. Authorize
        auth_resp = self.client.post(
            "/oauth/authorize",
            data={
                "client_id": self.client_id,
                "redirect_uri": self.redirect_uri,
                "response_type": "code",
                "state": "corr_999",
                "action": "approve"
            }
        )
        loc = auth_resp.headers["Location"]
        # Extract code
        import urllib.parse
        parsed = urllib.parse.urlparse(loc)
        q = urllib.parse.parse_qs(parsed.query)
        auth_code = q["code"][0]

        # 2. Token Exchange (using form-urlencoded and client_secret_post)
        token_resp = self.client.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "code": auth_code,
                "redirect_uri": self.redirect_uri
            }
        )
        self.assertEqual(token_resp.status_code, 200)
        tok_data = json.loads(token_resp.data)
        access_token = tok_data["access_token"]
        self.assertTrue(access_token.startswith("nexus_oat_"))

        # 3. Call MCP with OAuth Bearer Token
        mcp_resp = self.client.post(
            "/api/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "nexus.status",
                    "arguments": {}
                }
            },
            headers={"Authorization": f"Bearer {access_token}"}
        )
        self.assertEqual(mcp_resp.status_code, 200)
        res_json = json.loads(mcp_resp.data)
        self.assertNotIn("error", res_json)
        self.assertIn("result", res_json)

    def test_consequential_action_still_requires_approval_under_oauth(self):
        with self.client.session_transaction() as sess:
            sess["user_id"] = "admin"

        auth_resp = self.client.post(
            "/oauth/authorize",
            data={
                "client_id": self.client_id,
                "redirect_uri": self.redirect_uri,
                "action": "approve"
            }
        )
        import urllib.parse
        auth_code = urllib.parse.parse_qs(urllib.parse.urlparse(auth_resp.headers["Location"]).query)["code"][0]

        token_resp = self.client.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "code": auth_code,
                "redirect_uri": self.redirect_uri
            }
        )
        access_token = json.loads(token_resp.data)["access_token"]

        # Call consequential action lms.submit_assignment under legacy catalog mode
        orig_mode = getattr(config, "MCP_CATALOG_MODE", "semantic")
        config.MCP_CATALOG_MODE = "legacy"
        try:
            mcp_resp = self.client.post(
                "/api/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": "lms.submit_assignment",
                        "arguments": {
                            "submission_plan_id": "subplan_test_nonexistent"
                        }
                    }
                },
                headers={"Authorization": f"Bearer {access_token}"}
            )
            self.assertEqual(mcp_resp.status_code, 200)
            result_text = mcp_resp.json["result"]["content"][0]["text"]
            result_data = json.loads(result_text)
            # Must require separate approval or plan validation, cannot bypass
            self.assertFalse(result_data["ok"])
        finally:
            config.MCP_CATALOG_MODE = orig_mode


if __name__ == "__main__":
    unittest.main()
