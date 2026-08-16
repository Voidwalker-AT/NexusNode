#!/usr/bin/env python3
"""
NexusNode — Local Emergency Password Reset Helper (Termux CLI Only)
Authoritative local administration tool for emergency credential recovery.
NEVER exposed over HTTP / network routes.
"""
import os
import sys
import getpass
import argparse
import sqlite3

# Ensure server root is importable
SERVER_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SERVER_ROOT not in sys.path:
    sys.path.insert(0, SERVER_ROOT)

import config
import app as nexus_app


def emergency_reset_password(username: str = "admin", new_password: str = None) -> bool:
    """
    Executes emergency password reset locally:
    1. Verifies requested user exists
    2. Hashes password using exact nexus_app.hash_password
    3. Updates database while strictly preserving role, privileges, created_at
    4. Clears active lockouts for the account
    """
    username = (username or "admin").strip().lower()

    if not os.path.exists(config.DB_FILE):
        print(f"Error: NexusNode database not found at {config.DB_FILE}", file=sys.stderr)
        return False

    conn = sqlite3.connect(config.DB_FILE)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        cur.execute("SELECT user_id, role, privileges, created_at FROM users WHERE user_id = ?", (username,))
        user_row = cur.fetchone()
        if not user_row:
            print(f"Error: User '{username}' does not exist.", file=sys.stderr)
            return False

        # Get password interactively if not provided
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

        # Hash using exact app.py implementation
        pwd_hash, salt = nexus_app.hash_password(new_password)

        cur.execute(
            "UPDATE users SET password_hash = ?, salt = ? WHERE user_id = ?",
            (pwd_hash, salt, username)
        )
        conn.commit()

        # Clear failed login & lockout records
        nexus_app.clear_account_lockout(user_id=username)

        # Print ONLY clean status message, never password, hash, or salt
        print(f"Password reset successfully for user '{username}'.")
        return True
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="NexusNode Local Emergency Password Reset Helper")
    parser.add_argument("username", nargs="?", default="admin", help="Username to reset (default: admin)")
    parser.add_argument("--password", "-p", default=None, help="New password (optional; prompts securely if omitted)")
    args = parser.parse_args()

    success = emergency_reset_password(args.username, args.password)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
