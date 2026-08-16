"""
NexusNode CLI — User & RBAC Account Administration Command (Admin Only)
Communicates with /api/admin/users and /api/admin/users/update-privileges endpoints.
"""

import getpass

from .. import output
from ..client import NexusClient, NexusConnectionError


def cmd_users(client: NexusClient, args, as_json: bool = False) -> int:
    """Dispatcher for 'nexus users' commands."""
    subaction = getattr(args, "user_action", None) or "list"

    if subaction == "list" or subaction == "ls":
        return cmd_users_list(client, args, as_json)
    elif subaction == "create" or subaction == "add":
        return cmd_users_create(client, args, as_json)
    elif subaction == "delete" or subaction == "rm":
        return cmd_users_delete(client, args, as_json)
    elif subaction == "privileges":
        return cmd_users_privileges(client, args, as_json)
    else:
        output.print_error(f"Unknown users subcommand '{subaction}'. Type 'nexus users --help'.")
        return 1


def cmd_users_list(client: NexusClient, args, as_json: bool = False) -> int:
    try:
        status_code, resp = client.get("/api/admin/users")
    except NexusConnectionError as e:
        output.print_error(str(e))
        return 1

    if status_code == 403:
        output.print_error("Permission denied: your account lacks 'can_manage_users' privilege.")
        return 1
    if status_code != 200:
        output.print_error(f"Failed to list users (HTTP {status_code})")
        return 1

    if as_json or getattr(args, "json", False):
        output.print_json(resp)
        return 0

    if not isinstance(resp, list) or not resp:
        print("\nNo user accounts found.\n")
        return 0

    headers = ["USER ID", "ROLE", "PRIVILEGES COUNT", "CREATED AT"]
    rows = []
    for u in resp:
        privs = u.get("privileges", {})
        enabled_count = sum(1 for v in privs.values() if v) if isinstance(privs, dict) else 0
        rows.append([
            u.get("user_id", "N/A"),
            u.get("role", "user").upper(),
            f"{enabled_count} enabled",
            output.format_timestamp(u.get("created_at"))
        ])

    print(f"\n--- APPLICATION USERS ({len(resp)} accounts) ---")
    output.print_table(headers, rows)
    return 0


def cmd_users_create(client: NexusClient, args, as_json: bool = False) -> int:
    user_id = getattr(args, "username", None)
    if not user_id:
        try:
            user_id = input("New User ID: ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            print("\nCancelled.")
            return 1

    if not user_id:
        output.print_error("Username is required.")
        return 1

    password = getattr(args, "password", None)
    if not password:
        try:
            password = getpass.getpass("New User Password: ")
        except (KeyboardInterrupt, EOFError):
            print("\nCancelled.")
            return 1

    if not password:
        output.print_error("Password is required.")
        return 1

    role = getattr(args, "role", "user") or "user"
    payload = {
        "user_id": user_id,
        "password": password,
        "role": role
    }

    try:
        status_code, resp = client.post("/api/admin/users", data=payload)
    except NexusConnectionError as e:
        output.print_error(str(e))
        return 1

    if status_code == 403:
        output.print_error("Permission denied: your account lacks 'can_manage_users' privilege.")
        return 1
    if status_code != 200 and status_code != 201:
        err = resp.get("error", f"HTTP {status_code}") if isinstance(resp, dict) else str(resp)
        output.print_error(f"Failed to create user: {err}")
        return 1

    if as_json or getattr(args, "json", False):
        output.print_json(resp)
    else:
        output.print_success(f"User account '{user_id}' created with role '{role}'.")
    return 0


def cmd_users_delete(client: NexusClient, args, as_json: bool = False) -> int:
    user_id = getattr(args, "username", None)
    if not user_id:
        output.print_error("Username is required.")
        return 1

    yes = getattr(args, "yes", False)
    if not yes:
        try:
            confirm = input(f"Are you sure you want to delete user '{user_id}'? [y/N]: ").strip().lower()
            if confirm != "y":
                print("Operation cancelled.")
                return 0
        except (KeyboardInterrupt, EOFError):
            print("\nCancelled.")
            return 0

    try:
        status_code, resp = client.delete(f"/api/admin/users/{user_id}")
    except NexusConnectionError as e:
        output.print_error(str(e))
        return 1

    if status_code == 403:
        output.print_error("Permission denied.")
        return 1
    if status_code != 200:
        err = resp.get("error", f"HTTP {status_code}") if isinstance(resp, dict) else str(resp)
        output.print_error(f"Failed to delete user: {err}")
        return 1

    if as_json or getattr(args, "json", False):
        output.print_json(resp)
    else:
        output.print_success(f"User '{user_id}' deleted successfully.")
    return 0


def cmd_users_privileges(client: NexusClient, args, as_json: bool = False) -> int:
    user_id = getattr(args, "username", None)
    if not user_id:
        output.print_error("Username is required.")
        return 1

    grant = getattr(args, "grant", None)
    revoke = getattr(args, "revoke", None)

    # First fetch current user privileges
    try:
        status_code, resp = client.get("/api/admin/users")
    except NexusConnectionError as e:
        output.print_error(str(e))
        return 1

    if status_code != 200 or not isinstance(resp, list):
        output.print_error(f"Failed to fetch users (HTTP {status_code})")
        return 1

    target = next((u for u in resp if u.get("user_id") == user_id), None)
    if not target:
        output.print_error(f"User '{user_id}' not found.")
        return 1

    current_privs = dict(target.get("privileges", {}))

    if not grant and not revoke:
        # Display current privileges
        if as_json or getattr(args, "json", False):
            output.print_json({"user_id": user_id, "privileges": current_privs})
        else:
            print(f"\n--- PRIVILEGES FOR USER '{user_id}' ---")
            for priv, enabled in current_privs.items():
                print(f"  {priv:<28}: {'ENABLED' if enabled else 'DISABLED'}")
            print()
        return 0

    if grant:
        current_privs[grant] = True
    if revoke:
        current_privs[revoke] = False

    payload = {
        "user_id": user_id,
        "privileges": current_privs
    }

    try:
        status_code, resp = client.post("/api/admin/users/update-privileges", data=payload)
    except NexusConnectionError as e:
        output.print_error(str(e))
        return 1

    if status_code == 200:
        if as_json or getattr(args, "json", False):
            output.print_json(resp)
        else:
            output.print_success(f"Privileges updated for '{user_id}'.")
        return 0
    else:
        err = resp.get("error", f"HTTP {status_code}") if isinstance(resp, dict) else str(resp)
        output.print_error(f"Failed to update privileges: {err}")
        return 1
