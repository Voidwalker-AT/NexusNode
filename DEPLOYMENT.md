# 🚀 NexusNode Deployment & 24/7 Operational Guide

Complete guide for deploying and operating **NexusNode** on Android Termux (**TECNO BG6**, Android 13, ~4 GB RAM).

---

## 1. Prerequisites & Termux Setup

### 1.1. Install Termux & Termux:API
- Install **Termux** from [F-Droid](https://f-droid.org/en/packages/com.termux/) (Do **not** use Google Play version).
- Install **Termux:API** and **Termux:Boot** add-on APKs from F-Droid.

### 1.2. Android System Settings Hardening
To ensure Android does not kill NexusNode when the screen is locked:
1. **Disable Battery Optimization**: Go to *Settings $\rightarrow$ Apps $\rightarrow$ Termux $\rightarrow$ Battery $\rightarrow$ Unrestricted*.
2. **Lock Termux in Recent Apps**: Open Android task switcher and tap the lock icon on Termux.
3. **Allow Background Activity**: Ensure background data and autostart permissions are enabled.

---

## 2. Package Installation

Open Termux and execute:

```bash
pkg update && pkg upgrade -y
pkg install -y python git termux-services termux-api openssh yt-dlp ffmpeg p7zip
```

---

## 3. Clone Repository & Setup Virtual Environment

```bash
git clone https://github.com/Voidwalker-AT/NexusNode.git ~/server
cd ~/server
pip install -r requirements.txt
```

---

## 4. Production Service Supervision (runit / termux-services)

NexusNode uses **`runit`** as the single authoritative process supervisor for all background daemons.

### Step 1: Install runit Service Definitions
```bash
cd ~/server
bash scripts/install_services.sh
```

### Step 2: Control Services via `start_nexus.sh` (Convenience CLI)
`start_nexus.sh` provides unified commands to control `runit` services with automatic WakeLock management:

```bash
chmod +x start_nexus.sh

# Start services via runit with WakeLock (sv up sshd, localtonet, nexusnode)
./start_nexus.sh start

# Check live service states (sv status) and connection URLs
./start_nexus.sh status

# Follow authoritative svlogd logs
./start_nexus.sh logs

# Follow logs for a specific service
./start_nexus.sh logs nexusnode

# Restart runit services
./start_nexus.sh restart

# Stop all services and release WakeLock
./start_nexus.sh stop
```

---

### Step 3: Direct `sv` Command Control (Alternative)
You can also interact directly with `runit` using standard `sv` commands:

```bash
# Start individual services
sv up nexusnode
sv up localtonet
sv up sshd

# Check service status
sv status nexusnode
sv status localtonet
sv status sshd

# Stop individual services
sv down nexusnode
sv down localtonet
sv down sshd
```

---

### Mode C: `Termux:Boot` (Autostart on Phone Reboot)

NexusNode can automatically launch whenever your phone boots up:

1. Launch the **Termux:Boot** application once from your Android app drawer.
2. Verify the boot script is in place:
   ```bash
   cat ~/.termux/boot/start-nexusnode.sh
   ```
3. Whenever the phone powers on, Termux will automatically acquire a WakeLock, initialize SSHD, start LocalToNet, and boot the NexusNode server.

---

## 5. Remote Access

### 5.1. Local Network Access (Wi-Fi)
Access NexusNode from any phone, laptop, or tablet connected to the same Wi-Fi:
- Open browser: `http://<PHONE_IP>:5000`
- Example: `http://192.168.1.45:5000`

### 5.2. SSH Terminal Access
Connect to your phone's terminal remotely:
```bash
ssh user@<PHONE_IP> -p 8022
```

### 5.3. Public Internet Access (LocalToNet)
If LocalToNet is running:
1. Log into your [LocalToNet Dashboard](https://localtonet.com).
2. Configure a tunnel pointing to `127.0.0.1:5000` (HTTP).
3. Access your private mobile server securely from anywhere in the world.

---

## 6. Backup & Restore Procedures

### 6.1. Create System Backup
- **Via Web UI**: Navigate to *More $\rightarrow$ System Backups $\rightarrow$ Create Full Backup*.
- **Via CLI**:
  ```bash
  python -c "import app; app.create_system_backup_sync('manual')"
  ```
  Backups are saved to `storage_vault/backups/nexus_backup_YYYYMMDD_HHMMSS.zip` with SHA-256 integrity verification.

### 6.2. Safe Restore
- **Via Web UI**: Click *Restore* on any backup card and confirm.
- Safe restore applies the database snapshot, RAG knowledge index, and configuration without corrupting existing active connections.

---

## 7. Diagnostics & Troubleshooting

| Symptom | Diagnostic Command | Solution |
| :--- | :--- | :--- |
| **Server unreachable** | `./start_nexus.sh status` | Run `./start_nexus.sh restart` or check port 5000 binding. |
| **CPU sleeping when locked** | `termux-wake-lock` | Ensure Termux has battery optimization set to *Unrestricted*. |
| **Media download failing** | `yt-dlp -U` | Update yt-dlp to latest version. |
| **High thermal throttle** | Check UI Dashboard | Let phone cool; governor automatically resumes tasks $<55^\circ\text{C}$. |
| **Live logs** | `./start_nexus.sh logs` | Inspect realtime application and error output. |
