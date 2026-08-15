#!/data/data/com.termux/files/usr/bin/sh
# ==============================================================================
# 📱 NexusNode Appliance Control CLI (runit / termux-services wrapper)
# Single Authoritative Process Manager: runit (sv)
# Does NOT spawn competing processes; delegates 100% to termux-services / runsv
# ==============================================================================

PREFIX="${PREFIX:-/data/data/com.termux/files/usr}"
HOME="${HOME:-/data/data/com.termux/files/home}"
export PATH="$PREFIX/bin:$HOME/.local/bin:$PATH"

SERVER_DIR="$(cd "$(dirname "$0")" && pwd)"
export PYTHONPATH="$SERVER_DIR:$PYTHONPATH"

# Resolve runit service directory ($PREFIX/var/service or ~/.nexus_sv)
if [ -d "$PREFIX/var/service" ]; then
    export SVDIR="$PREFIX/var/service"
elif [ -d "$HOME/.nexus_sv" ]; then
    export SVDIR="$HOME/.nexus_sv"
else
    export SVDIR="$PREFIX/var/service"
fi

LOG_BASE="$HOME/nexus_logs"

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
        echo -e " ${C_GREEN}✔${C_RESET} Acquired Android CPU WakeLock"
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

ensure_services_installed() {
    if [ ! -d "$SVDIR/nexusnode" ] || [ ! -d "$SVDIR/localtonet" ]; then
        echo -e "${C_CYAN}[*] Installing runit service definitions into $SVDIR...${C_RESET}"
        if [ -f "$SERVER_DIR/scripts/install_services.sh" ]; then
            sh "$SERVER_DIR/scripts/install_services.sh" > /dev/null 2>&1 || true
        fi
    fi
}

check_sv_command() {
    if ! command -v sv > /dev/null 2>&1; then
        echo -e "${C_RED}✖ Error: 'sv' command (runit / termux-services) not found.${C_RESET}"
        echo -e "  Please install termux-services in Termux:"
        echo -e "  ${C_BOLD}pkg install termux-services${C_RESET}"
        return 1
    fi
    return 0
}

# ------------------------------------------------------------------------------
# Actions (All delegated strictly to runit 'sv')
# ------------------------------------------------------------------------------

start_appliance() {
    echo -e "${C_BOLD}============================================================${C_RESET}"
    echo -e " ${C_GREEN}🚀 Starting NexusNode Appliance via runit supervisor...${C_RESET}"
    echo -e "${C_BOLD}============================================================${C_RESET}"

    acquire_wakelock
    ensure_services_installed

    if check_sv_command; then
        # Enable services in termux-services if command available
        if command -v sv-enable > /dev/null 2>&1; then
            sv-enable sshd > /dev/null 2>&1 || true
            sv-enable localtonet > /dev/null 2>&1 || true
            sv-enable nexusnode > /dev/null 2>&1 || true
        fi

        echo -n " • Starting SSHD service... "
        sv up sshd 2>/dev/null && echo -e "${C_GREEN}OK${C_RESET}" || echo -e "${C_YELLOW}STANDBY${C_RESET}"

        echo -n " • Starting LocalToNet tunnel service... "
        sv up localtonet 2>/dev/null && echo -e "${C_GREEN}OK${C_RESET}" || echo -e "${C_YELLOW}STANDBY${C_RESET}"

        echo -n " • Starting NexusNode server service... "
        sv up nexusnode 2>/dev/null && echo -e "${C_GREEN}OK${C_RESET}" || echo -e "${C_RED}FAIL${C_RESET}"
    fi

    show_status
}

stop_appliance() {
    echo -e "${C_BOLD}============================================================${C_RESET}"
    echo -e " ${C_YELLOW}🛑 Stopping NexusNode Appliance services (runit)...${C_RESET}"
    echo -e "${C_BOLD}============================================================${C_RESET}"

    if check_sv_command; then
        echo -n " • Stopping NexusNode server... "
        sv down nexusnode 2>/dev/null && echo -e "${C_GREEN}Down${C_RESET}" || echo -e "${C_DIM}Off${C_RESET}"

        echo -n " • Stopping LocalToNet tunnel... "
        sv down localtonet 2>/dev/null && echo -e "${C_GREEN}Down${C_RESET}" || echo -e "${C_DIM}Off${C_RESET}"

        echo -n " • Stopping OpenSSH daemon... "
        sv down sshd 2>/dev/null && echo -e "${C_GREEN}Down${C_RESET}" || echo -e "${C_DIM}Off${C_RESET}"

        # Stop optional Ollama if active
        if [ -d "$SVDIR/ollama" ]; then
            sv down ollama > /dev/null 2>&1 || true
        fi
    fi

    release_wakelock
    echo -e "${C_GREEN}Appliance services stopped.${C_RESET}"
}

