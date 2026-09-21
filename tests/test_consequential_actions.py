"""
Unit Tests for Phase 3.6A: Consequential Action Engine, Cryptographic Approval Grants & LMS Submission Foundation
"""

import os
import sys
import time
import json
import uuid
import hmac
import shutil
import hashlib
import sqlite3
import tempfile
import unittest
from typing import Dict, Any, List, Optional, Tuple
from unittest.mock import MagicMock, patch


# Ensure server package path
SERVER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

import config
import agent
from agent import (
    ConsequentialActionManager,
    ConsequentialExecutor,
    ApprovalCryptoProvider,
    ConsequentialAction,
    ApprovalRequest,
    ApprovalGrant,
    ConsequentialState,
    ApprovalState,
    LMSService,
    VaultService,
    BrowserService,
    AgentOperationRegistry,
    RiskClass,
    init_consequential_tables,
)
from lms.models import LMSCourse, LMSAssignment, SubmissionPlan, SubmissionState
from lms.base import LMSProvider
from lms.errors import SubmissionPlanInvalidError


class SyntheticMockLMSProvider(LMSProvider):
    """Synthetic Moodle Provider for pure unit and integration testing without external networks."""

    def __init__(self):
        super().__init__()
        self.submitted_assignments = {}
        self.submit_call_count = 0

    @property
    def provider_name(self) -> str:
        return "synthetic_moodle"

    def check_auth(self) -> bool:
        return True

    def list_courses(self, query: Optional[str] = None, active_only: bool = True):
        return [LMSCourse(id="c1", course_id="lmscourse_101", short_name="DL", full_name="Deep Learning", is_active=True)], "synthetic"

    def get_course(self, course_id: str):
        return LMSCourse(id="c1", course_id="lmscourse_101", short_name="DL", full_name="Deep Learning", is_active=True), {"sections": []}, "synthetic"

    def list_resources(self, course_id: str = None, section: Optional[str] = None):
        return [], "synthetic"


    def download_resource(self, resource_id: str, dest_vault_abs_path: str, max_bytes: int = 52428800):
        return {"downloaded": True}

    def list_assignments(self, course_id: str = None, upcoming_only: bool = False):
        return [LMSAssignment(id="a1", assignment_id="lmsassign_999", course_id="lmscourse_101", title="Assignment 1", allows_submissions=True)], "synthetic"

    def get_assignment(self, assignment_id: str):
        return LMSAssignment(id="a1", assignment_id="lmsassign_999", course_id="lmscourse_101", title="Assignment 1", allows_submissions=True), "synthetic"

    def prepare_submission(self, assignment_id: str, vault_file_records, browser_service=None):
        return {
            "page_verified": True,
            "draft_upload_verified": True,
            "attached_files": [f["vault_path"] for f in vault_file_records],
            "capture_id": "cap_synth_001",
            "screenshot_artifact": "artifacts/pre_submit.png",
            "current_url": f"https://mock-moodle.example.com/mod/assign/view.php?id={assignment_id}",
            "final_action_required": True
        }, "synthetic"

    def inspect_submission_status(self, assignment_id: str, browser_service=None):
        is_sub = assignment_id in self.submitted_assignments
        return is_sub, {
            "assignment_id": assignment_id,
            "is_submitted": is_sub,
            "submission_status": "submitted" if is_sub else "draft",
            "submitted_timestamp": self.submitted_assignments.get(assignment_id, {}).get("timestamp")
        }

    def submit_final_assignment(self, assignment_id: str, vault_file_records, browser_service=None, session_id=None):
        self.submit_call_count += 1
        now = time.time()
        self.submitted_assignments[assignment_id] = {
            "timestamp": now,
            "files": vault_file_records
        }
        return True, {
            "verified": True,
            "submission_status": "submitted",
            "post_capture_id": "cap_synth_post_001",
            "post_screenshot_artifact": "artifacts/post_submit.png",
            "post_url": f"https://mock-moodle.example.com/mod/assign/view.php?id={assignment_id}",
            "timestamp": now
        }, "synthetic"


