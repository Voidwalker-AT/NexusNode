"""
NexusNode CLI — Appliance Settings & Configuration Command (Admin Only)
Communicates with /api/settings endpoint.
"""

import json

from .. import output
from .. import normalize
from ..client import NexusClient, NexusConnectionError


def cmd_settings(client: NexusClient, args, as_json: bool = False) -> int:
    """Dispatcher for 'nexus settings' commands."""
    subaction = getattr(args, "setting_action", None) or "get"

    if subaction == "get" or subaction == "list":
        return cmd_settings_get(client, args, as_json)
    elif subaction == "set":
        return cmd_settings_set(client, args, as_json)
    else:
        output.print_error(f"Unknown settings subcommand '{subaction}'. Type 'nexus settings --help'.")
        return 1


def cmd_settings_get(client: NexusClient, args, as_json: bool = False) -> int:
    try:
        status_code, resp = client.get("/api/settings")
    except NexusConnectionError as e:
        output.print_error(str(e))
        return 1

    if status_code == 403:
        output.print_error("Permission denied: your account lacks 'can_manage_settings' privilege.")
        return 1
    if status_code != 200 or not isinstance(resp, dict):
        err = resp.get("message", resp.get("error", f"HTTP {status_code}")) if isinstance(resp, dict) else str(resp)
        output.print_error(f"Failed to fetch settings ({err})")
        return 1

    key = getattr(args, "key", None)
    if key:
        val = resp.get(key)
        if as_json or getattr(args, "json", False):
            output.print_json({key: val})
        else:
            print(f"{key} = {val}")
        return 0

    if as_json or getattr(args, "json", False):
        output.print_json(resp)
        return 0

    print("\n--- APPLIANCE CONFIGURATION SETTINGS ---")
    for k, v in sorted(resp.items()):
        print(f"  {k:<32}: {v}")
    print()
    return 0


def cmd_settings_set(client: NexusClient, args, as_json: bool = False) -> int:
    key = getattr(args, "key", None)
    val = getattr(args, "value", None)
    if not key:
        output.print_error("Setting key is required. Usage: nexus settings set <key> <value>")
        return 1

    # Attempt to parse json value (bool, int, etc.)
    parsed_val = val
    if val is not None:
        try:
            parsed_val = json.loads(val)
        except Exception:
            parsed_val = val

    payload = {key: parsed_val}
    try:
        status_code, resp = client.post("/api/settings", data=payload)
    except NexusConnectionError as e:
        output.print_error(str(e))
        return 1

    if status_code == 403:
        output.print_error("Permission denied: your account lacks 'can_manage_settings' privilege.")
        return 1
    if status_code not in [200, 201]:
        err = resp.get("message", resp.get("error", f"HTTP {status_code}")) if isinstance(resp, dict) else str(resp)
        output.print_error(f"Failed to update setting: {err}")
        return 1

    if as_json or getattr(args, "json", False):
        output.print_json(resp)
    else:
        output.print_success(f"Setting '{key}' updated successfully.")
    return 0
