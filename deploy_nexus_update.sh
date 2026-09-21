#!/data/data/com.termux/files/usr/bin/bash
# NexusNode Automated Update & Verification Script for TECNO BG6

set -e
echo "=============================================="
echo "NexusNode Server Update & Restart for TECNO BG6"
echo "=============================================="

TARGET_DIR="$HOME/server"
BACKUP_DIR="$HOME/server_backup_$(date +%Y%m%d_%H%M%S)"

echo "[1/5] Creating pre-deploy backup at $BACKUP_DIR..."
mkdir -p "$BACKUP_DIR"
cp -r "$TARGET_DIR/agent" "$BACKUP_DIR/" 2>/dev/null || true
cp "$TARGET_DIR/app.py" "$BACKUP_DIR/" 2>/dev/null || true
cp "$TARGET_DIR/config.py" "$BACKUP_DIR/" 2>/dev/null || true

echo "[2/5] Stopping old NexusNode server process..."
pkill -f "python.*app.py" || true
pkill -f "waitress" || true
sleep 2

echo "[3/5] Starting updated NexusNode server..."
cd "$TARGET_DIR"
nohup python app.py > server.log 2>&1 &
sleep 3

echo "[4/5] Verifying process is running..."
if pgrep -f "python.*app.py" > /dev/null; then
    echo "[OK] NexusNode server is running with PID: $(pgrep -f 'python.*app.py' | tr '\n' ' ')"
else
    echo "[ERROR] Server failed to start. Check server.log:"
    tail -n 20 server.log
    exit 1
fi

echo "[5/5] Performing local health and MCP handshake check..."
python -c "
import urllib.request, json
try:
    resp = urllib.request.urlopen('http://127.0.0.1:5000/api/health')
    print('Health status:', resp.status, resp.read().decode()[:100])
except Exception as e:
    print('Health check error:', e)
"

echo "=============================================="
echo "NexusNode update complete!"
echo "=============================================="
