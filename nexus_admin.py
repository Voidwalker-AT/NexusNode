#!/usr/bin/env python3
"""
NexusNode — Local Appliance Account & Authentication Administration CLI
Authoritative command-line tool for managing and testing NexusNode application accounts
directly from an authenticated Termux shell or SSH session.

CRITICAL SECURITY ARCHITECTURE:
- SSH Login (Port 8022 into Android/Termux OS) and NexusNode Application Login are
  two distinct, decoupled authentication layers.
- This CLI manages NexusNode application accounts stored in SQLite (nexus_vault.db).
- Zero external dependencies: uses Python standard library only.
- Never prints passwords, hashes, salts, or session tokens by default.
- Reuses authoritative backend password hashing, DB access, RBAC, and lockout logic.
"""

import os
import sys
import json
import time
import getpass
import argparse
import datetime
from pathlib import Path

# Ensure server root directory is importable
SERVER_ROOT = os.path.dirname(os.path.abspath(__file__))
if SERVER_ROOT not in sys.path:
    sys.path.insert(0, SERVER_ROOT)

import config
import app as nexus_app


def get_session_file_path() -> Path:
    """Returns local user session storage file path under ~/.config/nexusnode/session."""
    config_dir = Path.home() / ".config" / "nexusnode"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / "session"


def save_local_session(token: str, user_id: str, role: str):
    """Saves session token securely to disk with mode 0600 on POSIX platforms."""
    session_file = get_session_file_path()
    payload = {
        "token": token,
        "user_id": user_id,
        "role": role,
        "created_at": time.time()
    }
    with open(session_file, "w", encoding="utf-8") as f:
        json.dump(payload, f)

    try:
        os.chmod(session_file, 0o600)
    except Exception:
        pass


def read_local_session() -> dict | None:
    """Reads and parses the local session file if present and valid."""
    session_file = get_session_file_path()
    if not session_file.exists():
        return None
    try:
        with open(session_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict) and data.get("token") and data.get("user_id"):
                return data
    except Exception:
        pass
    return None


def clear_local_session():
    """Removes the local session token file."""
    session_file = get_session_file_path()
    if session_file.exists():
        try:
            session_file.unlink()
        except Exception:
            pass


def format_created_ts(created_val, full: bool = False) -> str:
    """Formats numeric epoch, stringified float, or ISO timestamps safely."""
    if not created_val:
        return "N/A"
    try:
        if isinstance(created_val, str):
            val_str = created_val.strip()
            try:
                created_val = float(val_str)
            except ValueError:
                if not full and "T" in val_str:
                    return val_str.split("T")[0]
                return val_str[:19]

        if isinstance(created_val, (int, float)) and created_val > 0:
            fmt = '%Y-%m-%d %H:%M:%S UTC' if full else '%Y-%m-%d'
            return datetime.datetime.fromtimestamp(created_val).strftime(fmt)
    except Exception:
        pass
    return "N/A"


# ==============================================================================
# CLI Command Implementations
# ==============================================================================

def cmd_users(args):
    """Lists all users safely without exposing hashes, salts, or tokens."""
    users = nexus_app.db_get_all_users()
    if not users:
        print("No users found.")
        return 0

    now = time.time()
    print(f"{'USER ID':<16} {'ROLE':<10} {'STATUS':<10} {'CREATED':<12} {'LOCKOUT':<10}")
    print("-" * 62)

    with nexus_app.FAILED_LOGINS_LOCK:
        for user_id, u in sorted(users.items()):
            role = u.get("role", "user")
            created_str = format_created_ts(u.get("created_at"), full=False)

            fail_rec = nexus_app.FAILED_LOGINS.get(user_id) or nexus_app.FAILED_LOGINS.get("127.0.0.1")
            is_locked = False
            if fail_rec and now < fail_rec.get("locked_until", 0.0):
                is_locked = True

            lockout_str = "LOCKED" if is_locked else "UNLOCKED"
            status_str = "ACTIVE"

            print(f"{user_id:<16} {role:<10} {status_str:<10} {created_str:<12} {lockout_str:<10}")

    return 0


