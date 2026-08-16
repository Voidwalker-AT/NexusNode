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

    if status_code != 200 or not isinstance(resp, dict):
        output.print_error(f"Failed to fetch tasks (HTTP {status_code})")
        return 1

    if as_json or getattr(args, "json", False):
        output.print_json(resp)
        return 0

    tasks = resp.get("tasks", [])
    if not tasks:
        print("\nNo background tasks found.\n")
        return 0

    headers = ["TASK ID", "TYPE", "OWNER", "STATE", "PROGRESS", "ERROR/RESULT"]
    rows = []
    for t in tasks:
        prog = f"{t.get('progress', 0):.0f}%" if t.get('progress') is not None else "N/A"
        err_or_res = t.get("error") or t.get("result_summary") or "-"
        rows.append([
            t.get("task_id", "")[:12],
            t.get("type", "generic").upper(),
            t.get("user_id", "admin"),
            t.get("state", "UNKNOWN").upper(),
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
        status_code, resp = client.get("/api/tasks")
    except NexusConnectionError as e:
        output.print_error(str(e))
        return 1

    if status_code != 200 or not isinstance(resp, dict):
        output.print_error(f"Failed to fetch tasks (HTTP {status_code})")
        return 1

    tasks = resp.get("tasks", [])
    target = next((t for t in tasks if t.get("task_id") == task_id or t.get("task_id", "").startswith(task_id)), None)

    if not target:
        output.print_error(f"Task '{task_id}' not found or access denied.")
        return 1

    if as_json or getattr(args, "json", False):
        output.print_json(target)
        return 0

    print(f"\n--- TASK STATUS: {target.get('task_id')} ---")
    print(f"  Type:        {target.get('type')}")
    print(f"  Owner:       {target.get('user_id')}")
    print(f"  State:       {target.get('state', 'UNKNOWN').upper()}")
    print(f"  Progress:    {target.get('progress', 0):.1f}%")
    print(f"  Description: {target.get('description', 'N/A')}")
    print(f"  Created At:  {output.format_timestamp(target.get('created_at'))}")
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
