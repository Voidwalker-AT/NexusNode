"""
NexusNode CLI — Authoritative Authentication & Session Manager
Handles login, logout, whoami, and session token persistence.
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

    # Prompt interactively if not provided
    if not username:
        try:
            username = input("User ID: ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            print("\nOperation cancelled.")
            return False

    if not username:
        output.print_error("User ID cannot be empty.")
        return False

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

    if status_code == 200 and isinstance(resp, dict) and "token" in resp:
        token = resp["token"]
        user_id = resp.get("user_id", username)
        role = resp.get("role", "user")
        privileges = resp.get("privileges", {})

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
            output.print_success(f"Authentication successful.")
            print(f"  Server:   {client.server_url}")
            print(f"  User:     {user_id}")
            print(f"  Role:     {role.upper()}")
            print(f"  Session:  Active & stored locally in ~/.config/nexusnode/\n")
        return True

    elif status_code == 429:
        lockout_secs = resp.get("lockout_seconds") if isinstance(resp, dict) else None
        retry_msg = f"Account locked. Try again in {lockout_secs} seconds." if lockout_secs else "Account locked due to too many failed attempts."
        if as_json:
            output.print_json({"error": retry_msg, "status": 429, "lockout_seconds": lockout_secs})
        else:
            output.print_error(retry_msg)
        return False

    elif status_code == 401:
        err_msg = resp.get("error", "Authentication failed: invalid credentials.") if isinstance(resp, dict) else "Authentication failed."
        if as_json:
            output.print_json({"error": err_msg, "status": 401})
        else:
            output.print_error(err_msg)
        return False

    else:
        err_msg = resp.get("error", f"Server returned HTTP {status_code}") if isinstance(resp, dict) else f"HTTP {status_code}"
        if as_json:
            output.print_json({"error": err_msg, "status": status_code})
        else:
            output.print_error(err_msg)
        return False


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
        output.print_success("Logged out successfully.")
    return True


def whoami(client: NexusClient, as_json: bool = False) -> dict | None:
    """
    Inspects current authenticated session state against /api/auth/me.
    """
    if not client.token:
        if as_json:
            output.print_json({"authenticated": False, "error": "Not authenticated."})
        else:
            output.print_warning("No active session found. Run 'nexus login' to authenticate.")
        return None

    try:
        status_code, resp = client.get("/api/auth/me")
    except NexusConnectionError as e:
        output.print_error(str(e))
        return None

    if status_code == 200 and isinstance(resp, dict):
        if as_json:
            output.print_json(resp)
        else:
            print("\n" + "=" * 50)
            print("NexusNode Authenticated Session")
            print("=" * 50)
            print(f"  Server URL:   {client.server_url}")
            print(f"  User ID:      {resp.get('user_id')}")
            print(f"  Role:         {resp.get('role', 'user').upper()}")
            print(f"  Session Age:  {output.format_duration(time.time() - resp.get('created_at', time.time()))}")

            privs = resp.get("privileges", {})
            enabled_privs = [k for k, v in privs.items() if v]
            print(f"  Privileges:   {len(enabled_privs)} enabled ({', '.join(enabled_privs[:4])}...)")
            print("=" * 50 + "\n")
        return resp

    elif status_code == 401:
        config.clear_session()
        client.set_token(None)
        if as_json:
            output.print_json({"authenticated": False, "error": "Session expired or invalid."})
        else:
            output.print_error("Session expired or invalid. Please log in again using 'nexus login'.")
        return None

    else:
        err_msg = resp.get("error", f"HTTP {status_code}") if isinstance(resp, dict) else str(resp)
        output.print_error(err_msg)
        return None


def ensure_authenticated(client: NexusClient) -> bool:
    """
    Ensures the client has an active authenticated session; prompts for login if missing or expired.
    """
    if not client.token:
        print("Authentication required.")
        return login(client)

    # Validate token with server
    try:
        status_code, resp = client.get("/api/auth/me")
        if status_code == 200:
            return True
        elif status_code == 401:
            config.clear_session()
            client.set_token(None)
            print("Session expired. Please log in.")
            return login(client)
        else:
            output.print_error(f"Authentication validation failed: HTTP {status_code}")
            return False
    except NexusConnectionError as e:
        output.print_error(str(e))
        return False
