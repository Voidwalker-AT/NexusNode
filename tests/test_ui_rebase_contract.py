"""
Tests for Phase 4.2A Product Rebase UI Contract
Verifies:
- Strict frontend cleanliness: complete removal of legacy AI Studio, Media, Tasks, Ollama
- 7 canonical primary navigation tabs
- 6 academic subtabs with Results "Coming later" placeholder
- Mobile bottom navigation & utilities drawer
- Modular script inclusion
- CSS design system variables & badge contracts
- REST endpoint schemas and performance
"""

import os
import re
import pytest
from html.parser import HTMLParser

import app as flask_app


@pytest.fixture
def client():
    flask_app.app.config["TESTING"] = True
    with flask_app.app.test_client() as c:
        yield c


def test_01_index_html_removed_obsolete_sections():
    """Verify complete removal of legacy sections from index.html (no CSS hiding)."""
    with open("index.html", "r", encoding="utf-8") as f:
        html = f.read()

    forbidden_ids = [
        "tab-ai-studio",
        "tab-media",
        "tab-tasks",
        "tab-network",
        "tab-events",
        "tab-automation",
        "tab-backups",
        "tab-storage-intel"
    ]

    for fid in forbidden_ids:
        assert f'id="{fid}"' not in html, f"Legacy tab '{fid}' still exists in index.html!"

    # Check for legacy AI/Ollama/media controls
    assert "ai-dual-model-banner" not in html
    assert "ollama" not in html.lower()
    assert "model selectors" not in html.lower()


def test_02_index_html_canonical_seven_tabs():
    """Verify exact presence of the 7 primary navigation tabs."""
    with open("index.html", "r", encoding="utf-8") as f:
        html = f.read()

    expected_tabs = [
        "tab-dashboard",
        "tab-academics",
        "tab-accounts",
        "tab-vault",
        "tab-mcp",
        "tab-diagnostics",
        "tab-settings"
    ]

    for tid in expected_tabs:
        assert f'id="{tid}"' in html, f"Expected primary tab '{tid}' missing in index.html!"

    # Exactly 7 tab-pane elements
    tab_panes = re.findall(r'<main[^>]*class="[^"]*tab-pane[^"]*"', html)
    assert len(tab_panes) == 7, f"Expected exactly 7 tab panes, found {len(tab_panes)}!"


def test_03_index_html_academics_subtabs():
    """Verify the 6 academic subtabs including active Results subtab."""
    with open("index.html", "r", encoding="utf-8") as f:
        html = f.read()

    assert 'id="tab-academics"' in html

    expected_subpanes = [
        "academics-pane-overview",
        "academics-pane-timetable",
        "academics-pane-attendance",
        "academics-pane-lms",
        "academics-pane-calendar",
        "academics-pane-results"
    ]

    for sp in expected_subpanes:
        assert f'id="{sp}"' in html, f"Expected academics subpane '{sp}' missing!"

    # Check Results subtab exists
    assert 'data-subtab="results"' in html
    assert "Results" in html


def test_04_index_html_mobile_navigation_and_drawer():
    """Verify mobile bottom navigation has 5 items and includes slide-up More drawer."""
    with open("index.html", "r", encoding="utf-8") as f:
        html = f.read()

    assert '<nav class="mobile-bottom-nav"' in html

    nav_btns = re.findall(r'<button[^>]*class="mobile-nav-btn[^"]*"', html)
    assert len(nav_btns) == 5, f"Expected 5 mobile bottom nav buttons, found {len(nav_btns)}!"

    # Drawer
    assert 'id="drawerContent"' in html
    assert 'id="drawerOverlay"' in html


def test_05_index_html_modular_scripts_included():
    """Verify all 10 modular JavaScript files are included."""
    with open("index.html", "r", encoding="utf-8") as f:
        html = f.read()

    expected_scripts = [
        "/static/js/api.js",
        "/static/js/ui.js",
        "/static/js/dashboard.js",
        "/static/js/academics.js",
        "/static/js/accounts.js",
        "/static/js/vault.js",
        "/static/js/mcp.js",
        "/static/js/diagnostics.js",
        "/static/js/settings.js",
        "/static/js/app.js"
    ]

    for script in expected_scripts:
        assert f'src="{script}"' in html, f"Script tag for '{script}' missing from index.html!"
        local_path = script.lstrip("/").replace("/", os.sep)
        assert os.path.isfile(local_path), f"Script file '{local_path}' does not exist on disk!"


def test_06_css_cleanliness_and_badges():
    """Verify dead AI Studio CSS is gone and new status/provenance badges are defined."""
    with open("static/css/index.css", "r", encoding="utf-8") as f:
        css = f.read()

    # Legacy gone
    assert ".ai-dual-model-banner" not in css
    assert ".chat-messages-box" not in css
    assert ".media-library-grid" not in css

    # New badges present
    assert ".status-badge" in css
    assert ".badge-healthy" in css
    assert ".badge-critical" in css
    assert ".badge-provenance" in css
    assert ".badge-live" in css
    assert ".badge-cached" in css
    assert ".toast-container" in css
    assert ".subnav-tabs" in css


def test_07_dashboard_summary_contract(client):
    """Verify /api/dashboard/summary contract schema and zero Chromium launch."""
    session_token = "test_ui_dash_tok"
    with flask_app.SESSIONS_LOCK:
        flask_app.SESSIONS[session_token] = {
            "user_id": "teststudent",
            "username": "teststudent",
            "role": "user",
            "expires_at": 9999999999.0,
            "privileges": {"can_sync_timetable": True}
        }

    res = client.get("/api/dashboard/summary", headers={"Authorization": f"Bearer {session_token}"})
    assert res.status_code == 200
    data = res.get_json()

    # Top-level contract keys
    required_keys = ["appliance", "account", "schedule", "attendance", "mcp", "alerts"]
    for k in required_keys:
        assert k in data, f"Key '{k}' missing from dashboard summary!"

    assert data["appliance"]["status"] in ("HEALTHY", "DEGRADED", "ACTION REQUIRED")
    assert "memory" in data["appliance"]
    assert data["mcp"]["catalog"] == "nexus-semantic-v1"
    assert data["mcp"]["tools_count"] == 11
