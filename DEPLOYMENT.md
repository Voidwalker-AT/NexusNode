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

## 4. Operational Modes (Choose One)

### Mode A: All-in-One CLI Launcher (`start_nexus.sh`) — Easiest

The all-in-one launcher manages **OpenSSH (port 8022)**, **LocalToNet tunnel**, and **NexusNode server (port 5000)** simultaneously with automatic Android CPU WakeLock:

```bash
cd ~/server
chmod +x start_nexus.sh

# Start all services in background
./start_nexus.sh start

# Check live appliance status and URLs
./start_nexus.sh status

# Run in foreground (view live output directly)
./start_nexus.sh run

# Stream logs from all 3 services
./start_nexus.sh logs

# Stop all services gracefully
./start_nexus.sh stop

# Restart all services
./start_nexus.sh restart
```

---

### Mode B: `termux-services` (runit) Supervision — Production

For system-level automatic process restarts upon crash:

```bash
cd ~/server
bash scripts/install_services.sh

# Start / enable services
sv up nexusnode
sv up localtonet
sv up sshd

# Check status
sv status nexusnode
sv status localtonet
sv status sshd

# Stop services
sv down nexusnode
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
