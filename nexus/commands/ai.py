"""
NexusNode CLI — Authoritative Remote AI & LLM Inference Command
Communicates with /api/ai/models, /api/ai/state, /api/ai/models/select, and /chat/stream.
"""

import sys
import json

from .. import output
from .. import normalize
from ..client import NexusClient, NexusConnectionError


def cmd_ai(client: NexusClient, args, as_json: bool = False) -> int:
    """Dispatcher for 'nexus ai' subcommands."""
    subaction = getattr(args, "ai_action", None) or "state"

    if subaction == "models":
        return cmd_ai_models(client, args, as_json)
    elif subaction == "state":
        return cmd_ai_state(client, args, as_json)
    elif subaction == "select":
        return cmd_ai_select(client, args, as_json)
    elif subaction == "chat":
        return cmd_ai_chat(client, args, as_json)
    elif subaction == "metrics":
        return cmd_ai_metrics(client, args, as_json)
    else:
        output.print_error(f"Unknown AI subcommand '{subaction}'. Type 'nexus ai --help'.")
        return 1


def cmd_ai_models(client: NexusClient, args, as_json: bool = False) -> int:
    try:
        status_code, resp = client.get("/api/ai/models")
    except NexusConnectionError as e:
        output.print_error(str(e))
        return 1

    if status_code == 403:
        output.print_error("Permission denied: your account lacks 'can_use_ai' privilege.")
        return 1
    if status_code not in [200, 201, 202, 204]:
        err = resp.get("message", resp.get("error", f"HTTP {status_code}")) if isinstance(resp, dict) else str(resp)
        output.print_error(f"Failed to fetch AI models ({err})")
        return 1

    models = normalize.normalize_models(resp)

    if as_json or getattr(args, "json", False):
        output.print_json(resp if isinstance(resp, (list, dict)) else models)
        return 0

    if not models:
        print("\nNo AI models currently installed on the server.\n")
        return 0

    headers = ["MODEL NAME", "SIZE", "FAMILY", "PARAMETERS", "QUANTIZATION"]
    rows = []
    for m in models:
        rows.append([
            output.cyan(m.get("name", "N/A")),
            output.format_bytes(m.get("size_bytes", 0)) if m.get("size_bytes") is not None else "N/A",
            m.get("family", "N/A"),
            m.get("parameter_size", "N/A"),
            m.get("quantization_level", "N/A")
        ])

    print(f"\n" + output.magenta(f"--- INSTALLED AI MODELS ({len(models)} models) ---", bold=True))
    output.print_table(headers, rows)
    return 0


def cmd_ai_state(client: NexusClient, args, as_json: bool = False) -> int:
    try:
        status_code, resp = client.get("/api/ai/state")
    except NexusConnectionError as e:
        output.print_error(str(e))
        return 1

    if status_code == 403:
        output.print_error("Permission denied: your account lacks 'can_use_ai' privilege.")
        return 1
    if status_code != 200 or not isinstance(resp, dict):
        err = resp.get("message", resp.get("error", f"HTTP {status_code}")) if isinstance(resp, dict) else str(resp)
        output.print_error(f"Failed to fetch AI runtime state ({err})")
        return 1

    if as_json or getattr(args, "json", False):
        output.print_json(resp)
        return 0

    is_online = (resp.get("engine") == "running" or resp.get("service_online", False) or resp.get("online", False))
    vram_bytes = resp.get("size_vram_bytes") or resp.get("vram_bytes") or 0
    sel_mod = resp.get("selected_model")
    loaded_mod = resp.get("loaded_model")

    print("\n" + output.dim("=" * 55))
    print(output.magenta("NEXUSNODE AI RUNTIME STATE", bold=True))
    print(output.dim("=" * 55))
    print(f"  AI Engine Online:   {output.colorize_status('ONLINE' if is_online else 'OFFLINE')}")
    print(f"  Selected Model:     {output.cyan(sel_mod, bold=True) if sel_mod else output.dim('None')}")
    print(f"  Loaded Model:       {output.green(loaded_mod, bold=True) if loaded_mod else output.yellow('None (Idle in RAM)')}")
    print(f"  Keep-Alive TTL:     {resp.get('keep_alive', '5m')}")
    print(f"  Context Limit:      {resp.get('context_size', 2048)} tokens")
    print(f"  VRAM / RAM Usage:   {output.format_bytes(vram_bytes)}")
    print(output.dim("=" * 55) + "\n")
    return 0