def cmd_user_info(args):
    """Displays safe metadata and enabled privileges for a specific user."""
    user_id = str(args.user or "").strip().lower()
    if not user_id:
        print("Error: Target user ID is required (--user <user_id>).", file=sys.stderr)
        return 1

    user = nexus_app.db_get_user(user_id)
    if not user:
        print(f"Error: User '{user_id}' does not exist.", file=sys.stderr)
        return 1

    created_str = format_created_ts(user.get("created_at"), full=True)

    with nexus_app.FAILED_LOGINS_LOCK:
        fail_rec = nexus_app.FAILED_LOGINS.get(user_id) or nexus_app.FAILED_LOGINS.get("127.0.0.1", {})
        now = time.time()
        locked_until = fail_rec.get("locked_until", 0.0)
        failed_count = fail_rec.get("count", 0)

        if now < locked_until:
            rem = int(locked_until - now)
            lockout_str = f"LOCKED ({rem}s remaining, {failed_count} failed attempts)"
        else:
            lockout_str = f"UNLOCKED ({failed_count} failed attempts)"

    print(f"User ID:            {user['user_id']}")
    print(f"Role:               {user['role']}")
    print(f"Created:            {created_str}")
    print(f"Account Status:     ACTIVE")
    print(f"Lockout Status:     {lockout_str}")
    print("Enabled Privileges:")

    privileges = user.get("privileges", {})
    if isinstance(privileges, dict) and privileges:
        for p, enabled in sorted(privileges.items()):
            if enabled:
                print(f"  [+] {p}")
            else:
                print(f"  [-] {p}")
    else:
        print("  (None)")

    return 0


def cmd_create_user(args):
    """Creates a new user account with least-privilege RBAC assignment."""
    user_id = str(args.user or "").strip().lower()
    role = str(args.role or "user").strip().lower()

    if not user_id:
        print("Error: Target user ID is required (--user <user_id>).", file=sys.stderr)
        return 1

    if len(user_id) < 2 or len(user_id) > 32 or not all(c.isalnum() or c in "_-" for c in user_id):
        print("Error: User ID must be 2-32 alphanumeric characters, hyphens, or underscores.", file=sys.stderr)
        return 1

    if role not in ["admin", "user"]:
        print(f"Error: Invalid role '{role}'. Must be 'admin' or 'user'.", file=sys.stderr)
        return 1

    if nexus_app.db_get_user(user_id):
        print(f"Error: User '{user_id}' already exists.", file=sys.stderr)
        return 1

    # Require explicit confirmation for administrator creation
    if role == "admin" and not args.yes:
        try:
            confirm = input(f"Create administrator account '{user_id}'? [y/N]: ").strip().lower()
            if confirm not in ['y', 'yes']:
                print("Operation cancelled.")
                return 1
        except (KeyboardInterrupt, EOFError):
            print("\nOperation cancelled.")
            return 1

    # Secure password collection
    password = args.password
    if not password:
        try:
            p1 = getpass.getpass("Password: ")
            if not p1:
                print("Error: Password cannot be empty.", file=sys.stderr)
                return 1
            p2 = getpass.getpass("Confirm password: ")
            if p1 != p2:
                print("Error: Passwords do not match.", file=sys.stderr)
                return 1
            password = p1
        except (KeyboardInterrupt, EOFError):
            print("\nOperation cancelled.")
            return 1
    else:
        print("[WARNING] Password provided via command-line arguments may be visible in process listings and shell history.", file=sys.stderr)

    success, msg = nexus_app.db_create_user(user_id, password, role=role)
    if not success:
        print(f"Error: {msg}", file=sys.stderr)
        return 1

    print(f"User '{user_id}' created successfully with role '{role}'.")
    return 0


