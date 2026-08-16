#!/usr/bin/env python3
"""
NexusNode — Authoritative OpenSSH Key-Based Identity Mapping Dispatcher
Invoked dynamically by OpenSSH sshd (AuthorizedKeysCommand) on every incoming SSH connection.

OpenSSH sshd_config directive:
    AuthorizedKeysCommand /data/data/com.termux/files/usr/bin/python /data/data/com.termux/files/home/server/scripts/nexus_ssh_auth.py %u %k %t
    AuthorizedKeysCommandUser u0_a208

SECURITY ARCHITECTURE:
- Transport Account: Client always connects as host Termux account (e.g. u0_a208).
- Operator Key: Handled natively by OpenSSH via AuthorizedKeysFile .ssh/authorized_keys -> Unrestricted Termux shell (~ $).
- NexusNode User Key: AuthorizedKeysCommand receives %k, calculates SHA256 fingerprint, resolves single user in SQLite,
  and outputs ONLY the matching public key with forced nexus_shell.py execution and strict forwarding blocks.
- Unknown / Revoked / Deleted-user Key: Outputs nothing -> Connection rejected immediately.
"""

import os
import sys
import base64
import hashlib

SERVER_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SERVER_ROOT not in sys.path:
    sys.path.insert(0, SERVER_ROOT)

import config
import app as nexus_app


def compute_key_fingerprint(k_arg: str) -> str | None:
    """Computes OpenSSH SHA256 fingerprint from incoming %k key blob or formatted key string."""
    k_clean = k_arg.strip()
    if not k_clean:
        return None

    parts = k_clean.split()
    if len(parts) >= 2 and parts[0].startswith(("ssh-", "ecdsa-")):
        key_b64 = parts[1].strip()
    else:
        key_b64 = parts[0].strip()

    padded_b64 = key_b64 + "=" * ((4 - len(key_b64) % 4) % 4)
    try:
        raw_bytes = base64.b64decode(padded_b64)
        digest = hashlib.sha256(raw_bytes).digest()
        fp_b64 = base64.b64encode(digest).decode("ascii").rstrip("=")
        return f"SHA256:{fp_b64}"
    except Exception:
        return None


def main():
    # 1. Target Transport Account Validation
    # Application keys must ONLY authenticate against the host Termux user (e.g. u0_a208).
    connecting_user = sys.argv[1].strip() if len(sys.argv) > 1 else ""
    host_user = os.environ.get("USER") or os.environ.get("LOGNAME") or "u0_a208"
    valid_transport_users = {host_user, "u0_a208", "root"}

    if connecting_user and connecting_user not in valid_transport_users:
        # Do not treat application users (anmol, papa, rahul) as Unix accounts
        return 0

    # 2. Exact Incoming Key Resolution (%k)
    incoming_k = sys.argv[2].strip() if len(sys.argv) > 2 else ""
    if not incoming_k:
        # No key presented to dispatcher; operator keys are resolved by AuthorizedKeysFile
        return 0

    incoming_fp = compute_key_fingerprint(incoming_k)
    if not incoming_fp:
        return 0

    # 3. Authoritative SQLite Query for EXACT Matching Key
    try:
        key_rec = nexus_app.db_get_ssh_key_by_fingerprint(incoming_fp)
        if not key_rec:
            # Unknown key -> emit nothing
            return 0

        # Check if key is revoked
        if key_rec.get("revoked", 0) != 0:
            # Revoked key -> emit nothing
            return 0

        user_id = (key_rec.get("user_id") or "").strip().lower()
        if not user_id:
            return 0

        # 4. Verify Associated Application User Exists & Is Active
        user = nexus_app.db_get_user(user_id)
        if not user:
            # Deleted or non-existent user -> emit nothing
            return 0

        # 5. Emit ONLY the single matching key with forced command and tight restrictions
        python_bin = sys.executable or "/data/data/com.termux/files/usr/bin/python"
        shell_script = os.path.join(SERVER_ROOT, "nexus_shell.py")

        ktype = key_rec.get("key_type", "ssh-ed25519")
        kpub = key_rec.get("public_key", "")
        label = key_rec.get("label") or user_id

        if kpub:
            forced_cmd = (
                f'command="{python_bin} {shell_script} --user {user_id}",'
                f'no-port-forwarding,no-X11-forwarding,no-agent-forwarding,no-user-rc '
                f'{ktype} {kpub} {label}'
            )
            print(forced_cmd)

    except Exception:
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
