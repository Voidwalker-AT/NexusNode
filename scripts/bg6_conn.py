"""
NexusNode — Secure BG6 SSH Connection Helper
Prefers authorized OpenSSH Ed25519 identity key.
Falls back to BG6_SSH_PASSWORD environment variable if set.
Zero hardcoded passwords.
"""

import os
import paramiko

def get_bg6_ssh_client(
    host: str = "192.168.29.21",
    port: int = 8022,
    username: str = "u0_a208",
    timeout: int = 10
) -> paramiko.SSHClient:
    """Creates a hardened SSH connection to the physical BG6 server."""
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.WarningPolicy())
    
    key_file = os.environ.get("BG6_SSH_KEY", os.path.expanduser("~/.ssh/nexusnode_bg6_ed25519"))
    key_filename = key_file if os.path.exists(key_file) else None
    password = os.environ.get("BG6_SSH_PASSWORD")
    
    if key_filename:
        client.connect(host, port=port, username=username, key_filename=key_filename, timeout=timeout)
    elif password:
        client.connect(host, port=port, username=username, password=password, timeout=timeout)
    else:
        # Attempt agent / default keys
        client.connect(host, port=port, username=username, timeout=timeout)
        
    return client
