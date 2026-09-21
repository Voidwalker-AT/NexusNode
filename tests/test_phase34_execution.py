"""
NexusNode — Phase 3.4 Writable Vault & PinchTab Browser Execution Test Suite
Validates:
- Writable Vault Primitives (mkdir, create, write, rename, move, copy)
- PDF Document Text Extraction & Untrusted Boundary Encapsulation
- Browser Service Lifecycle & Session Ownership
- SSRF & Domain Safety Validation
- Consequential Action Guards (Submit/TurnIn Blocking)
- Paired browser.capture & Screenshot Artifact Storage
- Atomic Download & Staged Upload Transfer Pipelines
- Authoritative 27-Tool MCP 2026-07-28 Gateway Dispatch
"""

import os
import io
import time
import json
import uuid
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import config
import agent
from browser.base import BrowserProvider, BrowserSession, BrowserSnapshot, BrowserCapture, BrowserDownload
from agent.browser_service import BrowserService
from agent.vault_service import VaultService
from agent.policy import PolicyEngine, RiskClass
from agent.registry import AgentOperationRegistry
from agent.mcp_auth import AgentTokenManager
from agent.mcp_server import McpServerAdapter, MCP_TOOL_DEFINITIONS


class MockPinchTabProvider(BrowserProvider):
    """Deterministic mock provider for unit testing without live Chromium instance."""

    def __init__(self):
        self._sessions = {}
        self.navigate_calls = []
        self.action_calls = []

    @property
    def provider_name(self) -> str:
        return "pinchtab"

    def get_health(self):
        return {"status": "healthy", "provider": "pinchtab", "version": "0.15.2-mock"}

    def create_session(self, session_id: str, profile_name: str = None, **kwargs) -> BrowserSession:
        session = BrowserSession(
            session_id=session_id,
            profile_name=profile_name or "nexusnode-browser-profile",
            active_tab_id=f"tab_{session_id}",
            metadata={"instance_id": "inst_mock"}
        )
        self._sessions[session_id] = session
        return session

    def close_session(self, session_id: str) -> bool:
        self._sessions.pop(session_id, None)
        return True

    def navigate(self, session_id: str, url: str, wait_until: str = "load"):
        self.navigate_calls.append({"session_id": session_id, "url": url})
        return {"status": "ok", "url": url}

    def snapshot(self, session_id: str, include_screenshot: bool = False) -> BrowserSnapshot:
        elem_map = {
            "e0": {"ref": "e0", "role": "link", "text": "Course Syllabus PDF", "tag": "a"},
            "e1": {"ref": "e1", "role": "button", "text": "Submit Assignment", "tag": "button"},
            "e2": {"ref": "e2", "role": "textbox", "text": "Comments", "tag": "input"},
            "e3": {"ref": "e3", "role": "file", "text": "Attach Solution", "tag": "input"},
            "e4": {"ref": "e4", "role": "link", "text": "External Resource", "tag": "a"}
        }
        tree = "[e0] <a> Course Syllabus PDF\n[e1] <button> Submit Assignment\n[e2] <input> Comments\n[e3] <input> Attach Solution\n[e4] <a> External Resource"
        return BrowserSnapshot(
            url="https://learn.upes.ac.in/course/123",
            title="UPES LMS Course",
            tree_text=tree,
            element_map=elem_map,
            token_estimate=50
        )

    def capture(self, session_id: str, full_page: bool = False) -> BrowserCapture:
        # 1x1 transparent PNG base64
        sample_b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
        return BrowserCapture(
            url="https://learn.upes.ac.in/course/123",
            screenshot_base64=sample_b64,
            format="png",
            width=1280,
            height=800,
            timestamp=time.time()
        )

    def click(self, session_id: str, element_ref: str):
        self.action_calls.append({"action": "click", "element": element_ref})
        return {"clicked": element_ref}

    def type_text(self, session_id: str, element_ref: str, text: str, submit: bool = False):
        self.action_calls.append({"action": "type", "element": element_ref, "text": text})
        return {"typed": text}

    def press(self, session_id: str, key: str):
        self.action_calls.append({"action": "press", "key": key})
        return {"pressed": key}

    def upload_file(self, session_id: str, element_ref: str, file_path: str):
        self.action_calls.append({"action": "upload", "element": element_ref, "file": file_path})
        return {"uploaded": True, "file": os.path.basename(file_path)}

    def download_file(self, session_id: str, element_ref: str, target_dir: str) -> BrowserDownload:
        mock_file = os.path.join(target_dir, "downloaded_syllabus.pdf")
        with open(mock_file, "wb") as f:
            f.write(b"%PDF-1.4 Mock PDF Content For Testing")
        return BrowserDownload(
            file_name="downloaded_syllabus.pdf",
            file_path=mock_file,
            size_bytes=len(b"%PDF-1.4 Mock PDF Content For Testing"),
            content_type="application/pdf"
        )

    def get_cookies(self, session_id: str, domain: str = None):
        return []


