"""
NexusNode CLI — Background Tasks & Ownership Command
Communicates with /api/tasks and /api/tasks/<id>/cancel endpoints.
"""

from .. import output
from .. import normalize
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

    if status_code != 200:
        err = resp.get("message", resp.get("error", f"HTTP {status_code}")) if isinstance(resp, dict) else str(resp)
        output.print_error(f"Failed to fetch tasks ({err})")
        return 1

    if as_json or getattr(args, "json", False):
        output.print_json(resp)
        return 0

    tasks = normalize.normalize_tasks(resp)
    if not tasks:
        print("\nNo background tasks found.\n")
        return 0

    # Check for contradictions across tasks
    contradictions = [t for t in tasks if t.get("has_contradiction")]
    if contradictions:
        print()
        for c in contradictions:
            output.print_warning(f"Task '{c['task_id']}': backend returned STATUS={c['status']} with STAGE={c['stage']}")

    headers = ["TASK ID", "TYPE", "STATUS", "STAGE", "PROGRESS", "SPEED", "ETA", "CREATED", "ERROR"]
    rows = []
    for t in tasks:
        prog = f"{t['progress']:.0f}%" if t.get("progress") is not None else "--"
        speed_str = f"{round(t['speed_bps'] / (1024 * 1024), 1)} MB/s" if t.get("speed_bps") else "--"
        eta_str = f"{t['eta_seconds']}s" if t.get("eta_seconds") is not None else "--"
        created_str = output.format_timestamp(t.get("created_at"))
        raw_err = str(t.get("error")) if t.get("error") else "--"
        err_str = output.red(raw_err[:30]) if t.get("error") else output.dim("--")

        status_col = output.colorize_status(t["status"])
        stage_col = output.colorize_status(t["stage"]) if t.get("stage") else output.dim("--")

        rows.append([
            output.cyan(t["task_id"][:16]),
            t["task_type"].upper(),
            status_col,
            stage_col,
            prog,
            speed_str,
            eta_str,
            created_str,
            err_str
        ])

    print(f"\n--- BACKGROUND TASKS ({len(tasks)} items) ---")
    output.print_table(headers, rows)
    return 0


def cmd_tasks_status(client: NexusClient, args, as_json: bool = False) -> int:
    task_id = getattr(args, "task_id", None)
    if not task_id:
        output.print_error("Task ID is required.")
        return 1

    target = None
    try:
        status_code, resp = client.get(f"/api/tasks/{task_id}")
        if status_code == 200 and isinstance(resp, dict) and ("id" in resp or "task_id" in resp):
            target = normalize.normalize_task(resp)
        else:
            status_code, resp = client.get("/api/tasks")
            tasks = normalize.normalize_tasks(resp)
            target = next((t for t in tasks if t["task_id"] == str(task_id) or t["task_id"].startswith(str(task_id))), None)
    except NexusConnectionError as e:
        output.print_error(str(e))
        return 1

    if not target:
        output.print_error(f"Task '{task_id}' not found or access denied.")
        return 1

    if as_json or getattr(args, "json", False):
        output.print_json(target.get("raw", target))
        return 0

    if target.get("has_contradiction"):
        output.print_warning(target.get("contradiction_warning"))

    status_col = output.colorize_status(target.get("status"))
    stage_col = output.colorize_status(target.get("stage")) if target.get("stage") else output.dim("--")

    print(f"\n" + output.cyan(f"--- TASK STATUS: {target['task_id']} ---", bold=True))
    print(f"  Title:        {target.get('title', 'N/A')}")
    print(f"  Type:         {target.get('task_type')}")
    print(f"  Owner:        {target.get('owner')}")
    print(f"  Status:       {status_col}")
    print(f"  Stage:        {stage_col}")
    prog_str = f"{target['progress']:.0f}%" if target.get("progress") is not None else "--"
    print(f"  Progress:     {prog_str}")
    if target.get("speed_bps"):
        spd_mb = round(target["speed_bps"] / (1024 * 1024), 2)
        print(f"  Speed:        {output.cyan(f'{spd_mb} MB/s')}")
    else:
        print(f"  Speed:        {output.dim('--')}")
    if target.get("eta_seconds"):
        eta_val = target["eta_seconds"]
        print(f"  ETA:          {output.yellow(f'{eta_val}s')}")
    else:
        print(f"  ETA:          {output.dim('--')}")
    if target.get("output_path"):
        print(f"  Output Path:  {output.green(str(target['output_path']))}")
    else:
        print(f"  Output Path:  {output.dim('--')}")
    print(f"  Created At:   {output.format_timestamp(target.get('created_at'))}")
    if target.get("started_at"):
        print(f"  Started At:   {output.format_timestamp(target.get('started_at'))}")
    if target.get("completed_at"):
        print(f"  Completed At: {output.format_timestamp(target.get('completed_at'))}")
    if target.get("error"):
        print(f"  Error:        {output.red(str(target.get('error')), bold=True)}")
    else:
        print(f"  Error:        {output.dim('--')}")
    if target.get("result"):
        print(f"  Result:       {target.get('result')}")
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
        err = resp.get("error", resp.get("message", f"HTTP {status_code}")) if isinstance(resp, dict) else str(resp)
        output.print_error(f"Failed to cancel task: {err}")
        return 1

    if as_json or getattr(args, "json", False):
        output.print_json(resp)
    else:
        output.print_success(f"Task '{output.cyan(task_id)}' cancellation requested successfully.")
    return 0
