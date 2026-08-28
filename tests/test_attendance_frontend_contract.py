import unittest
import os
import re
import subprocess
import shutil

class TestAttendanceFrontendContract(unittest.TestCase):
    """
    Regression test suite verifying that the frontend JavaScript implementation
    properly defines all helper functions (e.g. apiRequest), contains zero Python-isms (bool),
    includes asset-versioning cache-busting, and executes cleanly in a DOM environment.
    """

    def setUp(self):
        self.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.app_js_path = os.path.join(self.base_dir, "static", "js", "app.js")
        self.index_html_path = os.path.join(self.base_dir, "index.html")

        with open(self.app_js_path, "r", encoding="utf-8") as f:
            self.app_js_content = f.read()

        with open(self.index_html_path, "r", encoding="utf-8") as f:
            self.index_html_content = f.read()

    def test_api_request_helper_defined(self):
        """Verify that apiRequest helper function is explicitly defined in app.js."""
        match = re.search(r"async\s+function\s+apiRequest\s*\(", self.app_js_content)
        self.assertIsNotNone(match, "apiRequest function definition missing from static/js/app.js")

    def test_no_pythonisms_in_javascript(self):
        """Verify that Python-specific functions/keywords like bool() are not in app.js."""
        bool_match = re.findall(r"[^\w]bool\s*\(", self.app_js_content)
        self.assertEqual(len(bool_match), 0, f"Found Python bool() calls in app.js: {bool_match}")

    def test_asset_version_cache_busting(self):
        """Verify index.html includes ?v={{ version }} on scripts and stylesheets."""
        self.assertIn('static/js/app.js?v={{ version }}', self.index_html_content)
        self.assertIn('static/css/index.css?v={{ version }}', self.index_html_content)

    def test_node_dom_rendering_contract(self):
        """Execute Node.js DOM rendering test to verify app.js parses and renders without exception."""
        node_bin = shutil.which("node")
        if not node_bin:
            self.skipTest("Node.js binary not available in environment")

        test_script = r"""
const fs = require('fs');
const vm = require('vm');

const dom = {};
const toasts = [];

const sandbox = {
  window: {},
  document: {
    addEventListener: () => {},
    querySelector: () => null,
    querySelectorAll: () => [],
    getElementById: (id) => {
      if (!dom[id]) {
        dom[id] = {
          textContent: '',
          innerHTML: '',
          style: {},
          className: '',
          classList: { toggle: () => {}, remove: () => {}, add: () => {}, contains: () => false }
        };
      }
      return dom[id];
    },
    createElement: () => ({ style: {}, appendChild: () => {}, remove: () => {}, innerHTML: '', className: '' })
  },
  localStorage: { getItem: (k) => k === 'nexusnode_auth_token' ? 'tok_123' : null, setItem: () => {}, removeItem: () => {} },
  sessionStorage: { getItem: () => null, setItem: () => {}, removeItem: () => {} },
  navigator: { userAgent: 'NodeTest' },
  FormData: class FormData {},
  AbortController: global.AbortController,
  showToast: (msg, type) => { toasts.push({ msg, type }); },
  fetch: async (url) => ({
    ok: true,
    status: 200,
    json: async () => ({
      user_id: 'test_user',
      as_of_date: '2026-08-28',
      overall: { conducted_classes: 10, attended_classes: 9, attendance_percentage: 90.0, total_safe_bunks: 2 },
      subjects: [{ module_id: 1, course_name: 'Test Course', conducted_classes: 10, attended_classes: 9, attendance_percentage: 90.0, safe_bunks_remaining: 2 }],
      today_classes: [{ session_id: 1, course_name: 'Test Class', start_time: '09:00:00', end_time: '10:00:00', is_punched: false, punch_in_time: null }],
      recent_sessions: []
    })
  }),
  console: console,
  setTimeout: (fn) => setTimeout(fn, 0),
  clearTimeout: (id) => clearTimeout(id),
  Date: Date,
  Math: Math,
  parseInt: parseInt,
  parseFloat: parseFloat,
  isNaN: isNaN,
  String: String,
  Boolean: Boolean
};
sandbox.window = sandbox;
sandbox.global = sandbox;
sandbox.globalThis = sandbox;

const appJs = fs.readFileSync('static/js/app.js', 'utf8');
const context = vm.createContext(sandbox);
vm.runInContext(appJs, context);

context.loadAttendanceData().then(() => {
  if (toasts.some(t => t.type === 'error')) {
    process.exit(2);
  }
  if (!dom['attOverallPct'] || dom['attOverallPct'].textContent !== '90%') {
    process.exit(3);
  }
  process.exit(0);
}).catch(err => {
  console.error(err);
  process.exit(1);
});
"""
        res = subprocess.run([node_bin, "-e", test_script], cwd=self.base_dir, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"Node DOM execution test failed: {res.stderr}")

if __name__ == "__main__":
    unittest.main()
