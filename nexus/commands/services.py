"""
NexusNode CLI — Services & Runit Supervision Command (Admin Only)
Communicates with /api/services/status, /start, and /stop endpoints.
"""

from .. import output
from .. import normalize
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
        err = resp.get("message", resp.get("error", f"HTTP {status_code}")) if isinstance(resp, dict) else str(resp)
        output.print_error(f"Failed to fetch services status ({err})")
        return 1

    if as_json or getattr(args, "json", False):
        output.print_json(resp)
        return 0

    services = normalize.normalize_services(resp)
    headers = ["SERVICE", "STATE", "STATUS", "PID", "SUPERVISED"]
    rows = []
    online_count = 0
    total_count = len(services)

    for sname, sdata in sorted(services.items()):
        is_running = bool(sdata.get("running") or sdata.get("online") or str(sdata.get("status", "")).lower() in ["online", "running"])
        if is_running:
            online_count += 1
            state_str = output.green("RUNNING", bold=True)
        else:
            state_str = output.red("STOPPED", bold=False)

        raw_stat = sdata.get("status") or sdata.get("state") or "N/A"
        pid_val = sdata.get("pid") or "-"

        rows.append([
            output.cyan(sname),
            state_str,
            str(raw_stat),
            str(pid_val),
            output.green("YES") if sdata.get("supervised", True) else output.dim("NO")
        ])

    count_str = output.green(f"{online_count}/{total_count}") if online_count == total_count else output.yellow(f"{online_count}/{total_count}")
    print(f"\n--- MANAGED SYSTEM SERVICES ({count_str} active) ---")
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
    if status_code not in [200, 201, 202]:
        err = resp.get("message", resp.get("error", f"HTTP {status_code}")) if isinstance(resp, dict) else str(resp)
        output.print_error(f"Failed to start '{service}': {err}")
        return 1

    if as_json or getattr(args, "json", False):
        output.print_json(resp)
    else:
        output.print_success(f"Service '{output.cyan(service)}' started successfully.")
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
    if status_code not in [200, 201, 202]:
        err = resp.get("message", resp.get("error", f"HTTP {status_code}")) if isinstance(resp, dict) else str(resp)
        output.print_error(f"Failed to stop '{service}': {err}")
        return 1

    if as_json or getattr(args, "json", False):
        output.print_json(resp)
    else:
        output.print_success(f"Service '{output.cyan(service)}' stopped successfully.")
    return 0


def cmd_services_restart(client: NexusClient, args, as_json: bool = False) -> int:
    service = getattr(args, "service_name", None)
    if not service:
        output.print_error("Service name is required.")
        return 1

    cmd_services_stop(client, args, as_json=as_json)
    return cmd_services_start(client, args, as_json=as_json)
