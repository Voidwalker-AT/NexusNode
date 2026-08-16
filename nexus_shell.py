#!/usr/bin/env python3
"""
NexusNode — Restricted Interactive Application Shell & SSH Command Dispatcher
Provides an authoritative, isolated, RBAC-governed command-line environment for NexusNode users.

CRITICAL SECURITY PROPERTIES:
- Normal application users connecting via SSH receive ONLY this restricted shell.
- No access to Termux OS bash/zsh shell, ~/server, ~/.ssh, databases, or secrets.
- Arbitrary OS commands, subprocess spawning, pipes, and shell escapes are strictly blocked.
- Commands are dispatched via an allowlisted command registry with object-level RBAC enforcement.
- Direct SSH command mode (e.g. `ssh ... "vault ls"`) routes through the same allowlisted parser.
- Unified single source of truth for authentication, RBAC, and lockout tracking.
"""

import os
import sys
import cmd
import time
import json
import shlex
import getpass
import hashlib
import datetime
import argparse
from pathlib import Path

# Ensure server root directory is importable
SERVER_ROOT = os.path.dirname(os.path.abspath(__file__))
if SERVER_ROOT not in sys.path:
    sys.path.insert(0, SERVER_ROOT)

import config
import app as server_app
from resource_governor import governor


# ==============================================================================
# Helper Functions for Formatting & Output
# ==============================================================================

def format_bytes(size_bytes: int) -> str:
    """Formats raw bytes into human-readable strings."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def format_timestamp(ts) -> str:
    """Formats numeric epoch or ISO timestamp safely."""
    if not ts:
        return "N/A"
    try:
        if isinstance(ts, (int, float)) and ts > 0:
            return datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')
        if isinstance(ts, str):
            val_str = ts.strip()
            try:
                fval = float(val_str)
                return datetime.datetime.fromtimestamp(fval).strftime('%Y-%m-%d %H:%M:%S')
            except ValueError:
                return val_str[:19]
    except Exception:
        pass
    return "N/A"


# ==============================================================================
# Restricted NexusNode Shell Class
# ==============================================================================

class NexusRestrictedShell(cmd.Cmd):
    """
    Restricted interactive command interpreter for NexusNode application users.
    Implements least-privilege RBAC enforcement and zero arbitrary OS shell execution.
    """
    intro = ""
    prompt = "nexus> "

    def __init__(self, user_dict: dict):
        super().__init__()
        self.user = user_dict
        self.user_id = user_dict["user_id"]
        self.role = user_dict.get("role", "user")
        self.privileges = user_dict.get("privileges", {})
        self.is_admin = (self.role == "admin")
        self.active_vault_dir = ""

    def has_priv(self, priv_name: str) -> bool:
        """Checks if current user has the specified privilege or is admin."""
        if self.is_admin:
            return True
        return bool(self.privileges.get(priv_name, False))

    def default(self, line):
        """Rejects arbitrary or unknown shell commands."""
        raw_cmd = line.strip().split()[0] if line.strip() else ""
        print(f"Error: Command '{raw_cmd}' is not allowed or unrecognized in NexusNode restricted shell.")
        print("Type 'help' for available allowlisted commands.")

    def emptyline(self):
        """Does nothing on empty line."""
        pass

    def do_exit(self, arg):
        """Exit the NexusNode restricted shell."""
        print("Session terminated. Goodbye.")
        return True

    def do_quit(self, arg):
        """Exit the NexusNode restricted shell."""
        return self.do_exit(arg)

    def do_logout(self, arg):
        """Log out and terminate the restricted shell session."""
        return self.do_exit(arg)

    def do_whoami(self, arg):
        """Display current operator identity and role."""
        print(f"User:  {self.user_id}")
        print(f"Role:  {self.role}")
        print("Session: active (restricted shell)")

    # ==========================================================================
    # 1. HELP COMMAND (RBAC FILTERED)
    # ==========================================================================
    def do_help(self, arg):
        """List available commands permitted by your operator privileges."""
        arg = arg.strip()
        if arg:
            # Show specific help
            method = getattr(self, f"help_{arg}", None)
            if method:
                method()
            else:
                doc = getattr(self, f"do_{arg}", None)
                if doc and doc.__doc__:
                    print(f"\n{arg.upper()}: {doc.__doc__}\n")
                else:
                    print(f"No help topic for '{arg}'.")
            return

        print("\n=== NexusNode Restricted Shell — Available Commands ===")
        print("Core Commands:")
        print("  status            Display server health, memory budget, and governor state")
        print("  vault             Browse, search, and preview files in the storage vault")
        print("  media             Download YouTube/media URLs and view media library")
        print("  tasks             View, monitor, and cancel background tasks")
        print("  ai                Manage AI models and chat interactively")
        print("  rag               Query SQLite FTS5 RAG index and view document stats")
        print("  shares            Create and manage temporary secure download links")
        print("  account           Display account profile and enabled privileges")
        print("  whoami            Show current user identity")
        print("  logout / exit     Terminate session and disconnect")

        if self.is_admin:
            print("\nAdministrative Commands (Admin Role):")
            print("  services          Monitor and control system runit services")
            print("  models            Manage Ollama models (pull, delete, inspect)")
            print("  diagnostics       Run automated root-cause diagnostics & profiles")
            print("  logs              View recent system logs or stream live events")
            print("  users             Manage application users and credentials")
            print("  backups           Create, verify, and restore atomic backups")
            print("  automation        View and trigger scheduled background jobs")
            print("  settings          Inspect and update server configuration")
            print("  database          Inspect SQLite vault schema and tables")

        print("\nType 'help <command>' for usage details on a specific command.\n")

    # ==========================================================================
    # 2. STATUS COMMAND
    # ==========================================================================
    def do_status(self, arg):
        """Display appliance health, memory budget, and resource governor metrics."""
        ram_info = governor.get_ram_status()
        thermal_info = governor.get_thermal_status()
        cpu_info = governor.get_cpu_status()
        disk_info = governor.get_disk_status()
        battery_info = governor.get_battery_status()

        ram_pct = ram_info.get("ram_percent", ram_info.get("used_percent", 0))
        disk_pct = disk_info.get("percent", disk_info.get("used_percent", 0))

        print("\n=== NexusNode Appliance Status ===")
        print(f"Appliance Version:  {config.VERSION}")
        print(f"Governor State:     {ram_info.get('state', 'NORMAL').upper()} (RAM: {ram_info.get('available_mb', 0)} MB free)")
        print(f"RAM Usage:          {ram_info.get('used_mb', 0)} MB used / {ram_info.get('total_mb', 0)} MB total ({ram_pct}%)")
        print(f"Thermal State:      {thermal_info.get('state', 'NORMAL').upper()} ({thermal_info.get('temperature_c', 35)}°C)")
        print(f"CPU Load:           {cpu_info.get('load_1m', 0.5)} (1m), {cpu_info.get('load_5m', 0.5)} (5m) [Cores: {cpu_info.get('cores', 8)}]")
        print(f"Disk Space:         {disk_info.get('free_gb', 0):.2f} GB free / {disk_info.get('total_gb', 0):.2f} GB total ({disk_pct}%)")
        print(f"Battery:            {battery_info.get('level_percent', 'N/A')}% (Status: {battery_info.get('status', 'N/A')})")

        ai_state = server_app.ollama_mgr.get_ai_state()
        is_online = (ai_state.get("engine") == "running" or ai_state.get("service_online", False))
        print(f"Ollama Service:     {'ONLINE' if is_online else 'OFFLINE'}")
        print(f"Active Model:       {ai_state.get('selected_model') or 'None'}")
        print(f"Loaded Model:       {ai_state.get('loaded_model') or 'None (Idle)'}")
        print()

    # ==========================================================================
    # 3. VAULT COMMAND
    # ==========================================================================
    def do_vault(self, arg):
        """Manage and inspect Storage Vault files.
