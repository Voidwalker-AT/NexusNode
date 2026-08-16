#!/usr/bin/env python3
"""
NexusNode — Local Emergency Password Reset Helper (Termux CLI Only)
Authoritative local administration tool for emergency credential recovery.
Reuses the central implementation in nexus_admin.py.
NEVER exposed over HTTP / network routes.
"""
import os
import sys
import argparse

# Ensure server root is importable
SERVER_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SERVER_ROOT not in sys.path:
    sys.path.insert(0, SERVER_ROOT)

from nexus_admin import emergency_reset_password


def main():
    parser = argparse.ArgumentParser(description="NexusNode Local Emergency Password Reset Helper")
    parser.add_argument("username", nargs="?", default="admin", help="Username to reset (default: admin)")
    parser.add_argument("--password", "-p", default=None, help="New password (optional; prompts securely if omitted)")
    args = parser.parse_args()

    success = emergency_reset_password(args.username, args.password)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
