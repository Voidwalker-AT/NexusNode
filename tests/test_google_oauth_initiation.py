"""
NexusNode — Google OAuth Initiation & CSRF Binding Regression Test Suite
========================================================================
Independently verifies:
1. Unauthenticated initiation is rejected with HTTP 401.
2. Authenticated initiation returns Google consent URL and CSRF state token with HTTP 200.
3. No Bearer tokens or sensitive secrets are leaked into query strings or URLs.
4. Role and privilege checks (can_sync_timetable or admin role) are strictly enforced.
5. OAuth state tokens are cryptographically bound to initiating user_id in SQLite.
6. OAuth state tokens are consumed upon first use (replay prevention).
7. Cross-user session mismatch on callback is rejected with HTTP 403 (tenant isolation).
8. Successful callback securely persists tokens and redirects to /#tab-accounts?google_auth=success.
9. Static UI templates do not expose direct unauthenticated <a href="/api/auth/google/authorize"> tags.
"""

import time
import os
import re
import unittest
from unittest.mock import patch, MagicMock

import app
import config
import timetable_sync


class TestGoogleOAuthInitiation(unittest.TestCase):

    def setUp(self):
        app.app.config["TESTING"] = True
        self.client = app.app.test_client()

        # Generate unique test tokens
        self.admin_token = "test_admin_oauth_tok_" + os.urandom(8).hex()
        self.user_token = "test_user_oauth_tok_" + os.urandom(8).hex()
        self.nopriv_token = "test_nopriv_oauth_tok_" + os.urandom(8).hex()

        with app.SESSIONS_LOCK:
            app.SESSIONS[self.admin_token] = {
                "user_id": "admin",
                "role": "admin",
                "privileges": dict(config.ADMIN_DEFAULT_PRIVILEGES),
                "created_at": time.time(),
                "expires_at": time.time() + 3600
            }
            app.SESSIONS[self.user_token] = {
                "user_id": "student_authorized",
                "role": "user",
                "privileges": {"can_sync_timetable": True},
                "created_at": time.time(),
                "expires_at": time.time() + 3600
            }
            app.SESSIONS[self.nopriv_token] = {
                "user_id": "student_unprivileged",
                "role": "user",
                "privileges": {"can_sync_timetable": False},
                "created_at": time.time(),
                "expires_at": time.time() + 3600
            }

        self.admin_headers = {"Authorization": f"Bearer {self.admin_token}"}
        self.user_headers = {"Authorization": f"Bearer {self.user_token}"}
        self.nopriv_headers = {"Authorization": f"Bearer {self.nopriv_token}"}

    def tearDown(self):
        with app.SESSIONS_LOCK:
            for tok in [self.admin_token, self.user_token, self.nopriv_token]:
                if tok in app.SESSIONS:
                    del app.SESSIONS[tok]

    # 1. Unauthenticated initiation
    def test_01_unauthenticated_initiation_rejected(self):
        """Unauthenticated requests to /api/auth/google/authorize must return 401."""
        res1 = self.client.get("/api/auth/google/authorize")
        self.assertEqual(res1.status_code, 401)
        data1 = res1.get_json()
        self.assertEqual(data1.get("error"), "unauthorized")

        res2 = self.client.get("/api/auth/google")
        self.assertEqual(res2.status_code, 401)

    # 2. Authenticated initiation
    def test_02_authenticated_initiation_success(self):
        """Authenticated requests with Bearer token must return JSON with authorization_url and state."""
        # Ensure dummy Google OAuth credentials exist for test
        with patch("timetable_sync.get_shared_google_oauth_config", return_value={
            "client_id": "test_client_id.apps.googleusercontent.com",
            "client_secret": "test_secret",
            "redirect_uri": "https://k09oezeyib.localto.net/api/auth/google/callback"
        }):
            res = self.client.get("/api/auth/google/authorize", headers=self.admin_headers)
            self.assertEqual(res.status_code, 200)
            data = res.get_json()

            self.assertIn("authorization_url", data)
            self.assertIn("state", data)

            auth_url = data["authorization_url"]
            state = data["state"]

            # Must point to official Google OAuth endpoint
            self.assertTrue(auth_url.startswith("https://accounts.google.com/o/oauth2/v2/auth"))
            self.assertIn("client_id=test_client_id.apps.googleusercontent.com", auth_url)
            self.assertIn("state=" + state, auth_url)
            self.assertIn("scope=", auth_url)

            # Verify state token is recorded in DB bound to user 'admin'
            conn = app.get_db_connection()
            try:
                cur = conn.cursor()
                cur.execute("SELECT user_id, expires_at FROM google_oauth_states WHERE state_token = ?", (state,))
                row = cur.fetchone()
                self.assertIsNotNone(row)
                self.assertEqual(row["user_id"], "admin")
                self.assertGreater(row["expires_at"], time.time())
            finally:
                conn.close()

    # 3. No Bearer token leakage in query parameters or auth_url
    def test_03_no_bearer_token_leakage_in_query_or_url(self):
        """Ensure NexusNode Bearer session tokens are NEVER leaked into the Google authorization URL."""
        with patch("timetable_sync.get_shared_google_oauth_config", return_value={
            "client_id": "test_client_id.apps.googleusercontent.com",
            "client_secret": "test_secret",
            "redirect_uri": "https://k09oezeyib.localto.net/api/auth/google/callback"
        }):
            res = self.client.get("/api/auth/google/authorize", headers=self.admin_headers)
            self.assertEqual(res.status_code, 200)
            auth_url = res.get_json()["authorization_url"]

            self.assertNotIn(self.admin_token, auth_url)
            self.assertNotIn("token=", auth_url)
            self.assertNotIn("auth=", auth_url)
            self.assertNotIn("Bearer", auth_url)

    # 4. Privilege verification
    def test_04_privilege_enforcement(self):
        """Users without can_sync_timetable privilege must be rejected with 403."""
        res = self.client.get("/api/auth/google/authorize", headers=self.nopriv_headers)
        self.assertEqual(res.status_code, 403)
        data = res.get_json()
        self.assertEqual(data.get("error"), "permission_denied")

    # 5. Missing or invalid OAuth state in callback
    def test_05_callback_missing_or_invalid_state(self):
        """Callback without state or with invalid state must be rejected."""
        res1 = self.client.get("/api/auth/google/callback?format=json")
        self.assertEqual(res1.status_code, 400)

        res2 = self.client.get("/api/auth/google/callback?code=mock_code&state=nonexistent_state&format=json")
        self.assertEqual(res2.status_code, 400)
        self.assertIn("Invalid or expired OAuth state", res2.get_json().get("error", ""))

    # 6. State single-use consumption (anti-replay)
    def test_06_state_single_use_consumption(self):
        """State token must be consumed atomically upon verification and cannot be replayed."""
        state = app.timetable_service.create_oauth_state("admin")
        self.assertIsNotNone(state)

        # First consumption must succeed
        consumed_user = app.timetable_service.validate_and_consume_state(state)
        self.assertEqual(consumed_user, "admin")

        # Second consumption must return None (replay attack blocked)
        replayed_user = app.timetable_service.validate_and_consume_state(state)
        self.assertIsNone(replayed_user)

    # 7. Cross-user session mismatch on callback blocked
    def test_07_callback_cross_user_mismatch_blocked(self):
        """If user B's session is active, callback with user A's state token must be rejected with 403."""
        state_for_admin = app.timetable_service.create_oauth_state("admin")

        # Call callback with student_authorized's bearer token
        res = self.client.get(
            f"/api/auth/google/callback?code=auth_code_123&state={state_for_admin}&format=json",
            headers=self.user_headers
        )
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.get_json().get("error"), "forbidden")

    # 8. Successful callback token persistence and redirect
    def test_08_successful_callback_flow(self):
        """Valid callback exchanges code, persists tokens, and redirects to #tab-accounts?google_auth=success."""
        state = app.timetable_service.create_oauth_state("admin")
        dummy_tokens = {
            "access_token": "ya29.mock_access_token",
            "refresh_token": "1//mock_refresh_token",
            "expires_at": time.time() + 3600
        }

        with patch("timetable_sync.GoogleCalendarClient.exchange_code_for_tokens", return_value=dummy_tokens), \
             patch.object(app.timetable_service, "save_oauth_tokens") as mock_save:

            res = self.client.get(f"/api/auth/google/callback?code=mock_auth_code&state={state}")
            self.assertEqual(res.status_code, 302)
            location = res.headers.get("Location", "")
            self.assertIn("#tab-accounts", location)
            self.assertIn("google_auth=success", location)
            mock_save.assert_called_once_with("admin", dummy_tokens)

    # 9. UI templates do not contain direct unauthenticated <a> links
    def test_09_frontend_no_direct_authorize_links(self):
        """Static UI templates must not contain raw <a href='/api/auth/google/authorize'> tags."""
        server_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        js_files = ["static/js/academics.js", "static/js/accounts.js"]

        for rel_path in js_files:
            full_path = os.path.join(server_dir, rel_path)
            with open(full_path, "r", encoding="utf-8") as f:
                content = f.read()
            matches = re.findall(r'<a\s+[^>]*href=["\']/api/auth/google/authorize[^"\']*["\']', content)
            self.assertEqual(len(matches), 0, f"Found raw direct authorization link in {rel_path}: {matches}")


if __name__ == "__main__":
    unittest.main()