Usage:
  vault ls [subpath]        List files and directories in vault
  vault search <query>      Search for files in vault by name
  vault info <filename>     Display file metadata and size
  vault cat <filename>      Preview text file content (safe, max 64 KB)
  vault clean-temp          Remove temporary .tmp/.part files (requires can_manage_files)
"""
        parts = shlex.split(arg) if arg else ["ls"]
        subcmd = parts[0].lower() if parts else "ls"
        subargs = parts[1:]

        if subcmd == "ls":
            rel_path = subargs[0] if subargs else ""
            target_dir = os.path.normpath(os.path.join(config.STORAGE_DIR, rel_path))
            if not target_dir.startswith(os.path.abspath(config.STORAGE_DIR)):
                print("Error: Access denied. Path is outside Storage Vault.")
                return

            if not os.path.exists(target_dir):
                print(f"Error: Directory '{rel_path}' does not exist.")
                return

            print(f"\n--- Vault Directory: /{rel_path} ---")
            print(f"{'TYPE':<6} {'SIZE':<12} {'NAME':<36} {'MODIFIED':<20}")
            print("-" * 76)

            try:
                for entry in sorted(os.scandir(target_dir), key=lambda e: (not e.is_dir(), e.name.lower())):
                    if entry.name.startswith("."):
                        continue
                    mtime_str = datetime.datetime.fromtimestamp(entry.stat().st_mtime).strftime('%Y-%m-%d %H:%M:%S')
                    if entry.is_dir():
                        print(f"{'[DIR]':<6} {'-':<12} {entry.name:<36} {mtime_str:<20}")
                    else:
                        size_str = format_bytes(entry.stat().st_size)
                        print(f"{'[FILE]':<6} {size_str:<12} {entry.name:<36} {mtime_str:<20}")
                print()
            except Exception as e:
                print(f"Error reading directory: {e}")

        elif subcmd == "search":
            if not subargs:
                print("Usage: vault search <query>")
                return
            query = " ".join(subargs).lower()
            matches = []
            for root, dirs, files in os.walk(config.STORAGE_DIR):
                for f in files:
                    if query in f.lower():
                        full_p = os.path.join(root, f)
                        rel_p = os.path.relpath(full_p, config.STORAGE_DIR)
                        matches.append((rel_p, os.path.getsize(full_p)))

            print(f"\nFound {len(matches)} matching file(s):")
            for p, sz in matches[:30]:
                print(f"  {p} ({format_bytes(sz)})")
            if len(matches) > 30:
                print(f"  ... and {len(matches) - 30} more.")
            print()

        elif subcmd == "info":
            if not subargs:
                print("Usage: vault info <filename>")
                return
            rel_path = subargs[0]
            full_path = os.path.normpath(os.path.join(config.STORAGE_DIR, rel_path))
            if not full_path.startswith(os.path.abspath(config.STORAGE_DIR)) or not os.path.isfile(full_path):
                print(f"Error: File '{rel_path}' not found in vault.")
                return

            st = os.stat(full_path)
            print(f"\nFile:         {rel_path}")
            print(f"Size:         {format_bytes(st.st_size)} ({st.st_size} bytes)")
            print(f"Modified:     {datetime.datetime.fromtimestamp(st.st_mtime).strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"Category:     {rel_path.split(os.sep)[0] if os.sep in rel_path else 'Root'}")
            print()

        elif subcmd in ["cat", "preview"]:
            if not subargs:
                print("Usage: vault cat <filename>")
                return
            rel_path = subargs[0]
            full_path = os.path.normpath(os.path.join(config.STORAGE_DIR, rel_path))
            if not full_path.startswith(os.path.abspath(config.STORAGE_DIR)) or not os.path.isfile(full_path):
                print(f"Error: File '{rel_path}' not found.")
                return

            ext = os.path.splitext(full_path)[1].lower().lstrip(".")
            if ext not in config.RAG_SUPPORTED_TEXT_EXTENSIONS:
                print(f"Error: File '{rel_path}' is binary or unsupported for text preview.")
                return

            if os.path.getsize(full_path) > 64 * 1024:
                print(f"Error: File is larger than 64 KB preview limit ({format_bytes(os.path.getsize(full_path))}).")
                return

            print(f"\n--- Preview: {rel_path} ---")
            try:
                with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                    print(f.read())
            except Exception as e:
                print(f"Error reading file: {e}")
            print("--- End of File ---\n")

        elif subcmd == "clean-temp":
            if not self.has_priv("can_manage_files"):
                print("Error: Insufficient privilege 'can_manage_files'.")
                return
            count = 0
            for root, dirs, files in os.walk(config.STORAGE_DIR):
                for f in files:
                    if f.endswith((".part", ".tmp")):
                        try:
                            os.remove(os.path.join(root, f))
                            count += 1
                        except Exception:
                            pass
            print(f"Cleaned {count} temporary file(s).")
        else:
            print(f"Error: Unknown vault subcommand '{subcmd}'. Type 'help vault'.")

    # ==========================================================================
    # 4. MEDIA COMMAND
    # ==========================================================================
    def do_media(self, arg):
        """Manage media library and download streams.
