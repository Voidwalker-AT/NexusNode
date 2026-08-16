"""
NexusNode CLI — Authoritative Single-Threaded Log Stream & Query Command (Admin)
Communicates with /api/events and /api/logs/stream endpoints.
"""

import sys
import json

from .. import output
from ..client import NexusClient, NexusConnectionError


def cmd_logs(client: NexusClient, args, as_json: bool = False) -> int:
    """Dispatcher for 'nexus logs' commands."""
    subaction = getattr(args, "log_action", None) or "recent"

    if subaction == "recent" or subaction == "list":
        return cmd_logs_recent(client, args, as_json)
    elif subaction == "stream" or subaction == "follow" or subaction == "tail":
        return cmd_logs_stream(client, args, as_json)
    else:
        output.print_error(f"Unknown logs subcommand '{subaction}'. Type 'nexus logs --help'.")
        return 1


def cmd_logs_recent(client: NexusClient, args, as_json: bool = False) -> int:
    limit = getattr(args, "limit", 50) or 50
    level = getattr(args, "level", None)
    component = getattr(args, "component", None)

    params = {"limit": limit}
    if level:
        params["level"] = level
    if component:
        params["component"] = component

    try:
        status_code, resp = client.get("/api/events", params=params)
    except NexusConnectionError as e:
        output.print_error(str(e))
        return 1

    if status_code == 403:
        output.print_error("Permission denied: your account lacks 'can_view_system_logs' privilege.")
        return 1
    if status_code != 200 or not isinstance(resp, dict):
        output.print_error(f"Failed to fetch system logs (HTTP {status_code})")
        return 1

    if as_json or getattr(args, "json", False):
        output.print_json(resp)
        return 0

    logs = resp.get("events", [])
    if not logs:
        print("\nNo log events recorded matching query.\n")
        return 0

    headers = ["TIMESTAMP", "LEVEL", "COMPONENT", "MESSAGE"]
    rows = []
    for l in logs:
        rows.append([
            output.format_timestamp(l.get("timestamp", 0)),
            l.get("level", "INFO").upper(),
            l.get("component", "SYS"),
            l.get("message", "")[:60]
        ])

    print(f"\n--- RECENT SYSTEM LOGS ({len(logs)} events) ---")
    output.print_table(headers, rows)
    return 0


def cmd_logs_stream(client: NexusClient, args, as_json: bool = False) -> int:
    print("Connecting to live log event stream (Ctrl+C to stop)...\n")

    def handle_log_line(raw_line: str):
        line = raw_line.strip()
        if not line:
            return
        if line.startswith("data:"):
            line = line[5:].strip()
        try:
            parsed = json.loads(line)
            ts = output.format_timestamp(parsed.get("timestamp", 0))
            lvl = parsed.get("level", "INFO")
            comp = parsed.get("component", "SYS")
            msg = parsed.get("message", "")
            print(f"[{ts}] [{lvl}] [{comp}] {msg}")
        except Exception:
            print(line)

    try:
        client.stream_post("/api/logs/stream", on_chunk=handle_log_line, timeout=3600)
        return 0
    except (KeyboardInterrupt, EOFError):
        print("\nLog streaming disconnected.")
        return 0
    except Exception as e:
        output.print_error(f"Log stream disconnected: {e}")
        return 1
