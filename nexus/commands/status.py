"""
NexusNode CLI — Appliance & Resource Status Command
Queries /api/system/status to display health, resource governor metrics, and service states.
"""

from .. import output
from .. import normalize
from ..client import NexusClient, NexusConnectionError


def cmd_status(client: NexusClient, args, as_json: bool = False) -> int:
    """Executes 'nexus status'."""
    try:
        status_code, resp = client.get("/api/system/status")
    except NexusConnectionError as e:
        output.print_error(str(e))
        return 1

    if status_code != 200 or not isinstance(resp, dict):
        err = resp.get("message", resp.get("error", f"HTTP {status_code}")) if isinstance(resp, dict) else str(resp)
        output.print_error(f"Failed to fetch system status ({err})")
        return 1

    if as_json or getattr(args, "json", False):
        output.print_json(resp)
        return 0

    norm = normalize.normalize_system_status(resp)
    appliance = norm.get("appliance", {})
    memory = norm.get("memory", {})
    disk = norm.get("disk", {})
    battery = norm.get("battery", {})
    thermal = norm.get("thermal", {})
    services = norm.get("services", {})
    tasks = norm.get("tasks", {})
    process = norm.get("process", {})
    cpu = norm.get("cpu", {})

    print("\n" + "=" * 60)
    print("NEXUSNODE APPLIANCE STATUS")
    print("=" * 60)
    print(f"  Appliance State:     {appliance.get('state', 'NORMAL')}")

    # CPU
    cpu_pct = cpu.get("percent")
    if cpu_pct is not None:
        print(f"  CPU Usage:           {cpu_pct:.1f}%")
    else:
        print(f"  CPU Usage:           UNAVAILABLE")

    # Thermal & Battery
    temp_c = thermal.get("temp_c")
    therm_stat = thermal.get("status", appliance.get("state", "NORMAL"))
    if temp_c is not None:
        print(f"  Thermal State:       {therm_stat} ({temp_c:.1f} °C)")
    else:
        print(f"  Thermal State:       {therm_stat} (UNAVAILABLE)")

    bat_lvl = battery.get("level")
    bat_stat = battery.get("status", "STANDBY")
    if bat_lvl is not None:
        print(f"  Battery:             {bat_lvl}% ({bat_stat})")
    else:
        print(f"  Battery:             UNAVAILABLE ({bat_stat})")

    print("-" * 60)

    # Memory / RAM
    ram_used = memory.get("used_mb")
    ram_total = memory.get("total_mb")
    ram_pct = memory.get("ram_percent", memory.get("percent"))
    if ram_used is not None and ram_total is not None:
        pct_val = ram_pct if ram_pct is not None else ((ram_used / ram_total * 100) if ram_total else 0.0)
        tier_val = appliance.get("tier") or memory.get("ram_tier", "NORMAL")
        print(f"  RAM Usage:           {ram_used} MB / {ram_total} MB ({pct_val:.1f}%) [Tier: {tier_val}]")
    else:
        print(f"  RAM Usage:           UNAVAILABLE")

    # Process Memory
    rss_mb = process.get("rss_mb")
    threads = process.get("threads")
    if rss_mb is not None and threads is not None:
        print(f"  Process Memory:      {rss_mb} MB RSS | Threads: {threads}")
    elif rss_mb is not None:
        print(f"  Process Memory:      {rss_mb} MB RSS")
    else:
        print(f"  Process Memory:      UNAVAILABLE")

    print("-" * 60)

    # Vault Storage / Disk
    free_gb = disk.get("free_gb")
    total_gb = disk.get("total_gb")
    disk_pct = disk.get("percent")
    if free_gb is not None and total_gb is not None:
        pct_str = f" ({disk_pct:.1f}% used)" if disk_pct is not None else ""
        print(f"  Vault Storage:       {free_gb:.1f} GB free of {total_gb:.1f} GB{pct_str}")
    elif disk.get("free_bytes") is not None and disk.get("total_bytes") is not None:
        f_b = output.format_bytes(disk.get("free_bytes"))
        t_b = output.format_bytes(disk.get("total_bytes"))
        print(f"  Vault Storage:       {f_b} free of {t_b}")
    else:
        print(f"  Vault Storage:       UNAVAILABLE")

    # Services
    svcs_dict = normalize.normalize_services(services)
    if svcs_dict:
        online_count = sum(1 for s in svcs_dict.values() if s.get("running") or s.get("online") or s.get("status") in ["online", "running"])
        total_count = len(svcs_dict)
        print(f"  Services Online:     {online_count} / {total_count} services active")
    else:
        print(f"  Services Online:     UNAVAILABLE")

    # Active Tasks
    active_cnt = tasks.get("active_count")
    if active_cnt is None and "active_tasks" in tasks and isinstance(tasks["active_tasks"], list):
        active_cnt = len(tasks["active_tasks"])
    if active_cnt is not None:
        print(f"  Active Tasks:        {active_cnt} active")
    else:
        print(f"  Active Tasks:        UNAVAILABLE")

    print("=" * 60 + "\n")
    return 0
