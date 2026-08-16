"""
NexusNode CLI — User & RBAC Account Administration Command (Admin Only)
Communicates with /api/admin/users, /api/admin/users/<id>/password, and /api/admin/users/<id>/sessions/revoke.
"""

import getpass

from .. import output
from .. import normalize
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
    elif subaction == "password":
        return cmd_users_password(client, args, as_json)
    elif subaction == "disable":
        return cmd_users_toggle_disabled(client, args, is_disabled=True, as_json=as_json)
    elif subaction == "enable":
        return cmd_users_toggle_disabled(client, args, is_disabled=False, as_json=as_json)
    elif subaction == "revoke-sessions":
        return cmd_users_revoke_sessions(client, args, as_json)
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
        output.print_error("Permission denied: your account lacks administrator privileges.")
        return 1
    if status_code != 200:
        err = resp.get("message", resp.get("error", f"HTTP {status_code}")) if isinstance(resp, dict) else str(resp)
        output.print_error(f"Failed to list users ({err})")
        return 1

    if as_json or getattr(args, "json", False):
        output.print_json(resp)
        return 0

    users_list = normalize.normalize_list(resp, "users")
    if not users_list:
        print("\nNo user accounts found.\n")
        return 0

    headers = ["USER ID", "ROLE", "STATUS", "PRIVILEGES COUNT", "CREATED AT"]
    rows = []
    for u in users_list:
        if not isinstance(u, dict):
            continue
        privs = u.get("privileges", {})
        enabled_count = sum(1 for v in privs.values() if v) if isinstance(privs, dict) else 0
        status_str = "DISABLED" if u.get("is_disabled") else "ACTIVE"
        rows.append([
            str(u.get("user_id") or u.get("username", "N/A")),
            str(u.get("role", "user")).upper(),
            status_str,
            f"{enabled_count} enabled",
            output.format_timestamp(u.get("created_at"))
        ])

    print(f"\n--- APPLICATION USERS ({len(users_list)} accounts) ---")
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
            password = getpass.getpass("New User Password (min 6 chars): ")
        except (KeyboardInterrupt, EOFError):
            print("\nCancelled.")
            return 1

    if not password or len(password) < 6:
        output.print_error("Password must be at least 6 characters.")
        return 1

    role = getattr(args, "role", "user") or "user"
    is_disabled = getattr(args, "is_disabled", False)
    payload = {
        "user_id": user_id,
        "password": password,
        "role": role,
        "is_disabled": is_disabled
    }

    try:
        status_code, resp = client.post("/api/admin/users", data=payload)
    except NexusConnectionError as e:
        output.print_error(str(e))
        return 1

    if status_code == 403:
        output.print_error("Permission denied: administrator privileges required.")
        return 1
    if status_code not in [200, 201]:
        err = resp.get("message", resp.get("error", f"HTTP {status_code}")) if isinstance(resp, dict) else str(resp)
        output.print_error(f"Failed to create user: {err}")
        return 1

    if as_json or getattr(args, "json", False):
        output.print_json(resp)
    else:
        output.print_success(f"User '{user_id}' created successfully with role '{role}'.")
    return 0


def cmd_users_delete(client: NexusClient, args, as_json: bool = False) -> int:
    user_id = getattr(args, "username", None)
    if not user_id:
        output.print_error("User ID is required to delete.")
        return 1

    yes = getattr(args, "yes", False)
    if not yes:
        try:
            confirm = input(f"Are you sure you want to delete user '{user_id}'? [y/N]: ").strip().lower()
            if confirm != "y":
                print("Deletion cancelled.")
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
    if status_code not in [200, 204]:
        err = resp.get("message", resp.get("error", f"HTTP {status_code}")) if isinstance(resp, dict) else str(resp)
        output.print_error(f"Failed to delete user: {err}")
        return 1

    if as_json or getattr(args, "json", False):
        output.print_json(resp)
    else:
        output.print_success(f"User '{user_id}' deleted successfully.")
    return 0


