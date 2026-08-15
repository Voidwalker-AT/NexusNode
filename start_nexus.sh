#!/data/data/com.termux/files/usr/bin/sh
# ==============================================================================
# 🚀 NexusNode All-in-One Appliance Launcher & Supervisor
# Starts: OpenSSH Daemon (port 8022), LocalToNet Tunnel, and NexusNode Server
# Target: Android 13 Termux (~4 GB RAM) & Linux / POSIX Environments
# ==============================================================================

# Strict paths for Termux / POSIX
PREFIX="${PREFIX:-/data/data/com.termux/files/usr}"
HOME="${HOME:-/data/data/com.termux/files/home}"
export PATH="$PREFIX/bin:$HOME/.local/bin:$HOME/localtonet:$PATH"
export PYTHONPATH="$HOME/server:$PYTHONPATH"

SERVER_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$HOME/nexus_logs"
PID_DIR="$SERVER_DIR/.pids"

mkdir -p "$LOG_DIR"
mkdir -p "$PID_DIR"

APP_LOG="$LOG_DIR/nexusnode.log"
SSH_LOG="$LOG_DIR/sshd.log"
TUNNEL_LOG="$LOG_DIR/localtonet.log"

APP_PID_FILE="$PID_DIR/app.pid"
SSH_PID_FILE="$PID_DIR/sshd.pid"
TUNNEL_PID_FILE="$PID_DIR/localtonet.pid"

# Colors for terminal output
C_RESET="\033[0m"
C_GREEN="\033[1;32m"
C_CYAN="\033[1;36m"
C_YELLOW="\033[1;33m"
C_RED="\033[1;31m"
C_BOLD="\033[1m"
C_DIM="\033[2m"

# ------------------------------------------------------------------------------
# Helper Functions
# ------------------------------------------------------------------------------

acquire_wakelock() {
    if command -v termux-wake-lock > /dev/null 2>&1; then
        termux-wake-lock
        echo -e " ${C_GREEN}✔${C_RESET} Acquired Android CPU WakeLock (prevents sleep during lockscreen)"
    fi
}

release_wakelock() {
    if command -v termux-wake-unlock > /dev/null 2>&1; then
        termux-wake-unlock
        echo -e " ${C_YELLOW}✔${C_RESET} Released Android CPU WakeLock"
    fi
}

get_local_ip() {
    local ip=""
    if command -v ip > /dev/null 2>&1; then
        ip=$(ip route get 1.1.1.1 2>/dev/null | awk '{print $7}')
    fi
    if [ -z "$ip" ] && command -v ifconfig > /dev/null 2>&1; then
        ip=$(ifconfig 2>/dev/null | grep -Eo 'inet (addr:)?([0-9]*\.){3}[0-9]*' | grep -Eo '([0-9]*\.){3}[0-9]*' | grep -v '127.0.0.1' | head -n 1)
    fi
    echo "${ip:-127.0.0.1}"
}

find_localtonet_bin() {
    if command -v localtonet > /dev/null 2>&1; then
        command -v localtonet
    elif [ -x "$HOME/localtonet/localtonet" ]; then
        echo "$HOME/localtonet/localtonet"
    elif [ -x "$HOME/localtonet" ]; then
        echo "$HOME/localtonet"
    elif [ -x "$PREFIX/bin/localtonet" ]; then
        echo "$PREFIX/bin/localtonet"
    else
        echo ""
    fi
}

# ------------------------------------------------------------------------------
# Start Subsystems
# ------------------------------------------------------------------------------

start_sshd() {
    echo -e "${C_CYAN}[1/3] Starting OpenSSH Daemon (port 8022)...${C_RESET}"
    if pgrep -x sshd > /dev/null 2>&1; then
        echo -e " ${C_GREEN}✔${C_RESET} SSHD is already running on port 8022 (PID: $(pgrep -x sshd | head -n 1))"
    else
        if command -v sshd > /dev/null 2>&1; then
            sshd -p 8022 >> "$SSH_LOG" 2>&1
            sleep 1
            if pgrep -x sshd > /dev/null 2>&1; then
                pgrep -x sshd | head -n 1 > "$SSH_PID_FILE"
                echo -e " ${C_GREEN}✔${C_RESET} SSHD started successfully on port 8022"
            else
                echo -e " ${C_RED}✖${C_RESET} Failed to start SSHD. Check $SSH_LOG"
            fi
        else
            echo -e " ${C_YELLOW}⚠${C_RESET} 'sshd' binary not found. Install with: pkg install openssh"
        fi
    fi
}

