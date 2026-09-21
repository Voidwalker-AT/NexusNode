"""
Tests for Phase 4.2A REST Endpoints:
- GET /api/dashboard/summary
- GET /api/mcp/summary
- GET /api/lms/courses
- GET /api/lms/assignments
- GET /api/lms/resources
- POST /api/vault/mkdir
- POST /api/vault/rename
"""

import os
import json
import pytest
import sqlite3
from unittest.mock import patch, MagicMock

import app as flask_app


@pytest.fixture
def client():
    flask_app.app.config["TESTING"] = True
    with flask_app.app.test_client() as c:
        yield c


def test_dashboard_summary_requires_auth(client):
    res = client.get("/api/dashboard/summary")
    assert res.status_code == 401


def test_dashboard_summary_authenticated(client):
    # Mock user session
    session_token = "test_dash_token_123"
    with flask_app.SESSIONS_LOCK:
        flask_app.SESSIONS[session_token] = {
            "user_id": "teststudent",
            "username": "teststudent",
            "role": "user",
            "expires_at": 9999999999.0,
            "privileges": {"can_sync_timetable": True, "can_upload_files": True}
        }

    res = client.get(
        "/api/dashboard/summary",
        headers={"Authorization": f"Bearer {session_token}"}
    )
    assert res.status_code == 200
    data = res.get_json()
    assert "appliance" in data
    assert data["appliance"]["device"] == "TECNO BG6 (Android 13 / Termux)"
    assert "account" in data
    assert data["account"]["user_id"] == "teststudent"
    assert "schedule" in data
    assert "attendance" in data
    assert "mcp" in data
    assert data["mcp"]["catalog"] == "nexus-semantic-v1"
    assert data["mcp"]["tools_count"] == 11
    assert "alerts" in data


def test_mcp_summary_requires_auth(client):
    res = client.get("/api/mcp/summary")
    assert res.status_code == 401


def test_mcp_summary_authenticated(client):
    session_token = "test_mcp_token_123"
    with flask_app.SESSIONS_LOCK:
        flask_app.SESSIONS[session_token] = {
            "user_id": "admin",
            "username": "admin",
            "role": "admin",
            "expires_at": 9999999999.0,
            "privileges": {}
        }

    res = client.get(
        "/api/mcp/summary",
        headers={"Authorization": f"Bearer {session_token}"}
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] in ("HEALTHY", "DISABLED")
    assert data["catalog_version"] == "nexus-semantic-v1"
    assert data["tools_count"] == 11
    assert len(data["tools"]) == 11
    assert any(t["name"] == "nexus.status" for t in data["tools"])
    assert any(t["name"] == "academic.query" for t in data["tools"])
    assert "authorized_clients" in data
    assert "recent_activity" in data


def test_lms_courses_authenticated(client):
    session_token = "test_lms_token_123"
    with flask_app.SESSIONS_LOCK:
        flask_app.SESSIONS[session_token] = {
            "user_id": "teststudent",
            "username": "teststudent",
            "role": "user",
            "expires_at": 9999999999.0,
            "privileges": {"can_sync_timetable": True}
        }

    res = client.get(
        "/api/lms/courses",
        headers={"Authorization": f"Bearer {session_token}"}
    )
    # Returns 200 with courses or 400 if auth required to LMS
    assert res.status_code in (200, 400)


def test_vault_mkdir_and_rename(client, tmp_path):
    session_token = "test_vault_token_123"
    with flask_app.SESSIONS_LOCK:
        flask_app.SESSIONS[session_token] = {
            "user_id": "admin",
            "username": "admin",
            "role": "admin",
            "expires_at": 9999999999.0,
            "privileges": {"can_manage_files": True}
        }

    # Create folder
    res_mkdir = client.post(
        "/api/vault/mkdir",
        headers={"Authorization": f"Bearer {session_token}"},
        json={"path": "", "name": "phase42a_test_folder"}
    )
    assert res_mkdir.status_code in (201, 200)

    # Rename folder
    res_rename = client.post(
        "/api/vault/rename",
        headers={"Authorization": f"Bearer {session_token}"},
        json={"old_path": "phase42a_test_folder", "new_name": "phase42a_renamed_folder"}
    )
    assert res_rename.status_code == 200

    # Clean up
    client.post(
        "/delete",
        headers={"Authorization": f"Bearer {session_token}"},
        json={"filename": "phase42a_renamed_folder"}
    )
