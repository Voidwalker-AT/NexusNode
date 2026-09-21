"""
Unit and Integration Tests for Agent API Endpoints:
/api/approvals, /api/approvals/<id>/approve, /api/approvals/<id>/deny,
/api/upes/session/status, /api/browser/status, and /api/agent/execute.
"""

import time
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch, MagicMock

import config
import app as nexus_app
import agent
from agent.policy import RiskClass, ApprovalStatus


class TestAgentAPIEndpoints(unittest.TestCase):

    def setUp(self):
        nexus_app.app.config['TESTING'] = True
        self.client = nexus_app.app.test_client()

        # Generate test auth session tokens
        self.admin_token = nexus_app.create_user_session({
            "user_id": "admin",
            "role": "admin",
            "privileges": config.ADMIN_DEFAULT_PRIVILEGES
        })
        self.user_token = nexus_app.create_user_session({
            "user_id": "test_student",
            "role": "user",
            "privileges": config.USER_DEFAULT_PRIVILEGES
        })

    def test_approvals_api_unauthenticated(self):
        resp = self.client.get("/api/approvals")
        self.assertEqual(resp.status_code, 401)

    def test_approvals_lifecycle_api(self):
        # 1. Create approval request
        pending = nexus_app.approval_manager.create_approval(
            operation="upes.submit_assignment",
            description="Submit assignment for Lab 4",
            requested_by="test_student",
            safe_context={"module_id": "CS302", "file": "lab4.pdf"}
        )
        appr_id = pending.id

        # 2. List approvals as user (sees own approval)
        resp = self.client.get(
            "/api/approvals",
            headers={"Authorization": f"Bearer {self.user_token}"}
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(any(a["id"] == appr_id for a in data["approvals"]))

        # 3. Get single approval
        resp = self.client.get(
            f"/api/approvals/{appr_id}",
            headers={"Authorization": f"Bearer {self.user_token}"}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["approval"]["id"], appr_id)

        # 4. Standard user cannot approve consequential action (Forbidden)
        resp = self.client.post(
            f"/api/approvals/{appr_id}/approve",
            headers={"Authorization": f"Bearer {self.user_token}"}
        )
        self.assertEqual(resp.status_code, 403)

        # 5. Admin authorizes action
        resp = self.client.post(
            f"/api/approvals/{appr_id}/approve",
            headers={"Authorization": f"Bearer {self.admin_token}"}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["approval"]["status"], "APPROVED")

    def test_upes_session_status_api(self):
        resp = self.client.get(
            "/api/upes/session/status",
            headers={"Authorization": f"Bearer {self.admin_token}"}
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("session", data)
        sess = data["session"]
        self.assertIn("state", sess)
        self.assertNotIn("encrypted_access_token", sess)

    def test_browser_status_api(self):
        resp = self.client.get(
            "/api/browser/status",
            headers={"Authorization": f"Bearer {self.admin_token}"}
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("browser", data)
        self.assertEqual(data["browser"]["provider"], "pinchtab")

    def test_agent_execute_api_read_only(self):
        resp = self.client.post(
            "/api/agent/execute",
            headers={"Authorization": f"Bearer {self.admin_token}"},
            json={"operation": "browser.status"}
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["operation"], "browser.status")
        self.assertEqual(data["provenance"]["provider"], "pinchtab")

    def test_agent_execute_api_consequential_flow(self):
        # Register test consequential operation
        nexus_app.agent_registry.register(
            "portal.payment",
            lambda user_id, params, **kw: agent.ExecutionResult(ok=True, operation="portal.payment", source="local", provider="test", data={"payment_status": "PAID"}),
            risk_class=RiskClass.CONSEQUENTIAL
        )

        # Consequential action without approval -> returns requires_approval=True
        resp = self.client.post(
            "/api/agent/execute",
            headers={"Authorization": f"Bearer {self.admin_token}"},
            json={
                "operation": "portal.payment",
                "params": {"amount": 500, "account": "1234"},
                "description": "Tuition Fee Payment"
            }
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertFalse(data["ok"])
        self.assertTrue(data["requires_approval"])
        appr_id = data["approval_id"]
        self.assertTrue(appr_id.startswith("appr_"))

        # Admin approves
        resp_appr = self.client.post(
            f"/api/approvals/{appr_id}/approve",
            headers={"Authorization": f"Bearer {self.admin_token}"}
        )
        self.assertEqual(resp_appr.status_code, 200)

        # Execute with approved grant
        resp_exec = self.client.post(
            "/api/agent/execute",
            headers={"Authorization": f"Bearer {self.admin_token}"},
            json={
                "operation": "portal.payment",
                "params": {"amount": 500, "account": "1234"},
                "approval_id": appr_id
            }
        )
        self.assertEqual(resp_exec.status_code, 200)
        data_exec = resp_exec.get_json()
        self.assertTrue(data_exec["ok"])
        self.assertEqual(data_exec["data"]["payment_status"], "PAID")


if __name__ == "__main__":
    unittest.main()