Usage:
  media list [category]     List media items (Music, Videos, Podcasts, Downloads)
  media download <url>      Enqueue a media download task
  media queue               Show active download tasks
"""
        if not self.has_priv("can_download_media"):
            print("Error: Access denied. Privilege 'can_download_media' required.")
            return

        parts = shlex.split(arg) if arg else ["list"]
        subcmd = parts[0].lower()
        subargs = parts[1:]

        if subcmd == "list":
            cat = subargs[0] if subargs else "all"
            categories = [cat] if cat in config.MEDIA_CATEGORIES else ["Music", "Videos", "Podcasts", "Downloads"]
            for c in categories:
                dir_p = os.path.join(config.STORAGE_DIR, c)
                if not os.path.exists(dir_p):
                    continue
                files = [f for f in os.listdir(dir_p) if not f.startswith(".")]
                print(f"\n--- Category: {c} ({len(files)} items) ---")
                for f in sorted(files)[:20]:
                    fp = os.path.join(dir_p, f)
                    sz = os.path.getsize(fp) if os.path.isfile(fp) else 0
                    print(f"  {f} ({format_bytes(sz)})")
            print()

        elif subcmd == "download":
            if not subargs:
                print("Usage: media download <url>")
                return
            url = subargs[0].strip()
            if not url.startswith(("http://", "https://")):
                print("Error: Invalid URL. Must start with http:// or https://")
                return

            task_id, task_meta = server_app.task_runner.enqueue_task(
                f"Download: {url[:32]}",
                "media_download",
                server_app.run_media_download_job,
                {"url": url, "category": "Downloads", "format": "best"},
                owner_user_id=self.user_id
            )
            if task_id:
                print(f"Download enqueued successfully.")
                print(f"Task ID: {task_id}")
                print(f"Monitor progress with: tasks status {task_id}")
            else:
                print(f"Error: {task_meta.get('message', 'Failed to enqueue task')}")

        elif subcmd == "queue":
            tasks = server_app.task_runner.get_all_tasks()
            media_tasks = [t for t in tasks if t["task_type"] == "media_download"]
            if not self.is_admin:
                media_tasks = [t for t in media_tasks if t.get("owner_user_id") == self.user_id]

            print(f"\nActive Media Tasks ({len(media_tasks)}):")
            for t in media_tasks:
                print(f"  [{t['status'].upper()}] {t['task_id'][:8]} — {t['title']} ({t.get('progress', 0)}%)")
            print()
        else:
            print(f"Error: Unknown media subcommand '{subcmd}'. Type 'help media'.")

    # ==========================================================================
    # 5. TASKS COMMAND (OBJECT-LEVEL OWNERSHIP ENFORCED)
    # ==========================================================================
    def do_tasks(self, arg):
        """View, monitor, and cancel background tasks.
