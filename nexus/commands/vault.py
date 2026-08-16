"""
NexusNode CLI — Vault & File Storage Management Command
Communicates with /files, /download, /upload, and /api/vault/checksum endpoints.
"""

from .. import output
from .. import normalize
from ..client import NexusClient, NexusConnectionError


def cmd_vault(client: NexusClient, args, as_json: bool = False) -> int:
    """Dispatcher for 'nexus vault' subcommands."""
    subaction = getattr(args, "vault_action", None) or "list"

    if subaction == "list" or subaction == "ls":
        return cmd_vault_list(client, args, as_json)
    elif subaction == "info":
        return cmd_vault_info(client, args, as_json)
    elif subaction == "checksum":
        return cmd_vault_checksum(client, args, as_json)
    elif subaction == "download" or subaction == "get":
        return cmd_vault_download(client, args, as_json)
    elif subaction == "delete" or subaction == "rm":
        return cmd_vault_delete(client, args, as_json)
    elif subaction == "clean-temp":
        return cmd_vault_clean_temp(client, args, as_json)
    else:
        output.print_error(f"Unknown vault subcommand '{subaction}'. Type 'nexus vault --help'.")
        return 1


def cmd_vault_list(client: NexusClient, args, as_json: bool = False) -> int:
    search_q = getattr(args, "search", None)
    cat = getattr(args, "category", None)
    path_arg = getattr(args, "path", None)
    params = {}
    if search_q:
        params["search"] = search_q
    if cat:
        params["category"] = cat
    if path_arg:
        params["path"] = path_arg

    try:
        status_code, resp = client.get("/files", params=params)
    except NexusConnectionError as e:
        output.print_error(str(e))
        return 1

    if status_code == 403:
        output.print_error("Permission denied: your account lacks file access privileges.")
        return 1
    if status_code != 200:
        err = resp.get("message", resp.get("error", f"HTTP {status_code}")) if isinstance(resp, dict) else str(resp)
        output.print_error(f"Failed to list vault files ({err})")
        return 1

    if as_json or getattr(args, "json", False):
        output.print_json(resp)
        return 0

    files = normalize.normalize_list(resp, "files")
    if not files:
        print(f"\nVault is empty or no files match query.\n")
        return 0

    headers = ["FILENAME", "SIZE", "CATEGORY", "MODIFIED"]
    rows = []
    total_bytes = 0
    file_count = 0
    folder_count = 0

    for f in files:
        if not isinstance(f, dict):
            continue
        is_dir = f.get("is_dir") or f.get("category") == "folder"
        if is_dir:
            folder_count += 1
            sz_str = "FOLDER"
            cat_str = "FOLDER"
        else:
            file_count += 1
            f_size = f.get("size", f.get("size_bytes", 0))
            total_bytes += f_size
            sz_str = output.format_bytes(f_size)
            cat_str = (f.get("category") or "document").upper()

        rows.append([
            f.get("name", f.get("filename", "N/A")),
            sz_str,
            cat_str,
            output.format_timestamp(f.get("modified") or f.get("modified_at") or f.get("mtime"))
        ])

    count_str = f"{file_count} files" if folder_count == 0 else f"{file_count} files, {folder_count} folders"
    print(f"\n--- VAULT DIRECTORY ({count_str} | {output.format_bytes(total_bytes)}) ---")
    output.print_table(headers, rows)
    return 0


def cmd_vault_info(client: NexusClient, args, as_json: bool = False) -> int:
    filename = getattr(args, "filename", None)
    if not filename:
        output.print_error("Filename is required for 'vault info'.")
        return 1

    try:
        status_code, resp = client.get(f"/api/vault/checksum/{filename}")
    except NexusConnectionError as e:
        output.print_error(str(e))
        return 1

    if status_code == 404:
        output.print_error(f"File '{filename}' not found in vault.")
        return 1
    if status_code != 200 or not isinstance(resp, dict):
        err = resp.get("message", resp.get("error", f"HTTP {status_code}")) if isinstance(resp, dict) else str(resp)
        output.print_error(f"Failed to get file info ({err})")
        return 1

    if as_json or getattr(args, "json", False):
        output.print_json(resp)
        return 0

    print(f"\n--- FILE DETAILS: {resp.get('filename')} ---")
    print(f"  Path:         {resp.get('path', 'N/A')}")
    print(f"  Size:         {output.format_bytes(resp.get('size_bytes', 0))}")
    print(f"  SHA-256:      {resp.get('sha256', 'N/A')}")
    print(f"  Last Modified:{output.format_timestamp(resp.get('modified_time'))}\n")
    return 0


def cmd_vault_checksum(client: NexusClient, args, as_json: bool = False) -> int:
    return cmd_vault_info(client, args, as_json)


def cmd_vault_download(client: NexusClient, args, as_json: bool = False) -> int:
    filename = getattr(args, "filename", None)
    dest = getattr(args, "dest", None) or filename
    if not filename:
        output.print_error("Remote filename is required for download.")
        return 1

    print(f"Downloading '{filename}' from vault...")
    try:
        client.download_file(f"/download/{filename}", dest)
        output.print_success(f"Downloaded '{filename}' -> '{dest}'")
        return 0
    except Exception as e:
        output.print_error(f"Download failed: {e}")
        return 1


def cmd_vault_delete(client: NexusClient, args, as_json: bool = False) -> int:
    filename = getattr(args, "filename", None)
    if not filename:
        output.print_error("Filename is required for delete.")
        return 1

    yes = getattr(args, "yes", False)
    if not yes:
        try:
            confirm = input(f"Are you sure you want to delete '{filename}' from vault? [y/N]: ").strip().lower()
            if confirm != "y":
                print("Deletion cancelled.")
                return 0
        except (KeyboardInterrupt, EOFError):
            print("\nCancelled.")
            return 0

    try:
        status_code, resp = client.delete(f"/files/{filename}")
    except NexusConnectionError as e:
        output.print_error(str(e))
        return 1

    if status_code in [200, 204]:
        output.print_success(f"File '{filename}' deleted from vault.")
        return 0
    else:
        err = resp.get("error", resp.get("message", f"HTTP {status_code}")) if isinstance(resp, dict) else str(resp)
        output.print_error(f"Delete failed: {err}")
        return 1


def cmd_vault_clean_temp(client: NexusClient, args, as_json: bool = False) -> int:
    try:
        status_code, resp = client.post("/api/vault/clean-temp")
    except NexusConnectionError as e:
        output.print_error(str(e))
        return 1

    if status_code in [200, 201] and isinstance(resp, dict):
        if as_json or getattr(args, "json", False):
            output.print_json(resp)
        else:
            output.print_success(f"Cleaned {resp.get('deleted_count', 0)} temporary files ({output.format_bytes(resp.get('freed_bytes', 0))} freed).")
        return 0
    else:
        err = resp.get("error", resp.get("message", f"HTTP {status_code}")) if isinstance(resp, dict) else str(resp)
        output.print_error(f"Clean temp failed: {err}")
        return 1