def cmd_delete_user(args):
    """Deletes a user account, purges active sessions, and clears lockouts."""
    user_id = str(args.user or "").strip().lower()
    if not user_id:
        print("Error: Target user ID is required (--user <user_id>).", file=sys.stderr)
        return 1

    if user_id == "admin":
        print("Error: Cannot delete primary admin account.", file=sys.stderr)
        return 1

    if not nexus_app.db_get_user(user_id):
        print(f"Error: User '{user_id}' does not exist.", file=sys.stderr)
        return 1

    if not args.yes:
        try:
            confirm = input(f"Delete user account '{user_id}'? [y/N]: ").strip().lower()
            if confirm not in ['y', 'yes']:
                print("Operation cancelled.")
                return 1
        except (KeyboardInterrupt, EOFError):
            print("\nOperation cancelled.")
            return 1

    success, msg = nexus_app.db_delete_user(user_id)
    if not success:
        print(f"Error: {msg}", file=sys.stderr)
        return 1

    print(f"User '{user_id}' deleted successfully.")
    return 0


def cmd_reset_password(args):
    """Resets user password locally and clears account lockout."""
    return 0 if emergency_reset_password(args.user, args.password) else 1


def cmd_unlock(args):
    """Clears failed login counter and unlocks an account."""
    user_id = str(args.user or "").strip().lower()
    if not user_id:
        print("Error: Target user ID is required (--user <user_id>).", file=sys.stderr)
        return 1

    if not nexus_app.db_get_user(user_id):
        print(f"Error: User '{user_id}' does not exist.", file=sys.stderr)
        return 1

    nexus_app.clear_account_lockout(user_id=user_id)
    print(f"User '{user_id}' unlocked successfully.")
    return 0


def cmd_login(args):
    """Tests local authentication and optionally establishes a CLI session."""
    user_id = str(args.user or "").strip().lower()
    if not user_id:
        print("Error: Target user ID is required (--user <user_id>).", file=sys.stderr)
        return 1

    password = args.password
    if not password:
        try:
            password = getpass.getpass("Password: ")
        except (KeyboardInterrupt, EOFError):
            print("\nOperation cancelled.")
            return 1
    else:
        print("[WARNING] Password provided via command-line arguments may be visible in process listings and shell history.", file=sys.stderr)

    success, msg, user, lockout_secs = nexus_app.authenticate_user_credentials(user_id, password, client_ip="127.0.0.1")
    if not success:
        if lockout_secs:
            print(f"Account locked. Try again in {lockout_secs} seconds.")
        else:
            print("Authentication failed.")
        return 1

    print("Authentication successful.")
    print(f"User: {user['user_id']}")
    print(f"Role: {user['role']}")

    if args.session:
        token = nexus_app.create_user_session(user)
        save_local_session(token, user["user_id"], user["role"])
        print("Session established.")
        print(f"Session stored securely in {get_session_file_path()}.")

        if args.show_token:
            print("[SECURITY WARNING] Exposing session tokens in terminal output is insecure.", file=sys.stderr)
            print(f"Session Token: {token}")

    return 0


def cmd_whoami(args):
    """Inspects the local CLI session state."""
    session = read_local_session()
    if not session:
        print("Not authenticated.")
        return 1

    token = session.get("token")
    with nexus_app.SESSIONS_LOCK:
        server_session = nexus_app.SESSIONS.get(token)

    if not server_session:
        # Check if user still exists in database
        user = nexus_app.db_get_user(session.get("user_id", ""))
        if not user:
            print("Not authenticated.")
            clear_local_session()
            return 1

        print("Authenticated")
        print(f"User: {session.get('user_id')}")
        print(f"Role: {session.get('role')}")
        print("Session: active (local)")
        return 0

    if time.time() > server_session.get("expires_at", 0):
        print("Not authenticated.")
        clear_local_session()
        return 1

    print("Authenticated")
    print(f"User: {server_session.get('user_id')}")
    print(f"Role: {server_session.get('role')}")
    print("Session: active")
    return 0


