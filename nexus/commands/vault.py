"""
NexusNode CLI — Vault & File Storage Management Command
Communicates with /files, /download, /upload, and /api/vault/checksum endpoints.
"""

import os
from pathlib import Path

from .. import output
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
    params = {}
    if search_q:
        params["search"] = search_q
    if cat:
        params["category"] = cat

    try:
        status_code, resp = client.get("/files", params=params)
    except NexusConnectionError as e:
        output.print_error(str(e))
        return 1

    if status_code == 403:
        output.print_error("Permission denied: your account lacks file access privileges.")
        return 1
    if status_code != 200 or not isinstance(resp, dict):
        output.print_error(f"Failed to list vault files (HTTP {status_code})")
        return 1

    if as_json or getattr(args, "json", False):
        output.print_json(resp)
        return 0

    files = resp.get("files", [])
    total_files = resp.get("total_count", len(files))
    used_space = output.format_bytes(resp.get("total_bytes", 0))

    if not files:
        print(f"\nVault is empty or no files match search query.\n")
        return 0

    headers = ["FILENAME", "SIZE", "CATEGORY", "MODIFIED"]
    rows = []
    for f in files:
        rows.append([
            f.get("name", "N/A"),
            output.format_bytes(f.get("size", 0)),
            f.get("category", "document").upper(),
            output.format_timestamp(f.get("modified", 0))
        ])

    print(f"\n--- VAULT DIRECTORY ({total_files} files, {used_space}) ---")
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
        output.print_error(f"Failed to get file info (HTTP {status_code})")
        return 1

    if as_json or getattr(args, "json", False):
        output.print_json(resp)
        return 0

    print(f"\n--- FILE DETAILS: {resp.get('filename')} ---")
    print(f"  Path:         {resp.get('path')}")
    print(f"  Size:         {output.format_bytes(resp.get('size_bytes', 0))}")
    print(f"  SHA-256:      {resp.get('sha256')}")
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

    if status_code == 200:
        output.print_success(f"File '{filename}' deleted from vault.")
        return 0
    else:
        err = resp.get("error", f"HTTP {status_code}") if isinstance(resp, dict) else str(resp)
        output.print_error(f"Delete failed: {err}")
        return 1


def cmd_vault_clean_temp(client: NexusClient, args, as_json: bool = False) -> int:
    try:
        status_code, resp = client.post("/api/vault/clean-temp")
    except NexusConnectionError as e:
        output.print_error(str(e))
        return 1

    if status_code == 200 and isinstance(resp, dict):
        if as_json or getattr(args, "json", False):
            output.print_json(resp)
        else:
            output.print_success(f"Cleaned {resp.get('deleted_count', 0)} temporary files ({output.format_bytes(resp.get('freed_bytes', 0))} freed).")
        return 0
    else:
        err = resp.get("error", f"HTTP {status_code}") if isinstance(resp, dict) else str(resp)
        output.print_error(f"Clean temp failed: {err}")
        return 1
