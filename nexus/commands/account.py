"""
NexusNode CLI — Account & Profile Command
Exposes session status, current role, permissions, self-service password changes, and logout.
"""

import getpass

from .. import auth
from .. import output
from ..client import NexusClient, NexusConnectionError


def cmd_account(client: NexusClient, args, as_json: bool = False) -> int:
    """Dispatcher for 'nexus account' subcommands."""
    subaction = getattr(args, "account_action", None) or "whoami"

    if subaction == "whoami" or subaction == "session":
        res = auth.whoami(client, as_json=as_json or getattr(args, "json", False))
        return 0 if res else 1
    elif subaction == "logout":
        auth.logout(client, as_json=as_json or getattr(args, "json", False))
        return 0
    elif subaction == "password":
        return cmd_account_password(client, args, as_json)
    elif subaction == "revoke-sessions":
        return cmd_account_revoke_sessions(client, args, as_json)
    else:
        output.print_error(f"Unknown account subcommand '{subaction}'. Type 'nexus account --help'.")
        return 1


def cmd_account_password(client: NexusClient, args, as_json: bool = False) -> int:
    current_pwd = getattr(args, "current_password", None)
    if not current_pwd:
        try:
            current_pwd = getpass.getpass("Current Password: ")
        except (KeyboardInterrupt, EOFError):
            print("\nCancelled.")
            return 1

    if not current_pwd:
        output.print_error("Current password is required.")
        return 1

    new_pwd = getattr(args, "new_password", None)
    if not new_pwd:
        try:
            new_pwd = getpass.getpass("New Password (min 6 chars): ")
        except (KeyboardInterrupt, EOFError):
            print("\nCancelled.")
            return 1

    if not new_pwd or len(new_pwd) < 6:
        output.print_error("New password must be at least 6 characters.")
        return 1

    try:
        status_code, resp = client.post("/api/account/password", data={
            "current_password": current_pwd,
            "new_password": new_pwd
        })
    except NexusConnectionError as e:
        output.print_error(str(e))
        return 1

    if status_code != 200:
        err = resp.get("message", resp.get("error", f"HTTP {status_code}")) if isinstance(resp, dict) else str(resp)
        output.print_error(f"Password change failed: {err}")
        return 1

    if as_json or getattr(args, "json", False):
        output.print_json(resp)
    else:
        output.print_success("Password changed successfully. All other sessions have been revoked.")
    return 0


def cmd_account_revoke_sessions(client: NexusClient, args, as_json: bool = False) -> int:
    try:
        status_code, resp = client.post("/api/account/sessions/revoke", data={})
    except NexusConnectionError as e:
        output.print_error(str(e))
        return 1

    if status_code != 200:
        err = resp.get("message", resp.get("error", f"HTTP {status_code}")) if isinstance(resp, dict) else str(resp)
        output.print_error(f"Session revocation failed: {err}")
        return 1

    if as_json or getattr(args, "json", False):
        output.print_json(resp)
    else:
        revoked = resp.get("revoked_count", 0) if isinstance(resp, dict) else 0
        output.print_success(f"Successfully revoked {revoked} other active session(s).")
    return 0
