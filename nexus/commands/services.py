"""
NexusNode CLI — Services & Runit Supervision Command (Admin Only)
Communicates with /api/services/status, /start, and /stop endpoints.
"""

from .. import output
from ..client import NexusClient, NexusConnectionError


def cmd_services(client: NexusClient, args, as_json: bool = False) -> int:
    """Dispatcher for 'nexus services' commands."""
    subaction = getattr(args, "service_action", None) or "status"

    if subaction == "status" or subaction == "list":
        return cmd_services_status(client, args, as_json)
    elif subaction == "start":
        return cmd_services_start(client, args, as_json)
    elif subaction == "stop":
        return cmd_services_stop(client, args, as_json)
    elif subaction == "restart":
        return cmd_services_restart(client, args, as_json)
    else:
        output.print_error(f"Unknown services subcommand '{subaction}'. Type 'nexus services --help'.")
        return 1


def cmd_services_status(client: NexusClient, args, as_json: bool = False) -> int:
    try:
        status_code, resp = client.get("/api/services/status")
    except NexusConnectionError as e:
        output.print_error(str(e))
        return 1

    if status_code == 403:
        output.print_error("Permission denied: your account lacks 'can_control_services' privilege.")
        return 1
    if status_code != 200 or not isinstance(resp, dict):
        output.print_error(f"Failed to fetch services status (HTTP {status_code})")
        return 1

    if as_json or getattr(args, "json", False):
        output.print_json(resp)
        return 0

    services = resp.get("services", {})
    headers = ["SERVICE", "STATE", "STATUS", "PID", "SUPERVISED"]
    rows = []
    for sname, sdata in services.items():
        state_str = "RUNNING" if sdata.get("online") else "STOPPED"
        rows.append([
            sname,
            state_str,
            sdata.get("status", "N/A"),
            sdata.get("pid", "-") or "-",
            "YES" if sdata.get("supervised") else "NO"
        ])

    print(f"\n--- MANAGED SYSTEM SERVICES ({resp.get('online_count', 0)}/{resp.get('total_count', 0)} active) ---")
    output.print_table(headers, rows)
    return 0


def cmd_services_start(client: NexusClient, args, as_json: bool = False) -> int:
    service = getattr(args, "service_name", None)
    if not service:
        output.print_error("Service name is required (e.g. ollama, cloudflared, localtonet).")
        return 1

    try:
        status_code, resp = client.post("/start", data={"service": service})
    except NexusConnectionError as e:
        output.print_error(str(e))
        return 1

    if status_code == 403:
        output.print_error("Permission denied: your account lacks service control privileges.")
        return 1
    if status_code != 200:
        err = resp.get("error", f"HTTP {status_code}") if isinstance(resp, dict) else str(resp)
        output.print_error(f"Failed to start '{service}': {err}")
        return 1

    if as_json or getattr(args, "json", False):
        output.print_json(resp)
    else:
        output.print_success(f"Service '{service}' started successfully.")
    return 0


def cmd_services_stop(client: NexusClient, args, as_json: bool = False) -> int:
    service = getattr(args, "service_name", None)
    if not service:
        output.print_error("Service name is required (e.g. ollama, cloudflared, localtonet).")
        return 1

    try:
        status_code, resp = client.post("/stop", data={"service": service})
    except NexusConnectionError as e:
        output.print_error(str(e))
        return 1

    if status_code == 403:
        output.print_error("Permission denied: your account lacks service control privileges.")
        return 1
    if status_code != 200:
        err = resp.get("error", f"HTTP {status_code}") if isinstance(resp, dict) else str(resp)
        output.print_error(f"Failed to stop '{service}': {err}")
        return 1

    if as_json or getattr(args, "json", False):
        output.print_json(resp)
    else:
        output.print_success(f"Service '{service}' stopped successfully.")
    return 0


def cmd_services_restart(client: NexusClient, args, as_json: bool = False) -> int:
    service = getattr(args, "service_name", None)
    if not service:
        output.print_error("Service name is required.")
        return 1

    # Call stop then start
    print(f"Restarting service '{service}' via runit supervisor...")
    try:
        client.post("/stop", data={"service": service})
        status_code, resp = client.post("/start", data={"service": service})
    except NexusConnectionError as e:
        output.print_error(str(e))
        return 1

    if status_code == 200:
        if as_json or getattr(args, "json", False):
            output.print_json(resp)
        else:
            output.print_success(f"Service '{service}' restarted successfully.")
        return 0
    else:
        err = resp.get("error", f"HTTP {status_code}") if isinstance(resp, dict) else str(resp)
        output.print_error(f"Restart failed: {err}")
        return 1
