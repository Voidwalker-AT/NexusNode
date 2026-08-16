from __future__ import annotations

import sys
import argparse

from . import __version__
from . import config
from . import auth
from . import output
from .client import NexusClient, NexusError, NexusConnectionError
from .shell import NexusShell
from .commands import (
    status as cmd_status_mod,
    vault as cmd_vault_mod,
    media as cmd_media_mod,
    tasks as cmd_tasks_mod,
    ai as cmd_ai_mod,
    rag as cmd_rag_mod,
    shares as cmd_shares_mod,
    account as cmd_account_mod,
    services as cmd_services_mod,
    models as cmd_models_mod,
    diagnostics as cmd_diag_mod,
    logs as cmd_logs_mod,
    users as cmd_users_mod,
    backups as cmd_backups_mod,
    automation as cmd_auto_mod,
    settings as cmd_settings_mod,
    database as cmd_db_mod,
)


class NexusArgumentParser(argparse.ArgumentParser):
    """
    Authoritative argument parser for NexusNode Universal Remote CLI.
    Guarantees standard connection and format options (server, user, json, no_color, debug)
    are always initialized on the parsed Namespace with deterministic defaults across all invocations.
    """
    def parse_args(self, args=None, namespace=None):
        if namespace is None:
            namespace = argparse.Namespace(
                server=None,
                user=None,
                json=False,
                no_color=False,
                debug=False
            )
        else:
            for k, v in [("server", None), ("user", None), ("json", False), ("no_color", False), ("debug", False)]:
                if not hasattr(namespace, k):
                    setattr(namespace, k, v)
        return super().parse_args(args=args, namespace=namespace)


