"""
NexusNode CLI — Secure Temporary Shares Command
Communicates with /api/shares and /api/shares/<id> endpoints.
"""

from .. import output
from ..client import NexusClient, NexusConnectionError


def cmd_shares(client: NexusClient, args, as_json: bool = False) -> int:
    """Dispatcher for 'nexus shares' subcommands."""
    subaction = getattr(args, "shares_action", None) or "list"

    if subaction == "list" or subaction == "ls":
        return cmd_shares_list(client, args, as_json)
    elif subaction == "create" or subaction == "add":
        return cmd_shares_create(client, args, as_json)
    elif subaction == "revoke" or subaction == "delete" or subaction == "rm":
        return cmd_shares_revoke(client, args, as_json)
    else:
        output.print_error(f"Unknown shares subcommand '{subaction}'. Type 'nexus shares --help'.")
        return 1


def cmd_shares_list(client: NexusClient, args, as_json: bool = False) -> int:
    try:
        status_code, resp = client.get("/api/shares")
    except NexusConnectionError as e:
        output.print_error(str(e))
        return 1

    if status_code == 403:
        output.print_error("Permission denied: your account lacks share management privileges.")
        return 1
    if status_code != 200 or not isinstance(resp, dict):
        output.print_error(f"Failed to list shares (HTTP {status_code})")
        return 1

    if as_json or getattr(args, "json", False):
        output.print_json(resp)
        return 0

    shares = resp.get("shares", [])
    if not shares:
        print("\nNo active temporary share links.\n")
        return 0

    headers = ["SHARE ID", "FILENAME", "TOKEN", "EXPIRES AT", "DOWNLOADS"]
    rows = []
    for s in shares:
        dl_str = f"{s.get('downloads_count', 0)}/{s.get('max_downloads', 'unlimited')}"
        rows.append([
            s.get("share_id", "")[:12],
            s.get("filename", "N/A"),
            s.get("token", "")[:12] + "...",
            output.format_timestamp(s.get("expires_at")),
            dl_str
        ])

    print(f"\n--- ACTIVE SHARE LINKS ({len(shares)} links) ---")
    output.print_table(headers, rows)
    return 0


def cmd_shares_create(client: NexusClient, args, as_json: bool = False) -> int:
    filename = getattr(args, "filename", None) or getattr(args, "filename_or_id", None)
    if not filename:
        output.print_error("Filename is required to create a share link.")
        return 1

    expire_hours = getattr(args, "expire_hours", 24) or 24
    max_dl = getattr(args, "max_downloads", 10) or 10

    payload = {
        "filename": filename,
        "expire_hours": expire_hours,
        "max_downloads": max_dl
    }

    try:
        status_code, resp = client.post("/api/shares", data=payload)
    except NexusConnectionError as e:
        output.print_error(str(e))
        return 1

    if status_code == 403:
        output.print_error("Permission denied: your account lacks 'can_create_shares' privilege.")
        return 1
    if status_code != 200 and status_code != 201:
        err = resp.get("error", f"HTTP {status_code}") if isinstance(resp, dict) else str(resp)
        output.print_error(f"Failed to create share: {err}")
        return 1

    if as_json or getattr(args, "json", False):
        output.print_json(resp)
        return 0

    output.print_success(f"Share link created successfully:")
    print(f"  Share ID:    {resp.get('share_id')}")
    print(f"  Filename:    {resp.get('filename')}")
    print(f"  Public URL:  {client.server_url}/s/{resp.get('token')}")
    print(f"  Expires:     {output.format_timestamp(resp.get('expires_at'))}")
    print(f"  Max DLs:     {resp.get('max_downloads')}\n")
    return 0


def cmd_shares_revoke(client: NexusClient, args, as_json: bool = False) -> int:
    share_id = getattr(args, "share_id", None) or getattr(args, "filename_or_id", None)
    if not share_id:
        output.print_error("Share ID is required to revoke.")
        return 1

    try:
        status_code, resp = client.delete(f"/api/shares/{share_id}")
    except NexusConnectionError as e:
        output.print_error(str(e))
        return 1

    if status_code == 403:
        output.print_error("Permission denied.")
        return 1
    if status_code != 200:
        err = resp.get("error", f"HTTP {status_code}") if isinstance(resp, dict) else str(resp)
        output.print_error(f"Failed to revoke share: {err}")
        return 1

    if as_json or getattr(args, "json", False):
        output.print_json(resp)
    else:
        output.print_success(f"Share link '{share_id}' revoked.")
    return 0
