#!/data/data/com.termux/files/usr/bin/sh
# ==============================================================================
# NexusNode — OpenSSH Dual-Layer Access Setup Script for Termux
# Configures OpenSSH to support both:
#   1. Administrator / Operator full Termux shell (e.g. u0_a208)
#   2. NexusNode Application Users (e.g. anmol) restricted to NexusNode CLI
# ==============================================================================

set -e

PREFIX="/data/data/com.termux/files/usr"
HOME_DIR="/data/data/com.termux/files/home"
SSHD_CONFIG="$PREFIX/etc/ssh/sshd_config"
SERVER_DIR="$HOME_DIR/server"
SSH_AUTH_SCRIPT="$SERVER_DIR/scripts/nexus_ssh_auth.py"
NEXUS_SHELL="$SERVER_DIR/nexus_shell.py"
CURRENT_USER=$(whoami)

echo "============================================================"
echo "NexusNode — OpenSSH Dual-Access Configuration"
echo "Current Termux User: $CURRENT_USER"
echo "============================================================"

# Ensure permissions
chmod +x "$NEXUS_SHELL" || true
chmod +x "$SSH_AUTH_SCRIPT" || true
mkdir -p "$SERVER_DIR/storage_vault/ssh_keys"

# Symlink nexus-shell to bin directory for convenience
if [ -d "$PREFIX/bin" ]; then
    ln -sf "$NEXUS_SHELL" "$PREFIX/bin/nexus-shell"
    echo "[+] Created symlink: $PREFIX/bin/nexus-shell"
fi

# Ensure sshd_config exists
if [ ! -f "$SSHD_CONFIG" ]; then
    echo "Creating default sshd_config..."
    mkdir -p "$PREFIX/etc/ssh"
    cat <<EOF > "$SSHD_CONFIG"
Port 8022
PermitRootLogin yes
PasswordAuthentication yes
PubkeyAuthentication yes
AuthorizedKeysFile .ssh/authorized_keys
EOF
fi

# Backup existing config
cp "$SSHD_CONFIG" "$SSHD_CONFIG.bak.$(date +%s)"

# Configure AuthorizedKeysCommand if not already present
if ! grep -q "nexus_ssh_auth.py" "$SSHD_CONFIG"; then
    echo "[+] Configuring AuthorizedKeysCommand in $SSHD_CONFIG..."
    cat <<EOF >> "$SSHD_CONFIG"

# NexusNode Dual-Access Authorization Hook
AuthorizedKeysCommand $PREFIX/bin/python $SSH_AUTH_SCRIPT %u %k %t
AuthorizedKeysCommandUser $CURRENT_USER
EOF
    echo "[+] AuthorizedKeysCommand configured successfully."
else
    echo "[*] AuthorizedKeysCommand already configured in $SSHD_CONFIG."
fi

echo "============================================================"
echo "Configuration Complete!"
echo "Restart sshd service via runit: sv restart sshd"
echo "============================================================"