class TestConsequentialActions(unittest.TestCase):
    """Test suite for Consequential Action Engine, Crypto Grants, and LMS Submission Pipeline."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_nexus.db")
        self.vault_dir = os.path.join(self.temp_dir, "vault")
        os.makedirs(self.vault_dir, exist_ok=True)

        self._orig_vault_root = config.AGENT_VAULT_ROOT
        config.AGENT_VAULT_ROOT = self.vault_dir

        self.conn_factory = lambda: sqlite3.connect(self.db_path)
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            init_consequential_tables(conn)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS submission_plans (
                    submission_plan_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    course_id TEXT NOT NULL,
                    assignment_id TEXT NOT NULL,
                    assignment_title TEXT NOT NULL,
                    vault_files_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    page_url TEXT NOT NULL,
                    capture_id TEXT,
                    screenshot_artifact TEXT,
                    page_verified INTEGER NOT NULL DEFAULT 0,
                    draft_upload_verified INTEGER NOT NULL DEFAULT 0,
                    state TEXT NOT NULL DEFAULT 'DRAFT',
                    final_action_required INTEGER NOT NULL DEFAULT 1
                );
            """)
            conn.commit()

        self.action_mgr = ConsequentialActionManager(self.conn_factory)
        self.executor = ConsequentialExecutor(self.action_mgr, self.conn_factory)
        self.mock_provider = SyntheticMockLMSProvider()
        self.lms_service = LMSService(
            conn_factory=self.conn_factory,
            provider=self.mock_provider,
            consequential_mgr=self.action_mgr
        )

    def tearDown(self):
        config.AGENT_VAULT_ROOT = self._orig_vault_root
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # --------------------------------------------------------------------------
    # 1. Cryptographic Domain Separation & Signing
    # --------------------------------------------------------------------------

    def test_approval_crypto_domain_separation(self):
        """Verifies ApprovalCryptoProvider uses HKDF domain 'nexusnode/approval/v1'."""
        key = ApprovalCryptoProvider._derive_approval_key()
        self.assertEqual(len(key), 32)

        # Signing and verification
        sig = ApprovalCryptoProvider.sign_grant(
            grant_id="grant_1",
            approval_id="appr_1",
            action_id="act_1",
            operation="lms.submit_assignment",
            user_id="alice",
            parameters_hash="abc123hash",
            created_at=1000.0,
            expires_at=1900.0,
            nonce="nonce123"
        )
        self.assertTrue(isinstance(sig, str))
        self.assertEqual(len(sig), 64)

        grant = ApprovalGrant(
            grant_id="grant_1",
            approval_id="appr_1",
            action_id="act_1",
            operation="lms.submit_assignment",
            user_id="alice",
            parameters_hash="abc123hash",
            created_at=1000.0,
            expires_at=1900.0,
            nonce="nonce123",
            signature=sig
        )
        self.assertTrue(ApprovalCryptoProvider.verify_grant_signature(grant))

        # Tampered parameter hash must fail
        grant_tampered = ApprovalGrant(
            grant_id="grant_1",
            approval_id="appr_1",
            action_id="act_1",
            operation="lms.submit_assignment",
            user_id="alice",
            parameters_hash="TAMPERED_HASH",
            created_at=1000.0,
            expires_at=1900.0,
            nonce="nonce123",
            signature=sig
        )
        self.assertFalse(ApprovalCryptoProvider.verify_grant_signature(grant_tampered))

    # --------------------------------------------------------------------------
    # 2. Consequential Action & Approval Request Lifecycle
    # --------------------------------------------------------------------------

    def test_consequential_action_request_and_deduplication(self):
        """Verifies ConsequentialAction and ApprovalRequest creation and deduplication."""
        action1, appr1, dedup1 = self.action_mgr.request_consequential_action(
            user_id="alice",
            principal="spark-agent",
            operation="lms.submit_assignment",
            target_type="moodle_assignment",
            target_id="lmsassign_101",
            parameters={"plan_id": "subplan_1"},
            summary={"title": "Assignment 1"},
            evidence_references={"screenshot": "pre.png"}
        )
        self.assertFalse(dedup1)
        self.assertEqual(action1.state, ConsequentialState.APPROVAL_REQUIRED)
        self.assertEqual(appr1.state, ApprovalState.PENDING)

        # Immediate second call with identical parameters must be deduplicated
        action2, appr2, dedup2 = self.action_mgr.request_consequential_action(
            user_id="alice",
            principal="spark-agent",
            operation="lms.submit_assignment",
            target_type="moodle_assignment",
            target_id="lmsassign_101",
            parameters={"plan_id": "subplan_1"},
            summary={"title": "Assignment 1"},
            evidence_references={"screenshot": "pre.png"}
        )
        self.assertTrue(dedup2)
        self.assertEqual(action1.action_id, action2.action_id)
        self.assertEqual(appr1.approval_id, appr2.approval_id)

    def test_approve_and_deny_lifecycle(self):
        """Verifies approval and denial state transitions."""
        action, appr, _ = self.action_mgr.request_consequential_action(
            user_id="bob",
            principal="spark-agent",
            operation="lms.submit_assignment",
            target_type="moodle_assignment",
            target_id="lmsassign_202",
            parameters={"plan_id": "subplan_2"},
            summary={"title": "Assignment 2"},
            evidence_references={}
        )

        # Approve
        act_approved, grant = self.action_mgr.approve_action(appr.approval_id, user_id="bob")
        self.assertEqual(act_approved.state, ConsequentialState.APPROVED)
        self.assertTrue(ApprovalCryptoProvider.verify_grant_signature(grant))

        # Re-approving must be idempotent
        act_reapp, grant_reapp = self.action_mgr.approve_action(appr.approval_id, user_id="bob")
        self.assertEqual(act_reapp.state, ConsequentialState.APPROVED)
        self.assertEqual(grant.grant_id, grant_reapp.grant_id)

    def test_denial_transition(self):
        """Verifies denial transitions action and prevents execution."""
        action, appr, _ = self.action_mgr.request_consequential_action(
            user_id="charlie",
            principal="spark-agent",
            operation="lms.submit_assignment",
            target_type="moodle_assignment",
            target_id="lmsassign_303",
            parameters={"plan_id": "subplan_3"},
            summary={"title": "Assignment 3"},
            evidence_references={}
        )

        denied_appr = self.action_mgr.deny_action(appr.approval_id, user_id="charlie", reason="Not ready")
        self.assertEqual(denied_appr.state, ApprovalState.DENIED)

        act = self.action_mgr.get_action(action.action_id)
        self.assertEqual(act.state, ConsequentialState.DENIED)

        # Denying twice is idempotent
        denied_again = self.action_mgr.deny_action(appr.approval_id, user_id="charlie")
        self.assertEqual(denied_again.state, ApprovalState.DENIED)

    def test_cross_user_authorization_rejected(self):
        """Ensures User B cannot approve or deny User A's approval request."""
        action, appr, _ = self.action_mgr.request_consequential_action(
            user_id="user_a",
            principal="spark-agent",
            operation="lms.submit_assignment",
            target_type="moodle_assignment",
            target_id="lmsassign_404",
            parameters={"plan_id": "subplan_4"},
            summary={},
            evidence_references={}
        )

        with self.assertRaises(PermissionError):
            self.action_mgr.approve_action(appr.approval_id, user_id="user_b")

        with self.assertRaises(PermissionError):
            self.action_mgr.deny_action(appr.approval_id, user_id="user_b")

    # --------------------------------------------------------------------------
    # 3. Single-Use Grants & Replay Protection
    # --------------------------------------------------------------------------

    def test_single_use_grant_replay_blocked(self):
        """Verifies an ApprovalGrant can only be consumed once."""
        action, appr, _ = self.action_mgr.request_consequential_action(
            user_id="alice",
            principal="spark-agent",
            operation="lms.submit_assignment",
            target_type="moodle_assignment",
            target_id="lmsassign_505",
            parameters={"plan_id": "subplan_5"},
            summary={},
            evidence_references={}
        )
        self.action_mgr.approve_action(appr.approval_id, user_id="alice")

        executed_count = 0
        def fake_exec(act, grt):
            nonlocal executed_count
            executed_count += 1
            return True, {"submitted": True}, None

        # First execution succeeds
        res1 = self.executor.execute_action(action.action_id, fake_exec)
        self.assertTrue(res1["ok"])
        self.assertEqual(executed_count, 1)

        # Second execution attempt with same action/grant must be rejected or report already succeeded
        res2 = self.executor.execute_action(action.action_id, fake_exec)
        self.assertEqual(res2["status"], "already_succeeded")
        self.assertEqual(executed_count, 1)

    # --------------------------------------------------------------------------
    # 4. TOCTOU File Protection & SubmissionPlan Binding
    # --------------------------------------------------------------------------

    def _create_synthetic_vault_file(self, rel_path: str, content: bytes) -> Dict[str, Any]:
        full_path = os.path.join(self.vault_dir, rel_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "wb") as f:
            f.write(content)
        return {
            "vault_path": rel_path,
            "size": len(content),
            "sha256": hashlib.sha256(content).hexdigest()
        }

    def _create_synthetic_submission_plan(self, user_id: str, file_records: list) -> str:
        plan_id = f"subplan_{uuid.uuid4().hex[:10]}"
        now = time.time()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO submission_plans (
                    submission_plan_id, user_id, course_id, assignment_id, assignment_title,
                    vault_files_json, created_at, expires_at, page_url, capture_id,
                    screenshot_artifact, page_verified, draft_upload_verified, state,
                    final_action_required
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 1, 'READY_FOR_REVIEW', 1)
            """, (
                plan_id, user_id, "lmscourse_101", "lmsassign_999", "Assignment 1",
                json.dumps(file_records), now, now + 3600.0, "https://mock-moodle.example.com",
                "cap_001", "artifacts/pre.png"
            ))
            conn.commit()
        return plan_id

    def test_spark_requests_submission_returns_approval_required(self):
        """Spark calls lms.submit_assignment -> returns APPROVAL_REQUIRED without secret material."""
        file_rec = self._create_synthetic_vault_file("DL/solution.pdf", b"Original Solution Content")
        plan_id = self._create_synthetic_submission_plan("admin", [file_rec])

        res = self.lms_service.submit_assignment("admin", {"submission_plan_id": plan_id})
        self.assertFalse(res.ok)
        self.assertEqual(res.error_code, "APPROVAL_REQUIRED")
        self.assertEqual(res.data["status"], "approval_required")
        self.assertIn("action_id", res.data)
        self.assertIn("approval_id", res.data)
        self.assertIn("summary", res.data)
        # Verify NO secret key material is returned to Spark
        self.assertNotIn("signature", res.data)
        self.assertNotIn("grant", res.data)

    def test_toctou_file_mutation_invalidates_submission(self):
        """Verifies mutating Vault file on disk after approval triggers TOCTOU invalidation."""
        file_rec = self._create_synthetic_vault_file("DL/report.pdf", b"Initial Report PDF")
        plan_id = self._create_synthetic_submission_plan("admin", [file_rec])

        # 1. Request submission
        res = self.lms_service.submit_assignment("admin", {"submission_plan_id": plan_id})
        appr_id = res.data["approval_id"]
        act_id = res.data["action_id"]

        # 2. Human approves action
        self.action_mgr.approve_action(appr_id, user_id="admin")

        # 3. Malicious / Concurrent modification of file on disk
        full_path = os.path.join(self.vault_dir, "DL/report.pdf")
        with open(full_path, "wb") as f:
            f.write(b"MUTATED CONTENT BY ADVERSARY")

        # 4. Executor executes
        exec_res = self.executor.execute_action(
            act_id,
            self.lms_service.execute_approved_submission,
            self.lms_service.inspect_remote_submission_state
        )

        self.assertFalse(exec_res["ok"])
        self.assertEqual(self.mock_provider.submit_call_count, 0)

        # Action and plan must be invalidated
        act = self.action_mgr.get_action(act_id)
        self.assertEqual(act.state, ConsequentialState.INVALIDATED)

    def test_synthetic_end_to_end_submission_flow(self):
        """
        Complete Synthetic E2E Flow:
        Prepare -> Submit Request (APPROVAL_REQUIRED) -> Human Approve -> Internal Execute -> Positive Verification.
        """
        file_rec = self._create_synthetic_vault_file("DL/final.pdf", b"Valid PDF Payload")
        plan_id = self._create_synthetic_submission_plan("admin", [file_rec])

        # 1. Spark request
        req_res = self.lms_service.submit_assignment("admin", {"submission_plan_id": plan_id})
        self.assertEqual(req_res.data["status"], "approval_required")
        appr_id = req_res.data["approval_id"]
        act_id = req_res.data["action_id"]

        # 2. Human approves via API
        action, grant = self.action_mgr.approve_action(appr_id, user_id="admin")
        self.assertEqual(action.state, ConsequentialState.APPROVED)

        # 3. Controlled internal executor runs
        exec_res = self.executor.execute_action(
            act_id,
            self.lms_service.execute_approved_submission,
            self.lms_service.inspect_remote_submission_state
        )

        self.assertTrue(exec_res["ok"])
        self.assertEqual(exec_res["status"], "succeeded")
        self.assertEqual(self.mock_provider.submit_call_count, 1)

        # Action is now SUCCEEDED
        act = self.action_mgr.get_action(act_id)
        self.assertEqual(act.state, ConsequentialState.SUCCEEDED)

        # Query action status via action.status
        stat_res = self.lms_service.get_action_status("admin", {"action_id": act_id})
        self.assertTrue(stat_res.ok)
        self.assertEqual(stat_res.data["state"], "SUCCEEDED")

    def test_crash_recovery_before_double_submit(self):
        """Simulates crash after remote Moodle submission: detects submitted state and recovers without re-clicking."""
        file_rec = self._create_synthetic_vault_file("DL/crash.pdf", b"Crash Recovery Test")
        plan_id = self._create_synthetic_submission_plan("admin", [file_rec])

        req_res = self.lms_service.submit_assignment("admin", {"submission_plan_id": plan_id})
        appr_id = req_res.data["approval_id"]
        act_id = req_res.data["action_id"]

        self.action_mgr.approve_action(appr_id, user_id="admin")

        # Simulate that remote Moodle already has the assignment submitted (e.g. from prior network attempt)
        self.mock_provider.submitted_assignments["lmsassign_999"] = {
            "timestamp": time.time() - 10,
            "files": [file_rec]
        }

        # Execute
        res = self.executor.execute_action(
            act_id,
            self.lms_service.execute_approved_submission,
            self.lms_service.inspect_remote_submission_state
        )

        self.assertTrue(res["ok"])
        self.assertEqual(res["status"], "recovered_succeeded")
        # Ensure submit was NOT called again
        self.assertEqual(self.mock_provider.submit_call_count, 0)

    def test_browser_consequential_guard_remains_active(self):
        """Ensures generic browser service continues to block consequential keywords."""
        mock_pinchtab = MagicMock()
        browser_svc = BrowserService(provider=mock_pinchtab, vault_service=VaultService(agent_vault_root=self.vault_dir))

        # Inject fake session with consequential submit element
        session_id = "test_sess"
        browser_svc._sessions[session_id] = {
            "owner": "admin",
            "created_at": time.time(),
            "last_activity": time.time()
        }
        browser_svc._element_cache[session_id] = {
            "e1": {"name": "Submit assignment", "role": "button", "text": "Submit"}
        }

        # Attempt to click Submit through generic browser tool
        click_res = browser_svc.click("admin", {"session_id": session_id, "element": "e1"})
        self.assertFalse(click_res.ok)
        self.assertEqual(click_res.error_code, "CONSEQUENTIAL_ACTION_BLOCKED")
        mock_pinchtab.click.assert_not_called()



    def test_audit_log_contains_zero_secrets(self):
        """Verifies consequential audit log entries do not leak passwords, tokens, or signing secrets."""
        file_rec = self._create_synthetic_vault_file("DL/audit.pdf", b"Audit Test")
        plan_id = self._create_synthetic_submission_plan("admin", [file_rec])

        req_res = self.lms_service.submit_assignment("admin", {"submission_plan_id": plan_id})
        appr_id = req_res.data["approval_id"]
        act_id = req_res.data["action_id"]

        self.action_mgr.approve_action(appr_id, user_id="admin")
        self.executor.execute_action(
            act_id,
            self.lms_service.execute_approved_submission,
            self.lms_service.inspect_remote_submission_state
        )

        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM consequential_audit_log")
            rows = cur.fetchall()
            self.assertGreater(len(rows), 0)
            for r in rows:
                details = r[11]  # details_json
                self.assertNotIn("password", details.lower())
                self.assertNotIn("token", details.lower())
                self.assertNotIn("secret", details.lower())
                self.assertNotIn("cookie", details.lower())


    def test_target_assignment_mismatch_rejected(self):
        """Verifies that if target assignment ID does not match the SubmissionPlan, execution is rejected."""
        file_rec = self._create_synthetic_vault_file("DL/mismatch.pdf", b"Mismatch Test")
        plan_id = self._create_synthetic_submission_plan("admin", [file_rec])

        req_res = self.lms_service.submit_assignment("admin", {"submission_plan_id": plan_id})
        appr_id = req_res.data["approval_id"]
        act_id = req_res.data["action_id"]

        self.action_mgr.approve_action(appr_id, user_id="admin")

        # Tamper target_id in consequential action
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("UPDATE consequential_actions SET target_id = 'lmsassign_WRONG' WHERE action_id = ?", (act_id,))
            conn.commit()

        exec_res = self.executor.execute_action(
            act_id,
            self.lms_service.execute_approved_submission,
            self.lms_service.inspect_remote_submission_state
        )
        self.assertFalse(exec_res["ok"])
        self.assertEqual(self.mock_provider.submit_call_count, 0)

    def test_expired_grant_rejected_at_execution(self):
        """Verifies that executing an expired grant raises ApprovalExpiredError."""
        file_rec = self._create_synthetic_vault_file("DL/expired.pdf", b"Expired Test")
        plan_id = self._create_synthetic_submission_plan("admin", [file_rec])

        req_res = self.lms_service.submit_assignment("admin", {"submission_plan_id": plan_id})
        appr_id = req_res.data["approval_id"]
        act_id = req_res.data["action_id"]

        self.action_mgr.approve_action(appr_id, user_id="admin")

        # Manually expire the grant in DB
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("UPDATE approval_grants SET expires_at = ? WHERE action_id = ?", (time.time() - 100, act_id))
            conn.commit()

        with self.assertRaises(agent.ApprovalExpiredError):
            self.executor.execute_action(
                act_id,
                self.lms_service.execute_approved_submission,
                self.lms_service.inspect_remote_submission_state
            )

    def test_event_dispatcher_receives_lifecycle_events(self):
        """Verifies register_event_listener receives approval.required, approval.approved, and consequential.succeeded."""
        events_received = []
        def listener(name, payload):
            events_received.append((name, payload))

        agent.register_event_listener(listener)

        file_rec = self._create_synthetic_vault_file("DL/events.pdf", b"Events Test")
        plan_id = self._create_synthetic_submission_plan("admin", [file_rec])

        req_res = self.lms_service.submit_assignment("admin", {"submission_plan_id": plan_id})
        appr_id = req_res.data["approval_id"]
        act_id = req_res.data["action_id"]

        self.action_mgr.approve_action(appr_id, user_id="admin")
        self.executor.execute_action(
            act_id,
            self.lms_service.execute_approved_submission,
            self.lms_service.inspect_remote_submission_state
        )

        event_names = [e[0] for e in events_received]
        self.assertIn("approval.required", event_names)
        self.assertIn("approval.approved", event_names)
        self.assertIn("consequential.started", event_names)
        self.assertIn("consequential.succeeded", event_names)

    def test_mcp_gateway_submit_assignment_tool_metadata(self):
        """Verifies MCP_TOOL_DEFINITIONS contains lms.submit_assignment with consequential capability."""
        from agent.mcp_server import MCP_TOOL_DEFINITIONS
        tool_names = {t["name"]: t for t in MCP_TOOL_DEFINITIONS}
        self.assertIn("lms.submit_assignment", tool_names)
        self.assertIn("action.status", tool_names)

        submit_tool = tool_names["lms.submit_assignment"]
        self.assertEqual(submit_tool["required_capability"], "lms.submission.request")
        self.assertIn("submission_plan_id", submit_tool["inputSchema"]["properties"])

        status_tool = tool_names["action.status"]
        self.assertEqual(status_tool["required_capability"], "action.status.read")


if __name__ == "__main__":
    unittest.main()