def cmd_logout(args):
    """Revokes active server session and deletes local session file."""
    session = read_local_session()
    if session and session.get("token"):
        nexus_app.revoke_user_session(session["token"])

    clear_local_session()
    print("Logged out.")
    return 0


def cmd_sessions(args):
    """Displays active server sessions safely without printing raw tokens."""
    active = nexus_app.get_active_sessions()
    if not active:
        print("No active sessions.")
        return 0

    print(f"{'USER ID':<16} {'ROLE':<10} {'CREATED':<20} {'EXPIRES':<20} {'STATUS':<10}")
    print("-" * 78)
    for s in active:
        created_str = datetime.datetime.fromtimestamp(s['created_at']).strftime('%Y-%m-%d %H:%M:%S')
        expires_str = datetime.datetime.fromtimestamp(s['expires_at']).strftime('%Y-%m-%d %H:%M:%S')
        print(f"{s['user_id']:<16} {s['role']:<10} {created_str:<20} {expires_str:<20} {s['status']:<10}")

    return 0


def cmd_help(args):
    """Displays comprehensive CLI help and highlights SSH vs NexusNode auth separation."""
    print_help_banner()
    return 0


def print_help_banner():
    help_text = """NexusNode - Local Appliance Account & Authentication Administration CLI

AUTHENTICATION ARCHITECTURE:
  1. SSH Authentication (OS Layer):
     ssh -p 8022 u0_a208@PHONE_IP
     Authenticates into the Android/Termux host operating system.

  2. NexusNode Application Authentication (Application Layer):
     python -m nexus_admin login --user <user_id>
     Authenticates application accounts stored in SQLite (nexus_vault.db).

AVAILABLE COMMANDS:
  users                                 List all application users (safe metadata)
  user-info --user <id>                 Display details and privileges for a user
  create-user --user <id> --role <role> Create a new user (role: 'user' or 'admin')
  delete-user --user <id>               Delete a non-primary user account
  reset-password --user <id>            Reset user password and clear lockout
  unlock --user <id>                    Unlock account and reset failed login count
  login --user <id> [--session]         Test local credentials and optional session
  whoami                                Inspect active local CLI session
  sessions                              List active application sessions
  logout                                Revoke active session and delete local credentials
  help                                  Show this detailed help guide
"""
    print(help_text)


# ==============================================================================
# Compatibility Helper for Emergency Password Reset
# ==============================================================================

def emergency_reset_password(username: str = "admin", new_password: str = None) -> bool:
    """
    Authoritative emergency password reset implementation:
    1. Verifies requested user exists
    2. Hashes password using exact nexus_app.hash_password
    3. Updates database while strictly preserving role, privileges, created_at
    4. Clears active lockouts for that user
    5. Never leaks password, hash, or salt in output
    """
    username = (username or "admin").strip().lower()

    if not os.path.exists(config.DB_FILE):
        print(f"Error: NexusNode database not found at {config.DB_FILE}", file=sys.stderr)
        return False

    user = nexus_app.db_get_user(username)
    if not user:
        print(f"Error: User '{username}' does not exist.", file=sys.stderr)
        return False

    if not new_password:
        try:
            p1 = getpass.getpass("Password: ")
            if not p1:
                print("Error: Password cannot be empty.", file=sys.stderr)
                return False
            p2 = getpass.getpass("Confirm password: ")
            if p1 != p2:
                print("Error: Passwords do not match.", file=sys.stderr)
                return False
            new_password = p1
        except (KeyboardInterrupt, EOFError):
            print("\nOperation cancelled.", file=sys.stderr)
            return False

    if not str(new_password).strip():
        print("Error: Password cannot be empty.", file=sys.stderr)
        return False

    pwd_hash, salt = nexus_app.hash_password(new_password)

    with nexus_app.DB_LOCK:
        conn = nexus_app.get_db_connection()
        try:
            conn.execute(
                "UPDATE users SET password_hash = ?, salt = ? WHERE user_id = ?",
                (pwd_hash, salt, username)
            )
            conn.commit()
        finally:
            conn.close()

    nexus_app.clear_account_lockout(user_id=username)
    print(f"Password reset successfully for user '{username}'.")
    return True


