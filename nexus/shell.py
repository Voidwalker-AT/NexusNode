from __future__ import annotations

import sys
import cmd
import shlex
import argparse

from . import auth
from . import output
from .client import NexusClient
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


class NexusShell(cmd.Cmd):
    """
    Authoritative interactive application terminal for NexusNode.
    """
    prompt = "nexus> "

    def __init__(self, client: NexusClient, session_info: dict = None):
        super().__init__()
        self.client = client
        self.session_info = session_info or {}
        self.user_id = self.session_info.get("user_id", "user")
        self.role = (self.session_info.get("role") or "user").lower()
        self.intro = ""
        if output.is_color_enabled():
            self.prompt = output.cyan("nexus>", bold=True) + " "
        else:
            self.prompt = "nexus> "

    def get_names(self):
        """Filters available command names by user role for tab completion and help."""
        names = super().get_names()
        if self.role != "admin":
            admin_cmds = [
                "do_services", "do_models", "do_diagnostics", "do_logs",
                "do_users", "do_backups", "do_automation", "do_settings", "do_database"
            ]
            names = [n for n in names if n not in admin_cmds]
        return names

    def default(self, line):
        cmd_name = line.strip().split()[0] if line.strip() else ""
        if cmd_name in ["bash", "sh", "python", "python3", "powershell", "cmd", "rm", "cd", "ls", "cat", "chmod", "curl", "wget"]:
            output.print_error(f"'{cmd_name}' is not an OS shell command. Type 'help' for available NexusNode commands.")
        else:
            output.print_error(f"Unknown command '{cmd_name}'. Type 'help' for available commands.")

    def emptyline(self):
        pass

    def do_exit(self, arg):
        """Exit the NexusNode interactive CLI terminal."""
        print("Session disconnected. Goodbye.")
        return True

    def do_quit(self, arg):
        """Exit the NexusNode interactive CLI terminal."""
        return self.do_exit(arg)

    def do_logout(self, arg):
        """Log out and revoke current session."""
        auth.logout(self.client)
        return True

    def do_disconnect(self, arg):
        """Disconnect and revoke current session."""
        return self.do_logout(arg)

    def do_whoami(self, arg):
        """Show current authenticated user and session details."""
        auth.whoami(self.client)

    def do_session(self, arg):
        """Show current session details."""
        auth.whoami(self.client)

    def do_help(self, arg):
        """List available commands categorized by subsystem."""
        if arg:
            # Delegate to standard cmd help for specific command
            super().do_help(arg)
            return

        print("\nNexusNode Application Commands")
        try:
            print("─" * 50)
        except UnicodeEncodeError:
            print("-" * 50)

        print("\nSYSTEM:")
        print("  status                Appliance health, RAM, thermals & services")

        print("\nSTORAGE:")
        print("  vault list            List files in vault storage")
        print("  vault search <term>   Search files by keyword")
        print("  vault download <file> Download file to local machine")
        print("  vault delete <file>   Delete file from vault")

        print("\nMEDIA:")
        print("  media queue           View active & queued media operations")
        print("  media download <url>  Queue background media download (yt-dlp)")
        print("  media library         List downloaded media files")

        print("\nTASKS:")
        print("  tasks list            List all background tasks and states")
        print("  tasks status <id>     Detailed progress for specific task")
        print("  tasks cancel <id>     Safely cancel a running task")

        print("\nAI:")
        print("  ai models             List installed Ollama LLM models")
        print("  ai state              Inspect active LLM inference engine state")
        print("  ai select <model>     Switch active model")
        print("  ai chat <prompt>      Run interactive prompt inference")

        print("\nRAG:")
        print("  rag status            View SQLite FTS5 RAG index stats")
        print("  rag search <query>    Execute full-text semantic search")

        print("\nSHARES:")
        print("  shares list           List active public temporary links")
        print("  shares create <file>  Generate temporary download share")
        print("  shares revoke <id>    Revoke an active share link")

        print("\nACCOUNT:")
        print("  whoami / session      Show active session identity & role")
        print("  disconnect / logout   Revoke session and exit")
        print("  exit / quit           Close terminal session")

        if self.role == "admin":
            print("\nADMINISTRATION:")
            print("  services [status|start|stop|restart] <svc>")
            print("  models   [list|details|estimate] <model>")
            print("  diagnostics [system|full|network]")
            print("  logs     [recent|stream]")
            print("  users    [list|create|delete|privileges]")
            print("  backups  [list|create|restore|download]")
            print("  automation [list|run|toggle]")
            print("  settings [get|set] <key> [val]")
            print("  database [diagnostics|query] <table>")

        print()

    # --- User Commands ---
    def do_status(self, arg):
        """Show system health, resource governor telemetry, and storage metrics."""
        args_mock = argparse.Namespace(json=False)
        cmd_status_mod.cmd_status(self.client, args_mock)

    def do_vault(self, arg):
        """Vault storage management: vault [list|search|info|download|delete|checksum|clean-temp]"""
        parts = shlex.split(arg) if arg else []
        action = parts[0] if parts else "list"
        args_mock = argparse.Namespace(
            vault_action=action,
            filename=parts[1] if len(parts) > 1 else None,
            dest=parts[2] if len(parts) > 2 else None,
            search=parts[1] if action == "search" and len(parts) > 1 else None,
            category=None,
            yes=False,
            json=False
        )
        cmd_vault_mod.cmd_vault(self.client, args_mock)

    def complete_vault(self, text, line, begidx, endidx):
        subcmds = ["list", "search", "info", "download", "delete", "checksum", "clean-temp"]
        return [s for s in subcmds if s.startswith(text)]

    def do_media(self, arg):
        """Media center operations: media [download|library|queue]"""
        parts = shlex.split(arg) if arg else []
        action = parts[0] if parts else "queue"
        args_mock = argparse.Namespace(
            media_action=action,
            url=parts[1] if len(parts) > 1 else None,
            format="mp4",
            quality="best",
            dest="Downloads",
            json=False
        )
        cmd_media_mod.cmd_media(self.client, args_mock)

    def complete_media(self, text, line, begidx, endidx):
        subcmds = ["download", "library", "queue"]
        return [s for s in subcmds if s.startswith(text)]

    def do_tasks(self, arg):
        """Background tasks management: tasks [list|status|cancel] <task_id>"""
        parts = shlex.split(arg) if arg else []
        action = parts[0] if parts else "list"
        args_mock = argparse.Namespace(
            task_action=action,
            task_id=parts[1] if len(parts) > 1 else None,
            json=False
        )
        cmd_tasks_mod.cmd_tasks(self.client, args_mock)

    def complete_tasks(self, text, line, begidx, endidx):
        subcmds = ["list", "status", "cancel"]
        return [s for s in subcmds if s.startswith(text)]

    def do_ai(self, arg):
        """Remote AI inference & state: ai [models|state|select|chat|metrics]"""
        parts = shlex.split(arg) if arg else []
        action = parts[0] if parts else "state"
        args_mock = argparse.Namespace(
            ai_action=action,
            model=parts[1] if len(parts) > 1 else None,
            prompt=" ".join(parts[1:]) if action == "chat" and len(parts) > 1 else None,
            json=False
        )
        cmd_ai_mod.cmd_ai(self.client, args_mock)

    def complete_ai(self, text, line, begidx, endidx):
        subcmds = ["models", "state", "select", "chat", "metrics"]
        return [s for s in subcmds if s.startswith(text)]

    def do_rag(self, arg):
        """SQLite FTS5 RAG operations: rag [status|search|sources|index|compact]"""
        parts = shlex.split(arg) if arg else []
        action = parts[0] if parts else "status"
        args_mock = argparse.Namespace(
            rag_action=action,
            query=" ".join(parts[1:]) if len(parts) > 1 else None,
            json=False
        )
        cmd_rag_mod.cmd_rag(self.client, args_mock)

    def complete_rag(self, text, line, begidx, endidx):
        subcmds = ["status", "search", "sources", "index", "compact"]
        return [s for s in subcmds if s.startswith(text)]

    def do_shares(self, arg):
        """Temporary share links: shares [list|create|revoke]"""
        parts = shlex.split(arg) if arg else []
        action = parts[0] if parts else "list"
        args_mock = argparse.Namespace(
            shares_action=action,
            filename=parts[1] if len(parts) > 1 else None,
            share_id=parts[1] if action == "revoke" and len(parts) > 1 else None,
            expire_hours=24,
            max_downloads=10,
            json=False
        )
        cmd_shares_mod.cmd_shares(self.client, args_mock)

    def complete_shares(self, text, line, begidx, endidx):
        subcmds = ["list", "create", "revoke"]
        return [s for s in subcmds if s.startswith(text)]

    # --- Admin Commands ---
    def do_services(self, arg):
        """Admin: System services supervision: services [status|start|stop|restart] <svc>"""
        if self.role != "admin":
            output.print_error("Permission denied: services management requires administrator role.")
            return
        parts = shlex.split(arg) if arg else []
        action = parts[0] if parts else "status"
        args_mock = argparse.Namespace(
            service_action=action,
            service_name=parts[1] if len(parts) > 1 else None,
            json=False
        )
        cmd_services_mod.cmd_services(self.client, args_mock)

    def complete_services(self, text, line, begidx, endidx):
        if self.role != "admin":
            return []
        subcmds = ["status", "start", "stop", "restart"]
        return [s for s in subcmds if s.startswith(text)]

    def do_models(self, arg):
        """Admin: AI Model management & memory estimation: models [list|details|estimate]"""
        if self.role != "admin":
            output.print_error("Permission denied: model management requires administrator role.")
            return
        parts = shlex.split(arg) if arg else []
        action = parts[0] if parts else "list"
        args_mock = argparse.Namespace(
            model_action=action,
            model_name=parts[1] if len(parts) > 1 else None,
            param="1.5b",
            quant="q4_k_m",
            json=False
        )
        cmd_models_mod.cmd_models(self.client, args_mock)

    def complete_models(self, text, line, begidx, endidx):
        if self.role != "admin":
            return []
        subcmds = ["list", "details", "estimate"]
        return [s for s in subcmds if s.startswith(text)]

    def do_diagnostics(self, arg):
        """Admin: Technical diagnostics & root-cause report: diagnostics [system|full|profile|network]"""
        if self.role != "admin":
            output.print_error("Permission denied: diagnostics requires administrator role.")
            return
        parts = shlex.split(arg) if arg else []
        action = parts[0] if parts else "system"
        args_mock = argparse.Namespace(
            diag_action=action,
            target=parts[1] if len(parts) > 1 else "internet",
            json=False
        )
        cmd_diag_mod.cmd_diagnostics(self.client, args_mock)

    def complete_diagnostics(self, text, line, begidx, endidx):
        if self.role != "admin":
            return []
        subcmds = ["system", "full", "profile", "network"]
        return [s for s in subcmds if s.startswith(text)]

    def do_logs(self, arg):
        """Admin: Query or stream system logs: logs [recent|stream]"""
        if self.role != "admin":
            output.print_error("Permission denied: log viewing requires administrator role.")
            return
        parts = shlex.split(arg) if arg else []
        action = parts[0] if parts else "recent"
        args_mock = argparse.Namespace(
            log_action=action,
            limit=50,
            level=None,
            component=None,
            json=False
        )
        cmd_logs_mod.cmd_logs(self.client, args_mock)

    def complete_logs(self, text, line, begidx, endidx):
        if self.role != "admin":
            return []
        subcmds = ["recent", "stream"]
        return [s for s in subcmds if s.startswith(text)]

    def do_users(self, arg):
        """Admin: User accounts & RBAC management: users [list|create|delete|privileges]"""
        if self.role != "admin":
            output.print_error("Permission denied: user management requires administrator role.")
            return
        parts = shlex.split(arg) if arg else []
        action = parts[0] if parts else "list"
        args_mock = argparse.Namespace(
            user_action=action,
            username=parts[1] if len(parts) > 1 else None,
            password=None,
            role="user",
            grant=None,
            revoke=None,
            yes=False,
            json=False
        )
        cmd_users_mod.cmd_users(self.client, args_mock)

    def complete_users(self, text, line, begidx, endidx):
        if self.role != "admin":
            return []
        subcmds = ["list", "create", "delete", "privileges"]
        return [s for s in subcmds if s.startswith(text)]

    def do_backups(self, arg):
        """Admin: System backup archives & restore: backups [list|create|restore|download]"""
        if self.role != "admin":
            output.print_error("Permission denied: backup management requires administrator role.")
            return
        parts = shlex.split(arg) if arg else []
        action = parts[0] if parts else "list"
        args_mock = argparse.Namespace(
            backup_action=action,
            backup_id=parts[1] if len(parts) > 1 else None,
            dest=None,
            yes=False,
            json=False
        )
        cmd_backups_mod.cmd_backups(self.client, args_mock)

    def complete_backups(self, text, line, begidx, endidx):
        if self.role != "admin":
            return []
        subcmds = ["list", "create", "restore", "download"]
        return [s for s in subcmds if s.startswith(text)]

    def do_automation(self, arg):
        """Admin: Scheduled background jobs: automation [list|run|toggle]"""
        if self.role != "admin":
            output.print_error("Permission denied: automation management requires administrator role.")
            return
        parts = shlex.split(arg) if arg else []
        action = parts[0] if parts else "list"
        args_mock = argparse.Namespace(
            auto_action=action,
            job_id=parts[1] if len(parts) > 1 else None,
            json=False
        )
        cmd_auto_mod.cmd_automation(self.client, args_mock)

    def complete_automation(self, text, line, begidx, endidx):
        if self.role != "admin":
            return []
        subcmds = ["list", "run", "toggle"]
        return [s for s in subcmds if s.startswith(text)]

    def do_settings(self, arg):
        """Admin: View or change appliance settings: settings [get|set] <key> [val]"""
        if self.role != "admin":
            output.print_error("Permission denied: settings management requires administrator role.")
            return
        parts = shlex.split(arg) if arg else []
        action = parts[0] if parts else "get"
        args_mock = argparse.Namespace(
            setting_action=action,
            key=parts[1] if len(parts) > 1 else None,
            value=parts[2] if len(parts) > 2 else None,
            json=False
        )
        cmd_settings_mod.cmd_settings(self.client, args_mock)

    def complete_settings(self, text, line, begidx, endidx):
        if self.role != "admin":
            return []
        subcmds = ["get", "set"]
        return [s for s in subcmds if s.startswith(text)]

    def do_database(self, arg):
        """Admin: SQLite database inspection: database [diagnostics|query]"""
        if self.role != "admin":
            output.print_error("Permission denied: database management requires administrator role.")
            return
        parts = shlex.split(arg) if arg else []
        action = parts[0] if parts else "diagnostics"
        args_mock = argparse.Namespace(
            db_action=action,
            table=parts[1] if len(parts) > 1 else "users",
            limit=25,
            json=False
        )
        cmd_db_mod.cmd_database(self.client, args_mock)

    def complete_database(self, text, line, begidx, endidx):
        if self.role != "admin":
            return []
        subcmds = ["diagnostics", "query"]
        return [s for s in subcmds if s.startswith(text)]
