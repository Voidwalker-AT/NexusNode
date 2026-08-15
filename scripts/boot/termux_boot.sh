#!/data/data/com.termux/files/usr/bin/sh
# ==============================================================================
# Termux:Boot Startup Script for NexusNode 24/7 Mobile Server Appliance
# Target: ~/.termux/boot/start-nexusnode.sh
# ==============================================================================

# 1. Acquire Android Wake Lock to prevent CPU sleep when screen is locked
if command -v termux-wake-lock > /dev/null 2>&1; then
    termux-wake-lock
    echo "[boot] Acquired Termux WakeLock."
fi

# 2. Environment Setup
export PREFIX="/data/data/com.termux/files/usr"
export HOME="/data/data/com.termux/files/home"
export PATH="$PREFIX/bin:$HOME/.local/bin:$HOME/localtonet:$PATH"
export PYTHONPATH="$HOME/server:$PYTHONPATH"

# Log boot initiation
BOOT_LOG="$HOME/nexus_logs/boot.log"
mkdir -p "$HOME/nexus_logs"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Android Boot Event Received. Initializing NexusNode..." >> "$BOOT_LOG"

# 3. Start Process Supervisor (runit / termux-services)
SVDIR="$PREFIX/var/service"

if [ -d "$SVDIR" ] && command -v sv > /dev/null 2>&1; then
    echo "[boot] Starting termux-services runit supervisor..." >> "$BOOT_LOG"
    # Ensure critical services are up
    sv-enable sshd > /dev/null 2>&1
    sv-enable localtonet > /dev/null 2>&1
    sv-enable nexusnode > /dev/null 2>&1
    sv up sshd >> "$BOOT_LOG" 2>&1
    sv up localtonet >> "$BOOT_LOG" 2>&1
    sv up nexusnode >> "$BOOT_LOG" 2>&1
else
    # Fallback to local runsvdir supervisor
    LOCAL_SV="$HOME/.nexus_sv"
    if [ -d "$LOCAL_SV" ] && command -v runsvdir > /dev/null 2>&1; then
        echo "[boot] Starting standalone runsvdir supervisor on $LOCAL_SV..." >> "$BOOT_LOG"
        runsvdir -P "$LOCAL_SV" >> "$BOOT_LOG" 2>&1 &
    else
        # Direct graceful fallback startup
        echo "[boot] Fallback: starting services directly in background..." >> "$BOOT_LOG"
        sshd -p 8022 >> "$BOOT_LOG" 2>&1 &
        
        if command -v localtonet > /dev/null 2>&1; then
            localtonet >> "$HOME/nexus_logs/localtonet.log" 2>&1 &
        elif [ -x "$HOME/localtonet/localtonet" ]; then
            "$HOME/localtonet/localtonet" >> "$HOME/nexus_logs/localtonet.log" 2>&1 &
        fi

        cd "$HOME/server" || cd "$HOME"
        python app.py >> "$HOME/nexus_logs/nexusnode.log" 2>&1 &
    fi
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Boot initialization completed successfully." >> "$BOOT_LOG"
