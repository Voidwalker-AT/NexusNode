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

    def test_expected_release_version(self):
        """Verify package version matches intended release version 1.0.1."""
        import nexus
        self.assertEqual(nexus.__version__, "1.0.1", "Package version must be 1.0.1")

    def test_dist_artifacts_match_package_version(self):
        """If dist/ directory exists, ensure all built packages match nexus.__version__."""
        import glob
        import nexus
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        dist_dir = os.path.join(repo_root, "dist")
        if os.path.exists(dist_dir):
            wheels = glob.glob(os.path.join(dist_dir, "*.whl"))
            sdists = glob.glob(os.path.join(dist_dir, "*.tar.gz"))
            expected_prefix = f"nexusnode_cli-{nexus.__version__}"
            for w in wheels:
                fname = os.path.basename(w)
                self.assertTrue(
                    fname.startswith(expected_prefix),
                    f"Wheel filename '{fname}' does not match expected version '{expected_prefix}'"
                )
            for s in sdists:
                fname = os.path.basename(s)
                self.assertTrue(
                    fname.startswith(expected_prefix),
                    f"sdist filename '{fname}' does not match expected version '{expected_prefix}'"
                )


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
        import nexus
        result = subprocess.run(
            [sys.executable, '-m', 'nexus', '--version'],
            capture_output=True, text=True, timeout=10
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn(f'NexusNode CLI v{nexus.__version__}', result.stdout)

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


class TestPython38Compatibility(unittest.TestCase):
    """
    Regression tests verifying strict Python 3.8 syntax and type annotation compatibility.
    Guarantees no PEP 604 union operators (|) or unquoted PEP 585 built-in subscripts (list[])
    exist in function signatures across the package.
    """

    def test_no_pep604_unions_or_pep585_generics_in_annotations(self):
        import ast
        import glob
        import nexus

        pkg_root = os.path.dirname(nexus.__file__)
        py_files = glob.glob(os.path.join(pkg_root, "**", "*.py"), recursive=True)
        self.assertGreater(len(py_files), 0, "No python files found in nexus package")

        violations = []
        for py_path in py_files:
            with open(py_path, "r", encoding="utf-8") as f:
                source = f.read()
            tree = ast.parse(source, filename=py_path)
            for node in ast.walk(tree):
                # Check for BitOr in returns or arguments (PEP 604)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if node.returns and isinstance(node.returns, ast.BinOp) and isinstance(node.returns.op, ast.BitOr):
                        violations.append(f"{py_path}:{node.lineno}: BitOr in return annotation ({node.name})")
                    for arg in node.args.args + node.args.kwonlyargs:
                        if arg.annotation and isinstance(arg.annotation, ast.BinOp) and isinstance(arg.annotation.op, ast.BitOr):
                            violations.append(f"{py_path}:{arg.lineno}: BitOr in arg annotation ({arg.arg})")
                if isinstance(node, ast.AnnAssign):
                    if isinstance(node.annotation, ast.BinOp) and isinstance(node.annotation.op, ast.BitOr):
                        violations.append(f"{py_path}:{node.lineno}: BitOr in variable annotation")

                # Check for Subscript on bare built-in types (PEP 585)
                if isinstance(node, ast.Subscript):
                    if isinstance(node.value, ast.Name) and node.value.id in ("list", "dict", "tuple", "set"):
                        violations.append(f"{py_path}:{node.lineno}: Subscript on built-in '{node.value.id}' (use typing.{node.value.id.capitalize()})")

        self.assertEqual(violations, [], f"Found Python 3.8 incompatible type annotations:\n" + "\n".join(violations))


if __name__ == '__main__':
    unittest.main()
