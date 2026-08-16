#!/usr/bin/env python3
"""
NexusNode — Local Appliance Admin CLI (Termux CLI Only)
"""
import sys
import argparse
from scripts.reset_admin_password import emergency_reset_password


def main():
    parser = argparse.ArgumentParser(description="NexusNode Local Appliance Admin CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    reset_parser = subparsers.add_parser("reset-password", help="Reset a user password locally")
    reset_parser.add_argument("--user", "-u", default="admin", help="Target username (default: admin)")
    reset_parser.add_argument("--password", "-p", default=None, help="New password (prompts securely if omitted)")

    args = parser.parse_args()
    if args.command == "reset-password":
        success = emergency_reset_password(args.user, args.password)
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
