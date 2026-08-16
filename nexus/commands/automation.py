"""
NexusNode CLI — Automation & Scheduled Maintenance Jobs Command (Admin Only)
Communicates with /api/automation/jobs, toggle, and run endpoints.
"""

from .. import output
from .. import normalize
from ..client import NexusClient, NexusConnectionError


def cmd_automation(client: NexusClient, args, as_json: bool = False) -> int:
    """Dispatcher for 'nexus automation' commands."""
    subaction = getattr(args, "auto_action", None) or "list"

    if subaction == "list" or subaction == "ls":
        return cmd_auto_list(client, args, as_json)
    elif subaction == "run":
        return cmd_auto_run(client, args, as_json)
    elif subaction == "toggle" or subaction == "enable" or subaction == "disable":
        return cmd_auto_toggle(client, args, as_json)
    else:
        output.print_error(f"Unknown automation subcommand '{subaction}'. Type 'nexus automation --help'.")
        return 1


def cmd_auto_list(client: NexusClient, args, as_json: bool = False) -> int:
    try:
        status_code, resp = client.get("/api/automation/jobs")
    except NexusConnectionError as e:
        output.print_error(str(e))
        return 1

    if status_code == 403:
        output.print_error("Permission denied: your account lacks 'can_manage_automation' privilege.")
        return 1
    if status_code != 200:
        err = resp.get("message", resp.get("error", f"HTTP {status_code}")) if isinstance(resp, dict) else str(resp)
        output.print_error(f"Failed to list automation jobs ({err})")
        return 1

    if as_json or getattr(args, "json", False):
        output.print_json(resp)
        return 0

    jobs = normalize.normalize_list(resp, "jobs")
    if not jobs:
        print("\nNo scheduled automation jobs configured.\n")
        return 0

    headers = ["JOB ID", "DESCRIPTION / NAME", "SCHEDULE", "ENABLED", "LAST RUN"]
    rows = []
    for j in jobs:
        if not isinstance(j, dict):
            continue
        jid = str(j.get("id", "N/A"))
        jdesc = str(j.get("name") or j.get("description") or j.get("job_type", "N/A"))[:32]
        sched = str(j.get("schedule") or j.get("interval_or_cron") or f"Every {j.get('interval_seconds', 60)}s")
        is_enabled = bool(j.get("enabled"))
        last_run = output.format_timestamp(j.get("last_run") or j.get("last_run_at"))

        rows.append([
            jid,
            jdesc,
            sched,
            "YES" if is_enabled else "NO",
            last_run
        ])

    print(f"\n--- SCHEDULED AUTOMATION JOBS ({len(jobs)} jobs) ---")
    output.print_table(headers, rows)
    return 0


def cmd_auto_run(client: NexusClient, args, as_json: bool = False) -> int:
    job_id = getattr(args, "job_id", None)
    if not job_id:
        output.print_error("Job ID is required to run.")
        return 1

    try:
        status_code, resp = client.post(f"/api/automation/jobs/{job_id}/run")
    except NexusConnectionError as e:
        output.print_error(str(e))
        return 1

    if status_code == 403:
        output.print_error("Permission denied.")
        return 1
    if status_code not in [200, 201, 202]:
        err = resp.get("message", resp.get("error", f"HTTP {status_code}")) if isinstance(resp, dict) else str(resp)
        output.print_error(f"Failed to run job: {err}")
        return 1

    if as_json or getattr(args, "json", False):
        output.print_json(resp)
    else:
        output.print_success(f"Job '{job_id}' executed successfully on server.")
    return 0


def cmd_auto_toggle(client: NexusClient, args, as_json: bool = False) -> int:
    job_id = getattr(args, "job_id", None)
    if not job_id:
        output.print_error("Job ID is required to toggle.")
        return 1

    try:
        status_code, resp = client.post(f"/api/automation/jobs/{job_id}/toggle")
    except NexusConnectionError as e:
        output.print_error(str(e))
        return 1

    if status_code == 403:
        output.print_error("Permission denied.")
        return 1
    if status_code not in [200, 201, 202]:
        err = resp.get("message", resp.get("error", f"HTTP {status_code}")) if isinstance(resp, dict) else str(resp)
        output.print_error(f"Failed to toggle job: {err}")
        return 1

    if as_json or getattr(args, "json", False):
        output.print_json(resp)
    else:
        output.print_success(f"Job '{job_id}' state updated successfully.")
    return 0
