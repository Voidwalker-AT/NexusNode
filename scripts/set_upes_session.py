"""
NexusNode — Secure UPES Session Configuration Utility
Saves authenticated UPES portal Bearer access token and Student UUID directly
into NexusNode's encrypted database vault using AES-GCM at rest.

Usage:
    Interactive (recommended - hides token input from shell history):
        python scripts/set_upes_session.py

    Command line:
        python scripts/set_upes_session.py --student-uuid <UUID> --token <BEARER_TOKEN>
"""

import argparse
import getpass
import os
import sys
import sqlite3
import time

# Ensure server root is on python path
server_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if server_root not in sys.path:
    sys.path.insert(0, server_root)

import config
import timetable_sync
from timetable_sync import TimetableService, init_timetable_tables


def main():
    parser = argparse.ArgumentParser(description="Configure UPES portal session credentials securely.")
    parser.add_argument("--user-id", default="admin", help="NexusNode user ID (default: admin)")
    parser.add_argument("--student-uuid", help="UPES Student UUID (e.g. 3a678d8e-8817-41e6-b1a8-5a3ec6ee4948)")
    parser.add_argument("--token", help="UPES Portal Bearer Access Token")
    parser.add_argument("--api-url", default=config.UPES_TIMETABLE_API_URL, help="UPES API Gateway URL")
    args = parser.parse_args()

    student_uuid = args.student_uuid
    token = args.token

    if not student_uuid:
        try:
            student_uuid = input("Enter UPES Student UUID: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nAborted.")
            sys.exit(1)

    if not token:
        try:
            token = getpass.getpass("Enter UPES Bearer Access Token (input hidden): ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nAborted.")
            sys.exit(1)

    if not student_uuid:
        print("[ERROR] Student UUID cannot be empty.")
        sys.exit(1)

    if not token:
        print("[ERROR] Bearer token cannot be empty.")
        sys.exit(1)

    db_path = getattr(config, "UNIFIED_DB_FILE", config.SQLITE_DB_PATH)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    def conn_factory():
        c = sqlite3.connect(db_path)
        c.row_factory = sqlite3.Row
        return c

    # Ensure tables exist
    conn = conn_factory()
    try:
        init_timetable_tables(conn)
        conn.commit()
    finally:
        conn.close()

    service = TimetableService(conn_factory)
    service.save_upes_session(
        user_id=args.user_id,
        access_token=token,
        student_code=student_uuid,
        api_url=args.api_url
    )

    exp = timetable_sync.decode_jwt_expiration(token)
    exp_str = "Not embedded in JWT"
    if exp:
        import datetime
        dt = datetime.datetime.fromtimestamp(exp, datetime.timezone.utc)
        ttl = max(0, int(exp - time.time()))
        hours = ttl // 3600
        mins = (ttl % 3600) // 60
        exp_str = f"{dt.strftime('%Y-%m-%d %H:%M:%S UTC')} (valid for ~{hours}h {mins}m)"

    masked_uuid = student_uuid[:4] + "..." + student_uuid[-4:] if len(student_uuid) > 8 else "***"
    print(f"[SUCCESS] UPES session configured and AES-GCM encrypted for user '{args.user_id}'.")
    print(f"          Student UUID : {masked_uuid}")
    print(f"          Target URL   : {args.api_url}")
    print(f"          Expires At   : {exp_str}")
    print("          Bearer Token : [ENCRYPTED AT REST]")


if __name__ == "__main__":
    main()