start_localtonet() {
    echo -e "${C_CYAN}[2/3] Starting LocalToNet Tunnel Daemon...${C_RESET}"
    if pgrep -f "localtonet" > /dev/null 2>&1; then
        echo -e " ${C_GREEN}✔${C_RESET} LocalToNet tunnel is already running (PID: $(pgrep -f localtonet | head -n 1))"
    else
        LOCALTONET_BIN="$(find_localtonet_bin)"
        if [ -n "$LOCALTONET_BIN" ] && [ -x "$LOCALTONET_BIN" ]; then
            nohup "$LOCALTONET_BIN" >> "$TUNNEL_LOG" 2>&1 &
            echo $! > "$TUNNEL_PID_FILE"
            sleep 2
            if kill -0 $(cat "$TUNNEL_PID_FILE" 2>/dev/null) 2>/dev/null; then
                echo -e " ${C_GREEN}✔${C_RESET} LocalToNet tunnel started in background (PID: $(cat "$TUNNEL_PID_FILE"))"
            else
                echo -e " ${C_YELLOW}⚠${C_RESET} LocalToNet exited early. Check logs: $TUNNEL_LOG"
            fi
        else
            echo -e " ${C_YELLOW}⚠${C_RESET} LocalToNet binary not found. (Optional: tunnel for remote internet access)"
        fi
    fi
}

start_nexusnode() {
    local mode="$1"
    echo -e "${C_CYAN}[3/3] Starting NexusNode WSGI Server (port 5000)...${C_RESET}"
    
    if pgrep -f "python.*app.py" > /dev/null 2>&1; then
        echo -e " ${C_GREEN}✔${C_RESET} NexusNode server is already running (PID: $(pgrep -f "python.*app.py" | head -n 1))"
    else
        cd "$SERVER_DIR" || exit 1
        if [ "$mode" = "foreground" ]; then
            echo -e " ${C_GREEN}✔${C_RESET} Launching NexusNode in foreground (Press Ctrl+C to terminate)..."
            echo "------------------------------------------------------------"
            exec python app.py
        else
            nohup python app.py >> "$APP_LOG" 2>&1 &
            echo $! > "$APP_PID_FILE"
            sleep 2
            if kill -0 $(cat "$APP_PID_FILE" 2>/dev/null) 2>/dev/null; then
                echo -e " ${C_GREEN}✔${C_RESET} NexusNode server started in background (PID: $(cat "$APP_PID_FILE"))"
            else
                echo -e " ${C_RED}✖${C_RESET} NexusNode failed to start. Check logs: $APP_LOG"
            fi
        fi
    fi
}

# ------------------------------------------------------------------------------
# Stop Subsystems
# ------------------------------------------------------------------------------

stop_all() {
    echo -e "${C_BOLD}Shutting down NexusNode Mobile Server Appliance...${C_RESET}"

    # 1. Stop NexusNode
    if pgrep -f "python.*app.py" > /dev/null 2>&1; then
        echo -n " • Stopping NexusNode server... "
        pkill -f "python.*app.py" || true
        echo -e "${C_GREEN}Done${C_RESET}"
    fi
    rm -f "$APP_PID_FILE"

    # 2. Stop LocalToNet
    if pgrep -f "localtonet" > /dev/null 2>&1; then
        echo -n " • Stopping LocalToNet tunnel... "
        pkill -f "localtonet" || true
        echo -e "${C_GREEN}Done${C_RESET}"
    fi
    rm -f "$TUNNEL_PID_FILE"

    # 3. Stop SSHD (optional confirmation)
    if pgrep -x sshd > /dev/null 2>&1; then
        echo -n " • Stopping SSHD daemon... "
        pkill -x sshd || true
        echo -e "${C_GREEN}Done${C_RESET}"
    fi
    rm -f "$SSH_PID_FILE"

    release_wakelock
    echo -e "${C_GREEN}All NexusNode appliance services stopped.${C_RESET}"
}

# ------------------------------------------------------------------------------
# Status Dashboard
# ------------------------------------------------------------------------------

