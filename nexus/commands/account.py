"""
NexusNode CLI — Account & Profile Command
Exposes session status, current role, permissions, and logout.
"""

from .. import auth
from .. import output
from ..client import NexusClient


def cmd_account(client: NexusClient, args, as_json: bool = False) -> int:
    """Dispatcher for 'nexus account' subcommands."""
    subaction = getattr(args, "account_action", None) or "whoami"

    if subaction == "whoami" or subaction == "session":
        res = auth.whoami(client, as_json=as_json or getattr(args, "json", False))
        return 0 if res else 1
    elif subaction == "logout":
        auth.logout(client, as_json=as_json or getattr(args, "json", False))
        return 0
    else:
        output.print_error(f"Unknown account subcommand '{subaction}'. Type 'nexus account --help'.")
        return 1
