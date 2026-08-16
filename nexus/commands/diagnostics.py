"""
NexusNode CLI — Authoritative Technical Diagnostics & Automated Root-Cause Engine (Admin)
Communicates with /api/admin/diagnostics/* and /api/network/test endpoints.
"""

from .. import output
from ..client import NexusClient, NexusConnectionError


def cmd_diagnostics(client: NexusClient, args, as_json: bool = False) -> int:
    """Dispatcher for 'nexus diagnostics' subcommands."""
    subaction = getattr(args, "diag_action", None) or "system"

    if subaction == "system":
        return cmd_diag_system(client, args, as_json)
    elif subaction == "full" or subaction == "full-report":
        return cmd_diag_full(client, args, as_json)
    elif subaction == "profile":
        return cmd_diag_profile(client, args, as_json)
    elif subaction == "network":
        return cmd_diag_network(client, args, as_json)
    else:
        output.print_error(f"Unknown diagnostics subcommand '{subaction}'. Type 'nexus diagnostics --help'.")
        return 1


def cmd_diag_system(client: NexusClient, args, as_json: bool = False) -> int:
    try:
        status_code, resp = client.get("/api/admin/diagnostics/system")
    except NexusConnectionError as e:
        output.print_error(str(e))
        return 1

    if status_code == 403:
        output.print_error("Permission denied: your account lacks administrative diagnostics privileges.")
        return 1
    if status_code != 200 or not isinstance(resp, dict):
        output.print_error(f"Failed to fetch diagnostics (HTTP {status_code})")
        return 1

    if as_json or getattr(args, "json", False):
        output.print_json(resp)
        return 0

    hw = resp.get("hardware", {})
    proc = resp.get("process", {})
    health = resp.get("health", {})

    print("\n" + "=" * 65)
    print("NEXUSNODE TECHNICAL SYSTEM DIAGNOSTICS")
    print("=" * 65)
    print(f"  Appliance Uptime:    {output.format_duration(resp.get('uptime_seconds', 0))}")
    print(f"  Overall Health:      {health.get('status', 'HEALTHY').upper()}")
    print("-" * 65)
    print("HARDWARE & OS:")
    print(f"  RAM Total / Free:    {output.format_bytes(hw.get('ram_total_bytes', 0))} / {output.format_bytes(hw.get('ram_available_bytes', 0))}")
    print(f"  Swap Total / Free:   {output.format_bytes(hw.get('swap_total_bytes', 0))} / {output.format_bytes(hw.get('swap_free_bytes', 0))}")
    print(f"  CPU Cores / Load:    {hw.get('cpu_cores', 8)} cores | 1m: {hw.get('load_avg_1m', '0.0')}, 5m: {hw.get('load_avg_5m', '0.0')}")
    print(f"  Thermal State:       {hw.get('thermal_status', 'NORMAL')} | Battery: {hw.get('battery_pct', 100)}% ({hw.get('battery_temp_c', 0.0):.1f} C)")
    print("-" * 65)
    print("PROCESS & RUNTIME:")
    print(f"  Process PID:         {proc.get('pid', '-')}")
    print(f"  Memory (RSS/VMS):    {output.format_bytes(proc.get('rss_bytes', 0))} / {output.format_bytes(proc.get('vms_bytes', 0))}")
    print(f"  Active Threads:      {proc.get('threads_count', 0)}")
    print(f"  Open File Handles:   {proc.get('open_files_count', 0)}")
    print("=" * 65 + "\n")
    return 0


def cmd_diag_full(client: NexusClient, args, as_json: bool = False) -> int:
    print("Generating comprehensive diagnostic report & root-cause analysis...")
    try:
        status_code, resp = client.get("/api/admin/diagnostics/full-report")
    except NexusConnectionError as e:
        output.print_error(str(e))
        return 1

    if status_code == 403:
        output.print_error("Permission denied: your account lacks administrative diagnostics privileges.")
        return 1
    if status_code != 200 or not isinstance(resp, dict):
        output.print_error(f"Failed to generate full diagnostic report (HTTP {status_code})")
        return 1

    if as_json or getattr(args, "json", False):
        output.print_json(resp)
        return 0

    issues = resp.get("issues", [])
    recommendations = resp.get("recommendations", [])

    print("\n" + "=" * 70)
    print("AUTOMATED ROOT-CAUSE & HEALTH ANALYSIS REPORT")
    print("=" * 70)
    print(f"  Timestamp:           {output.format_timestamp(resp.get('timestamp'))}")
    print(f"  Overall Condition:   {resp.get('condition', 'STABLE').upper()}")
    print("-" * 70)

    if not issues:
        print("\n[+] No critical issues or warnings detected across system components.\n")
    else:
        print(f"\nDETECTED ISSUES ({len(issues)} findings):")
        for idx, iss in enumerate(issues, 1):
            sev = iss.get("severity", "INFO").upper()
            print(f"\n  [{idx}] [{sev}] {iss.get('problem')}")
            print(f"      Evidence:       {iss.get('evidence')}")
            print(f"      Likely Cause:   {iss.get('likely_cause')}")
            print(f"      Recommendation: {iss.get('recommendation')}")

    if recommendations:
        print("\nRECOMMENDED ACTIONS:")
        for r in recommendations:
            print(f"  - {r}")
    print("\n" + "=" * 70 + "\n")
    return 0


def cmd_diag_profile(client: NexusClient, args, as_json: bool = False) -> int:
    try:
        status_code, resp = client.post("/api/admin/diagnostics/profile-snapshot")
    except NexusConnectionError as e:
        output.print_error(str(e))
        return 1

    if status_code == 200 and isinstance(resp, dict):
        if as_json or getattr(args, "json", False):
            output.print_json(resp)
        else:
            output.print_success("Diagnostics profile snapshot captured on server.")
            print(f"  Snapshot ID: {resp.get('snapshot_id')}")
            print(f"  RSS:         {output.format_bytes(resp.get('rss_bytes', 0))}")
            print(f"  Threads:     {resp.get('threads', 0)}\n")
        return 0
    else:
        err = resp.get("error", f"HTTP {status_code}") if isinstance(resp, dict) else str(resp)
        output.print_error(f"Snapshot capture failed: {err}")
        return 1


def cmd_diag_network(client: NexusClient, args, as_json: bool = False) -> int:
    target = getattr(args, "target", "internet") or "internet"
    try:
        status_code, resp = client.post("/api/network/test", data={"target": target})
    except NexusConnectionError as e:
        output.print_error(str(e))
        return 1

    if status_code == 200 and isinstance(resp, dict):
        if as_json or getattr(args, "json", False):
            output.print_json(resp)
        else:
            lat = f"{resp.get('latency_ms', 0):.1f} ms" if resp.get("latency_ms") is not None else "N/A"
            stat = resp.get("status", "UNKNOWN").upper()
            output.print_success(f"Network probe to '{target}': Status={stat}, Latency={lat}")
        return 0
    else:
        output.print_error(f"Network probe failed (HTTP {status_code})")
        return 1