def cmd_users_password(client: NexusClient, args, as_json: bool = False) -> int:
    user_id = getattr(args, "username", None)
    if not user_id:
        output.print_error("User ID is required.")
        return 1

    new_pwd = getattr(args, "password", None)
    if not new_pwd:
        try:
            new_pwd = getpass.getpass(f"New Password for '{user_id}' (min 6 chars): ")
        except (KeyboardInterrupt, EOFError):
            print("\nCancelled.")
            return 1

    if not new_pwd or len(new_pwd) < 6:
        output.print_error("Password must be at least 6 characters.")
        return 1

    try:
        status_code, resp = client.post(f"/api/admin/users/{user_id}/password", data={"password": new_pwd})
    except NexusConnectionError as e:
        output.print_error(str(e))
        return 1

    if status_code != 200:
        err = resp.get("message", resp.get("error", f"HTTP {status_code}")) if isinstance(resp, dict) else str(resp)
        output.print_error(f"Password reset failed: {err}")
        return 1

    if as_json or getattr(args, "json", False):
        output.print_json(resp)
    else:
        output.print_success(f"Password reset successfully for '{user_id}'. Active sessions revoked.")
    return 0


def cmd_users_toggle_disabled(client: NexusClient, args, is_disabled: bool, as_json: bool = False) -> int:
    user_id = getattr(args, "username", None)
    if not user_id:
        output.print_error("User ID is required.")
        return 1

    try:
        status_code, resp = client.patch(f"/api/admin/users/{user_id}", data={"is_disabled": is_disabled})
    except NexusConnectionError as e:
        output.print_error(str(e))
        return 1

    if status_code != 200:
        err = resp.get("message", resp.get("error", f"HTTP {status_code}")) if isinstance(resp, dict) else str(resp)
        action_name = "disable" if is_disabled else "enable"
        output.print_error(f"Failed to {action_name} user '{user_id}': {err}")
        return 1

    if as_json or getattr(args, "json", False):
        output.print_json(resp)
    else:
        state_str = "disabled" if is_disabled else "enabled"
        output.print_success(f"User '{user_id}' has been {state_str}.")
    return 0


def cmd_users_revoke_sessions(client: NexusClient, args, as_json: bool = False) -> int:
    user_id = getattr(args, "username", None)
    if not user_id:
        output.print_error("User ID is required.")
        return 1

    try:
        status_code, resp = client.post(f"/api/admin/users/{user_id}/sessions/revoke", data={})
    except NexusConnectionError as e:
        output.print_error(str(e))
        return 1

    if status_code != 200:
        err = resp.get("message", resp.get("error", f"HTTP {status_code}")) if isinstance(resp, dict) else str(resp)
        output.print_error(f"Failed to revoke sessions: {err}")
        return 1

    if as_json or getattr(args, "json", False):
        output.print_json(resp)
    else:
        revoked = resp.get("revoked_count", 0) if isinstance(resp, dict) else 0
        output.print_success(f"Revoked {revoked} active session(s) for user '{user_id}'.")
    return 0


def cmd_users_privileges(client: NexusClient, args, as_json: bool = False) -> int:
    user_id = getattr(args, "username", None)
    if not user_id:
        output.print_error("User ID is required.")
        return 1

    priv_key = getattr(args, "grant", None) or getattr(args, "revoke", None) or getattr(args, "privilege", None)
    is_grant = getattr(args, "grant", None) is not None
    is_revoke = getattr(args, "revoke", None) is not None

    if priv_key and (is_grant or is_revoke):
        val_bool = is_grant
        payload = {
            "privileges": {priv_key: val_bool}
        }
        try:
            status_code, resp = client.patch(f"/api/admin/users/{user_id}", data=payload)
        except NexusConnectionError as e:
            output.print_error(str(e))
            return 1

        if status_code != 200:
            err = resp.get("message", resp.get("error", f"HTTP {status_code}")) if isinstance(resp, dict) else str(resp)
            output.print_error(f"Failed to update privilege: {err}")
            return 1

        if as_json or getattr(args, "json", False):
            output.print_json(resp)
        else:
            action_word = "granted to" if val_bool else "revoked from"
            output.print_success(f"Privilege '{priv_key}' {action_word} user '{user_id}'.")
        return 0

    # Otherwise display user's current privileges
    try:
        status_code, resp = client.get(f"/api/admin/users/{user_id}")
    except NexusConnectionError as e:
        output.print_error(str(e))
        return 1

    if status_code != 200 or not isinstance(resp, dict):
        output.print_error(f"User '{user_id}' not found.")
        return 1

    privs = resp.get("privileges", {})
    if as_json or getattr(args, "json", False):
        output.print_json(privs)
        return 0

    print(f"\n--- PRIVILEGES FOR USER '{user_id}' ---")
    if isinstance(privs, dict):
        for p, enabled in sorted(privs.items()):
            state = "ENABLED" if enabled else "DISABLED"
            print(f"  {p:<32}: {state}")
    else:
        print("  (No specific privileges configured)")
    print()
    return 0
