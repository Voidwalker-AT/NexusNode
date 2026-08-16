"""
NexusNode CLI — Safe Database Diagnostics & Read-Only Inspection Command (Admin Only)
Communicates with /api/admin/db/diagnostics and /api/admin/db/query endpoints.
"""

from .. import output
from .. import normalize
from ..client import NexusClient, NexusConnectionError


def cmd_database(client: NexusClient, args, as_json: bool = False) -> int:
    """Dispatcher for 'nexus database' commands."""
    subaction = getattr(args, "db_action", None) or "diagnostics"

    if subaction == "diagnostics" or subaction == "stats":
        return cmd_db_diagnostics(client, args, as_json)
    elif subaction == "query" or subaction == "inspect":
        return cmd_db_query(client, args, as_json)
    else:
        output.print_error(f"Unknown database subcommand '{subaction}'. Type 'nexus database --help'.")
        return 1


def cmd_db_diagnostics(client: NexusClient, args, as_json: bool = False) -> int:
    try:
        status_code, resp = client.get("/api/admin/db/diagnostics")
    except NexusConnectionError as e:
        output.print_error(str(e))
        return 1

    if status_code == 403:
        output.print_error("Permission denied: your account lacks database inspection privileges.")
        return 1
    if status_code != 200 or not isinstance(resp, dict):
        err = resp.get("message", resp.get("error", f"HTTP {status_code}")) if isinstance(resp, dict) else str(resp)
        output.print_error(f"Failed to fetch database diagnostics ({err})")
        return 1

    if as_json or getattr(args, "json", False):
        output.print_json(resp)
        return 0

    print("\n" + "=" * 55)
    print("NEXUSNODE SQLITE VAULT DATABASE DIAGNOSTICS")
    print("=" * 55)
    print(f"  DB File:        {resp.get('db_file', 'N/A')}")
    print(f"  DB Size:        {resp.get('db_size_kb', 0):.2f} KB")
    print(f"  WAL Size:       {resp.get('wal_size_kb', 0):.2f} KB")
    print(f"  SHM Size:       {resp.get('shm_size_kb', 0):.2f} KB")
    print("-" * 55)
    print("TABLE ROW COUNTS:")
    for tbl, count in sorted(resp.get("table_counts", {}).items()):
        print(f"  {tbl:<24}: {count} rows")
    print("=" * 55 + "\n")
    return 0


def cmd_db_query(client: NexusClient, args, as_json: bool = False) -> int:
    table = getattr(args, "table", "users") or "users"
    limit = getattr(args, "limit", 25) or 25

    try:
        status_code, resp = client.get("/api/admin/db/query", params={"table": table, "limit": limit})
    except NexusConnectionError as e:
        output.print_error(str(e))
        return 1

    if status_code == 403:
        output.print_error("Permission denied: your account lacks database query privileges.")
        return 1
    if status_code != 200 or not isinstance(resp, dict):
        err = resp.get("message", resp.get("error", f"HTTP {status_code}")) if isinstance(resp, dict) else str(resp)
        output.print_error(f"Database query failed ({err})")
        return 1

    if as_json or getattr(args, "json", False):
        output.print_json(resp)
        return 0

    rows = normalize.normalize_list(resp, "rows")
    if not rows:
        print(f"\nTable '{table}' has no records.\n")
        return 0

    headers = list(rows[0].keys())[:6]
    table_rows = []
    for r in rows:
        table_rows.append([str(r.get(h, ""))[:24] for h in headers])

    print(f"\n--- TABLE: {table.upper()} ({len(rows)} records shown) ---")
    output.print_table(headers, table_rows)
    return 0
