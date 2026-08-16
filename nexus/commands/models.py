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
        compat = "PASS" if m.get("budget_status", {}).get("allowed", True) else "WARN/OOM"
        rows.append([
            m.get("name", "N/A"),
            output.format_bytes(m.get("size_bytes", 0)) if m.get("size_bytes") is not None else "N/A",
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
        err = resp.get("message", resp.get("error", f"HTTP {status_code}")) if isinstance(resp, dict) else str(resp)
        output.print_error(f"Failed to fetch model details ({err})")
        return 1

    if as_json or getattr(args, "json", False):
        output.print_json(resp)
        return 0

    print(f"\n--- MODEL SPECIFICATION: {resp.get('name')} ---")
    print(f"  Family:          {resp.get('family', 'N/A')}")
    print(f"  Parameter Size:  {resp.get('parameter_size', 'N/A')}")
    print(f"  Quantization:    {resp.get('quantization_level', 'N/A')}")
    print(f"  Size on Disk:    {output.format_bytes(resp.get('size_bytes', 0)) if resp.get('size_bytes') is not None else 'N/A'}")
    print(f"  RAM Budget Est:  {output.format_bytes(resp.get('estimated_ram_bytes', 0)) if resp.get('estimated_ram_bytes') is not None else 'N/A'}")
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
        err = resp.get("message", resp.get("error", f"HTTP {status_code}")) if isinstance(resp, dict) else str(resp)
        output.print_error(f"Estimation failed ({err})")
        return 1

    if as_json or getattr(args, "json", False):
        output.print_json(resp)
        return 0

    est_model_bytes = resp.get("estimated_model_bytes") or (resp.get("model_size_mb", 0) * 1024 * 1024)
    est_total_bytes = resp.get("estimated_total_bytes") or (resp.get("total_ram_required_mb", 0) * 1024 * 1024)
    is_safe = resp.get("allowed", resp.get("budget_status", {}).get("allowed", True))

    print(f"\n--- MEMORY BUDGET ESTIMATION: {name} ---")
    print(f"  Parameters:          {param}")
    print(f"  Quantization:        {quant}")
    print(f"  Estimated Model RAM: {output.format_bytes(est_model_bytes)}")
    print(f"  Total Memory Needed: {output.format_bytes(est_total_bytes)}")
    print(f"  Hardware Safe?:      {'YES' if is_safe else 'NO (High OOM Risk)'}\n")
    return 0
