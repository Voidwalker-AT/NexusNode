"""
NexusNode CLI — Authoritative Technical Diagnostics & Automated Root-Cause Engine (Admin)
Communicates with /api/admin/diagnostics/* and /api/network/test endpoints.
"""

from .. import output
from .. import normalize
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
        err = resp.get("message", resp.get("error", f"HTTP {status_code}")) if isinstance(resp, dict) else str(resp)
        output.print_error(f"Failed to fetch diagnostics ({err})")
        return 1

    if as_json or getattr(args, "json", False):
        output.print_json(resp)
        return 0

    dev = resp.get("device", {})
    proc = resp.get("nexusnode_process", resp.get("process", {}))
    mem = resp.get("memory", {})
    disk = resp.get("disk", {})
    dev_telem = resp.get("device_telemetry", resp.get("hardware", {}))
    health = resp.get("health", {})

    print("\n" + "=" * 65)
    print("NEXUSNODE TECHNICAL SYSTEM DIAGNOSTICS")
    print("=" * 65)
    print(f"  Device / OS:         {dev.get('model', 'Android Appliance')} ({dev.get('android_version', 'Android 13')})")
    print(f"  Overall Health:      {health.get('status', 'HEALTHY').upper()}")
    print("-" * 65)
    print("HARDWARE & OS:")

    ram_used = mem.get("used_mb")
    ram_total = mem.get("total_mb")
    if ram_used is not None and ram_total is not None:
        print(f"  RAM Used / Total:    {ram_used} MB / {ram_total} MB ({mem.get('ram_percent', 0):.1f}%)")
    elif mem.get("ram_total_bytes"):
        print(f"  RAM Total / Free:    {output.format_bytes(mem.get('ram_total_bytes'))} / {output.format_bytes(mem.get('ram_available_bytes', 0))}")
    else:
        print(f"  RAM Used / Total:    UNAVAILABLE")

    swap_used = mem.get("swap_used_mb")
    swap_total = mem.get("swap_total_mb")
    if swap_used is not None and swap_total is not None:
        print(f"  Swap Used / Total:   {swap_used} MB / {swap_total} MB")
    else:
        print(f"  Swap Used / Total:   UNAVAILABLE")

    cores = dev_telem.get("cpu_cores", 8)
    l1 = dev_telem.get("load_avg_1m", "0.0")
    l5 = dev_telem.get("load_avg_5m", "0.0")
    print(f"  CPU Cores / Load:    {cores} cores | 1m: {l1}, 5m: {l5}")

    cpu_temp = dev_telem.get("cpu_temperature_c")
    bat_pct = dev_telem.get("battery_percent", dev_telem.get("battery_pct"))
    bat_temp = dev_telem.get("battery_temp_c")
    temp_str = f"{cpu_temp:.1f} °C" if cpu_temp is not None else "UNAVAILABLE"
    bat_str = f"{bat_pct}%" if bat_pct is not None else "UNAVAILABLE"
    if bat_temp is not None:
        bat_str += f" ({bat_temp:.1f} °C)"
    print(f"  Thermal State:       {temp_str} | Battery: {bat_str}")

    print("-" * 65)
    print("PROCESS & RUNTIME:")
    print(f"  Process PID:         {proc.get('pid', '-')}")
    rss_mb = proc.get("rss_mb")
    vms_mb = proc.get("vms_mb")
    if rss_mb is not None:
        vms_str = f" / {vms_mb} MB VMS" if vms_mb is not None else ""
        print(f"  Memory (RSS/VMS):    {rss_mb} MB RSS{vms_str}")
    elif proc.get("rss_bytes"):
        print(f"  Memory (RSS/VMS):    {output.format_bytes(proc.get('rss_bytes'))} / {output.format_bytes(proc.get('vms_bytes', 0))}")
    else:
        print(f"  Memory (RSS/VMS):    UNAVAILABLE")

    threads = proc.get("threads", proc.get("threads_count"))
    print(f"  Active Threads:      {threads if threads is not None else 'UNAVAILABLE'}")
    open_files = proc.get("open_files", proc.get("open_files_count"))
    if open_files is not None:
        print(f"  Open File Handles:   {open_files}")
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
        err = resp.get("message", resp.get("error", f"HTTP {status_code}")) if isinstance(resp, dict) else str(resp)
        output.print_error(f"Failed to generate full diagnostic report ({err})")
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
        print(f"\nDETECTED ISSUES ({len(issues)}):")
        for i, iss in enumerate(issues, 1):
            sev = iss.get("severity", "WARN").upper()
            comp = iss.get("component", "SYSTEM")
            desc = iss.get("description", "")
            print(f"  [{sev}] ({comp}) {desc}")

    if recommendations:
        print("\nACTIONABLE RECOMMENDATIONS:")
        for r in recommendations:
            print(f"  • {r}")
    print("=" * 70 + "\n")
    return 0


def cmd_diag_profile(client: NexusClient, args, as_json: bool = False) -> int:
    print("Capturing runtime performance profile snapshot...")
    try:
        status_code, resp = client.post("/api/admin/diagnostics/profile-snapshot")
    except NexusConnectionError as e:
        output.print_error(str(e))
        return 1

    if status_code == 403:
        output.print_error("Permission denied.")
        return 1
    if status_code not in [200, 201]:
        err = resp.get("message", resp.get("error", f"HTTP {status_code}")) if isinstance(resp, dict) else str(resp)
        output.print_error(f"Snapshot capture failed ({err})")
        return 1

    if as_json or getattr(args, "json", False):
        output.print_json(resp)
        return 0

    output.print_success("Performance profile snapshot captured successfully.")
    print(f"  Snapshot ID: {resp.get('snapshot_id')}")
    print(f"  Saved Path:  {resp.get('path', 'diagnostics/')}\n")
    return 0


def cmd_diag_network(client: NexusClient, args, as_json: bool = False) -> int:
    print("Executing network interface & connectivity probe...")
    try:
        status_code, resp = client.get("/api/network/test")
    except NexusConnectionError as e:
        output.print_error(str(e))
        return 1

    if status_code != 200 or not isinstance(resp, dict):
        err = resp.get("message", resp.get("error", f"HTTP {status_code}")) if isinstance(resp, dict) else str(resp)
        output.print_error(f"Network probe failed ({err})")
        return 1

    if as_json or getattr(args, "json", False):
        output.print_json(resp)
        return 0

    print("\n--- NETWORK CONNECTIVITY PROBE ---")
    print(f"  Gateway Reached:     {'YES' if resp.get('gateway_reachable', True) else 'NO'}")
    print(f"  DNS Resolution:      {'YES' if resp.get('dns_working', True) else 'NO'}")
    print(f"  Public IP / Mode:    {resp.get('public_ip', 'LAN / Tunnel')}")
    print(f"  WAN Latency:         {resp.get('ping_ms', '--')} ms\n")
    return 0
