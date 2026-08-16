"""
NexusNode CLI — Interactive REPL Shell
Dedicated application shell with command autocompletion and error handling.
Does NOT execute arbitrary OS commands.
"""

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
    Interactive application shell for NexusNode.
    """
    prompt = "nexus> "

    def __init__(self, client: NexusClient, session_info: dict = None):
        super().__init__()
        self.client = client
        self.session_info = session_info or {}
        user_id = self.session_info.get("user_id", "user")
        role = self.session_info.get("role", "user")
        self.intro = (
            f"\nNexusNode Interactive CLI\n"
            f"Server:   {self.client.server_url}\n"
            f"User:     {user_id} (Role: {role.upper()})\n"
            f"Type 'help' or '?' to list commands. Type 'exit' to quit.\n"
        )

    def default(self, line):
        cmd_name = line.strip().split()[0] if line.strip() else ""
        if cmd_name in ["bash", "sh", "python", "python3", "powershell", "cmd", "rm", "cd", "ls", "cat", "chmod"]:
            output.print_error(f"'{cmd_name}' is not an arbitrary OS shell command. Type 'help' for available NexusNode commands.")
        else:
            output.print_error(f"Unknown command '{cmd_name}'. Type 'help' for available commands.")

    def emptyline(self):
        pass

    def do_exit(self, arg):
        """Exit the NexusNode interactive CLI."""
        print("Goodbye.")
        return True

    def do_quit(self, arg):
        """Exit the NexusNode interactive CLI."""
        return self.do_exit(arg)

    def do_logout(self, arg):
        """Log out and revoke current session."""
        auth.logout(self.client)
        return True

    def do_whoami(self, arg):
        """Show current authenticated user and session details."""
        auth.whoami(self.client)

    # --- User Commands ---
    def do_status(self, arg):
        """Show system health, resource governor telemetry, and storage metrics."""
        args_mock = argparse.Namespace(json=False)
        cmd_status_mod.cmd_status(self.client, args_mock)

    def do_vault(self, arg):
        """Vault storage management: vault [list|info|download|delete|checksum|clean-temp]"""
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
        action = parts[0] if parts else "library"
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
        parts = shlex.split(arg) if arg else []
        action = parts[0] if parts else "status"
        args_mock = argparse.Namespace(
            service_action=action,
            service_name=parts[1] if len(parts) > 1 else None,
            json=False
        )
        cmd_services_mod.cmd_services(self.client, args_mock)

    def complete_services(self, text, line, begidx, endidx):
        subcmds = ["status", "start", "stop", "restart"]
        return [s for s in subcmds if s.startswith(text)]

    def do_models(self, arg):
        """Admin: AI Model management & memory estimation: models [list|details|estimate]"""
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
        subcmds = ["list", "details", "estimate"]
        return [s for s in subcmds if s.startswith(text)]

    def do_diagnostics(self, arg):
        """Admin: Technical diagnostics & root-cause report: diagnostics [system|full|profile|network]"""
        parts = shlex.split(arg) if arg else []
        action = parts[0] if parts else "system"
        args_mock = argparse.Namespace(
            diag_action=action,
            target=parts[1] if len(parts) > 1 else "internet",
            json=False
        )
        cmd_diag_mod.cmd_diagnostics(self.client, args_mock)

    def complete_diagnostics(self, text, line, begidx, endidx):
        subcmds = ["system", "full", "profile", "network"]
        return [s for s in subcmds if s.startswith(text)]

    def do_logs(self, arg):
        """Admin: Query or stream system logs: logs [recent|stream]"""
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
        subcmds = ["recent", "stream"]
        return [s for s in subcmds if s.startswith(text)]

    def do_users(self, arg):
        """Admin: User accounts & RBAC management: users [list|create|delete|privileges]"""
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
        subcmds = ["list", "create", "delete", "privileges"]
        return [s for s in subcmds if s.startswith(text)]

    def do_backups(self, arg):
        """Admin: System backup archives & restore: backups [list|create|restore|download]"""
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
        subcmds = ["list", "create", "restore", "download"]
        return [s for s in subcmds if s.startswith(text)]

    def do_automation(self, arg):
        """Admin: Scheduled background jobs: automation [list|run|toggle]"""
        parts = shlex.split(arg) if arg else []
        action = parts[0] if parts else "list"
        args_mock = argparse.Namespace(
            auto_action=action,
            job_id=parts[1] if len(parts) > 1 else None,
            json=False
        )
        cmd_auto_mod.cmd_automation(self.client, args_mock)

    def complete_automation(self, text, line, begidx, endidx):
        subcmds = ["list", "run", "toggle"]
        return [s for s in subcmds if s.startswith(text)]

    def do_settings(self, arg):
        """Admin: View or change appliance settings: settings [get|set] <key> [val]"""
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
        subcmds = ["get", "set"]
        return [s for s in subcmds if s.startswith(text)]

    def do_database(self, arg):
        """Admin: SQLite database inspection: database [diagnostics|query]"""
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
        subcmds = ["diagnostics", "query"]
        return [s for s in subcmds if s.startswith(text)]
