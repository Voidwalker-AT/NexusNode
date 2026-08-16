#!/data/data/com.termux/files/usr/bin/sh
# ==============================================================================
# NexusNode — OpenSSH Key-Based Dual Access Configuration Script for Termux
#
# SAFETY NOTICE:
# - This script backs up sshd_config before making changes.
# - It validates syntax with 'sshd -t'.
# - It does NOT restart the SSH daemon automatically.
# - The operator account (u0_a208) retains full unrestricted shell access.
# - Application users with registered SSH keys receive the restricted NexusNode shell.
# ==============================================================================

set -e

PREFIX="/data/data/com.termux/files/usr"
HOME_DIR="/data/data/com.termux/files/home"
SSHD_CONFIG="$PREFIX/etc/ssh/sshd_config"
SERVER_DIR="$HOME_DIR/server"
SSH_AUTH_SCRIPT="$SERVER_DIR/scripts/nexus_ssh_auth.py"
NEXUS_SHELL="$SERVER_DIR/nexus_shell.py"
CURRENT_USER=$(whoami 2>/dev/null || echo "u0_a208")
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_CONFIG="$SSHD_CONFIG.bak.$TIMESTAMP"

echo "============================================================"
echo "NexusNode — OpenSSH Key-Based Dual Access Setup"
echo "Host Termux User: $CURRENT_USER"
echo "SSHD Config:      $SSHD_CONFIG"
echo "============================================================"

# 1. Ensure scripts have execution permissions
chmod +x "$NEXUS_SHELL" 2>/dev/null || true
chmod +x "$SSH_AUTH_SCRIPT" 2>/dev/null || true
mkdir -p "$SERVER_DIR/storage_vault"

# 2. Check if sshd_config exists
if [ ! -f "$SSHD_CONFIG" ]; then
    echo "[!] Warning: $SSHD_CONFIG not found. Creating minimal default..."
    mkdir -p "$PREFIX/etc/ssh"
    cat <<EOF > "$SSHD_CONFIG"
Port 8022
PubkeyAuthentication yes
AuthorizedKeysFile .ssh/authorized_keys
EOF
fi

# 3. Create timestamped backup of sshd_config
echo "[1/4] Creating backup of sshd_config -> $BACKUP_CONFIG..."
cp "$SSHD_CONFIG" "$BACKUP_CONFIG"

# 4. Check if AuthorizedKeysCommand is already present
if grep -q "nexus_ssh_auth.py" "$SSHD_CONFIG"; then
    echo "[*] AuthorizedKeysCommand is already configured in $SSHD_CONFIG."
else
    echo "[2/4] Appending AuthorizedKeysCommand hook to $SSHD_CONFIG..."
    cat <<EOF >> "$SSHD_CONFIG"

# --- NexusNode Key-Based Identity Mapping Hook ---
AuthorizedKeysCommand $PREFIX/bin/python $SSH_AUTH_SCRIPT %u %k %t
AuthorizedKeysCommandUser $CURRENT_USER
EOF
fi

# 5. Validate configuration with sshd -t
echo "[3/4] Validating sshd configuration syntax (sshd -t)..."
if sshd -t; then
    echo "[+] SSH configuration validation PASSED."
else
    echo "[-] ERROR: sshd configuration validation FAILED!"
    echo "[!] Restoring previous configuration from $BACKUP_CONFIG..."
    cp "$BACKUP_CONFIG" "$SSHD_CONFIG"
    echo "[!] Rollback complete. sshd_config restored to original state."
    exit 1
fi

echo "[4/4] Configuration applied safely."
echo ""
echo "============================================================"
echo "CONFIGURATION SUMMARY & NEXT STEPS"
echo "============================================================"
echo "1. The SSH daemon was NOT restarted automatically to protect remote access."
echo ""
echo "2. Manual verification command:"
echo "   sshd -t"
echo ""
echo "3. To activate changes, restart the runit SSH service:"
echo "   sv restart sshd"
echo ""
echo "4. Rollback command (if needed):"
echo "   cp $BACKUP_CONFIG $SSHD_CONFIG && sv restart sshd"
echo ""
echo "5. Access Verification:"
echo "   • Operator key -> Unrestricted Termux shell (~ $)"
echo "   • User key     -> Restricted NexusNode CLI (nexus> )"
echo "============================================================"
