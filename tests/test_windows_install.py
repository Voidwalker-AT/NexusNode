"""
NexusNode CLI — Windows Installation & PATH Discovery Tests
Verifies that:
1. Package installation creates the 'nexus' console script.
2. Executable location is correctly identified across standard Python directories.
3. The automatic Windows User PATH remediation mechanism safely registers Python Scripts.
4. 'nexus --version', 'nexus --help', and 'nexus connect --help' are fully discoverable and functional.
5. Package installation success, executable creation, and PATH discovery are distinctly verified.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path


class TestWindowsInstallationUX(unittest.TestCase):
    """Test suite for Windows installation and executable PATH discovery."""

    def test_01_package_installed_and_importable(self):
        """Phase 1: Verify package installation success."""
        try:
            import nexus
            self.assertTrue(hasattr(nexus, "__version__"))
            self.assertEqual(nexus.__version__, "1.0.2")
        except ImportError as e:
            self.fail(f"Package 'nexus' is not installed or importable: {e}")

    def test_02_executable_creation_and_location(self):
        """Phase 2: Verify executable creation across candidate Scripts directories."""
        from nexus.windows import find_nexus_executable, get_candidate_scripts_dirs

        candidates = get_candidate_scripts_dirs()
        self.assertIsInstance(candidates, list)
        self.assertGreater(len(candidates), 0)

        # Ensure all candidate directories are plausible strings
        for c in candidates:
            self.assertTrue(isinstance(c, str) and len(c) > 0)

        # On the local test environment, check if nexus executable is discoverable
        exe_path = find_nexus_executable()
        if exe_path is not None:
            self.assertTrue(os.path.isfile(exe_path), f"Executable not found at {exe_path}")
            # Verify direct execution works
            res = subprocess.run([exe_path, "--version"], capture_output=True, text=True, timeout=10)
            self.assertEqual(res.returncode, 0)
            self.assertIn("NexusNode CLI", res.stdout)

    def test_03_windows_path_remediation_mechanism(self):
        """Phase 3: Verify the automatic PATH remediation mechanism."""
        from nexus.windows import ensure_windows_path, is_directory_on_path

        if sys.platform != "win32":
            res = ensure_windows_path(silent=True)
            self.assertEqual(res["status"], "skipped_non_windows")
            return

        # On Windows, ensure_windows_path should run safely without raising exceptions
        res = ensure_windows_path(silent=True)
        self.assertIn(res["status"], ["configured", "already_present"])

        # Check that candidate directories are now recognized as on PATH
        from nexus.windows import get_candidate_scripts_dirs
        candidates = get_candidate_scripts_dirs()
        # At least one candidate directory should be on PATH or in HKCU
        found_on_path = any(is_directory_on_path(c) for c in candidates if os.path.exists(c))
        self.assertTrue(found_on_path, "At least one candidate Scripts directory must be on PATH or in HKCU")

    def test_04_executable_path_discovery_commands(self):
        """Phase 4: Verify 'nexus --version', 'nexus --help', and 'nexus connect --help'."""
        # Find which command runner to use: direct 'nexus' on PATH, or with updated user PATH env
        env = os.environ.copy()
        if sys.platform == "win32":
            try:
                import winreg
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment", 0, winreg.KEY_READ) as key:
                    hkcu_path, _ = winreg.QueryValueEx(key, "Path")
                    env["PATH"] = hkcu_path + ";" + env.get("PATH", "")
            except Exception:
                pass

        # Expand environment variables in PATH
        env = {k: os.path.expandvars(v) for k, v in env.items()}

        # 1. Test nexus --version
        import nexus
        res_ver = subprocess.run(
            ["nexus", "--version"],
            capture_output=True, text=True, timeout=10, shell=True, env=env
        )
        self.assertEqual(res_ver.returncode, 0, f"nexus --version failed: {res_ver.stderr}")
        self.assertIn(f"NexusNode CLI v{nexus.__version__}", res_ver.stdout)

        # 2. Test nexus --help
        res_help = subprocess.run(
            ["nexus", "--help"],
            capture_output=True, text=True, timeout=10, shell=True, env=env
        )
        self.assertEqual(res_help.returncode, 0, f"nexus --help failed: {res_help.stderr}")
        self.assertIn("connect", res_help.stdout)
        self.assertIn("vault", res_help.stdout)
        self.assertIn("media", res_help.stdout)

        # 3. Test nexus connect --help
        res_conn = subprocess.run(
            ["nexus", "connect", "--help"],
            capture_output=True, text=True, timeout=10, shell=True, env=env
        )
        self.assertEqual(res_conn.returncode, 0, f"nexus connect --help failed: {res_conn.stderr}")
        self.assertIn("url", res_conn.stdout)
        self.assertIn("--server", res_conn.stdout)
        self.assertIn("--user", res_conn.stdout)

    def test_05_setup_subcommand(self):
        """Phase 5: Verify 'nexus setup' and 'nexus-setup' entry point."""
        from nexus.__main__ import create_parser, setup_path_cli
        parser = create_parser()
        args = parser.parse_args(["setup"])
        self.assertEqual(args.command, "setup")

        # Run setup_path_cli directly
        rc = setup_path_cli()
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
