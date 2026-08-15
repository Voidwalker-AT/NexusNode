#!/data/data/com.termux/files/usr/bin/sh
# ==============================================================================
# NexusNode Service Installation Script (Idempotent)
# Sets up runit service supervision & Termux:Boot integration on Android Termux
# ==============================================================================

set -e

PREFIX="/data/data/com.termux/files/usr"
HOME="/data/data/com.termux/files/home"
SERVER_DIR="$HOME/server"

if [ ! -d "$SERVER_DIR" ]; then
    SERVER_DIR="$(cd "$(dirname "$0")/.." && pwd)"
fi

echo "============================================================"
echo " 🚀 NexusNode 24/7 Mobile Service Supervisor Installer"
echo "============================================================"

# 1. Ensure required log & service directories exist
mkdir -p "$HOME/nexus_logs/nexusnode"
mkdir -p "$HOME/nexus_logs/localtonet"
mkdir -p "$HOME/nexus_logs/ollama"
mkdir -p "$HOME/nexus_logs/sshd"
mkdir -p "$HOME/.termux/boot"

# 2. Check for termux-services package
if ! command -v sv > /dev/null 2>&1; then
    echo "[*] Installing termux-services package for runit supervision..."
    pkg update -y || true
    pkg install -y termux-services || true
fi

# 3. Install Services into $PREFIX/var/service (if available) or ~/.nexus_sv
SV_TARGET="$PREFIX/var/service"
if [ ! -d "$SV_TARGET" ]; then
    SV_TARGET="$HOME/.nexus_sv"
    mkdir -p "$SV_TARGET"
fi

echo "[*] Installing service definitions to $SV_TARGET..."

for SVC in nexusnode localtonet ollama sshd; do
    SRC_DIR="$SERVER_DIR/services/$SVC"
    DEST_DIR="$SV_TARGET/$SVC"

    # Single SSHD Supervisor Ownership Rule:
    # If Termux official openssh service already exists at $SV_TARGET/sshd, do not overwrite it.
    if [ "$SVC" = "sshd" ] && [ -f "$DEST_DIR/run" ] && [ "$SV_TARGET" = "$PREFIX/var/service" ]; then
        echo "  ✔ Using Termux official sshd service in $DEST_DIR (avoiding duplicate supervisor)"
        continue
    fi

    if [ -d "$SRC_DIR" ]; then
        mkdir -p "$DEST_DIR/log"
        cp -f "$SRC_DIR/run" "$DEST_DIR/run"
        chmod +x "$DEST_DIR/run"

        if [ -f "$SRC_DIR/log/run" ]; then
            cp -f "$SRC_DIR/log/run" "$DEST_DIR/log/run"
            chmod +x "$DEST_DIR/log/run"
        fi

        # Make optional services down by default
        if [ "$SVC" = "ollama" ]; then
            touch "$DEST_DIR/down"
        fi

        echo "  ✔ Configured service: $SVC"
    fi
done

# 4. Install Termux:Boot script
BOOT_SCRIPT="$HOME/.termux/boot/start-nexusnode.sh"
if [ -f "$SERVER_DIR/scripts/boot/termux_boot.sh" ]; then
    cp -f "$SERVER_DIR/scripts/boot/termux_boot.sh" "$BOOT_SCRIPT"
    chmod +x "$BOOT_SCRIPT"
    echo "[*] Termux:Boot auto-startup script installed at: $BOOT_SCRIPT"
fi

echo ""
echo "============================================================"
echo " ✅ Installation Complete!"
echo "============================================================"
echo " Service Control Commands (run in Termux):"
echo "  • sv up nexusnode        - Start NexusNode server"
echo "  • sv down nexusnode      - Stop NexusNode server"
echo "  • sv status nexusnode    - Check NexusNode service status"
echo "  • sv status localtonet   - Check LocalToNet tunnel status"
echo "  • sv status sshd         - Check SSH service status"
echo "  • sv up ollama           - Start optional Ollama AI engine"
echo "  • sv down ollama         - Stop optional Ollama AI engine"
echo "============================================================"
