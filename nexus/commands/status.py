"""
NexusNode CLI — Appliance & Resource Status Command
Queries /api/system/status to display health, resource governor metrics, and service states.
"""

from .. import output
from ..client import NexusClient, NexusConnectionError


def cmd_status(client: NexusClient, args, as_json: bool = False) -> int:
    """Executes 'nexus status'."""
    try:
        status_code, resp = client.get("/api/system/status")
    except NexusConnectionError as e:
        output.print_error(str(e))
        return 1

    if status_code != 200:
        output.print_error(f"Failed to fetch system status (HTTP {status_code})")
        return 1

    if as_json or getattr(args, "json", False):
        output.print_json(resp)
        return 0

    appliance = resp.get("appliance", {})
    ram = resp.get("ram", {})
    thermal = resp.get("thermal", {})
    storage = resp.get("storage", {})
    services = resp.get("services", {})
    process = resp.get("process", {})

    print("\n" + "=" * 60)
    print("NEXUSNODE APPLIANCE STATUS")
    print("=" * 60)
    print(f"  Appliance State:     {appliance.get('state', 'UNKNOWN')}")
    print(f"  CPU Load (1m/5m/15m):{thermal.get('cpu_load_1m', '0.0')} / {thermal.get('cpu_load_5m', '0.0')} / {thermal.get('cpu_load_15m', '0.0')}")
    print(f"  Thermal State:       {thermal.get('thermal_status', 'NORMAL')} (Headroom: {thermal.get('thermal_headroom', 'NORMAL')})")
    print(f"  Battery:             {thermal.get('battery_level', 0)}% ({'Charging' if thermal.get('battery_charging') else 'Discharging'}) | Temp: {thermal.get('battery_temp_c', 0.0):.1f} C")
    print("-" * 60)
    ram_used = ram.get("used_mb", 0)
    ram_total = ram.get("total_mb", 1)
    ram_pct = (ram_used / ram_total * 100) if ram_total else 0
    print(f"  RAM Usage:           {ram_used} MB / {ram_total} MB ({ram_pct:.1f}%) [Tier: {ram.get('ram_tier', 'NORMAL')}]")
    print(f"  Process Memory:      {process.get('rss_mb', 0)} MB RSS | Threads: {process.get('threads', 0)}")
    print("-" * 60)
    vault_free = output.format_bytes(storage.get("free_bytes", 0))
    vault_total = output.format_bytes(storage.get("total_bytes", 0))
    print(f"  Vault Storage:       {vault_free} free of {vault_total} ({storage.get('percent_used', 0):.1f}% used)")
    print(f"  Vault Total Files:   {storage.get('vault_files_count', 0)}")
    print("-" * 60)
    print(f"  Services Online:     {services.get('online_count', 0)} / {services.get('total_count', 0)} services active")
    print(f"  Active Tasks:        {resp.get('tasks', {}).get('running_tasks_count', 0)} running, {resp.get('tasks', {}).get('queued_tasks_count', 0)} queued")
    print("=" * 60 + "\n")
    return 0
