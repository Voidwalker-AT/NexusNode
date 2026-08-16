#!/usr/bin/env python3
"""
NexusNode — OpenSSH Key-Based Identity Mapping Dispatcher
Invoked dynamically by OpenSSH sshd (AuthorizedKeysCommand) on every incoming SSH connection.

ARCHITECTURE:
- The SSH transport account is ALWAYS the host Termux user (e.g. u0_a208).
- Client connects as: `ssh -i ~/.ssh/nexus_anmol -p 8022 u0_a208@PHONE_IP`
- AuthorizedKeysCommand resolves the public key against registered NexusNode identities:
    1. Operator Key (e.g. ~/.ssh/authorized_keys): outputs unconstrained key -> Unrestricted Termux Shell (~ $)
    2. NexusNode User Key (SQLite ssh_keys): outputs forced command key -> Restricted NexusNode Shell (nexus> )
    3. Revoked or Unknown Keys: not output -> Authentication rejected immediately.
"""

import os
import sys

SERVER_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SERVER_ROOT not in sys.path:
    sys.path.insert(0, SERVER_ROOT)

import config
import app as nexus_app


def main():
    connecting_user = sys.argv[1].strip() if len(sys.argv) > 1 else os.environ.get("USER", "u0_a208")

    # 1. Output Operator Keys for unrestricted Termux administrative shell (~ $)
    operator_keys_file = os.path.expanduser("~/.ssh/authorized_keys")
    if os.path.exists(operator_keys_file):
        try:
            with open(operator_keys_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "nexus_shell" not in line:
                        print(line)
        except Exception:
            pass

    # 2. Output Registered NexusNode Application User Keys with forced restricted command
    python_bin = sys.executable or "/data/data/com.termux/files/usr/bin/python"
    shell_script = os.path.join(SERVER_ROOT, "nexus_shell.py")

    # Query active, non-revoked SSH keys from SQLite database
    try:
        keys = nexus_app.db_list_ssh_keys(include_revoked=False)
        for k in keys:
            user_id = k.get("user_id", "").strip().lower()
            if not user_id:
                continue

            # Verify that the associated application user exists in SQLite users table
            user = nexus_app.db_get_user(user_id)
            if not user:
                continue

            ktype = k.get("key_type", "ssh-ed25519")
            kpub = k.get("public_key", "")
            label = k.get("label") or user_id

            if kpub:
                forced_cmd = (
                    f'command="{python_bin} {shell_script} --user {user_id}",'
                    f'no-port-forwarding,no-X11-forwarding,no-agent-forwarding '
                    f'{ktype} {kpub} {label}'
                )
                print(forced_cmd)
    except Exception:
        pass


if __name__ == "__main__":
    main()