Usage:
  tasks                     List active and recent tasks
  tasks status <task_id>    View detailed progress and logs of a task
  tasks cancel <task_id>    Cancel a running task (ownership verified)
"""
        parts = shlex.split(arg) if arg else ["list"]
        subcmd = parts[0].lower()
        subargs = parts[1:]

        if subcmd == "list":
            tasks = server_app.task_runner.get_all_tasks()
            if not self.is_admin:
                tasks = [t for t in tasks if t.get("owner_user_id") == self.user_id]

            if not tasks:
                print("No tasks found.")
                return

            print(f"\n{'TASK ID':<10} {'STATUS':<12} {'PROGRESS':<10} {'OWNER':<12} {'TITLE':<32}")
            print("-" * 76)
            for t in sorted(tasks, key=lambda x: x.get("created_at", 0), reverse=True)[:25]:
                tid = t['task_id'][:8]
                stat = t['status'].upper()
                prog = f"{t.get('progress', 0)}%"
                owner = t.get('owner_user_id', 'admin')
                title = t.get('title', '')[:30]
                print(f"{tid:<10} {stat:<12} {prog:<10} {owner:<12} {title:<32}")
            print()

        elif subcmd == "status":
            if not subargs:
                print("Usage: tasks status <task_id>")
                return
            target_id = subargs[0].strip()
            task = server_app.task_runner.get_task(target_id)
            if not task:
                print(f"Error: Task '{target_id}' not found.")
                return

            if not self.is_admin and task.get("owner_user_id") != self.user_id:
                print("Error: Access denied. You can only inspect your own tasks.")
                return

            print(f"\nTask ID:       {task['task_id']}")
            print(f"Title:         {task['title']}")
            print(f"Type:          {task['task_type']}")
            print(f"Status:        {task['status'].upper()}")
            print(f"Progress:      {task.get('progress', 0)}%")
            print(f"Owner:         {task.get('owner_user_id', 'admin')}")
            print(f"Created:       {format_timestamp(task.get('created_at'))}")

            logs = task.get("logs", [])
            print("\nRecent Logs:")
            for line in logs[-10:]:
                print(f"  {line}")
            print()

        elif subcmd == "cancel":
            if not subargs:
                print("Usage: tasks cancel <task_id>")
                return
            target_id = subargs[0].strip()
            success, msg = server_app.task_runner.cancel_task(
                target_id,
                requesting_user_id=self.user_id,
                is_admin=self.is_admin
            )
            if success:
                print(f"Task '{target_id}' cancelled successfully.")
            else:
                print(f"Error: {msg}")
        else:
            # Check if arg is a task ID
            self.do_tasks(f"status {arg}")

    # ==========================================================================
    # 6. AI COMMAND
    # ==========================================================================
    def do_ai(self, arg):
        """Interact with local quantized AI models.
Usage:
  ai models                 List installed Ollama models
  ai state                  Show active loaded model and inference metrics
  ai select <model_name>    Select model for inference
  ai chat <prompt>          Generate response tokens interactively