def create_parser() -> NexusArgumentParser:
    common_parser = argparse.ArgumentParser(add_help=False)
    common_parser.add_argument("--server", help="NexusNode remote server URL (e.g. https://...)", default=argparse.SUPPRESS)
    common_parser.add_argument("--user", help="NexusNode username / user ID", default=argparse.SUPPRESS)
    common_parser.add_argument("--json", action="store_true", help="Output machine-readable JSON format", default=argparse.SUPPRESS)
    common_parser.add_argument("--no-color", action="store_true", help="Disable ANSI color output", default=argparse.SUPPRESS)
    common_parser.add_argument("--debug", action="store_true", help="Enable verbose debug exception logs", default=argparse.SUPPRESS)

    parser = NexusArgumentParser(
        prog="nexus",
        description="NexusNode Universal Remote CLI Client - Authoritative HTTPS Frontend",
        epilog="For interactive connection, run 'nexus connect <url>' or simply 'nexus'.",
        parents=[common_parser]
    )
    parser.add_argument("--version", action="version", version=f"NexusNode CLI v{__version__}")

    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # --- Primary Connection Commands ---
    p_connect = subparsers.add_parser("connect", help="Connect interactively to NexusNode server", parents=[common_parser])
    p_connect.add_argument("url", nargs="?", default=None, help="Remote server URL (e.g. https://nexus.localto.net)")
    p_connect.add_argument("--password", help="User password (hidden prompt if omitted)", default=None)

    subparsers.add_parser("disconnect", help="Revoke session and disconnect", parents=[common_parser])
    subparsers.add_parser("session", help="Inspect current authenticated session", parents=[common_parser])

    # --- Legacy / Direct Auth Commands ---
    p_login = subparsers.add_parser("login", help="Log in to NexusNode server", parents=[common_parser])
    p_login.add_argument("--password", help="User password (hidden prompt if omitted)", default=None)

    subparsers.add_parser("logout", help="Log out and revoke session", parents=[common_parser])
    subparsers.add_parser("whoami", help="Display current user identity and active session details", parents=[common_parser])
    subparsers.add_parser("shell", help="Launch interactive application shell", parents=[common_parser])

    # --- status ---
    subparsers.add_parser("status", help="Appliance telemetry, load, RAM, and services overview", parents=[common_parser])

    # --- vault ---
    p_vault = subparsers.add_parser("vault", help="Vault file storage management", parents=[common_parser])
    p_vault.add_argument("vault_action", nargs="?", default="list", choices=["list", "ls", "info", "checksum", "download", "get", "delete", "rm", "clean-temp"], help="Action to perform")
    p_vault.add_argument("filename", nargs="?", default=None, help="Target file name")
    p_vault.add_argument("dest", nargs="?", default=None, help="Local destination path for download")
    p_vault.add_argument("--search", help="Search filter for vault list", default=None)
    p_vault.add_argument("--category", help="Category filter (image, video, document, audio)", default=None)
    p_vault.add_argument("-y", "--yes", action="store_true", help="Skip confirmation prompts")

    # --- media ---
    p_media = subparsers.add_parser("media", help="Media downloads & library", parents=[common_parser])
    p_media.add_argument("media_action", nargs="?", default="queue", choices=["download", "library", "queue"], help="Action")
    p_media.add_argument("url", nargs="?", default=None, help="Media URL to download (e.g. YouTube)")
    p_media.add_argument("--format", choices=["mp4", "mp3", "m4a", "webm"], default="mp4", help="Download format")
    p_media.add_argument("--quality", default="best", help="Video/Audio quality")
    p_media.add_argument("--dest", default="Downloads", help="Vault destination folder")

    # --- tasks ---
    p_tasks = subparsers.add_parser("tasks", help="Background tasks & progress", parents=[common_parser])
    p_tasks.add_argument("task_action", nargs="?", default="list", choices=["list", "ls", "status", "info", "cancel", "kill"], help="Action")
    p_tasks.add_argument("task_id", nargs="?", default=None, help="Task ID")

    # --- ai ---
    p_ai = subparsers.add_parser("ai", help="AI & LLM inference controls", parents=[common_parser])
    p_ai.add_argument("ai_action", nargs="?", default="state", choices=["models", "state", "select", "chat", "metrics"], help="Action")
    p_ai.add_argument("model_or_prompt", nargs="?", default=None, help="Model name or chat prompt")
    p_ai.add_argument("--model", help="Specify AI model name", default=None)
    p_ai.add_argument("--prompt", help="Specify chat prompt", default=None)

    # --- rag ---
    p_rag = subparsers.add_parser("rag", help="SQLite FTS5 RAG search & indexing", parents=[common_parser])
    p_rag.add_argument("rag_action", nargs="?", default="status", choices=["status", "diagnostics", "search", "sources", "index", "compact"], help="Action")
    p_rag.add_argument("query", nargs="?", default=None, help="Search query string")

    # --- shares ---
    p_shares = subparsers.add_parser("shares", help="Temporary public file shares", parents=[common_parser])
    p_shares.add_argument("shares_action", nargs="?", default="list", choices=["list", "ls", "create", "add", "revoke", "delete", "rm"], help="Action")
    p_shares.add_argument("filename_or_id", nargs="?", default=None, help="Filename to share or Share ID to revoke")
    p_shares.add_argument("--expire-hours", type=int, default=24, help="Hours until link expires")
    p_shares.add_argument("--max-downloads", type=int, default=10, help="Max permitted downloads")

    # --- account ---
    p_acc = subparsers.add_parser("account", help="Account and session settings", parents=[common_parser])
    p_acc.add_argument("account_action", nargs="?", default="whoami", choices=["whoami", "session", "logout", "password", "revoke-sessions"], help="Action")
    p_acc.add_argument("--current-password", help="Current account password", default=None)
    p_acc.add_argument("--new-password", help="New account password", default=None)

    # --- services (Admin) ---
    p_svc = subparsers.add_parser("services", help="Admin: System services supervision", parents=[common_parser])
    p_svc.add_argument("service_action", nargs="?", default="status", choices=["status", "list", "start", "stop", "restart"], help="Action")
    p_svc.add_argument("service_name", nargs="?", default=None, help="Service name (e.g. ollama, cloudflared, localtonet)")

    # --- models (Admin) ---
    p_mod = subparsers.add_parser("models", help="Admin: AI Model management", parents=[common_parser])
    p_mod.add_argument("model_action", nargs="?", default="list", choices=["list", "ls", "pull", "delete", "rm", "active", "set-active"], help="Action")
    p_mod.add_argument("model_name", nargs="?", default=None, help="Ollama model name (e.g. llama3.2:1b)")

    # --- diagnostics (Admin) ---
    p_diag = subparsers.add_parser("diagnostics", help="Admin: Appliance technical diagnostics", parents=[common_parser])
    p_diag.add_argument("diag_action", nargs="?", default="system", choices=["system", "full", "full-report", "profile", "network"], help="Action")
    p_diag.add_argument("--target", default="internet", choices=["internet", "tunnel", "ollama", "nexusnode"], help="Network test target")

    # --- logs (Admin) ---
    p_logs = subparsers.add_parser("logs", help="Admin: System event logs", parents=[common_parser])
    p_logs.add_argument("log_action", nargs="?", default="recent", choices=["recent", "list", "stream", "follow", "tail"], help="Action")
    p_logs.add_argument("--limit", type=int, default=50, help="Number of recent logs")
    p_logs.add_argument("--level", help="Filter by level (INFO, WARN, ERROR)")
    p_logs.add_argument("--component", help="Filter by component")

    # --- users (Admin) ---
    p_users = subparsers.add_parser("users", help="Admin: User accounts & privileges", parents=[common_parser])
    p_users.add_argument("user_action", nargs="?", default="list", choices=["list", "ls", "create", "add", "delete", "rm", "privileges", "password", "disable", "enable", "revoke-sessions"], help="Action")
    p_users.add_argument("username", nargs="?", default=None, help="User ID")
    p_users.add_argument("--password", help="User password for create/reset", default=None)
    p_users.add_argument("--role", choices=["admin", "user"], default="user", help="Account role")
    p_users.add_argument("--is-disabled", action="store_true", help="Mark user as disabled on create")
    p_users.add_argument("--grant", help="Privilege to grant")
    p_users.add_argument("--revoke", help="Privilege to revoke")
    p_users.add_argument("-y", "--yes", action="store_true", help="Skip confirmation prompts")

    # --- backups (Admin) ---
    p_backups = subparsers.add_parser("backups", help="Admin: Atomic database backups", parents=[common_parser])
    p_backups.add_argument("backup_action", nargs="?", default="list", choices=["list", "ls", "create", "restore", "download", "get"], help="Action")
    p_backups.add_argument("backup_id", nargs="?", default=None, help="Backup ID")
    p_backups.add_argument("dest", nargs="?", default=None, help="Local file destination for download")
    p_backups.add_argument("-y", "--yes", action="store_true", help="Skip confirmation prompts")

    # --- automation (Admin) ---
    p_auto = subparsers.add_parser("automation", help="Admin: Scheduled automation jobs", parents=[common_parser])
    p_auto.add_argument("auto_action", nargs="?", default="list", choices=["list", "ls", "run", "toggle", "enable", "disable"], help="Action")
    p_auto.add_argument("job_id", nargs="?", default=None, help="Job ID")

    # --- settings (Admin) ---
    p_set = subparsers.add_parser("settings", help="Admin: Appliance settings", parents=[common_parser])
    p_set.add_argument("setting_action", nargs="?", default="get", choices=["get", "list", "set"], help="Action")
    p_set.add_argument("key", nargs="?", default=None, help="Setting key")
    p_set.add_argument("value", nargs="?", default=None, help="Setting value to assign")

    # --- database (Admin) ---
    p_db = subparsers.add_parser("database", help="Admin: Safe read-only SQLite inspection", parents=[common_parser])
    p_db.add_argument("db_action", nargs="?", default="diagnostics", choices=["diagnostics", "stats", "query", "inspect"], help="Action")
    p_db.add_argument("table", nargs="?", default="users", help="Table name to inspect")
    p_db.add_argument("--limit", type=int, default=25, help="Max rows to retrieve")

    # --- setup ---
    p_setup = subparsers.add_parser("setup", help="Environment & Windows PATH auto-configuration", parents=[common_parser])
    p_setup.add_argument("setup_action", nargs="?", default="status", choices=["status", "path", "fix"], help="Setup action")

    return parser


