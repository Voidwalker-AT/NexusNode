#!/usr/bin/env python3
"""
NexusNode — OpenSSH AuthorizedKeysCommand Dispatcher
Invoked by OpenSSH sshd to map incoming SSH public keys to NexusNode restricted shells.

OpenSSH sshd_config directive:
    AuthorizedKeysCommand /data/data/com.termux/files/usr/bin/python /data/data/com.termux/files/home/server/scripts/nexus_ssh_auth.py %u %k %t
    AuthorizedKeysCommandUser u0_a208

ARCHITECTURE:
- If user is the Termux operator account (e.g. u0_a208 / admin), returns normal authorized_keys for unrestricted OS shell.
- If user is a NexusNode application account (e.g. anmol), returns the key prefixed with:
  command="python /path/to/nexus_shell.py --user <username>",no-port-forwarding,no-X11-forwarding,no-agent-forwarding <key>
"""

import os
import sys
import sqlite3

SERVER_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SERVER_ROOT not in sys.path:
    sys.path.insert(0, SERVER_ROOT)

import config
import app as nexus_app


def main():
    if len(sys.argv) < 2:
        sys.exit(0)

    target_user = sys.argv[1].strip().lower()
    ssh_keys_dir = os.path.join(config.STORAGE_DIR, "ssh_keys")
    os.makedirs(ssh_keys_dir, exist_ok=True)

    # 1. System OS / Termux Operator Account: return standard authorized_keys
    termux_user = os.environ.get("USER", "u0_a208")
    if target_user in [termux_user, "admin_os", "root"]:
        user_auth_keys = os.path.expanduser("~/.ssh/authorized_keys")
        if os.path.exists(user_auth_keys):
            with open(user_auth_keys, "r", encoding="utf-8") as f:
                print(f.read().strip())
        return

    # 2. NexusNode Application User: check if user exists in database
    user = nexus_app.db_get_user(target_user)
    if not user:
        # User not recognized in NexusNode DB
        sys.exit(0)

    # Look for user's public key file in storage_vault/ssh_keys/<user>.pub
    user_key_file = os.path.join(ssh_keys_dir, f"{target_user}.pub")
    python_bin = sys.executable or "/data/data/com.termux/files/usr/bin/python"
    shell_script = os.path.join(SERVER_ROOT, "nexus_shell.py")

    if os.path.exists(user_key_file):
        with open(user_key_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    forced_cmd = f'command="{python_bin} {shell_script} --user {target_user}",no-port-forwarding,no-X11-forwarding,no-agent-forwarding {line}'
                    print(forced_cmd)


if __name__ == "__main__":
    main()
