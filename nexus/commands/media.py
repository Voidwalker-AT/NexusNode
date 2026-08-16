"""
NexusNode CLI — Media Center & YouTube/Audio Download Command
Communicates with /api/media/download, /api/media/library, and /api/tasks endpoints.
"""

from .. import output
from .. import normalize
from ..client import NexusClient, NexusConnectionError


def cmd_media(client: NexusClient, args, as_json: bool = False) -> int:
    """Dispatcher for 'nexus media' subcommands."""
    subaction = getattr(args, "media_action", None) or "queue"

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
    if status_code not in [200, 201, 202] or not isinstance(resp, dict):
        err = resp.get("message", resp.get("error", f"HTTP {status_code}")) if isinstance(resp, dict) else str(resp)
        output.print_error(f"Failed to enqueue download: {err}")
        return 1

    if as_json or getattr(args, "json", False):
        output.print_json(resp)
        return 0

    task_id = resp.get("task_id")
    if not task_id and isinstance(resp.get("task_ids"), list) and resp["task_ids"]:
        task_id = resp["task_ids"][0]

    output.print_success("Download task submitted to server queue.")
    print(f"  Task ID:     {output.cyan(task_id or 'unknown', bold=True)}")
    print(f"  Format:      {fmt.upper()} ({quality})")
    print(f"  Destination: Vault -> {dest}/")
    print(f"  Status:      {output.colorize_status(resp.get('status', 'QUEUED'))}")
    print(f"Use '{output.cyan('nexus media queue')}' or '{output.cyan('nexus tasks status ' + (task_id or ''))}' to track progress.\n")
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
    if status_code != 200:
        err = resp.get("message", resp.get("error", f"HTTP {status_code}")) if isinstance(resp, dict) else str(resp)
        output.print_error(f"Failed to load media library ({err})")
        return 1

    if as_json or getattr(args, "json", False):
        output.print_json(resp)
        return 0

    items = normalize.normalize_list(resp, "items")
    total_size = output.format_bytes(sum(item.get("size", item.get("size_bytes", 0)) for item in items if isinstance(item, dict)))

    if not items:
        print("\nMedia library is empty.\n")
        return 0

    headers = ["FILENAME", "CATEGORY", "FORMAT", "SIZE"]
    rows = []
    for item in items:
        if not isinstance(item, dict):
            continue
        fname = item.get("name", item.get("filename", "N/A"))
        cat = (item.get("category") or "other").upper()
        fmt = (item.get("format") or "").upper()
        sz = output.format_bytes(item.get("size", item.get("size_bytes", 0)))
        rows.append([output.cyan(fname[:35]), cat, fmt, sz])

    print(f"\n--- MEDIA LIBRARY ({len(items)} items, {total_size}) ---")
    output.print_table(headers, rows)
    return 0


def cmd_media_queue(client: NexusClient, args, as_json: bool = False) -> int:
    try:
        status_code, resp = client.get("/api/tasks?type=media_download")
    except NexusConnectionError as e:
        output.print_error(str(e))
        return 1

    if status_code == 403:
        output.print_error("Permission denied.")
        return 1
    if status_code != 200:
        err = resp.get("message", resp.get("error", f"HTTP {status_code}")) if isinstance(resp, dict) else str(resp)
        output.print_error(f"Failed to fetch media task queue ({err})")
        return 1

    all_tasks = normalize.normalize_tasks(resp)
    media_tasks = [t for t in all_tasks if "media" in t["task_type"].lower() or "download" in t["task_type"].lower()]

    if as_json or getattr(args, "json", False):
        output.print_json([t.get("raw", t) for t in media_tasks])
        return 0

    if not media_tasks:
        print("\nNo active or queued media operations.\n")
        return 0

    active_tasks = [t for t in media_tasks if t["status"] in ["STARTING", "RUNNING", "POST_PROCESSING", "VERIFYING", "CANCELLING"]]
    queued_tasks = [t for t in media_tasks if t["status"] == "QUEUED"]
    terminal_tasks = [t for t in media_tasks if t not in active_tasks and t not in queued_tasks]

    print()
    if active_tasks:
        print(output.cyan("ACTIVE", bold=True))
        try:
            print(output.dim("─" * 40))
        except UnicodeEncodeError:
            print(output.dim("-" * 40))
        for t in active_tasks:
            title = t.get("title") or "Media Download"
            status_col = output.colorize_status(t["status"])
            stage_col = f" / {output.colorize_status(t['stage'])}" if t.get("stage") and t["stage"] != t["status"] else ""
            print(f"Download: {output.white(title, bold=True)}")
            print(f"{status_col}{stage_col}")
            if t.get("progress") is not None:
                prog_val = t['progress']
                prog_col = output.green(f"{prog_val:.0f}%", bold=True) if prog_val >= 99 else output.yellow(f"{prog_val:.0f}%")
                print(f"Progress:        {prog_col}")
            if t.get("speed_bps"):
                spd_mb = round(t["speed_bps"] / (1024 * 1024), 2)
                print(f"Speed:           {output.cyan(f'{spd_mb} MB/s')}")
            if t.get("eta_seconds") is not None:
                eta_val = t["eta_seconds"]
                print(f"ETA:             {output.yellow(f'{eta_val}s')}")
            if t.get("output_path"):
                print(f"Output:          {output.green(str(t['output_path']))}")
            print()

    if queued_tasks:
        print(output.yellow("QUEUED", bold=True))
        try:
            print(output.dim("─" * 40))
        except UnicodeEncodeError:
            print(output.dim("-" * 40))
        for t in queued_tasks:
            title = t.get("title") or "Media Download"
            print(f"Download: {title}")
            print(f"{output.yellow('QUEUED')}\n")

    if not active_tasks and not queued_tasks and terminal_tasks:
        headers = ["TASK ID", "STATUS", "STAGE", "TITLE", "ERROR", "CREATED"]
        rows = []
        for t in terminal_tasks[:10]:
            status_col = output.colorize_status(t["status"])
            stage_col = output.colorize_status(t["stage"]) if t.get("stage") else output.dim("--")
            err_raw = str(t.get("error")) if t.get("error") else "--"
            err_col = output.red(err_raw[:24]) if t.get("error") else output.dim("--")
            rows.append([
                output.cyan(t["task_id"][:14]),
                status_col,
                stage_col,
                t.get("title", "Media Download")[:30],
                err_col,
                output.format_timestamp(t.get("created_at"))
            ])
        print(output.cyan("RECENT MEDIA TASKS", bold=True))
        output.print_table(headers, rows)

    return 0
