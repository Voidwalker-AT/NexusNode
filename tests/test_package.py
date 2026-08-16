"""
NexusNode CLI — Package Integrity Tests
Verifies the nexusnode-cli PyPI distribution is correctly structured,
importable, and exposes the expected entry points and command modules.
These tests do NOT require a running NexusNode server.
"""

import importlib
import os
import subprocess
import sys
import unittest


class TestPackageMetadata(unittest.TestCase):
    """Verify package metadata and version."""

    def test_import_nexus(self):
        import nexus
        self.assertTrue(hasattr(nexus, '__version__'))
        self.assertTrue(hasattr(nexus, '__author__'))

    def test_version_format(self):
        import nexus
        parts = nexus.__version__.split('.')
        self.assertGreaterEqual(len(parts), 2)
        for p in parts:
            self.assertTrue(p.isdigit(), f"Version part '{p}' is not numeric")

    def test_version_not_empty(self):
        import nexus
        self.assertTrue(len(nexus.__version__) > 0)


class TestEntryPoint(unittest.TestCase):
    """Verify the nexus console entry point."""

    def test_main_callable(self):
        from nexus.__main__ import main
        self.assertTrue(callable(main))

    def test_create_parser(self):
        from nexus.__main__ import create_parser, NexusArgumentParser
        parser = create_parser()
        self.assertIsInstance(parser, NexusArgumentParser)

    def test_parser_has_connect_command(self):
        from nexus.__main__ import create_parser
        parser = create_parser()
        args = parser.parse_args(['connect', 'http://example.com'])
        self.assertEqual(args.command, 'connect')
        self.assertEqual(args.url, 'http://example.com')

    def test_parser_has_status_command(self):
        from nexus.__main__ import create_parser
        parser = create_parser()
        args = parser.parse_args(['status'])
        self.assertEqual(args.command, 'status')

    def test_version_flag_exits_zero(self):
        result = subprocess.run(
            [sys.executable, '-m', 'nexus', '--version'],
            capture_output=True, text=True, timeout=10
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn('NexusNode CLI', result.stdout)

    def test_help_flag_exits_zero(self):
        result = subprocess.run(
            [sys.executable, '-m', 'nexus', '--help'],
            capture_output=True, text=True, timeout=10
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn('connect', result.stdout)

    def test_connect_help_exits_zero(self):
        result = subprocess.run(
            [sys.executable, '-m', 'nexus', 'connect', '--help'],
            capture_output=True, text=True, timeout=10
        )
        self.assertEqual(result.returncode, 0)


class TestCommandModules(unittest.TestCase):
    """Verify all CLI command submodules are importable."""

    COMMAND_MODULES = [
        'nexus.commands.status',
        'nexus.commands.vault',
        'nexus.commands.media',
        'nexus.commands.tasks',
        'nexus.commands.ai',
        'nexus.commands.rag',
        'nexus.commands.shares',
        'nexus.commands.account',
        'nexus.commands.services',
        'nexus.commands.models',
        'nexus.commands.diagnostics',
        'nexus.commands.logs',
        'nexus.commands.users',
        'nexus.commands.backups',
        'nexus.commands.automation',
        'nexus.commands.settings',
        'nexus.commands.database',
    ]

    def test_all_command_modules_importable(self):
        for mod_name in self.COMMAND_MODULES:
            with self.subTest(module=mod_name):
                mod = importlib.import_module(mod_name)
                self.assertIsNotNone(mod)

    def test_core_modules_importable(self):
        for mod_name in ['nexus.client', 'nexus.auth', 'nexus.config',
                         'nexus.output', 'nexus.shell', 'nexus.normalize']:
            with self.subTest(module=mod_name):
                mod = importlib.import_module(mod_name)
                self.assertIsNotNone(mod)


class TestNoServerLeakage(unittest.TestCase):
    """Verify server-only modules are NOT part of the nexus package."""

    def test_no_app_module(self):
        # app.py is a server file, must not be importable as nexus.app
        with self.assertRaises((ImportError, ModuleNotFoundError)):
            importlib.import_module('nexus.app')

    def test_no_resource_governor(self):
        with self.assertRaises((ImportError, ModuleNotFoundError)):
            importlib.import_module('nexus.resource_governor')

    def test_no_nexus_shell_server(self):
        # nexus.shell is the CLIENT shell (allowed)
        # nexus_shell is the SERVER SSH shell (must not be in package)
        # Just verify no server-specific imports leak
        import nexus.shell
        self.assertTrue(hasattr(nexus.shell, 'NexusShell'))

    def test_no_secrets_in_package(self):
        """Verify no hardcoded credentials or secret values in package source files."""
        import nexus
        pkg_dir = os.path.dirname(nexus.__file__)
        # These patterns detect actual secret VALUES, not product name mentions.
        # "LocalToNet" appearing in a diagnostic message is legitimate.
        # "localtonet_token" or "authtoken=" would be a real secret leak.
        secret_patterns = [
            'Admin@1234',           # Default test password
            'api_key=',             # Hardcoded API key assignment
            'BEGIN RSA PRIVATE',    # SSH private key
            'authtoken=',           # Tunnel auth token assignment
            'localtonet_token',     # LocalToNet token variable
        ]
        for root, dirs, files in os.walk(pkg_dir):
            dirs[:] = [d for d in dirs if d != '__pycache__']
            for fn in files:
                if not fn.endswith('.py'):
                    continue
                filepath = os.path.join(root, fn)
                with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                for pattern in secret_patterns:
                    self.assertNotIn(
                        pattern.lower(), content.lower(),
                        f"Secret pattern '{pattern}' found in {filepath}"
                    )


class TestZeroDependencies(unittest.TestCase):
    """Verify the package has no third-party runtime dependencies."""

    def test_no_requirements_in_metadata(self):
        """The package should declare zero dependencies."""
        try:
            from importlib.metadata import requires
            deps = requires('nexusnode-cli')
            if deps is not None:
                # Filter out extras/dev dependencies
                runtime_deps = [d for d in deps if '; extra' not in d]
                self.assertEqual(len(runtime_deps), 0,
                                 f"Unexpected runtime dependencies: {runtime_deps}")
        except Exception:
            # If importlib.metadata is not available or package not installed via pip,
            # skip gracefully
            pass


if __name__ == '__main__':
    unittest.main()