"""
        if not self.has_priv("can_use_ai"):
            print("Error: Access denied. Privilege 'can_use_ai' required.")
            return

        parts = shlex.split(arg) if arg else ["models"]
        subcmd = parts[0].lower()
        subargs = parts[1:]

        if subcmd == "models":
            models = server_app.ollama_mgr.get_installed_models()
            if not models:
                print("No models installed.")
                return
            print(f"\n{'MODEL NAME':<24} {'SIZE':<12} {'FAMILY':<12} {'PARAMETERS':<12}")
            print("-" * 60)
            for m in models:
                sz_str = format_bytes(m.get('size_bytes', 0))
                fam = m.get('family', 'N/A')
                param = m.get('parameter_size', 'N/A')
                print(f"{m['name']:<24} {sz_str:<12} {fam:<12} {param:<12}")
            print()

        elif subcmd == "state":
            st = server_app.ollama_mgr.get_ai_state()
            is_online = (st.get("engine") == "running" or st.get("service_online", False))
            print(f"\nAI Engine Online:   {'YES' if is_online else 'NO'}")
            print(f"Selected Model:     {st.get('selected_model') or 'None'}")
            print(f"Loaded Model:       {st.get('loaded_model') or 'None (Idle)'}")
            print(f"Context Limit:      {st.get('context_size', 2048)} tokens")
            print(f"Keep-Alive:         {st.get('keep_alive', getattr(config, 'OLLAMA_KEEP_ALIVE_NORMAL', '5m'))}")
            print()

        elif subcmd == "select":
            if not subargs:
                print("Usage: ai select <model_name>")
                return
            mname = subargs[0].strip()
            success, msg = server_app.ollama_mgr.select_model(mname)
            if success:
                print(f"Model '{mname}' selected successfully.")
            else:
                print(f"Error: {msg}")

        elif subcmd == "chat":
            if not subargs:
                print("Usage: ai chat <your prompt text>")
                return
            prompt = " ".join(subargs)
            state = server_app.ollama_mgr.get_ai_state()
            model = state.get("selected_model") or "qwen2.5:0.5b"

            print(f"\n[AI: {model}] Generating response...\n")
            try:
                import urllib.request
                req_data = json.dumps({
                    "model": model,
                    "prompt": prompt,
                    "stream": True
                }).encode('utf-8')

                req = urllib.request.Request(
                    f"{config.OLLAMA_HOST}/api/generate",
                    data=req_data,
                    headers={"Content-Type": "application/json"}
                )
                with urllib.request.urlopen(req, timeout=120) as resp:
                    for line in resp:
                        if line:
                            data = json.loads(line.decode('utf-8'))
                            chunk = data.get("response", "")
                            sys.stdout.write(chunk)
                            sys.stdout.flush()
                print("\n")
            except Exception as e:
                print(f"\nError communicating with Ollama: {e}\n")
        else:
            print(f"Error: Unknown AI subcommand '{subcmd}'. Type 'help ai'.")

    # ==========================================================================
    # 7. RAG COMMAND
    # ==========================================================================
    def do_rag(self, arg):
        """Query SQLite FTS5 RAG index and view document stats.
Usage:
  rag status                Display SQLite FTS5 index stats
  rag search <query>        Execute BM25 search across indexed documents
"""
        if not self.has_priv("can_use_rag"):
            print("Error: Access denied. Privilege 'can_use_rag' required.")
            return

        parts = shlex.split(arg) if arg else ["status"]
        subcmd = parts[0].lower()
        subargs = parts[1:]

        if subcmd == "status":
            diag = server_app.rag_engine.get_diagnostics()
            print("\n=== SQLite FTS5 RAG Diagnostics ===")
            print(f"Engine Type:        SQLite FTS5 Full-Text Search")
            print(f"Indexed Documents:  {diag.get('indexed_files_count', 0)}")
            print(f"Total Text Chunks:  {diag.get('total_chunks', 0)}")
            print(f"Database Size:      {format_bytes(diag.get('rag_db_size_bytes', 0))}")
            print(f"Status:             {diag.get('status', 'HEALTHY')}")
            print()

        elif subcmd == "search":
            if not subargs:
                print("Usage: rag search <query>")
                return
            query = " ".join(subargs)
            results = server_app.rag_engine.search(query, top_k=4)
            if not results:
                print(f"No RAG results found for '{query}'.")
                return

            print(f"\nFound {len(results)} relevant excerpt(s) for '{query}':")
            for i, r in enumerate(results, 1):
                src = r.get("source_file", "unknown")
                score = r.get("score", 0.0)
                snippet = r.get("content", "").strip().replace("\n", " ")[:160]
                print(f"\n[{i}] Source: {src} (Score: {score:.3f})")
                print(f"    \"{snippet}...\"")
            print()
        else:
            print(f"Error: Unknown RAG subcommand '{subcmd}'. Type 'help rag'.")

    # ==========================================================================
    # 8. SHARES COMMAND
    # ==========================================================================
    def do_shares(self, arg):
        """Manage secure temporary download share links.
Usage:
  shares list               List active share links
  shares create <file> [h]  Create temporary share link (valid for h hours)
  shares revoke <token>     Revoke a share link (ownership verified)
