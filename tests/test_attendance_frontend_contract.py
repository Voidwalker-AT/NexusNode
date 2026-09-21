import unittest
import os
import re
import subprocess
import shutil

class TestAttendanceFrontendContract(unittest.TestCase):
    """
    Regression test suite verifying that the frontend JavaScript implementation
    properly defines all API helpers (e.g. apiJson in api.js), contains zero Python-isms (bool),
    includes correct script and stylesheet references in index.html, and passes Node.js syntax checks.
    """

    def setUp(self):
        self.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.app_js_path = os.path.join(self.base_dir, "static", "js", "app.js")
        self.api_js_path = os.path.join(self.base_dir, "static", "js", "api.js")
        self.academics_js_path = os.path.join(self.base_dir, "static", "js", "academics.js")
        self.index_html_path = os.path.join(self.base_dir, "index.html")

        with open(self.app_js_path, "r", encoding="utf-8") as f:
            self.app_js_content = f.read()

        with open(self.api_js_path, "r", encoding="utf-8") as f:
            self.api_js_content = f.read()

        with open(self.academics_js_path, "r", encoding="utf-8") as f:
            self.academics_js_content = f.read()

        with open(self.index_html_path, "r", encoding="utf-8") as f:
            self.index_html_content = f.read()

    def test_api_request_helper_defined(self):
        """Verify that apiJson helper function is explicitly defined in api.js."""
        match = re.search(r"async\s+function\s+apiJson\s*\(", self.api_js_content)
        self.assertIsNotNone(match, "apiJson function definition missing from static/js/api.js")

    def test_no_pythonisms_in_javascript(self):
        """Verify that Python-specific functions/keywords like bool() are not in academics or app js."""
        for name, content in [("academics.js", self.academics_js_content), ("app.js", self.app_js_content)]:
            bool_match = re.findall(r"[^\w]bool\s*\(", content)
            self.assertEqual(len(bool_match), 0, f"Found Python bool() calls in {name}: {bool_match}")

    def test_asset_version_cache_busting(self):
        """Verify index.html includes scripts and stylesheets for academics."""
        self.assertIn('/static/js/academics.js', self.index_html_content)
        self.assertIn('/static/js/api.js', self.index_html_content)
        self.assertIn('/static/js/app.js', self.index_html_content)
        self.assertIn('/static/css/index.css', self.index_html_content)

    def test_academics_controller_contract(self):
        """Verify static/js/academics.js defines attendance and academic lifecycle functions."""
        self.assertIn("function switchAcademicsSubtab", self.academics_js_content)
        self.assertIn("async function loadAcademics", self.academics_js_content)
        self.assertIn("async function loadAcademicsAttendance", self.academics_js_content)
        self.assertIn("async function loadAcademicsOverview", self.academics_js_content)
        self.assertIn("async function loadAcademicsTimetable", self.academics_js_content)

    def test_node_syntax_validity(self):
        """Execute Node.js syntax verification on modular frontend scripts."""
        node_bin = shutil.which("node")
        if not node_bin:
            self.skipTest("Node.js binary not available in environment")

        res = subprocess.run(
            [node_bin, "-c", self.api_js_path, self.academics_js_path, self.app_js_path],
            cwd=self.base_dir, capture_output=True, text=True
        )
        self.assertEqual(res.returncode, 0, f"Node syntax check failed: {res.stderr}")


if __name__ == "__main__":
    unittest.main()