def cmd_ai_select(client: NexusClient, args, as_json: bool = False) -> int:
    model_name = getattr(args, "model", None) or getattr(args, "model_or_prompt", None)
    if not model_name:
        output.print_error("Model name is required. Usage: nexus ai select <model>")
        return 1

    payload = {"model": model_name}
    try:
        status_code, resp = client.post("/api/ai/models/select", data=payload)
    except NexusConnectionError as e:
        output.print_error(str(e))
        return 1

    if status_code == 403:
        output.print_error("Permission denied: your account lacks model management privileges.")
        return 1
    if status_code != 200:
        err = resp.get("error", resp.get("message", f"HTTP {status_code}")) if isinstance(resp, dict) else str(resp)
        output.print_error(f"Failed to select model: {err}")
        return 1

    if as_json or getattr(args, "json", False):
        output.print_json(resp)
    else:
        output.print_success(f"Model '{output.cyan(model_name)}' selected successfully.")
    return 0


def cmd_ai_chat(client: NexusClient, args, as_json: bool = False) -> int:
    prompt = getattr(args, "prompt", None) or getattr(args, "model_or_prompt", None)
    model = getattr(args, "model", None)

    # If prompt not given via args, prompt interactively
    if not prompt:
        try:
            prompt = input("AI Prompt: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nCancelled.")
            return 0

    if not prompt:
        output.print_error("Prompt cannot be empty.")
        return 1

    payload = {
        "messages": [{"role": "user", "content": prompt}],
        "stream": True
    }
    if model:
        payload["model"] = model

    print("\n" + output.cyan("[AI Assistant]", bold=True) + " Generating response...\n")

    try:
        # Stream response via SSE chunks
        resp = client.session.post(
            f"{client.server_url}/chat/stream",
            json=payload,
            headers=client.get_headers(),
            stream=True,
            timeout=120
        )
        if resp.status_code == 403:
            output.print_error("Permission denied: your account lacks 'can_use_ai' privilege.")
            return 1
        if resp.status_code != 200:
            output.print_error(f"AI chat stream returned HTTP {resp.status_code}")
            return 1

        for line in resp.iter_lines():
            if line:
                decoded = line.decode("utf-8")
                if decoded.startswith("data: "):
                    chunk = decoded[6:]
                    if chunk == "[DONE]":
                        break
                    try:
                        data = json.loads(chunk)
                        token = data.get("delta") or data.get("message", {}).get("content", "")
                        if token:
                            sys.stdout.write(token)
                            sys.stdout.flush()
                    except Exception:
                        sys.stdout.write(chunk)
                        sys.stdout.flush()
        print("\n")
        return 0
    except Exception as e:
        output.print_error(f"Chat stream error: {e}")
        return 1


def cmd_ai_metrics(client: NexusClient, args, as_json: bool = False) -> int:
    try:
        status_code, resp = client.get("/api/ai/metrics")
    except NexusConnectionError as e:
        output.print_error(str(e))
        return 1

    if status_code == 403:
        output.print_error("Permission denied: your account lacks 'can_view_metrics' privilege.")
        return 1
    if status_code != 200 or not isinstance(resp, dict):
        err = resp.get("message", resp.get("error", f"HTTP {status_code}")) if isinstance(resp, dict) else str(resp)
        output.print_error(f"Failed to fetch AI metrics ({err})")
        return 1

    if as_json or getattr(args, "json", False):
        output.print_json(resp)
        return 0

    print("\n" + output.magenta("--- AI INFERENCE METRICS ---", bold=True))
    print(f"  Total Inferences:   {resp.get('total_inferences', 0)}")
    print(f"  Avg Prompt Speed:   {resp.get('avg_prompt_tokens_per_sec', 0):.1f} tok/s")
    print(f"  Avg Eval Speed:     {resp.get('avg_eval_tokens_per_sec', 0):.1f} tok/s")
    print(f"  Avg Latency:        {resp.get('avg_latency_ms', 0):.1f} ms\n")
    return 0
