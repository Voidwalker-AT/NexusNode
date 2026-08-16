"""
NexusNode CLI — Media Center & YouTube/Audio Download Command
Communicates with /api/media/download, /api/media/library, and /api/tasks endpoints.
"""

from .. import output
from ..client import NexusClient, NexusConnectionError


def cmd_media(client: NexusClient, args, as_json: bool = False) -> int:
    """Dispatcher for 'nexus media' subcommands."""
    subaction = getattr(args, "media_action", None) or "library"

    if subaction == "download":
        return cmd_media_download(client, args, as_json)
    elif subaction == "library":
        return cmd_media_library(client, args, as_json)
    elif subaction == "queue":
        return cmd_media_queue(client, args, as_json)
    else:
        output.print_error(f"Unknown media subcommand '{subaction}'. Type 'nexus media --help'.")
        return 1


def cmd_media_download(client: NexusClient, args, as_json: bool = False) -> int:
    url = getattr(args, "url", None)
    if not url:
        try:
            url = input("Media URL to download (e.g. YouTube, direct link): ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nCancelled.")
            return 1

    if not url:
        output.print_error("Media URL is required.")
        return 1

    fmt = getattr(args, "format", None) or "mp4"
    quality = getattr(args, "quality", None) or "best"
    dest = getattr(args, "dest", None) or "Downloads"

    payload = {
        "url": url,
        "format": fmt,
        "quality": quality,
        "destination": dest,
        "metadata": True
    }

    try:
        status_code, resp = client.post("/api/media/download", data=payload)
    except NexusConnectionError as e:
        output.print_error(str(e))
        return 1

    if status_code == 403:
        output.print_error("Permission denied: your account lacks 'can_download_media' privilege.")
        return 1
    if status_code != 200 or not isinstance(resp, dict):
        err = resp.get("error", f"HTTP {status_code}") if isinstance(resp, dict) else str(resp)
        output.print_error(f"Failed to enqueue download: {err}")
        return 1

    if as_json or getattr(args, "json", False):
        output.print_json(resp)
        return 0

    output.print_success("Download task submitted to server queue.")
    print(f"  Task ID:     {resp.get('task_id')}")
    print(f"  Format:      {fmt.upper()} ({quality})")
    print(f"  Destination: Vault -> {dest}/")
    print(f"  Status:      {resp.get('status', 'QUEUED').upper()}")
    print("Use 'nexus tasks' to track progress.\n")
    return 0


def cmd_media_library(client: NexusClient, args, as_json: bool = False) -> int:
    try:
        status_code, resp = client.get("/api/media/library")
    except NexusConnectionError as e:
        output.print_error(str(e))
        return 1

    if status_code == 403:
        output.print_error("Permission denied: your account lacks media access privileges.")
        return 1
    if status_code != 200 or not isinstance(resp, dict):
        output.print_error(f"Failed to load media library (HTTP {status_code})")
        return 1

    if as_json or getattr(args, "json", False):
        output.print_json(resp)
        return 0

    items = resp.get("items", [])
    total_size = output.format_bytes(resp.get("total_size_bytes", 0))

    if not items:
        print("\nMedia library is empty.\n")
        return 0

    headers = ["FILENAME", "FORMAT", "SIZE", "MODIFIED"]
    rows = []
    for item in items:
        rows.append([
            item.get("name", "N/A"),
            item.get("ext", "").upper().lstrip("."),
            output.format_bytes(item.get("size", 0)),
            output.format_timestamp(item.get("modified", 0))
        ])

    print(f"\n--- MEDIA LIBRARY ({len(items)} items, {total_size}) ---")
    output.print_table(headers, rows)
    return 0


def cmd_media_queue(client: NexusClient, args, as_json: bool = False) -> int:
    try:
        status_code, resp = client.get("/api/tasks")
    except NexusConnectionError as e:
        output.print_error(str(e))
        return 1

    if status_code == 403:
        output.print_error("Permission denied.")
        return 1
    if status_code != 200 or not isinstance(resp, dict):
        output.print_error(f"Failed to fetch task queue (HTTP {status_code})")
        return 1

    tasks = resp.get("tasks", [])
    media_tasks = [t for t in tasks if "media" in str(t.get("type", "")).lower() or "download" in str(t.get("type", "")).lower()]

    if as_json or getattr(args, "json", False):
        output.print_json(media_tasks)
        return 0

    if not media_tasks:
        print("\nNo media download tasks in queue.\n")
        return 0

    headers = ["TASK ID", "STATE", "PROGRESS", "DESCRIPTION", "CREATED"]
    rows = []
    for t in media_tasks:
        prog = f"{t.get('progress', 0):.0f}%"
        rows.append([
            t.get("task_id", "")[:12],
            t.get("state", "UNKNOWN").upper(),
            prog,
            t.get("description", "Media Download")[:32],
            output.format_timestamp(t.get("created_at", 0))
        ])

    print("\n--- ACTIVE MEDIA DOWNLOADS ---")
    output.print_table(headers, rows)
    return 0