# ==============================================================================
# CLI Argument Parser & Entry Point
# ==============================================================================

def build_parser():
    parser = argparse.ArgumentParser(
        prog="nexus_admin",
        description="NexusNode Local Account & Authentication Administration CLI",
        epilog="Note: SSH login and NexusNode application login are separate authentication systems."
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    # users
    subparsers.add_parser("users", help="List all application accounts")

    # user-info
    p_info = subparsers.add_parser("user-info", help="Display details and permissions for a user")
    p_info.add_argument("--user", "-u", required=True, help="Target username")

    # create-user
    p_create = subparsers.add_parser("create-user", help="Create a new application user")
    p_create.add_argument("--user", "-u", required=True, help="Target username")
    p_create.add_argument("--role", "-r", default="user", choices=["user", "admin"], help="Account role (default: user)")
    p_create.add_argument("--password", "-p", default=None, help="Password (optional; prompts securely if omitted)")
    p_create.add_argument("--yes", "-y", action="store_true", help="Skip interactive confirmations")

    # delete-user
    p_del = subparsers.add_parser("delete-user", help="Delete a user account")
    p_del.add_argument("--user", "-u", required=True, help="Target username")
    p_del.add_argument("--yes", "-y", action="store_true", help="Skip confirmation prompt")

    # reset-password
    p_reset = subparsers.add_parser("reset-password", help="Reset password for an application user")
    p_reset.add_argument("--user", "-u", default="admin", help="Target username (default: admin)")
    p_reset.add_argument("--password", "-p", default=None, help="New password (optional; prompts securely if omitted)")

    # unlock
    p_unlock = subparsers.add_parser("unlock", help="Unlock account and reset failed login attempts")
    p_unlock.add_argument("--user", "-u", required=True, help="Target username")

    # login
    p_login = subparsers.add_parser("login", help="Test local credentials and optional session creation")
    p_login.add_argument("--user", "-u", required=True, help="Target username")
    p_login.add_argument("--password", "-p", default=None, help="Password (optional; prompts securely if omitted)")
    p_login.add_argument("--session", "-s", action="store_true", help="Establish a local application session")
    p_login.add_argument("--show-token", action="store_true", help="Display raw session token (insecure)")

    # whoami
    subparsers.add_parser("whoami", help="Inspect local CLI session state")

    # sessions
    subparsers.add_parser("sessions", help="List active server sessions")

    # logout
    subparsers.add_parser("logout", help="Revoke active local session")

    # help
    subparsers.add_parser("help", help="Display detailed help and architecture guide")

    return parser


def main():
    if len(sys.argv) == 1:
        print_help_banner()
        sys.exit(0)

    parser = build_parser()
    args = parser.parse_args()

    command_handlers = {
        "users": cmd_users,
        "user-info": cmd_user_info,
        "create-user": cmd_create_user,
        "delete-user": cmd_delete_user,
        "reset-password": cmd_reset_password,
        "unlock": cmd_unlock,
        "login": cmd_login,
        "whoami": cmd_whoami,
        "sessions": cmd_sessions,
        "logout": cmd_logout,
        "help": cmd_help
    }

    handler = command_handlers.get(args.command)
    if not handler:
        parser.print_help()
        sys.exit(1)

    code = handler(args)
    sys.exit(code if isinstance(code, int) else 0)


if __name__ == "__main__":
    main()