show_status() {
    local local_ip="$(get_local_ip)"

    echo ""
    echo -e "${C_BOLD}============================================================${C_RESET}"
    echo -e " ${C_CYAN}📱 NexusNode Personal Mobile Server Appliance Status${C_RESET}"
    echo -e "${C_BOLD}============================================================${C_RESET}"

    # 1. NexusNode
    if pgrep -f "python.*app.py" > /dev/null 2>&1; then
        local app_pid=$(pgrep -f "python.*app.py" | head -n 1)
        echo -e "  NexusNode Core : ${C_GREEN}ONLINE${C_RESET} (PID: $app_pid, Port: 5000)"
        echo -e "  Local URL      : ${C_BOLD}http://$local_ip:5000${C_RESET}"
        echo -e "  Loopback URL   : ${C_DIM}http://127.0.0.1:5000${C_RESET}"
    else
        echo -e "  NexusNode Core : ${C_RED}OFFLINE${C_RESET}"
    fi

    # 2. SSHD
    if pgrep -x sshd > /dev/null 2>&1; then
        local ssh_pid=$(pgrep -x sshd | head -n 1)
        echo -e "  OpenSSH Daemon : ${C_GREEN}ONLINE${C_RESET} (PID: $ssh_pid, Port: 8022)"
        echo -e "  SSH Access     : ${C_BOLD}ssh $(whoami 2>/dev/null || echo user)@$local_ip -p 8022${C_RESET}"
    else
        echo -e "  OpenSSH Daemon : ${C_RED}OFFLINE${C_RESET}"
    fi

    # 3. LocalToNet
    if pgrep -f "localtonet" > /dev/null 2>&1; then
        local tunnel_pid=$(pgrep -f "localtonet" | head -n 1)
        echo -e "  LocalToNet     : ${C_GREEN}ONLINE${C_RESET} (PID: $tunnel_pid)"
    else
        echo -e "  LocalToNet     : ${C_YELLOW}OFFLINE / STANDBY${C_RESET}"
    fi

    echo -e "${C_BOLD}============================================================${C_RESET}"
    echo -e " Log files directory: ${C_CYAN}$LOG_DIR${C_RESET}"
    echo ""
}

# ------------------------------------------------------------------------------
# Command Dispatcher
# ------------------------------------------------------------------------------

ACTION="${1:-start}"

case "$ACTION" in
    start)
        echo -e "${C_BOLD}============================================================${C_RESET}"
        echo -e " ${C_GREEN}🚀 Starting NexusNode 24/7 Mobile Server Appliance...${C_RESET}"
        echo -e "${C_BOLD}============================================================${C_RESET}"
        acquire_wakelock
        start_sshd
        start_localtonet
        start_nexusnode "background"
        show_status
        ;;
    run|foreground)
        echo -e "${C_BOLD}============================================================${C_RESET}"
        echo -e " ${C_GREEN}🚀 Starting NexusNode in Foreground Mode...${C_RESET}"
        echo -e "${C_BOLD}============================================================${C_RESET}"
        acquire_wakelock
        start_sshd
        start_localtonet
        start_nexusnode "foreground"
        ;;
    stop)
        stop_all
        ;;
    restart)
        stop_all
        sleep 2
        acquire_wakelock
        start_sshd
        start_localtonet
        start_nexusnode "background"
        show_status
        ;;
    status)
        show_status
        ;;
    logs)
        echo -e "${C_CYAN}Streaming live NexusNode appliance logs (Ctrl+C to exit)...${C_RESET}"
        tail -n 50 -f "$APP_LOG" "$SSH_LOG" "$TUNNEL_LOG" 2>/dev/null || tail -n 50 -f "$APP_LOG"
        ;;
    *)
        echo "Usage: $0 {start|run|stop|restart|status|logs}"
        echo ""
        echo "Commands:"
        echo "  start       - Start SSHD, LocalToNet, and NexusNode in background (default)"
        echo "  run         - Start SSHD & LocalToNet, then run NexusNode in foreground"
        echo "  stop        - Gracefully stop all 3 services and release wakelock"
        echo "  restart     - Restart all 3 services"
        echo "  status      - Display current appliance health and connection URLs"
        echo "  logs        - Stream live logs from all subsystems"
        exit 1
        ;;
esac