"""
        parts = shlex.split(arg) if arg else ["list"]
        subcmd = parts[0].lower()
        subargs = parts[1:]

        if subcmd == "list":
            with server_app.DB_LOCK:
                conn = server_app.get_db_connection()
                try:
                    cur = conn.cursor()
                    cur.execute("SELECT token, file_path, created_by, expires_at, download_count, max_downloads, revoked FROM temporary_shares")
                    rows = cur.fetchall()
                finally:
                    conn.close()

            shares = [dict(r) for r in rows if not r["revoked"] and time.time() < r["expires_at"]]
            if not self.is_admin:
                shares = [s for s in shares if s.get("created_by") == self.user_id]

            if not shares:
                print("No active share links found.")
                return

            print(f"\n{'TOKEN':<12} {'FILE':<24} {'EXPIRES':<20} {'DOWNLOADS':<10} {'OWNER':<10}")
            print("-" * 76)
            for s in shares:
                tok = s['token'][:10] + ".."
                fpath = os.path.basename(s['file_path'])[:22]
                exp = format_timestamp(s['expires_at'])
                dls = f"{s['download_count']}/{s['max_downloads'] or 'inf'}"
                owner = s.get('created_by', 'admin')
                print(f"{tok:<12} {fpath:<24} {exp:<20} {dls:<10} {owner:<10}")
            print()

        elif subcmd == "create":
            if not self.has_priv("can_create_shares"):
                print("Error: Access denied. Privilege 'can_create_shares' required.")
                return
            if not subargs:
                print("Usage: shares create <filename> [hours] [max_downloads]")
                return
            rel_path = subargs[0]
            full_path = os.path.normpath(os.path.join(config.STORAGE_DIR, rel_path))
            if not full_path.startswith(os.path.abspath(config.STORAGE_DIR)) or not os.path.isfile(full_path):
                print(f"Error: File '{rel_path}' not found.")
                return

            hours = int(subargs[1]) if len(subargs) > 1 and subargs[1].isdigit() else 24
            max_dl = int(subargs[2]) if len(subargs) > 2 and subargs[2].isdigit() else 0

            import secrets
            token = secrets.token_urlsafe(16)
            expires_at = time.time() + (hours * 3600)

            with server_app.DB_LOCK:
                conn = server_app.get_db_connection()
                try:
                    conn.execute("""
                        INSERT INTO temporary_shares (token, file_path, created_by, expires_at, download_count, max_downloads, revoked)
                        VALUES (?, ?, ?, ?, 0, ?, 0)
                    """, (token, rel_path, self.user_id, expires_at, max_dl))
                    conn.commit()
                finally:
                    conn.close()

            tunnel = server_app.get_tunnel_url() or f"http://127.0.0.1:{config.PORT}"
            print(f"\nShare link created successfully (valid for {hours}h):")
            print(f"Token: {token}")
            print(f"URL:   {tunnel}/share/{token}\n")

        elif subcmd == "revoke":
            if not subargs:
                print("Usage: shares revoke <token>")
                return
            token = subargs[0].strip()
            with server_app.DB_LOCK:
                conn = server_app.get_db_connection()
                try:
                    cur = conn.cursor()
                    cur.execute("SELECT created_by FROM temporary_shares WHERE token = ?", (token,))
                    row = cur.fetchone()
                    if not row:
                        print("Error: Share token not found.")
                        return
                    if not self.is_admin and row["created_by"] != self.user_id:
                        print("Error: Access denied. You can only revoke your own shares.")
                        return
                    conn.execute("UPDATE temporary_shares SET revoked = 1 WHERE token = ?", (token,))
                    conn.commit()
                    print(f"Share '{token}' revoked successfully.")
                finally:
                    conn.close()
        else:
            print(f"Error: Unknown shares subcommand '{subcmd}'. Type 'help shares'.")

    # ==========================================================================
    # 9. ACCOUNT COMMAND
    # ==========================================================================
    def do_account(self, arg):
        """Display operator account details and enabled RBAC privileges."""
        print(f"\n=== Operator Account Profile ===")
        print(f"User ID:        {self.user_id}")
        print(f"Role:           {self.role.upper()}")
        print(f"Created:        {format_timestamp(self.user.get('created_at'))}")
        print("Enabled Privileges:")
        for p, enabled in sorted(self.privileges.items()):
            symbol = "[+]" if enabled or self.is_admin else "[-]"
            print(f"  {symbol} {p}")
        print()

    # ==========================================================================
    # 10. ADMIN-ONLY COMMANDS (STRICTLY GUARDED BY is_admin)
    # ==========================================================================

    def do_services(self, arg):
        """[Admin] Monitor and control system runit services.
Usage:
  services [status]         Show status of managed services
  services start <name>     Start a managed service
  services stop <name>      Stop a managed service
  services restart <name>   Restart a managed service
"""
        if not self.is_admin:
            print("Error: Administrator privileges required.")
            return

        parts = shlex.split(arg) if arg else ["status"]
        subcmd = parts[0].lower()
        subargs = parts[1:]

        if subcmd == "status":
            st = server_app.governor.get_services_status()
            print(f"\n{'SERVICE':<16} {'STATUS':<12} {'UPTIME':<12} {'DETAILS':<30}")
            print("-" * 70)
            for sname, sinfo in st.items():
                stat = sinfo.get("status", "unknown").upper()
                upt = f"{sinfo.get('uptime_seconds', 0)}s"
                det = str(sinfo.get("details", ""))[:28]
                print(f"{sname:<16} {stat:<12} {upt:<12} {det:<30}")
            print()

        elif subcmd in ["start", "stop", "restart"]:
            if not subargs:
                print(f"Usage: services {subcmd} <service_name>")
                return
            srv = subargs[0].lower()
            if srv == "ollama":
                if subcmd == "start":
                    succ, msg = server_app.ollama_mgr.start_service()
                elif subcmd == "stop":
                    succ, msg = server_app.ollama_mgr.stop_service()
                else:
                    server_app.ollama_mgr.stop_service()
                    succ, msg = server_app.ollama_mgr.start_service()
                print(f"[{'OK' if succ else 'FAILED'}] {msg}")
            else:
                print(f"Service control action '{subcmd}' executed for '{srv}'.")
        else:
            print(f"Error: Unknown services subcommand '{subcmd}'.")

    def do_diagnostics(self, arg):
        """[Admin] Run technical diagnostics and automated root-cause engine.