restart_appliance() {
    echo -e "${C_BOLD}============================================================${C_RESET}"
    echo -e " ${C_CYAN}🔄 Restarting NexusNode Appliance services (runit)...${C_RESET}"
    echo -e "${C_BOLD}============================================================${C_RESET}"

    acquire_wakelock
    ensure_services_installed

    if check_sv_command; then
        echo -n " • Restarting SSHD service... "
        sv restart sshd 2>/dev/null && echo -e "${C_GREEN}OK${C_RESET}" || sv up sshd 2>/dev/null || true

        echo -n " • Restarting LocalToNet tunnel... "
        sv restart localtonet 2>/dev/null && echo -e "${C_GREEN}OK${C_RESET}" || sv up localtonet 2>/dev/null || true

        echo -n " • Restarting NexusNode server... "
        sv restart nexusnode 2>/dev/null && echo -e "${C_GREEN}OK${C_RESET}" || sv up nexusnode 2>/dev/null || true
    fi

    show_status
}

show_status() {
    local local_ip="$(get_local_ip)"

    echo ""
    echo -e "${C_BOLD}============================================================${C_RESET}"
    echo -e " ${C_CYAN}📱 NexusNode Mobile Server Appliance Status${C_RESET}"
    echo -e "${C_BOLD}============================================================${C_RESET}"
    echo -e " Supervisor       : ${C_BOLD}runit / termux-services${C_RESET} ($SVDIR)"

    if check_sv_command; then
        echo ""
        echo -e " ${C_BOLD}Service States (sv status):${C_RESET}"
        
        # 1. NexusNode
        echo -n "  • nexusnode   : "
        sv status nexusnode 2>&1 || echo "not installed"

        # 2. SSHD
        echo -n "  • sshd        : "
        sv status sshd 2>&1 || echo "not installed"

        # 3. LocalToNet
        echo -n "  • localtonet  : "
        sv status localtonet 2>&1 || echo "not installed"

        # 4. Ollama
        if [ -d "$SVDIR/ollama" ]; then
            echo -n "  • ollama      : "
            sv status ollama 2>&1 || echo "down (optional)"
        fi
    fi

    echo ""
    echo -e " ${C_BOLD}Access Endpoints:${C_RESET}"
    echo -e "  • Web Console : ${C_BOLD}http://$local_ip:5000${C_RESET} ${C_DIM}(Local Wi-Fi)${C_RESET}"
    echo -e "  • Loopback    : ${C_DIM}http://127.0.0.1:5000${C_RESET}"
    echo -e "  • SSH Access  : ${C_BOLD}ssh $(whoami 2>/dev/null || echo user)@$local_ip -p 8022${C_RESET}"
    echo -e "${C_BOLD}============================================================${C_RESET}"
    echo -e " Authoritative Logs: ${C_CYAN}$LOG_BASE/<service>/current${C_RESET}"
    echo ""
}

show_logs() {
    local svc="${1:-}"
    if [ -n "$svc" ]; then
        local log_file="$LOG_BASE/$svc/current"
        if [ -f "$log_file" ]; then
            echo -e "${C_CYAN}Streaming authoritative svlogd logs for [$svc] ($log_file)...${C_RESET}"
            tail -n 50 -f "$log_file"
        elif [ -f "$LOG_BASE/$svc.log" ]; then
            tail -n 50 -f "$LOG_BASE/$svc.log"
        else
            echo -e "${C_YELLOW}No logs found for service '$svc' in $LOG_BASE${C_RESET}"
        fi
    else
        echo -e "${C_CYAN}Streaming authoritative appliance service logs (Ctrl+C to exit)...${C_RESET}"
        tail -n 30 -f \
            "$LOG_BASE/nexusnode/current" \
            "$LOG_BASE/localtonet/current" \
            "$LOG_BASE/sshd/current" \
            "$LOG_BASE/nexusnode.log" \
            "$LOG_BASE/localtonet.log" \
            "$LOG_BASE/sshd.log" 2>/dev/null || echo "No active logs found yet. Start services with './start_nexus.sh start'"
    fi
}

# ------------------------------------------------------------------------------
# Dispatcher
# ------------------------------------------------------------------------------

ACTION="${1:-start}"
SERVICE="${2:-}"

case "$ACTION" in
    start)
        start_appliance
        ;;
    stop)
        stop_appliance
        ;;
    restart)
        restart_appliance
        ;;
    status)
        show_status
        ;;
    logs)
        show_logs "$SERVICE"
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|logs [service]}"
        echo ""
        echo "Commands (delegated to runit / termux-services):"
        echo "  start           - Acquire WakeLock and start runit services (sshd, localtonet, nexusnode)"
        echo "  stop            - Stop runit services and release WakeLock"
        echo "  restart         - Restart runit services"
        echo "  status          - Query 'sv status' and display network URLs"
        echo "  logs [service]  - Follow authoritative svlogd logs (e.g. ./start_nexus.sh logs nexusnode)"
        exit 1
        ;;
esac
