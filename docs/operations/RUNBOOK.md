# Operational Runbook

> **Status**: VERIFIED CURRENT  
> **Scope**: Day-to-day operations, service lifecycle, monitoring commands, health checks, and log inspection  
> **Last verified**: 2026-09-20 (Phase 4.2B Post-Rebase Audit)  
> **Evidence basis**: Verified production deployment on TECNO BG6 appliance under Termux `runit`

---

## 1. System Access & Appliance Topology

NexusNode operates as an appliance on a dedicated physical mobile device. All routine operations can be performed either locally over Wi-Fi SSH or via the public HTTPS management interface:

- **Local Network IP**: `192.168.29.21` (SSH Port: `8022`)
- **Appliance User**: `u0_a208`
- **Working Directory**: `/data/data/com.termux/files/home/nexusnode`
- **Internal HTTP Port**: `127.0.0.1:5000` (Waitress WSGI)
- **Public Ingress URL**: `https://k09oezeyib.localto.net` (Localtonet Tunnel)

### Connecting via SSH
```bash
ssh -p 8022 u0_a208@192.168.29.21
```

---

## 2. Service Lifecycle Management (`runit`)

NexusNode uses UNIX `runit` under Termux to supervise background daemons:

```bash
# Check status of all supervised services
sv status nexusnode
sv status localtonet

# Restart the core NexusNode application
sv restart nexusnode

# Restart the public ingress tunnel
sv restart localtonet

# Gracefully stop NexusNode
sv stop nexusnode

# Start NexusNode
sv start nexusnode
```

> [!NOTE]
> In an emergency, if `runit` is unavailable, you can manually start the server:
> ```bash
> cd /data/data/com.termux/files/home/nexusnode
> python app.py
> ```

---

## 3. Daily Health Checks & Monitoring

### A. Health Check Endpoints
Inspect the operational state via cURL or browser:

```bash
# Basic Liveness Probe (Returns HTTP 200 OK)
curl -s http://127.0.0.1:5000/health

# Detailed System Status (JSON: CPU, memory, uptime, DB stats)
curl -s http://127.0.0.1:5000/api/system/status | jq .

# Public Ingress Liveness
curl -s https://k09oezeyib.localto.net/health
```

Expected output for `/health`:
```json
{
  "status": "healthy",
  "appliance": "TECNO BG6",
  "uptime_seconds": 3024820,
  "database": "connected",
  "version": "nexus-semantic-v1"
}
```

### B. Memory Footprint Verification
Check the mobile host's resident set size:
```bash
# Check NexusNode process memory
ps -o pid,user,rss,args -C python

# Check overall device memory and available RAM
cat /proc/meminfo | grep -E "MemTotal|MemFree|MemAvailable|SwapTotal|SwapFree"
```
*Nominal baseline: Python process RSS between 22 MB and 25 MB; MemAvailable >= 1,500 MB.*

---

## 4. Log Inspection & Auditing

### A. Supervisor Logs
Server logs captured by `runit` are located in `log/run`:
```bash
# Tail live server standard output and errors
tail -f /data/data/com.termux/files/home/nexusnode/log/current

# Search for runtime exceptions or errors
grep -i "exception\|error\|traceback" /data/data/com.termux/files/home/nexusnode/log/current | tail -n 30
```

### B. SQLite System Audit Logs
Inspect high-resolution database event logs:
```bash
# View last 20 system log entries
sqlite3 /data/data/com.termux/files/home/nexusnode/storage_vault/nexus_unified.db \
  "SELECT id, level, module, message, created_at FROM system_logs ORDER BY created_at DESC LIMIT 20;"

# Check recent background sync executions
sqlite3 /data/data/com.termux/files/home/nexusnode/storage_vault/nexus_unified.db \
  "SELECT id, user_id, status, items_synced, error_message, synced_at FROM timetable_sync_history ORDER BY synced_at DESC LIMIT 5;"
```

---

## 5. Ephemeral Browser Operations

### Testing Browser Engine Health
To test the headless Chromium subsystem without triggering full academic workflows:
```bash
cd /data/data/com.termux/files/home/nexusnode
pytest tests/test_bg6_browser_runtime.py -v
```

### Running the Empirical Browser Benchmark Suite
To re-run the 10-run cold start, navigation, and cleanup benchmark:
```bash
python scripts/audit_browser_runtime.py
```
*Verify that `orphaned_pids_remaining` reports 0 and peak RSS remains within bounds.*

---

## 6. Zero-Touch Sync Operations

### Manually Triggering Background Sync
If a student's timetable or attendance must be refreshed immediately:
```bash
# Trigger immediate attendance sync for all active students
python attendance_sync.py --force-all

# Trigger Google Calendar timetable reconciliation
python timetable_sync.py --force-sync
```

### Clearing Sync Locks
If an unexpected crash left a lock record in the database:
```bash
sqlite3 /data/data/com.termux/files/home/nexusnode/storage_vault/nexus_unified.db \
  "DELETE FROM timetable_sync_locks; DELETE FROM attendance_sync_locks;"
```