def setup_path_cli() -> int:
    """Entry point for nexus-setup console script."""
    from .windows import main as windows_setup_main
    return windows_setup_main()


def main(argv=None) -> int:
    # 0. Automatic Windows PATH self-healing on startup
    if sys.platform == "win32":
        try:
            from .windows import ensure_windows_path
            ensure_windows_path(silent=True)
        except Exception:
            pass

    parser = create_parser()
    args = parser.parse_args(argv)

    # Handle setup command before resolving server URL
    if args.command == "setup":
        from .windows import main as windows_setup_main
        return windows_setup_main()

    # 1. Resolve target server URL with explicit precedence rule:
    # Explicit positional 'url' on connect wins over global '--server'.
    target_server = args.server
    if args.command == "connect" and getattr(args, "url", None):
        target_server = args.url

    debug = args.debug
    as_json = args.json
    no_color = args.no_color

    if as_json or no_color:
        output.set_color_enabled(False)

    server_url = config.resolve_server_url(cli_server=target_server, prompt_if_missing=(args.command is None or args.command == "connect" or args.command == "login"))
    client = NexusClient(server_url=server_url, debug=debug)

    try:
        # 2. If no command specified, default to interactive session/connect
        if not args.command:
            # Check if valid session exists
            if client.token:
                try:
                    status_code, resp = client.get("/api/auth/me")
                    if status_code == 200 and isinstance(resp, dict):
                        user_info = resp.get("user") if isinstance(resp.get("user"), dict) else resp
                        shell = NexusShell(client, session_info=user_info)
                        shell.cmdloop()
                        return 0
                except Exception:
                    pass

            # Fallback to connect sequence
            if auth.connect_sequence(client, username=args.user, password=getattr(args, "password", None)):
                sess_info = auth.whoami(client, as_json=False)
                shell = NexusShell(client, session_info=sess_info)
                shell.cmdloop()
                return 0
            return 1

        # 3. Handle Connect Command
        if args.command == "connect":
            if auth.connect_sequence(client, server_url=target_server, username=args.user, password=getattr(args, "password", None)):
                sess_info = auth.whoami(client, as_json=False)
                shell = NexusShell(client, session_info=sess_info)
                shell.cmdloop()
                return 0
            return 1

        # 4. Handle Disconnect / Logout
        if args.command in ["disconnect", "logout"]:
            return 0 if auth.logout(client, as_json=as_json) else 1

        # 5. Handle Session / Whoami
        if args.command in ["session", "whoami"]:
            return 0 if auth.whoami(client, as_json=as_json) else 1

        # 6. Handle Login (Direct/Legacy)
        if args.command == "login":
            return 0 if auth.login(client, username=args.user, password=getattr(args, "password", None), as_json=as_json) else 1

        # 7. Shell Command
        if args.command == "shell":
            if not auth.ensure_authenticated(client):
                return 1
            sess_info = auth.whoami(client, as_json=False)
            shell = NexusShell(client, session_info=sess_info)
            shell.cmdloop()
            return 0

        # 8. Check for active session before executing operational subcommands
        if not client.token:
            sess = config.load_session()
            if not sess:
                output.print_error("Authentication required. Run 'nexus connect <url>' or 'nexus login' first.")
                return 1
            client.set_token(sess.get("token"))

        # 9. Dispatch commands
        cmd = args.command
        if cmd == "status":
            return cmd_status_mod.cmd_status(client, args, as_json)
        elif cmd == "vault":
            return cmd_vault_mod.cmd_vault(client, args, as_json)
        elif cmd == "media":
            return cmd_media_mod.cmd_media(client, args, as_json)
        elif cmd == "tasks":
            return cmd_tasks_mod.cmd_tasks(client, args, as_json)
        elif cmd == "ai":
            if getattr(args, "model_or_prompt", None):
                if args.ai_action == "select":
                    args.model = args.model_or_prompt
                elif args.ai_action == "chat":
                    args.prompt = args.model_or_prompt
            return cmd_ai_mod.cmd_ai(client, args, as_json)
        elif cmd == "rag":
            return cmd_rag_mod.cmd_rag(client, args, as_json)
        elif cmd == "shares":
            if getattr(args, "filename_or_id", None):
                if args.shares_action in ["create", "add"]:
                    args.filename = args.filename_or_id
                elif args.shares_action in ["revoke", "delete", "rm"]:
                    args.share_id = args.filename_or_id
            return cmd_shares_mod.cmd_shares(client, args, as_json)
        elif cmd == "account":
            return cmd_account_mod.cmd_account(client, args, as_json)
        elif cmd == "services":
            return cmd_services_mod.cmd_services(client, args, as_json)
        elif cmd == "models":
            return cmd_models_mod.cmd_models(client, args, as_json)
        elif cmd == "diagnostics":
            return cmd_diag_mod.cmd_diagnostics(client, args, as_json)
        elif cmd == "logs":
            return cmd_logs_mod.cmd_logs(client, args, as_json)
        elif cmd == "users":
            return cmd_users_mod.cmd_users(client, args, as_json)
        elif cmd == "backups":
            return cmd_backups_mod.cmd_backups(client, args, as_json)
        elif cmd == "automation":
            return cmd_auto_mod.cmd_automation(client, args, as_json)
        elif cmd == "settings":
            return cmd_settings_mod.cmd_settings(client, args, as_json)
        elif cmd == "database":
            return cmd_db_mod.cmd_database(client, args, as_json)
        else:
            output.print_error(f"Unknown command '{cmd}'. Run 'nexus --help'.")
            return 1

    except KeyboardInterrupt:
        print("\nOperation cancelled.")
        return 130
    except NexusConnectionError as e:
        output.print_error(str(e))
        if debug:
            import traceback
            traceback.print_exc()
        return 1
    except NexusError as e:
        output.print_error(str(e))
        if debug:
            import traceback
            traceback.print_exc()
        return 1
    except Exception as e:
        output.print_error(f"Unexpected error: {e}")
        if debug:
            import traceback
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