class TestPhase34Execution(unittest.TestCase):
    """Comprehensive test suite for Phase 3.4 features."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.vault_dir = os.path.join(self.temp_dir, "vault")
        self.artifact_dir = os.path.join(self.temp_dir, "artifacts")
        os.makedirs(self.vault_dir, exist_ok=True)
        os.makedirs(self.artifact_dir, exist_ok=True)

        self.vault_service = VaultService(agent_vault_root=self.vault_dir)
        self.mock_provider = MockPinchTabProvider()
        self.browser_service = BrowserService(
            provider=self.mock_provider,
            vault_service=self.vault_service,
            max_sessions_per_principal=2,
            idle_session_ttl_sec=60.0,
            artifact_dir=self.artifact_dir
        )

        self.policy_engine = PolicyEngine(approval_manager=None)
        self.registry = AgentOperationRegistry(policy_engine=self.policy_engine)

        # Register Vault operations
        self.registry.register("vault.list", lambda uid, p, **kw: self.vault_service.list_files(uid, p), RiskClass.READ_ONLY)
        self.registry.register("vault.search", lambda uid, p, **kw: self.vault_service.search_vault(uid, p), RiskClass.READ_ONLY)
        self.registry.register("vault.read", lambda uid, p, **kw: self.vault_service.read_file(uid, p), RiskClass.READ_ONLY)
        self.registry.register("vault.mkdir", lambda uid, p, **kw: self.vault_service.mkdir(uid, p), RiskClass.WRITE_LOW_RISK)
        self.registry.register("vault.create", lambda uid, p, **kw: self.vault_service.create_file(uid, p), RiskClass.WRITE_LOW_RISK)
        self.registry.register("vault.write", lambda uid, p, **kw: self.vault_service.write_file(uid, p), RiskClass.WRITE_LOW_RISK)
        self.registry.register("vault.rename", lambda uid, p, **kw: self.vault_service.rename_item(uid, p), RiskClass.WRITE_LOW_RISK)
        self.registry.register("vault.move", lambda uid, p, **kw: self.vault_service.move_item(uid, p), RiskClass.WRITE_LOW_RISK)
        self.registry.register("vault.copy", lambda uid, p, **kw: self.vault_service.copy_item(uid, p), RiskClass.WRITE_LOW_RISK)

        # Register Browser operations
        self.registry.register("browser.status", lambda uid, p, **kw: self.browser_service.get_status(uid), RiskClass.READ_ONLY)
        self.registry.register("browser.open", lambda uid, p, **kw: self.browser_service.open_session(uid, p), RiskClass.WRITE_LOW_RISK)
        self.registry.register("browser.close", lambda uid, p, **kw: self.browser_service.close_session(uid, p), RiskClass.WRITE_LOW_RISK)
        self.registry.register("browser.navigate", lambda uid, p, **kw: self.browser_service.navigate(uid, p), RiskClass.WRITE_LOW_RISK)
        self.registry.register("browser.snapshot", lambda uid, p, **kw: self.browser_service.snapshot(uid, p), RiskClass.READ_ONLY)
        self.registry.register("browser.screenshot", lambda uid, p, **kw: self.browser_service.screenshot(uid, p), RiskClass.READ_ONLY)
        self.registry.register("browser.capture", lambda uid, p, **kw: self.browser_service.capture(uid, p), RiskClass.READ_ONLY)
        self.registry.register("browser.click", lambda uid, p, **kw: self.browser_service.click(uid, p), RiskClass.WRITE_LOW_RISK)
        self.registry.register("browser.type", lambda uid, p, **kw: self.browser_service.type_text(uid, p), RiskClass.WRITE_LOW_RISK)
        self.registry.register("browser.press", lambda uid, p, **kw: self.browser_service.press(uid, p), RiskClass.WRITE_LOW_RISK)
        self.registry.register("browser.upload", lambda uid, p, **kw: self.browser_service.upload(uid, p), RiskClass.WRITE_LOW_RISK)
        self.registry.register("browser.download", lambda uid, p, **kw: self.browser_service.download(uid, p), RiskClass.WRITE_LOW_RISK)
        self.orig_exposed = getattr(config, "MCP_EXPOSED_TOOLS", None)
        config.MCP_EXPOSED_TOOLS = None

    def tearDown(self):
        config.MCP_EXPOSED_TOOLS = self.orig_exposed
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # ==========================================================================
    # 1. Writable Vault Primitives Tests
    # ==========================================================================

    def test_01_vault_mkdir_and_create(self):
        # Create Directory
        res = self.vault_service.mkdir("spark-agent", {"path": "Deep Learning/Assignment 1"})
        self.assertTrue(res.ok)
        self.assertEqual(res.data["path"], "Deep Learning/Assignment 1")

        # Create File
        res = self.vault_service.create_file("spark-agent", {
            "path": "Deep Learning/Assignment 1/notes.md",
            "content": "# Deep Learning Assignment 1\nNotes on CNN architectures."
        })
        self.assertTrue(res.ok)
        self.assertEqual(res.data["path"], "Deep Learning/Assignment 1/notes.md")
        self.assertEqual(res.data["created_by"], "spark-agent")
        self.assertTrue(os.path.exists(os.path.join(self.vault_dir, "Deep Learning", "Assignment 1", "notes.md")))

        # Duplicate create should fail with FILE_EXISTS
        res_dup = self.vault_service.create_file("spark-agent", {
            "path": "Deep Learning/Assignment 1/notes.md",
            "content": "Overwriting content"
        })
        self.assertFalse(res_dup.ok)
        self.assertEqual(res_dup.error_code, "FILE_EXISTS")

    def test_02_vault_write_replace_and_append(self):
        # Initial write
        self.vault_service.create_file("spark-agent", {
            "path": "test.txt",
            "content": "Line 1\n"
        })

        # Append mode
        res_app = self.vault_service.write_file("spark-agent", {
            "path": "test.txt",
            "content": "Line 2\n",
            "mode": "append"
        })
        self.assertTrue(res_app.ok)
        self.assertEqual(res_app.data["mode"], "append")

        # Read back
        res_read = self.vault_service.read_file("spark-agent", {"path": "test.txt"})
        self.assertTrue(res_read.ok)
        self.assertIn("Line 1\nLine 2\n", res_read.data["text"])

        # Replace mode
        res_rep = self.vault_service.write_file("spark-agent", {
            "path": "test.txt",
            "content": "Completely Replaced\n",
            "mode": "replace"
        })
        self.assertTrue(res_rep.ok)
        res_read2 = self.vault_service.read_file("spark-agent", {"path": "test.txt"})
        self.assertEqual(res_read2.data["text"], "Completely Replaced\n")

    def test_03_vault_rename_move_copy(self):
        self.vault_service.create_file("spark-agent", {"path": "src.txt", "content": "Original content"})
        self.vault_service.mkdir("spark-agent", {"path": "subfolder"})

        # Copy
        res_copy = self.vault_service.copy_item("spark-agent", {"source_path": "src.txt", "destination_path": "subfolder/src_copy.txt"})
        self.assertTrue(res_copy.ok)
        self.assertTrue(os.path.exists(os.path.join(self.vault_dir, "subfolder", "src_copy.txt")))

        # Rename
        res_ren = self.vault_service.rename_item("spark-agent", {"source_path": "src.txt", "target_path": "renamed.txt"})
        self.assertTrue(res_ren.ok)
        self.assertFalse(os.path.exists(os.path.join(self.vault_dir, "src.txt")))
        self.assertTrue(os.path.exists(os.path.join(self.vault_dir, "renamed.txt")))

        # Move
        res_mv = self.vault_service.move_item("spark-agent", {"source_path": "renamed.txt", "destination_path": "subfolder/moved.txt"})
        self.assertTrue(res_mv.ok)
        self.assertTrue(os.path.exists(os.path.join(self.vault_dir, "subfolder", "moved.txt")))

    def test_04_vault_path_traversal_escapes_blocked(self):
        # Parent traversal (..)
        res = self.vault_service.create_file("spark-agent", {
            "path": "../../../secret.txt",
            "content": "Malicious escape"
        })
        self.assertFalse(res.ok)
        self.assertIn(res.error_code, ("INVALID_PATH", "ACCESS_DENIED"))

        # Traversal in mkdir
        res_mkdir = self.vault_service.mkdir("spark-agent", {"path": "foo/../../bar/../../escape"})
        self.assertFalse(res_mkdir.ok)

    # ==========================================================================
    # 2. Document Reading & PDF Text Extraction Tests
    # ==========================================================================

    def test_05_pdf_document_text_extraction(self):
        pdf_path = os.path.join(self.vault_dir, "test_document.pdf")
        # Create minimal synthetic PDF with pypdf or mock
        from pypdf import PdfWriter
        writer = PdfWriter()
        writer.add_blank_page(width=72, height=72)
        with open(pdf_path, "wb") as f:
            writer.write(f)

        res = self.vault_service.read_file("spark-agent", {"path": "test_document.pdf"})
        self.assertTrue(res.ok)
        self.assertEqual(res.data["content_type"], "extracted_pdf_text")
        self.assertEqual(res.data["mime_type"], "application/pdf")
        self.assertIn("<untrusted_document_content", res.data["envelope"])

    # ==========================================================================
    # 3. Browser Service Lifecycle & Session Ownership Tests
    # ==========================================================================

    def test_06_browser_session_lifecycle_and_ownership(self):
        # Open Session
        res_open = self.browser_service.open_session("spark-agent", {"url": "about:blank"})
        self.assertTrue(res_open.ok)
        session_id = res_open.data["session_id"]
        self.assertTrue(session_id.startswith("brs_"))

        # Snapshot
        res_snap = self.browser_service.snapshot("spark-agent", {"session_id": session_id})
        self.assertTrue(res_snap.ok)
        self.assertIn("<untrusted_web_content", res_snap.data["envelope"])
        self.assertEqual(res_snap.data["element_count"], 5)

        # Cross-Principal Access Denied
        res_other = self.browser_service.snapshot("other-user", {"session_id": session_id})
        self.assertFalse(res_other.ok)
        self.assertEqual(res_other.error_code, "ACCESS_DENIED")

        # Concurrency limit (Max 2 per principal)
        res_open2 = self.browser_service.open_session("spark-agent")
        self.assertTrue(res_open2.ok)
        res_open3 = self.browser_service.open_session("spark-agent")
        self.assertFalse(res_open3.ok)
        self.assertEqual(res_open3.error_code, "SESSION_LIMIT_EXCEEDED")

        # Close session
        res_close = self.browser_service.close_session("spark-agent", {"session_id": session_id})
        self.assertTrue(res_close.ok)
        self.assertTrue(res_close.data["closed"])

    # ==========================================================================
    # 4. Domain Policy & SSRF Rules Tests
    # ==========================================================================

    def test_07_domain_policy_and_ssrf_blocking(self):
        # Trusted UPES / LMS domain
        safe, cat, _ = self.browser_service.validate_url_safety("https://learn.upes.ac.in/ultra/courses")
        self.assertTrue(safe)
        self.assertEqual(cat, "trusted_academic")

        # Blackboard domain
        safe, cat, _ = self.browser_service.validate_url_safety("https://upes.blackboard.com/webapps/login")
        self.assertTrue(safe)
        self.assertEqual(cat, "trusted_academic")

        # Microsoft Auth
        safe, cat, _ = self.browser_service.validate_url_safety("https://login.microsoftonline.com/common/oauth2")
        self.assertTrue(safe)
        self.assertEqual(cat, "trusted_academic")

        # Safe Public Web
        safe, cat, _ = self.browser_service.validate_url_safety("https://en.wikipedia.org/wiki/Deep_learning")
        self.assertTrue(safe)
        self.assertEqual(cat, "safe_public_web")

        # Block Loopback / Localhost
        safe, cat, reason = self.browser_service.validate_url_safety("http://localhost:8080/admin")
        self.assertFalse(safe)
        self.assertEqual(cat, "ssrf_blocked")

        safe, cat, reason = self.browser_service.validate_url_safety("http://127.0.0.1:5000/api")
        self.assertFalse(safe)
        self.assertEqual(cat, "ssrf_blocked")

        # Block Private RFC1918 IPs
        safe, cat, reason = self.browser_service.validate_url_safety("http://192.168.1.1/router")
        self.assertFalse(safe)
        self.assertEqual(cat, "ssrf_blocked")

        safe, cat, reason = self.browser_service.validate_url_safety("http://10.0.0.1/internal")
        self.assertFalse(safe)
        self.assertEqual(cat, "ssrf_blocked")

        # Block Dangerous Schemes
        safe, cat, reason = self.browser_service.validate_url_safety("file:///etc/passwd")
        self.assertFalse(safe)
        self.assertEqual(cat, "dangerous_scheme")

        safe, cat, reason = self.browser_service.validate_url_safety("javascript:alert(1)")
        self.assertFalse(safe)
        self.assertEqual(cat, "dangerous_scheme")

    # ==========================================================================
    # 5. Consequential Action Guard Tests
    # ==========================================================================

    def test_08_consequential_click_and_submit_blocked(self):
        res_open = self.browser_service.open_session("spark-agent")
        sid = res_open.data["session_id"]
        # Populate snapshot element cache
        self.browser_service.snapshot("spark-agent", {"session_id": sid})

        # e1 is 'Submit Assignment' -> MUST BE BLOCKED
        res_click_submit = self.browser_service.click("spark-agent", {"session_id": sid, "element": "e1"})
        self.assertFalse(res_click_submit.ok)
        self.assertEqual(res_click_submit.error_code, "CONSEQUENTIAL_ACTION_BLOCKED")
        self.assertIn("submit", res_click_submit.error.lower())

        # e0 is 'Course Syllabus PDF' -> Allowed
        res_click_link = self.browser_service.click("spark-agent", {"session_id": sid, "element": "e0"})
        self.assertTrue(res_click_link.ok)

        # press Enter on focused consequential button -> MUST BE BLOCKED
        res_press_submit = self.browser_service.press("spark-agent", {
            "session_id": sid,
            "element": "e1",
            "key": "Enter"
        })
        self.assertFalse(res_press_submit.ok)
        self.assertEqual(res_press_submit.error_code, "CONSEQUENTIAL_ACTION_BLOCKED")

        # press Space on focused consequential button -> MUST BE BLOCKED
        res_space_submit = self.browser_service.press("spark-agent", {
            "session_id": sid,
            "element": "e1",
            "key": "Space"
        })
        self.assertFalse(res_space_submit.ok)
        self.assertEqual(res_space_submit.error_code, "CONSEQUENTIAL_ACTION_BLOCKED")

        # press Enter inside an input on a page with submit button -> MUST BE BLOCKED
        self.browser_service.type_text("spark-agent", {"session_id": sid, "element": "e2", "text": "Draft"})
        res_press_input = self.browser_service.press("spark-agent", {
            "session_id": sid,
            "key": "Enter"
        })
        self.assertFalse(res_press_input.ok)
        self.assertEqual(res_press_input.error_code, "CONSEQUENTIAL_ACTION_BLOCKED")

    # ==========================================================================
    # 6. Paired browser.capture & Screenshot Artifact Storage Tests
    # ==========================================================================

    def test_09_paired_browser_capture_and_screenshot_artifact(self):
        res_open = self.browser_service.open_session("spark-agent")
        sid = res_open.data["session_id"]

        # Paired capture
        res_cap = self.browser_service.capture("spark-agent", {"session_id": sid})
        self.assertTrue(res_cap.ok)
        data = res_cap.data
        self.assertTrue(data["capture_id"].startswith("cap_"))
        self.assertEqual(data["session_id"], sid)
        self.assertIn("<untrusted_web_content", data["envelope"])
        self.assertIn("screenshot", data)
        self.assertTrue(os.path.exists(data["screenshot"]["storage_path"]))
        self.assertTrue(data["screenshot"]["artifact_uri"].startswith("/api/artifacts/screenshots/"))
        self.assertGreater(data["screenshot"]["size_bytes"], 0)

        # Standalone screenshot
        res_scr = self.browser_service.screenshot("spark-agent", {"session_id": sid})
        self.assertTrue(res_scr.ok)
        self.assertTrue(os.path.exists(res_scr.data["storage_path"]))

    # ==========================================================================
    # 7. Controlled Transfer Pipelines (Download & Upload) Tests
    # ==========================================================================

    def test_10_controlled_download_pipeline(self):
        res_open = self.browser_service.open_session("spark-agent")
        sid = res_open.data["session_id"]

        res_dl = self.browser_service.download("spark-agent", {
            "session_id": sid,
            "element": "e0",
            "destination_path": "Deep Learning/syllabus.pdf"
        })
        self.assertTrue(res_dl.ok)
        self.assertEqual(res_dl.data["vault_path"], "Deep Learning/syllabus.pdf")
        self.assertTrue(os.path.exists(os.path.join(self.vault_dir, "Deep Learning", "syllabus.pdf")))
        self.assertGreater(res_dl.data["size_bytes"], 0)
        self.assertTrue(res_dl.data["sha256"])

    def test_11_controlled_upload_draft_pipeline(self):
        res_open = self.browser_service.open_session("spark-agent")
        sid = res_open.data["session_id"]

        # Create file in vault first
        self.vault_service.create_file("spark-agent", {
            "path": "solution.pdf",
            "content": "%PDF-1.4 Solution data"
        })

        res_up = self.browser_service.upload("spark-agent", {
            "session_id": sid,
            "element": "e3",
            "vault_path": "solution.pdf"
        })
        self.assertTrue(res_up.ok)
        self.assertTrue(res_up.data["uploaded_draft"])
        self.assertFalse(res_up.data["is_final_submission"])

    # ==========================================================================
    # 8. MCP 2026-07-28 27-Tool Catalog & Gateway Tests
    # ==========================================================================

    def test_12_mcp_gateway_27_tools_and_schemas(self):
        self.assertGreaterEqual(len(MCP_TOOL_DEFINITIONS), 27)

        token_mgr = MagicMock()
        adapter = McpServerAdapter(registry=self.registry, token_manager=token_mgr)

        req = {
            "jsonrpc": "2.0",
            "id": 100,
            "method": "tools/list",
            "params": {"_meta": {"io.modelcontextprotocol/protocolVersion": "2026-07-28"}}
        }
        token_meta = {
            "principal": "spark-agent",
            "capabilities": [t["required_capability"] for t in MCP_TOOL_DEFINITIONS]
        }
        orig_mode = getattr(config, "MCP_CATALOG_MODE", "semantic")
        config.MCP_CATALOG_MODE = "legacy"
        try:
            resp = adapter.handle_json_rpc(req, token_meta)
            tools = resp["result"]["tools"]
            self.assertGreaterEqual(len(tools), 27)

            # Verify JSON Schema 2020-12 in every tool
            for t in tools:
                schema = t["inputSchema"]
                self.assertEqual(schema.get("$schema"), "https://json-schema.org/draft/2020-12/schema")
                self.assertEqual(schema.get("type"), "object")
        finally:
            config.MCP_CATALOG_MODE = orig_mode


if __name__ == "__main__":
    unittest.main()