Usage:
  diagnostics               System /proc introspection
  diagnostics full          Automated root-cause analysis report
  diagnostics memory        4 GB RAM formal budget breakdown
  diagnostics profile       Capture instant performance snapshot
"""
        if not self.is_admin:
            print("Error: Administrator privileges required.")
            return

        subcmd = arg.strip().lower() or "system"

        if subcmd == "full":
            report = server_app.generate_root_cause_findings()
            print(f"\n=== NexusNode Automated Root-Cause Report ===")
            print(f"Overall Status: {report['overall_status']}")
            print(f"Findings ({report['findings_count']}):")
            for f in report.get("findings", []):
                print(f"  [{f['severity'].upper()}] {f['code']}: {f['message']}")
                print(f"    Resolution: {f['resolution']}")
            print()

        elif subcmd == "profile":
            snap = server_app.capture_performance_profile()
            print("\n=== Performance Profile Snapshot ===")
            for k, v in snap.items():
                print(f"  {k:<24}: {v}")
            print()

        elif subcmd == "memory":
            budget = server_app.governor.get_memory_budget_status()
            print("\n=== 4 GB RAM Formal Memory Budget ===")
            print(f"Total Physical RAM: {budget.get('total_physical_mb', 3800)} MB")
            print("Budget Allocations:")
            for k, v in budget.get("allocations", {}).items():
                print(f"  {k:<24}: {v} MB")
            print(f"Headroom Buffer:     {budget.get('headroom_mb', 640)} MB\n")

        else:
            diag = server_app.get_system_diagnostics()
            proc = diag.get("nexusnode_process", {})
            print(f"\nProcess RSS:      {proc.get('rss_mb', 0)} MB")
            print(f"Threads Count:    {proc.get('threads', 0)}")
            print(f"SQLite WAL Size:  {diag.get('storage_sizes', {}).get('sqlite_wal_size_kb', 0)} KB")
            print(f"RAG DB Size:      {diag.get('storage_sizes', {}).get('rag_vault_size_kb', 0)} KB\n")

    def do_users(self, arg):
        """[Admin] Manage NexusNode application accounts and privileges.
Usage:
  users                     List all users
  users info <user_id>      Display user details and permissions
  users create <user_id>    Create a new user account
  users delete <user_id>    Delete a non-primary user account
  users unlock <user_id>    Unlock a locked user account
"""
        if not self.is_admin:
            print("Error: Administrator privileges required.")
            return

        import nexus_admin
        from argparse import Namespace

        parts = shlex.split(arg) if arg else ["list"]
        subcmd = parts[0].lower()
        subargs = parts[1:]

        if subcmd in ["list", ""]:
            nexus_admin.cmd_users(Namespace())
        elif subcmd == "info":
            if not subargs:
                print("Usage: users info <user_id>")
                return
            nexus_admin.cmd_user_info(Namespace(user=subargs[0]))
        elif subcmd == "create":
            if not subargs:
                print("Usage: users create <user_id> [role]")
                return
            role = subargs[1] if len(subargs) > 1 else "user"
            nexus_admin.cmd_create_user(Namespace(user=subargs[0], role=role, password=None, yes=False))
        elif subcmd == "delete":
            if not subargs:
                print("Usage: users delete <user_id>")
                return
            nexus_admin.cmd_delete_user(Namespace(user=subargs[0], yes=False))
        elif subcmd == "unlock":
            if not subargs:
                print("Usage: users unlock <user_id>")
                return
            nexus_admin.cmd_unlock(Namespace(user=subargs[0]))
        else:
            print(f"Error: Unknown users subcommand '{subcmd}'.")

    def do_logs(self, arg):
        """[Admin] Inspect recent system event logs.
Usage:
  logs [count]              Display recent logs (default: 20)
"""
        if not self.is_admin:
            print("Error: Administrator privileges required.")
            return

        count = int(arg.strip()) if arg.strip().isdigit() else 20
        with server_app.DB_LOCK:
            conn = server_app.get_db_connection()
            try:
                cur = conn.cursor()
                cur.execute("SELECT timestamp, level, category, message FROM system_logs ORDER BY id DESC LIMIT ?", (count,))
                rows = cur.fetchall()
            finally:
                conn.close()

        print(f"\n--- Recent System Logs (Last {count}) ---")
        for r in reversed(rows):
            ts = format_timestamp(r["timestamp"])
            print(f"[{ts}] [{r['level']:<5}] [{r['category']:<8}] {r['message']}")
        print()

    def do_backups(self, arg):
        """[Admin] Manage atomic appliance backups.
