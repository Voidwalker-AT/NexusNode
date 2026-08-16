"""
NexusNode CLI — Background Tasks & Ownership Command
Communicates with /api/tasks and /api/tasks/<id>/cancel endpoints.
"""

from .. import output
from ..client import NexusClient, NexusConnectionError


def cmd_tasks(client: NexusClient, args, as_json: bool = False) -> int:
    """Dispatcher for 'nexus tasks' commands."""
    subaction = getattr(args, "task_action", None) or "list"

    if subaction == "list" or subaction == "ls":
        return cmd_tasks_list(client, args, as_json)
    elif subaction == "status" or subaction == "info":
        return cmd_tasks_status(client, args, as_json)
    elif subaction == "cancel" or subaction == "kill":
        return cmd_tasks_cancel(client, args, as_json)
    else:
        output.print_error(f"Unknown task subcommand '{subaction}'. Type 'nexus tasks --help'.")
        return 1


def cmd_tasks_list(client: NexusClient, args, as_json: bool = False) -> int:
    try:
        status_code, resp = client.get("/api/tasks")
    except NexusConnectionError as e:
        output.print_error(str(e))
        return 1

    if status_code != 200 or not (isinstance(resp, (list, dict))):
        output.print_error(f"Failed to fetch tasks (HTTP {status_code})")
        return 1

    if as_json or getattr(args, "json", False):
        output.print_json(resp)
        return 0

    tasks = resp if isinstance(resp, list) else resp.get("tasks", [])
    if not tasks:
        print("\nNo background tasks found.\n")
        return 0

    headers = ["TASK ID", "TYPE", "OWNER", "STATUS", "PROGRESS", "ERROR/RESULT"]
    rows = []
    for t in tasks:
        prog = f"{t.get('progress', 0):.0f}%" if t.get('progress') is not None else "N/A"
        raw_status = (t.get("status") or t.get("state") or "UNKNOWN").upper()
        raw_stage = (t.get("stage") or "").upper()
        status_disp = f"{raw_status} ({raw_stage})" if raw_stage and raw_stage != raw_status else raw_status
        err_or_res = t.get("error") or t.get("result_summary") or t.get("output_path") or "-"
        rows.append([
            (t.get("id") or t.get("task_id", ""))[:14],
            (t.get("type") or t.get("task_type", "generic")).upper(),
            t.get("owner_user_id") or t.get("owner") or t.get("user_id", "admin"),
            status_disp,
            prog,
            str(err_or_res)[:28]
        ])

    print(f"\n--- BACKGROUND TASKS ({len(tasks)} items) ---")
    output.print_table(headers, rows)
    return 0


def cmd_tasks_status(client: NexusClient, args, as_json: bool = False) -> int:
    task_id = getattr(args, "task_id", None)
    if not task_id:
        output.print_error("Task ID is required.")
        return 1

    try:
        status_code, resp = client.get(f"/api/tasks/{task_id}")
        if status_code == 200 and isinstance(resp, dict) and "id" in resp:
            target = resp
        else:
            status_code, resp = client.get("/api/tasks")
            tasks = resp if isinstance(resp, list) else (resp.get("tasks", []) if isinstance(resp, dict) else [])
            target = next((t for t in tasks if str(t.get("id") or t.get("task_id")) == str(task_id) or str(t.get("id") or t.get("task_id", "")).startswith(str(task_id))), None)
    except NexusConnectionError as e:
        output.print_error(str(e))
        return 1

    if not target:
        output.print_error(f"Task '{task_id}' not found or access denied.")
        return 1

    if as_json or getattr(args, "json", False):
        output.print_json(target)
        return 0

    raw_id = target.get("id") or target.get("task_id")
    raw_status = (target.get("status") or target.get("state") or "UNKNOWN").upper()
    raw_stage = (target.get("stage") or "").upper()
    status_disp = f"{raw_status} ({raw_stage})" if raw_stage and raw_stage != raw_status else raw_status

    print(f"\n--- TASK STATUS: {raw_id} ---")
    print(f"  Title:       {target.get('title', 'N/A')}")
    print(f"  Type:        {target.get('type') or target.get('task_type')}")
    print(f"  Owner:       {target.get('owner_user_id') or target.get('owner') or target.get('user_id')}")
    print(f"  Status:      {status_disp}")
    print(f"  Progress:    {target.get('progress', 0):.0f}%")
    if target.get("speed_bps"):
        spd_mb = round(target["speed_bps"] / (1024 * 1024), 2)
        print(f"  Speed:       {spd_mb} MB/s")
    if target.get("eta_seconds"):
        print(f"  ETA:         {target['eta_seconds']}s")
    if target.get("output_path"):
        print(f"  Output Path: {target['output_path']}")
    print(f"  Created At:  {output.format_timestamp(target.get('created_at'))}")
    if target.get("started_at"):
        print(f"  Started At:  {output.format_timestamp(target.get('started_at'))}")
    if target.get("completed_at"):
        print(f"  Completed At:{output.format_timestamp(target.get('completed_at'))}")
    if target.get("error"):
        print(f"  Error:       {target.get('error')}")
    if target.get("result"):
        print(f"  Result:      {target.get('result')}")
    print()
    return 0


def cmd_tasks_cancel(client: NexusClient, args, as_json: bool = False) -> int:
    task_id = getattr(args, "task_id", None)
    if not task_id:
        output.print_error("Task ID is required to cancel.")
        return 1

    try:
        status_code, resp = client.post(f"/api/tasks/{task_id}/cancel")
    except NexusConnectionError as e:
        output.print_error(str(e))
        return 1

    if status_code == 403:
        output.print_error(f"Permission denied: you cannot cancel other users' tasks.")
        return 1
    elif status_code == 404:
        output.print_error(f"Task '{task_id}' not found.")
        return 1
    elif status_code != 200:
        err = resp.get("error", f"HTTP {status_code}") if isinstance(resp, dict) else str(resp)
        output.print_error(f"Failed to cancel task: {err}")
        return 1

    if as_json or getattr(args, "json", False):
        output.print_json(resp)
    else:
        output.print_success(f"Task '{task_id}' cancellation requested successfully.")
    return 0
