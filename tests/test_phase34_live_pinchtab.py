"""
NexusNode — Phase 3.4 Live PinchTab Provider Integration Test
Tests live communication between NexusNode and Windows PinchTab worker on LAN.
"""

import os
import json
import time
import unittest
from browser.pinchtab import PinchTabProvider
from agent.browser_service import BrowserService
from agent.vault_service import VaultService

class TestLivePinchTabIntegration(unittest.TestCase):

    def setUp(self):
        # Load token
        cfg_path = os.path.expandvars(r"%APPDATA%\pinchtab\config.json")
        self.token = None
        if os.path.exists(cfg_path):
            with open(cfg_path, "r") as f:
                self.token = json.load(f).get("server", {}).get("token")

        self.provider = PinchTabProvider(
            base_url="http://192.168.29.74:9867",
            auth_token=self.token,
            timeout=10.0
        )
        self.vault_service = VaultService()
        self.browser_service = BrowserService(provider=self.provider, vault_service=self.vault_service)

    def test_live_health_and_session_flow(self):
        # 1. Health check over LAN (environment-dependent)
        health = self.provider.get_health()
        if health.get("status") != "healthy":
            self.skipTest(f"Live PinchTab worker at {self.provider.base_url} is offline or unreachable")

        self.assertEqual(health.get("status"), "healthy")
        self.assertEqual(health.get("base_url"), "http://192.168.29.74:9867")

        # 2. Open session
        res_open = self.browser_service.open_session("spark-agent", {"url": "about:blank"})
        self.assertTrue(res_open.ok)
        session_id = res_open.data["session_id"]

        try:
            # 3. Navigate to a safe public site (e.g. Wikipedia)
            res_nav = self.browser_service.navigate("spark-agent", {
                "session_id": session_id,
                "url": "https://en.wikipedia.org/wiki/Main_Page"
            })
            self.assertTrue(res_nav.ok)

            # 4. Paired capture
            res_cap = self.browser_service.capture("spark-agent", {"session_id": session_id})
            self.assertTrue(res_cap.ok)
            self.assertTrue(res_cap.data["capture_id"].startswith("cap_"))
            self.assertIn("envelope", res_cap.data)
            self.assertIn("screenshot", res_cap.data)
            self.assertTrue(os.path.exists(res_cap.data["screenshot"]["storage_path"]))

            # 5. Snapshot
            res_snap = self.browser_service.snapshot("spark-agent", {"session_id": session_id})
            self.assertTrue(res_snap.ok)
            self.assertGreater(res_snap.data["element_count"], 0)

        finally:
            # 6. Close session
            res_close = self.browser_service.close_session("spark-agent", {"session_id": session_id})
            self.assertTrue(res_close.ok)

if __name__ == "__main__":
    unittest.main()