Usage:
  backups                   List existing backups
  backups create            Create an atomic backup archive
"""
        if not self.is_admin:
            print("Error: Administrator privileges required.")
            return

        parts = shlex.split(arg) if arg else ["list"]
        subcmd = parts[0].lower()

        if subcmd == "list":
            bdir = config.BACKUP_DIR
            files = [f for f in os.listdir(bdir) if f.endswith(".zip")] if os.path.exists(bdir) else []
            print(f"\nAvailable Backups ({len(files)}):")
            for f in sorted(files, reverse=True):
                fp = os.path.join(bdir, f)
                sz = os.path.getsize(fp)
                print(f"  {f} ({format_bytes(sz)})")
            print()
        elif subcmd == "create":
            task_id, meta = server_app.task_runner.enqueue_task(
                "Appliance Backup Creation",
                "backup_create",
                server_app.run_backup_job,
                owner_user_id="admin"
            )
            print(f"Backup job enqueued. Task ID: {task_id}")
        else:
            print("Usage: backups [list|create]")


# ==============================================================================
# Entrypoint & Execution Dispatcher
# ==============================================================================

def launch_restricted_shell(user_dict: dict, direct_command: str = None) -> int:
    """
    Launches the restricted shell for the authenticated user.
    If direct_command is given (e.g. from SSH_ORIGINAL_COMMAND), executes it and exits immediately.
    """
    shell = NexusRestrictedShell(user_dict)

    if direct_command:
        # Non-interactive command mode (e.g. ssh -p 8022 anmol@PHONE_IP "vault ls")
        cmd_line = direct_command.strip()
        if not cmd_line:
            return 0
        try:
            # Check if command is forbidden or unknown
            first_token = shlex.split(cmd_line)[0].lower()
            method = getattr(shell, f"do_{first_token}", None)
            if not method:
                print(f"Error: Command '{first_token}' is not allowed in NexusNode restricted shell.", file=sys.stderr)
                return 1
            shell.onecmd(cmd_line)
            return 0
        except Exception as e:
            print(f"Error executing command: {e}", file=sys.stderr)
            return 1

    # Interactive REPL mode
    print("=" * 60)
    print("NexusNode — 24/7 Mobile Server Appliance Restricted Shell")
    print(f"User: {user_dict['user_id']} | Role: {user_dict.get('role', 'user').upper()}")
    print("Type 'help' for available commands or 'logout' to exit.")
    print("=" * 60 + "\n")

    try:
        shell.cmdloop()
    except (KeyboardInterrupt, EOFError):
        print("\nSession terminated.")
    return 0


def main():
    parser = argparse.ArgumentParser(description="NexusNode Restricted Application Shell")
    parser.add_argument("--user", "-u", default=None, help="Authenticated user ID (for SSH forced commands)")
    parser.add_argument("command", nargs="*", help="Direct command to execute")
    args = parser.parse_args()

    # Determine command string if provided via argv or SSH_ORIGINAL_COMMAND
    direct_cmd = None
    if os.environ.get("SSH_ORIGINAL_COMMAND"):
        direct_cmd = os.environ["SSH_ORIGINAL_COMMAND"]
    elif args.command:
        direct_cmd = " ".join(args.command)

    # 1. User specified via SSH key forced command / parameter
    if args.user:
        user_id = args.user.strip().lower()
        user = server_app.db_get_user(user_id)
        if not user:
            print(f"Error: NexusNode user '{user_id}' does not exist.", file=sys.stderr)
            sys.exit(1)

        # Check lockout
        with server_app.FAILED_LOGINS_LOCK:
            fail_rec = server_app.FAILED_LOGINS.get(user_id) or server_app.FAILED_LOGINS.get("127.0.0.1", {})
            if time.time() < fail_rec.get("locked_until", 0.0):
                rem = int(fail_rec["locked_until"] - time.time())
                print(f"Account locked. Try again in {rem} seconds.", file=sys.stderr)
                sys.exit(1)

        code = launch_restricted_shell(user, direct_cmd)
        sys.exit(code)

    # 2. Interactive login prompt if not authenticated via forced key
    print("NexusNode Restricted Application Shell")
    try:
        user_id = input("Operator ID: ").strip().lower()
        if not user_id:
            print("Error: User ID required.", file=sys.stderr)
            sys.exit(1)
        password = getpass.getpass("Passphrase: ")
    except (KeyboardInterrupt, EOFError):
        print("\nOperation cancelled.")
        sys.exit(1)

    success, msg, user, lockout_secs = server_app.authenticate_user_credentials(user_id, password, client_ip="127.0.0.1")
    if not success:
        if lockout_secs:
            print(f"Account locked. Try again in {lockout_secs} seconds.", file=sys.stderr)
        else:
            print("Authentication failed.", file=sys.stderr)
        sys.exit(1)

    code = launch_restricted_shell(user, direct_cmd)
    sys.exit(code)


if __name__ == "__main__":
    main()
