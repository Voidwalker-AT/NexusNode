"""
NexusNode CLI — Authoritative Model Registry & Memory Budget Command (Admin)
Communicates with /api/ai/models, /api/ai/models/<model_name>, and /api/models/estimate.
"""

from .. import output
from .. import normalize
from ..client import NexusClient, NexusConnectionError


def cmd_models(client: NexusClient, args, as_json: bool = False) -> int:
    """Dispatcher for 'nexus models' commands."""
    subaction = getattr(args, "model_action", None) or "list"

    if subaction == "list" or subaction == "ls":
        return cmd_models_list(client, args, as_json)
    elif subaction == "details" or subaction == "info":
        return cmd_models_details(client, args, as_json)
    elif subaction == "estimate":
        return cmd_models_estimate(client, args, as_json)
    else:
        output.print_error(f"Unknown models subcommand '{subaction}'. Type 'nexus models --help'.")
        return 1


def cmd_models_list(client: NexusClient, args, as_json: bool = False) -> int:
    try:
        status_code, resp = client.get("/api/ai/models")
    except NexusConnectionError as e:
        output.print_error(str(e))
        return 1

    if status_code == 403:
        output.print_error("Permission denied: your account lacks model management privileges.")
        return 1
    if status_code not in [200, 201, 202, 204]:
        err = resp.get("message", resp.get("error", f"HTTP {status_code}")) if isinstance(resp, dict) else str(resp)
        output.print_error(f"Failed to list models ({err})")
        return 1

    models = normalize.normalize_models(resp)

    if as_json or getattr(args, "json", False):
        output.print_json(resp if isinstance(resp, (list, dict)) else models)
        return 0

    if not models:
        print("\nNo models found.\n")
        return 0

    headers = ["NAME", "SIZE", "FAMILY", "PARAMS", "QUANT", "COMPATIBILITY"]
    rows = []
    for m in models:
        is_pass = m.get("budget_status", {}).get("allowed", True)
        compat = output.green("PASS", bold=True) if is_pass else output.yellow("WARN/OOM")
        rows.append([
            output.cyan(m.get("name", "N/A")),
            output.format_bytes(m.get("size_bytes", 0)) if m.get("size_bytes") is not None else "N/A",
            m.get("family", "N/A"),
            m.get("parameter_size", "N/A"),
            m.get("quantization_level", "N/A"),
            compat
        ])

    print(f"\n" + output.magenta(f"--- AUTHORITATIVE MODEL REGISTRY ({len(models)} models) ---", bold=True))
    output.print_table(headers, rows)
    return 0


def cmd_models_details(client: NexusClient, args, as_json: bool = False) -> int:
    name = getattr(args, "model_name", None)
    if not name:
        output.print_error("Model name is required.")
        return 1

    try:
        status_code, resp = client.get(f"/api/ai/models/{name}")
    except NexusConnectionError as e:
        output.print_error(str(e))
        return 1

    if status_code == 404:
        output.print_error(f"Model '{name}' not found in registry.")
        return 1
    if status_code != 200 or not isinstance(resp, dict):
        err = resp.get("message", resp.get("error", f"HTTP {status_code}")) if isinstance(resp, dict) else str(resp)
        output.print_error(f"Failed to fetch model details ({err})")
        return 1

    if as_json or getattr(args, "json", False):
        output.print_json(resp)
        return 0

    print(f"\n" + output.magenta(f"--- MODEL SPECIFICATION: {resp.get('name')} ---", bold=True))
    print(f"  Family:          {resp.get('family', 'N/A')}")
    print(f"  Parameter Size:  {resp.get('parameter_size', 'N/A')}")
    print(f"  Quantization:    {resp.get('quantization_level', 'N/A')}")
    print(f"  Size on Disk:    {output.format_bytes(resp.get('size_bytes', 0)) if resp.get('size_bytes') is not None else 'N/A'}")
    print(f"  RAM Budget Est:  {output.format_bytes(resp.get('estimated_ram_bytes', 0)) if resp.get('estimated_ram_bytes') is not None else 'N/A'}")
    print(f"  Modified:        {output.format_timestamp(resp.get('modified_at'))}\n")
    return 0


def cmd_models_estimate(client: NexusClient, args, as_json: bool = False) -> int:
    name = getattr(args, "model_name", None)
    ctx = getattr(args, "ctx", None)

    params = {}
    if name:
        params["model"] = name
    if ctx:
        params["ctx"] = ctx

    try:
        status_code, resp = client.get("/api/models/estimate", params=params)
    except NexusConnectionError as e:
        output.print_error(str(e))
        return 1

    if status_code != 200 or not isinstance(resp, dict):
        err = resp.get("message", resp.get("error", f"HTTP {status_code}")) if isinstance(resp, dict) else str(resp)
        output.print_error(f"Failed to estimate model memory budget ({err})")
        return 1

    if as_json or getattr(args, "json", False):
        output.print_json(resp)
        return 0

    is_allowed = resp.get("allowed", True)
    status_col = output.green("ALLOWED / PASS", bold=True) if is_allowed else output.red("BLOCKED / OOM RISK", bold=True)

    print("\n" + output.magenta("--- MODEL MEMORY BUDGET ESTIMATE ---", bold=True))
    print(f"  Target Model:       {output.cyan(resp.get('model', 'N/A'))}")
    print(f"  Context Size:       {resp.get('context_tokens', 2048)} tokens")
    print(f"  Estimated RAM:      {output.format_bytes(resp.get('estimated_ram_bytes', 0))}")
    print(f"  Available RAM:      {output.format_bytes(resp.get('available_ram_bytes', 0))}")
    print(f"  Governor Status:    {status_col}")
    if resp.get("reason"):
        print(f"  Governor Reason:    {resp.get('reason')}")
    print()
    return 0
