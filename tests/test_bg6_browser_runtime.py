"""
Unit and Integration Tests for NexusNode Ephemeral Browser Runtime (Phase 4.1B).
Validates CDP target filtering regression, memory admission governance, single-flight
concurrency locks, profile tenant isolation, bounded observation <= 50 KB, stale ref rejection,
strict SSRF protection, and artifact retention cleanup.
"""

import os
import time
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from browser.cdp_client import select_page_target
from browser.chromium_runtime import (
    SingleFlightLock,
    MemoryAdmissionGovernor,
    BrowserUnavailableError,
    ConcurrencyLockError,
    EphemeralChromiumRuntime,
    EXACT_CHROMIUM_FLAGS,
)
from browser.profile_manager import ProfileManager, ProfileType, ProfileSecurityError
from browser.observation import (
    build_bounded_observation,
    ObservationRegistry,
    ElementStaleError,
    MAX_OBSERVATION_BYTES,
)
from agent.browser_service import BrowserService


class TestBG6BrowserRuntime(unittest.TestCase):

    # 1. CDP Target Filter Regression
    def test_cdp_target_filter_regression(self):
        """
        Verify the critical regression fix: background extension pages, devtools,
        and internal chrome pages are rejected, and only true web page targets are selected.
        """
        mock_targets = [
            {
                "id": "ext-1",
                "type": "background_page",
                "url": "chrome-extension://mhjfbmdgcfjbbpaeojofohoefgiehjai/background.html",
                "title": "Chrome Extension"
            },
            {
                "id": "ext-2",
                "type": "page",
                "url": "chrome-extension://abcdefghijklmno/popup.html",
                "title": "Extension Popup"
            },
            {
                "id": "devtools-1",
                "type": "other",
                "url": "devtools://devtools/bundled/inspector.html",
                "title": "DevTools"
            },
            {
                "id": "chrome-1",
                "type": "page",
                "url": "chrome://newtab/",
                "title": "New Tab"
            },
            {
                "id": "page-real",
                "type": "page",
                "url": "https://myupes-beta.upes.ac.in/oneportal/app/auth/login",
                "title": "MyUPES : Login",
                "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/page-real"
            }
        ]

        selected = select_page_target(mock_targets)
        self.assertIsNotNone(selected)
        self.assertEqual(selected["id"], "page-real")
        self.assertEqual(selected["title"], "MyUPES : Login")

        # Verify None if no real web page target exists
        only_bad_targets = mock_targets[:4]
        self.assertIsNone(select_page_target(only_bad_targets))

    # 2. Memory Admission Governor
    @patch("browser.chromium_runtime.read_system_meminfo")
    @patch("browser.chromium_runtime.read_zram_used_mb")
    def test_memory_admission_governor(self, mock_zram, mock_meminfo):
        """
        Verify memory admission governor rejects when MemAvailable < threshold,
        and permits when MemAvailable >= threshold.
        """
        governor = MemoryAdmissionGovernor(min_available_mb=800)

        # Case A: Low memory (500 MB < 800 MB)
        mock_meminfo.return_value = {"MemAvailable": 500, "MemTotal": 3770}
        mock_zram.return_value = 50

        with self.assertRaises(BrowserUnavailableError) as ctx:
            governor.check_admission()
        self.assertIn("BROWSER_RESOURCE_PRESSURE", str(ctx.exception))
        self.assertIn("500 MB", str(ctx.exception))

        # Case B: Healthy memory (1625 MB >= 800 MB, based on empirical BG6 floor)
        mock_meminfo.return_value = {"MemAvailable": 1625, "MemTotal": 3770}
        mock_zram.return_value = 0

        telemetry = governor.check_admission()
        self.assertTrue(telemetry["admission_allowed"])
        self.assertEqual(telemetry["mem_available_mb"], 1625)
        self.assertEqual(telemetry["threshold_mb"], 800)

    # 3. Single Flight Concurrency Lock (MAX_BROWSER_JOBS=1)
    def test_browser_single_flight_lock(self):
        """
        Verify concurrency=1 lock prevents simultaneous browser instances.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            lock_path = os.path.join(tmp_dir, "test_browser.lock")
            lock1 = SingleFlightLock(lock_path)
            lock2 = SingleFlightLock(lock_path)

            # First acquisition succeeds
            self.assertTrue(lock1.acquire())
            self.assertTrue(os.path.exists(lock_path))

            # Second concurrent acquisition fails immediately
            with self.assertRaises(ConcurrencyLockError):
                lock2.acquire()

            # Release first lock
            lock1.release()

            # Second lock can now acquire
            self.assertTrue(lock2.acquire())
            lock2.release()

    # 4. Profile Management & Tenant Isolation
    def test_profile_isolation_and_path_traversal(self):
        """
        Verify ephemeral vs persistent profile lifecycle and strict tenant isolation.
        """
        with tempfile.TemporaryDirectory() as base_tmp:
            vault_dir = os.path.join(base_tmp, "storage_vault")
            scratch_tmp = os.path.join(base_tmp, "tmp")
            mgr = ProfileManager(base_vault_dir=vault_dir, tmp_dir=scratch_tmp)

            # Ephemeral Profile
            eph_path = mgr.allocate_profile(ProfileType.EPHEMERAL)
            self.assertTrue(os.path.exists(eph_path))
            self.assertTrue(eph_path.startswith(os.path.realpath(scratch_tmp)))

            # Ephemeral cleanup removes directory completely
            mgr.cleanup_profile(eph_path, ProfileType.EPHEMERAL)
            self.assertFalse(os.path.exists(eph_path))

            # Tenant Persistent Profiles
            user_a = "student_alpha_101"
            user_b = "student_beta_202"

            path_a = mgr.allocate_profile(ProfileType.TENANT_PERSISTENT, user_id=user_a, provider="bg6_cdp")
            path_b = mgr.allocate_profile(ProfileType.TENANT_PERSISTENT, user_id=user_b, provider="bg6_cdp")

            self.assertTrue(os.path.exists(path_a))
            self.assertTrue(os.path.exists(path_b))
            self.assertNotEqual(path_a, path_b)
            self.assertIn(user_a, path_a)
            self.assertIn(user_b, path_b)

            # Persistent cleanup leaves data intact
            test_file = os.path.join(path_a, "Cookies")
            with open(test_file, "w") as f:
                f.write("mock_cookie_data")

            mgr.cleanup_profile(path_a, ProfileType.TENANT_PERSISTENT)
            self.assertTrue(os.path.exists(test_file))

            # Path Traversal Attacks
            with self.assertRaises(ProfileSecurityError):
                mgr.allocate_profile(ProfileType.TENANT_PERSISTENT, user_id="../../etc", provider="bg6_cdp")

            with self.assertRaises(ProfileSecurityError):
                mgr.allocate_profile(ProfileType.TENANT_PERSISTENT, user_id="user/../../secret", provider="bg6_cdp")

            with self.assertRaises(ProfileSecurityError):
                mgr.allocate_profile(ProfileType.TENANT_PERSISTENT, user_id="", provider="bg6_cdp")

    # 5. Observation Bounds & Stale Reference Detection
    def test_observation_bounds_and_envelope(self):
        """
        Verify observation payload is bounded <= 50 KB and wrapped in security envelope.
        """
        # Create a massive list of mock raw AX nodes to exceed 50 KB
        mock_ax_nodes = []
        for i in range(1500):
            mock_ax_nodes.append({
                "nodeId": i + 1,
                "backendDOMNodeId": (i + 1) * 10,
                "role": {"value": "button"},
                "name": {"value": f"Interactive Button Element Index {i} With Very Long Descriptive Label"}
            })

        obs = build_bounded_observation(
            raw_ax_nodes=mock_ax_nodes,
            url="https://portal.university.edu/dashboard",
            title="Student Dashboard",
            epoch=1
        )

        envelope = obs.to_envelope()
        self.assertIn("<untrusted_web_content origin=", envelope)
        self.assertIn("<page_title>Student Dashboard</page_title>", envelope)
        self.assertIn("</untrusted_web_content>", envelope)

        # Verify size budget constraint
        payload_bytes = len(obs.tree_text.encode("utf-8")) + len(obs.text_excerpt.encode("utf-8"))
        self.assertLessEqual(payload_bytes, MAX_OBSERVATION_BYTES)

    def test_stale_reference_rejection(self):
        """
        Verify ElementStaleError is raised when attempting to resolve refs from a prior epoch.
        """
        registry = ObservationRegistry()
        session_id = "test_sess_001"
        registry.init_session(session_id)

        # Epoch 1 Observation
        nodes_epoch_1 = [
            {"nodeId": 10, "role": {"value": "textbox"}, "name": {"value": "Username"}},
            {"nodeId": 20, "role": {"value": "button"}, "name": {"value": "Submit"}}
        ]
        obs_1 = build_bounded_observation(nodes_epoch_1, "https://test.edu/login", "Login", epoch=1)
        registry.register_observation(session_id, obs_1)

        # In epoch 1, resolving e0 succeeds
        elem_e0 = registry.resolve_ref(session_id, "e0")
        self.assertEqual(elem_e0.name, "Username")
        self.assertEqual(elem_e0.epoch, 1)

        # Page navigates or updates -> Advance epoch to 2
        registry.advance_epoch(session_id)

        # Resolving e0 from epoch 1 now raises ElementStaleError
        with self.assertRaises(ElementStaleError):
            registry.resolve_ref(session_id, "e0")

        # Register epoch 2 observation
        nodes_epoch_2 = [
            {"nodeId": 30, "role": {"value": "heading"}, "name": {"value": "Welcome"}}
        ]
        obs_2 = build_bounded_observation(nodes_epoch_2, "https://test.edu/home", "Home", epoch=2)
        registry.register_observation(session_id, obs_2)

        elem_new_e0 = registry.resolve_ref(session_id, "e0")
        self.assertEqual(elem_new_e0.name, "Welcome")
        self.assertEqual(elem_new_e0.epoch, 2)

    # 6. SSRF Strict Blocking
    def test_ssrf_strict_blocking(self):
        """
        Verify SSRF validation strictly blocks loopback, private RFC1918 IPs,
        and non-HTTP schemes for external callers.
        """
        service = BrowserService()

        # Blocked addresses
        blocked_urls = [
            "http://127.0.0.1:5000/admin",
            "http://127.0.0.1:9222/json",
            "http://localhost:5000/",
            "http://localhost/secret",
            "http://192.168.1.1/router",
            "http://192.168.29.21:5000/internal",
            "http://10.0.0.1/metadata",
            "http://172.16.0.1/private",
            "http://169.254.169.254/latest/meta-data/",
            "file:///etc/passwd",
            "javascript:alert(1)"
        ]

        for url in blocked_urls:
            is_safe, cat, reason = service.validate_url_safety(url, allow_internal_diagnostics=False)
            self.assertFalse(is_safe, f"Should have blocked {url}")

        # Internal diagnostics bypass allows loopback only when explicitly requested
        is_safe, cat, reason = service.validate_url_safety("http://127.0.0.1:5000/test", allow_internal_diagnostics=True)
        self.assertTrue(is_safe)
        self.assertEqual(cat.lower(), "internal_diagnostic")

        # Allowed public addresses
        is_safe, cat, reason = service.validate_url_safety("https://myupes-beta.upes.ac.in/oneportal/app/auth/login")
        self.assertTrue(is_safe)

        is_safe, cat, reason = service.validate_url_safety("https://lms.upes.ac.in")
        self.assertTrue(is_safe)

    # 7. Screenshot & Artifact Retention Cleanup
    def test_screenshot_artifact_retention(self):
        """
        Verify cleanup_artifacts prunes old screenshots according to max_age, max_count, max_bytes.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = BrowserService()
            service.artifact_dir = tmp_dir

            now = time.time()
            # Create 5 files with varying ages
            fpaths = []
            for i in range(5):
                fp = os.path.join(tmp_dir, f"shot_{i}.png")
                with open(fp, "w") as f:
                    f.write("x" * 1024)  # 1 KB
                # Set mtime backwards
                mtime = now - (5 - i) * 100
                os.utime(fp, (mtime, mtime))
                fpaths.append(fp)

            # Prune with max_count=2
            res = service.cleanup_artifacts(max_age_sec=3600, max_count=2, max_bytes=10000)
            self.assertEqual(res["deleted_count"], 3)
            self.assertEqual(res["freed_bytes"], 3072)

            remaining = os.listdir(tmp_dir)
            self.assertEqual(len(remaining), 2)
            self.assertIn("shot_3.png", remaining)
            self.assertIn("shot_4.png", remaining)

    # 8. Exact Chromium Flags Baseline
    def test_exact_chromium_flags_freeze(self):
        """
        Verify production flags match the Phase 4.1A empirical baseline.
        """
        expected_flags = [
            "--headless=new",
            "--no-sandbox",
            "--disable-gpu",
            "--disable-dev-shm-usage",
            "--disable-extensions",
            "--remote-debugging-address=127.0.0.1"
        ]
        self.assertEqual(EXACT_CHROMIUM_FLAGS, expected_flags)


if __name__ == "__main__":
    unittest.main()
