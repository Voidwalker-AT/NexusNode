"""
NexusNode CLI — Authoritative Remote AI & LLM Inference Command
Communicates with /api/ai/models, /api/ai/state, /api/ai/models/select, and /chat/stream.
"""

import sys
import json

from .. import output
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
    if status_code != 200 or not isinstance(resp, dict):
        output.print_error(f"Failed to fetch AI models (HTTP {status_code})")
        return 1

    if as_json or getattr(args, "json", False):
        output.print_json(resp)
        return 0

    models = resp.get("models", [])
    if not models:
        print("\nNo AI models currently installed on the server.\n")
        return 0

    headers = ["MODEL NAME", "SIZE", "FAMILY", "PARAMETERS", "QUANTIZATION"]
    rows = []
    for m in models:
        rows.append([
            m.get("name", "N/A"),
            output.format_bytes(m.get("size_bytes", 0)),
            m.get("family", "N/A"),
            m.get("parameter_size", "N/A"),
            m.get("quantization_level", "N/A")
        ])

    print(f"\n--- INSTALLED AI MODELS ({len(models)} models) ---")
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
        output.print_error(f"Failed to fetch AI runtime state (HTTP {status_code})")
        return 1

    if as_json or getattr(args, "json", False):
        output.print_json(resp)
        return 0

    is_online = (resp.get("engine") == "running" or resp.get("service_online", False))
    print("\n" + "=" * 55)
    print("NEXUSNODE AI RUNTIME STATE")
    print("=" * 55)
    print(f"  AI Engine Online:   {'YES' if is_online else 'NO'}")
    print(f"  Selected Model:     {resp.get('selected_model') or 'None'}")
    print(f"  Loaded Model:       {resp.get('loaded_model') or 'None (Idle in RAM)'}")
    print(f"  Keep-Alive TTL:     {resp.get('keep_alive', '5m')}")
    print(f"  Context Limit:      {resp.get('context_size', 2048)} tokens")
    print(f"  VRAM / RAM Usage:   {output.format_bytes(resp.get('size_vram_bytes', 0))}")
    print("=" * 55 + "\n")
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
        err = resp.get("error", f"HTTP {status_code}") if isinstance(resp, dict) else str(resp)
        output.print_error(f"Failed to select model: {err}")
        return 1

    if as_json or getattr(args, "json", False):
        output.print_json(resp)
    else:
        output.print_success(f"Model '{model_name}' selected successfully.")
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

    print("\n[AI Assistant] Generating response...\n")
    accumulated = []

    def handle_chunk(chunk_line: str):
        # Line can be SSE 'data: {...}' or raw JSON or text
        line = chunk_line.strip()
        if not line:
            return
        if line.startswith("data:"):
            line = line[5:].strip()
        if line == "[DONE]":
            return
        try:
            parsed = json.loads(line)
            # Ollama format
            token = parsed.get("message", {}).get("content") or parsed.get("response") or ""
            if token:
                sys.stdout.write(token)
                sys.stdout.flush()
                accumulated.append(token)
        except Exception:
            # Raw string chunk
            sys.stdout.write(line)
            sys.stdout.flush()
            accumulated.append(line)

    try:
        client.stream_post("/chat/stream", data=payload, on_chunk=handle_chunk)
        print("\n")
        return 0
    except Exception as e:
        print(f"\n[!] AI Chat Error: {e}\n", file=sys.stderr)
        return 1


def cmd_ai_metrics(client: NexusClient, args, as_json: bool = False) -> int:
    try:
        status_code, resp = client.get("/api/ai/metrics")
    except NexusConnectionError as e:
        output.print_error(str(e))
        return 1

    if status_code != 200 or not isinstance(resp, dict):
        output.print_error(f"Failed to fetch AI metrics (HTTP {status_code})")
        return 1

    if as_json or getattr(args, "json", False):
        output.print_json(resp)
        return 0

    print("\n--- AI INFERENCE METRICS ---")
    print(f"  Total Inferences:    {resp.get('total_inferences', 0)}")
    print(f"  Avg Eval Rate:       {resp.get('avg_tokens_per_sec', 0.0):.1f} tokens/sec")
    print(f"  Avg Time-To-First:   {resp.get('avg_prompt_eval_duration_ms', 0.0):.1f} ms\n")
    return 0
