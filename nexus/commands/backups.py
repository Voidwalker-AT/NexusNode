"""
NexusNode CLI — Atomic Backups & Restore Command (Admin Only)
Communicates with /api/backups, /api/backups/create, /api/backups/restore, and download endpoints.
"""

from .. import output
from .. import normalize
from ..client import NexusClient, NexusConnectionError


def cmd_backups(client: NexusClient, args, as_json: bool = False) -> int:
    """Dispatcher for 'nexus backups' commands."""
    subaction = getattr(args, "backup_action", None) or "list"

    if subaction == "list" or subaction == "ls":
        return cmd_backups_list(client, args, as_json)
    elif subaction == "create":
        return cmd_backups_create(client, args, as_json)
    elif subaction == "restore":
        return cmd_backups_restore(client, args, as_json)
    elif subaction == "download" or subaction == "get":
        return cmd_backups_download(client, args, as_json)
    else:
        output.print_error(f"Unknown backups subcommand '{subaction}'. Type 'nexus backups --help'.")
        return 1


def cmd_backups_list(client: NexusClient, args, as_json: bool = False) -> int:
    try:
        status_code, resp = client.get("/api/backups")
    except NexusConnectionError as e:
        output.print_error(str(e))
        return 1

    if status_code == 403:
        output.print_error("Permission denied: your account lacks 'can_manage_backups' privilege.")
        return 1
    if status_code != 200:
        err = resp.get("message", resp.get("error", f"HTTP {status_code}")) if isinstance(resp, dict) else str(resp)
        output.print_error(f"Failed to list backups ({err})")
        return 1

    if as_json or getattr(args, "json", False):
        output.print_json(resp)
        return 0

    backups = normalize.normalize_list(resp, "backups")
    if not backups:
        print("\nNo system backups available.\n")
        return 0

    headers = ["BACKUP ID", "FILENAME", "SIZE", "CHECKSUM / SHA256", "CREATED AT"]
    rows = []
    for b in backups:
        if not isinstance(b, dict):
            continue
        sz = b.get("size_bytes", b.get("size", 0))
        csum = b.get("checksum") or b.get("sha256") or "--"
        csum_disp = csum[:12] + "..." if len(csum) > 12 else csum
        ts = b.get("created_at") or b.get("created")
        rows.append([
            str(b.get("id", "N/A")),
            str(b.get("filename", "N/A")),
            output.format_bytes(sz),
            csum_disp,
            output.format_timestamp(ts)
        ])

    print(f"\n--- ATOMIC SYSTEM BACKUPS ({len(backups)} archives) ---")
    output.print_table(headers, rows)
    return 0


def cmd_backups_create(client: NexusClient, args, as_json: bool = False) -> int:
    print("Initiating atomic database & settings backup on server...")
    try:
        status_code, resp = client.post("/api/backups/create")
    except NexusConnectionError as e:
        output.print_error(str(e))
        return 1

    if status_code == 403:
        output.print_error("Permission denied: your account lacks 'can_manage_backups' privilege.")
        return 1
    if status_code not in [200, 201, 202]:
        err = resp.get("message", resp.get("error", f"HTTP {status_code}")) if isinstance(resp, dict) else str(resp)
        output.print_error(f"Backup creation failed: {err}")
        return 1

    if as_json or getattr(args, "json", False):
        output.print_json(resp)
        return 0

    output.print_success("System backup task enqueued successfully:")
    if isinstance(resp, dict):
        if resp.get("task_id"):
            print(f"  Task ID:     {resp.get('task_id')}")
            print(f"  Status:      {resp.get('status', 'QUEUED').upper()}")
        elif resp.get("id"):
            print(f"  Backup ID:   {resp.get('id')}")
            print(f"  Filename:    {resp.get('filename')}")
            print(f"  Size:        {output.format_bytes(resp.get('size_bytes', 0))}")
    print()
    return 0


def cmd_backups_restore(client: NexusClient, args, as_json: bool = False) -> int:
    backup_id = getattr(args, "backup_id", None)
    if not backup_id:
        output.print_error("Backup ID is required to restore.")
        return 1

    yes = getattr(args, "yes", False)
    if not yes:
        try:
            confirm = input(f"WARNING: Restoring backup '{backup_id}' will overwrite current configuration. Proceed? [y/N]: ").strip().lower()
            if confirm != "y":
                print("Restore cancelled.")
                return 0
        except (KeyboardInterrupt, EOFError):
            print("\nCancelled.")
            return 0

    try:
        status_code, resp = client.post("/api/backups/restore", data={"backup_id": backup_id})
    except NexusConnectionError as e:
        output.print_error(str(e))
        return 1

    if status_code == 403:
        output.print_error("Permission denied: your account lacks backup restoration privileges.")
        return 1
    if status_code not in [200, 201, 202]:
        err = resp.get("message", resp.get("error", f"HTTP {status_code}")) if isinstance(resp, dict) else str(resp)
        output.print_error(f"Restore failed: {err}")
        return 1

    if as_json or getattr(args, "json", False):
        output.print_json(resp)
    else:
        output.print_success(f"Backup '{backup_id}' restored successfully.")
    return 0


def cmd_backups_download(client: NexusClient, args, as_json: bool = False) -> int:
    backup_id = getattr(args, "backup_id", None)
    if not backup_id:
        output.print_error("Backup ID is required.")
        return 1

    dest = getattr(args, "dest", None) or f"{backup_id}.tar.gz"
    print(f"Downloading backup archive '{backup_id}' from server...")
    try:
        client.download_file(f"/api/backups/download/{backup_id}", dest)
        output.print_success(f"Downloaded backup -> '{dest}'")
        return 0
    except Exception as e:
        output.print_error(f"Download failed: {e}")
        return 1
