"""
NexusNode CLI — Authoritative Authentication & Session Manager
Handles login, logout, whoami, session token persistence, and the worldwide connect sequence.
"""

import sys
import time
import getpass

from . import config
from . import output
from .client import NexusClient, NexusConnectionError


def login(client: NexusClient, username: str = None, password: str = None, as_json: bool = False) -> bool:
    """
    Authenticates user credentials against /api/auth/login and stores session token locally.
    Uses hidden password input; never prints or logs password.
    """
    if not client.server_url:
        client.server_url = config.resolve_server_url(prompt_if_missing=True)
        if not client.server_url:
            output.print_error("Server URL is required to log in.")
            return False

    # Prompt interactively for username if not supplied
    if not username:
        try:
            username = input("NexusNode ID: ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            print("\nOperation cancelled.")
            return False

    if not username:
        output.print_error("NexusNode ID cannot be empty.")
        return False

    # Prompt interactively for password if not supplied
    if not password:
        try:
            password = getpass.getpass("Password: ")
        except (KeyboardInterrupt, EOFError):
            print("\nOperation cancelled.")
            return False

    if not password:
        output.print_error("Password cannot be empty.")
        return False

    payload = {
        "user_id": username,
        "password": password
    }

    try:
        status_code, resp = client.post("/api/auth/login", data=payload)
    except NexusConnectionError as e:
        output.print_error(str(e))
        return False

    # 1. Successful Authentication (2xx with token)
    if status_code in (200, 201) and isinstance(resp, dict):
        # Extract token and user details from either root or nested 'user' dict
        token = resp.get("token") or (resp.get("user", {}) if isinstance(resp.get("user"), dict) else {}).get("token")

        if token:
            user_data = resp.get("user") if isinstance(resp.get("user"), dict) else {}
            user_id = user_data.get("user_id") or resp.get("user_id") or username
            role = user_data.get("role") or resp.get("role") or "user"
            privileges = user_data.get("privileges") or resp.get("privileges") or {}

            session_data = {
                "token": token,
                "user_id": user_id,
                "role": role,
                "privileges": privileges,
                "server_url": client.server_url,
                "created_at": time.time()
            }
            config.save_session(session_data)
            client.set_token(token)

            if as_json:
                clean_resp = dict(resp)
                output.print_json(clean_resp)
            else:
                print()
                output.print_success("Authentication successful.")
                print()
                role_upper = role.upper()
                role_col = output.magenta(role_upper, bold=True) if role.lower() == "admin" else output.cyan(role_upper, bold=True)
                print(f"User        : {output.cyan(user_id, bold=True)}")
                print(f"Role        : {role_col}")
                print(f"Session     : {output.green('ACTIVE', bold=True)}")
                print()
            return True

        # Check if the 200 response was HTML from an interstitial or WAF
        if resp.get("_is_html"):
            msg = resp.get("message", "NexusNode API expected JSON but received HTML.")
            if as_json:
                output.print_json({"error": "html_response", "message": msg, "status": 200})
            else:
                output.print_error(msg)
                if resp.get("_is_waf"):
                    print("  Note: LocalToNet WAF interstitial detected. Verify tunnel status or parameters.")
                else:
                    print("  Possible causes:\n  - Incorrect server URL\n  - Tunnel/WAF warning page\n  - Reverse proxy gateway error")
            return False

        # 200 response without token and not HTML
        err_msg = resp.get("error") or resp.get("message") or "Authentication failed: Server did not return a session token."
        if as_json:
            output.print_json({"error": err_msg, "status": status_code})
        else:
            output.print_error(err_msg)
        return False

    # 2. Account Lockout (429)
    elif status_code == 429:
        lockout_secs = (resp.get("lockout_seconds") or resp.get("remaining_seconds") or resp.get("retry_after")) if isinstance(resp, dict) else None
        retry_msg = f"Account locked. Retry in {lockout_secs} seconds." if lockout_secs else "Account locked due to too many failed attempts."
        if as_json:
            output.print_json({"error": retry_msg, "status": 429, "lockout_seconds": lockout_secs, "remaining_seconds": lockout_secs})
        else:
            output.print_error(retry_msg)
        return False

    # 3. Invalid Credentials (401)
    elif status_code == 401:
        err_msg = resp.get("message") or resp.get("error", "Authentication failed: invalid credentials.") if isinstance(resp, dict) else "Authentication failed."
        if as_json:
            output.print_json({"error": err_msg, "status": 401})
        else:
            output.print_error(err_msg)
        return False

    # 4. Forbidden (403)
    elif status_code == 403:
        err_msg = resp.get("message") or resp.get("error", "Permission denied.") if isinstance(resp, dict) else "Permission denied."
        if as_json:
            output.print_json({"error": err_msg, "status": 403})
        else:
            output.print_error(err_msg)
        return False

    # 5. Other Errors (5xx, HTML, etc.)
    else:
        if isinstance(resp, dict) and resp.get("_is_html"):
            err_msg = resp.get("message", "NexusNode API expected JSON but received HTML.")
        elif isinstance(resp, dict):
            err_msg = resp.get("message") or resp.get("error") or f"Server returned HTTP {status_code}"
        else:
            err_msg = f"Server returned HTTP {status_code}"

        if as_json:
            output.print_json({"error": err_msg, "status": status_code})
        else:
            output.print_error(err_msg)
        return False


def connect_sequence(client: NexusClient, server_url: str = None, username: str = None, password: str = None) -> bool:
    """
    Executes the interactive connection sequence:
    1. Displays ASCII branding banner
    2. Probes endpoint DNS, TLS, and API health
    3. Displays real server metadata and latency
    4. Authenticates credentials
    """
    if server_url:
        client.server_url = config.normalize_server_url(server_url)

    if not client.server_url:
        client.server_url = config.resolve_server_url(prompt_if_missing=True)
        if not client.server_url:
            output.print_error("Server URL is required to connect.")
            return False

    # 1. Banner
    output.print_banner()
    print()
    print("Connecting to NexusNode...")
    print()

    # 2. Handshake & Health Probe
    probe = client.probe_handshake(timeout=6)
    if not probe.get("ok"):
        output.print_step("Endpoint", "FAIL")
        if probe.get("is_html"):
            output.print_error(probe.get("error", "Received HTML instead of NexusNode API JSON."))
            print("  Possible causes:\n  - Invalid server URL\n  - Cloudflare / LocalToNet interstitial\n  - Server is not running NexusNode")
        else:
            output.print_error(f"Connection failed: {probe.get('error')}")
        return False

    # 3. Connection Steps
    output.print_step("Endpoint", "OK")
    output.print_step("TLS", "OK")
    output.print_step("API", "OK")

    # 4. Server Metadata Panel
    output.print_panel("Server", [
        ("Name", probe.get("name", "NexusNode Mobile Appliance")),
        ("Device", probe.get("device", "TECNO BG6")),
        ("Version", probe.get("version", "2.3.2")),
        ("Status", output.colorize_status(probe.get("status", "HEALTHY"))),
        ("Latency", output.cyan(f"{probe.get('latency_ms', 0)} ms")),
    ])

    # 5. Authenticate
    return login(client, username=username, password=password, as_json=False)


def logout(client: NexusClient, as_json: bool = False) -> bool:
    """
    Revokes the active session on the server and purges local credentials.
    """
    if client.token:
        try:
            client.post("/api/auth/logout")
        except Exception:
            pass

    config.clear_session()
    client.set_token(None)

    if as_json:
        output.print_json({"message": "Logged out successfully."})
    else:
        output.print_success("Logged out successfully. Session revoked.")
    return True


def whoami(client: NexusClient, as_json: bool = False) -> dict | None:
    """
    Inspects current authenticated session state against /api/auth/me.
    """
    if not client.token:
        if as_json:
            output.print_json({"authenticated": False, "error": "Not authenticated."})
        else:
            output.print_warning("No active session found. Run 'nexus connect <url>' to authenticate.")
        return None

    try:
        status_code, resp = client.get("/api/auth/me")
    except NexusConnectionError as e:
        output.print_error(str(e))
        return None

    if status_code == 200 and isinstance(resp, dict):
        user_info = resp.get("user") if isinstance(resp.get("user"), dict) else resp
        user_id = user_info.get("user_id") or user_info.get("username")
        role = user_info.get("role", "user")
        privs = user_info.get("privileges", {})

        if as_json:
            output.print_json(resp)
        else:
            role_upper = role.upper()
            role_col = output.magenta(role_upper, bold=True) if role.lower() == "admin" else output.cyan(role_upper, bold=True)
            output.print_panel("NexusNode Authenticated Session", [
                ("Server URL", client.server_url),
                ("User ID", output.cyan(user_id, bold=True)),
                ("Role", role_col),
                ("Session Age", output.format_duration(time.time() - resp.get("created_at", time.time())) if resp.get("created_at") else "Active"),
                ("Privileges", output.green(f"{len([k for k, v in privs.items() if v])} enabled")),
            ])
        return {
            "user_id": user_id,
            "role": role,
            "privileges": privs,
            "server_url": client.server_url
        }

    elif status_code == 401:
        config.clear_session()
        client.set_token(None)
        if as_json:
            output.print_json({"authenticated": False, "error": "Session expired or invalid."})
        else:
            output.print_error("Session expired or invalid. Please connect again using 'nexus connect'.")
        return None

    else:
        err_msg = resp.get("error", f"HTTP {status_code}") if isinstance(resp, dict) else str(resp)
        output.print_error(err_msg)
        return None


def ensure_authenticated(client: NexusClient) -> bool:
    """
    Ensures the client has an active authenticated session; initiates connect flow if missing.
    """
    if not client.token:
        return connect_sequence(client)

    # Validate token with server
    try:
        status_code, resp = client.get("/api/auth/me")
        if status_code == 200:
            return True
        elif status_code == 401:
            config.clear_session()
            client.set_token(None)
            print("Session expired. Please authenticate.")
            return connect_sequence(client)
        else:
            output.print_error(f"Authentication validation failed: HTTP {status_code}")
            return False
    except NexusConnectionError as e:
        output.print_error(str(e))
        return False
