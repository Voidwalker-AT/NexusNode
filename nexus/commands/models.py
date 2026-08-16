"""
NexusNode CLI — Authoritative Model Registry & Memory Budget Command (Admin)
Communicates with /api/ai/models, /api/ai/models/<model_name>, and /api/models/estimate.
"""

from .. import output
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
    if status_code != 200 or not isinstance(resp, dict):
        output.print_error(f"Failed to list models (HTTP {status_code})")
        return 1

    if as_json or getattr(args, "json", False):
        output.print_json(resp)
        return 0

    models = resp.get("models", [])
    if not models:
        print("\nNo models found.\n")
        return 0

    headers = ["NAME", "SIZE", "FAMILY", "PARAMS", "QUANT", "COMPATIBILITY"]
    rows = []
    for m in models:
        compat = "PASS" if m.get("budget_status", {}).get("allowed", True) else "WARN/OOM"
        rows.append([
            m.get("name", "N/A"),
            output.format_bytes(m.get("size_bytes", 0)),
            m.get("family", "N/A"),
            m.get("parameter_size", "N/A"),
            m.get("quantization_level", "N/A"),
            compat
        ])

    print(f"\n--- AUTHORITATIVE MODEL REGISTRY ({len(models)} models) ---")
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
        output.print_error(f"Failed to fetch model details (HTTP {status_code})")
        return 1

    if as_json or getattr(args, "json", False):
        output.print_json(resp)
        return 0

    print(f"\n--- MODEL SPECIFICATION: {resp.get('name')} ---")
    print(f"  Family:          {resp.get('family')}")
    print(f"  Parameter Size:  {resp.get('parameter_size')}")
    print(f"  Quantization:    {resp.get('quantization_level')}")
    print(f"  Size on Disk:    {output.format_bytes(resp.get('size_bytes', 0))}")
    print(f"  RAM Budget Est:  {output.format_bytes(resp.get('estimated_ram_bytes', 0))}")
    print(f"  Modified:        {output.format_timestamp(resp.get('modified_at'))}\n")
    return 0


def cmd_models_estimate(client: NexusClient, args, as_json: bool = False) -> int:
    name = getattr(args, "model_name", None) or "custom-model"
    param = getattr(args, "param", "1.5b")
    quant = getattr(args, "quant", "q4_k_m")

    payload = {
        "model": name,
        "parameter_size": param,
        "quantization": quant
    }

    try:
        status_code, resp = client.post("/api/models/estimate", data=payload)
    except NexusConnectionError as e:
        output.print_error(str(e))
        return 1

    if status_code != 200 or not isinstance(resp, dict):
        output.print_error(f"Estimation failed (HTTP {status_code})")
        return 1

    if as_json or getattr(args, "json", False):
        output.print_json(resp)
        return 0

    print(f"\n--- MEMORY BUDGET ESTIMATION: {name} ---")
    print(f"  Parameters:          {param}")
    print(f"  Quantization:        {quant}")
    print(f"  Estimated Model RAM: {output.format_bytes(resp.get('estimated_model_bytes', 0))}")
    print(f"  KV Cache Est:        {output.format_bytes(resp.get('estimated_kv_cache_bytes', 0))}")
    print(f"  Total Memory Needed: {output.format_bytes(resp.get('estimated_total_bytes', 0))}")
    print(f"  Hardware Safe?:      {'YES' if resp.get('budget_status', {}).get('allowed', True) else 'NO (High OOM Risk)'}\n")
    return 0
