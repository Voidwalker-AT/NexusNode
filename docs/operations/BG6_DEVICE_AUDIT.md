# TECNO BG6 Physical Device & Termux Appliance Audit

> **Status**: OBSERVED ON DEVICE (Phase 0 Reconnaissance)  
> **Target Hardware**: TECNO BG6 (product: `BG6-IN`, device: `TECNO-BG6`)  
> **Serial Number**: `109973141A030946`  
> **Operating System**: Android 13 (`ro.build.version.release: 13`), Kernel 5.4  
> **CPU Architecture**: `arm64-v8a` (Unisoc T606 Octa-core)  
> **Inspection Date**: 2026-10-21  
> **Verification Authority**: Google Antigravity (Gravitas Read-Only Audit)

---

## 1. Hardware & System Telemetry

Direct physical introspection was executed over USB ADB (`109973141A030946`) and Termux `run-as com.termux` sandbox inspection.

| Metric | Measured Value | Operational Assessment |
|---|---|---|
| **Model** | `TECNO BG6` (BG6-IN) | Target appliance confirmed. |
| **Android Version** | 13 (API 33) | Modern unrooted Android sandbox. |
| **Total Physical RAM** | 3,861,584 kB (~3.77 GB) | Matches 4 GB hardware specification. |
| **Available RAM (`MemAvailable`)** | **2,244 MB – 2,368 MB** | **Substantial headroom (>2.2 GB free)**. |
| **ZRAM / Swap Total** | 2,828 MB (749 MB used, 26%) | Normal kernel memory compression. |
| **Internal Storage (`/data`)** | 53.2 GB total, 22.4 GB used, **30.7 GB free (42% used)** | Plenty of flash storage for Vault & SQLite. |
| **Battery Level** | **100% (USB powered)** | Active charging via USB debugging tether. |
| **Battery Health & Temp** | Health: GOOD (2), **Temperature: 30.6°C** | Completely cool thermal baseline. |
| **System Uptime** | 9 days, 17 hours | Appliance has remained powered continuously. |
| **Network Interfaces** | `wlan0`: **`192.168.29.21/24`**; `lo`: `127.0.0.1` | Local IP stable on LAN. |

---

## 2. Termux Runtime Environment

| Component | Location / Configuration | State |
|---|---|---|
| **Termux Package** | `com.termux` (version `0.118.3`) | Installed |
| **Termux User / UID** | `u0_a208` (UID: `10208`) | Authenticated sandbox |
| **Termux Prefix** | `/data/data/com.termux/files/usr` | Verified |
| **Termux Home** | `/data/data/com.termux/files/home` | Verified |
| **Python Runtime** | `/data/data/com.termux/files/usr/bin/python` | **Python 3.14.6** |
| **Process Supervisor** | `runit` (`runsvdir` / `service-daemon`) | Configured in `$PREFIX/var/service` |
| **WakeLock Status** | `termux-wake-lock` | **Active (`PowerManagerService.WakeLocks: 1`)** |
| **Autoboot Package** | `com.termux.boot` | **NOT INSTALLED (Critical Gap)** |

---

## 3. Running Services & Daemon Supervisions

At initial connection, Termux was found stopped in the background. After launching the foreground activity and executing `service-daemon start`, all supervisors reported healthy operational states:

```
run: /data/data/com.termux/files/usr/var/service/nexusnode: (pid 5024)
run: /data/data/com.termux/files/usr/var/service/localtonet: (pid 5020)
run: /data/data/com.termux/files/usr/var/service/sshd: (pid 5022)
```

1. **NexusNode WSGI (`waitress`)**:
   - Entry point: `python /data/data/com.termux/files/home/server/app.py`
   - Bind: `0.0.0.0:5000` (Threads: 6)
   - Resident Memory (RSS): **~69.3 MB – 115 MB**
   - Health check: `/api/health` -> `HTTP 200 OK` (`{"status": "healthy", "version": "2.3.8"}`)

2. **OpenSSH Server (`sshd`)**:
   - Bind: `0.0.0.0:8022`
   - RSS: **~8.3 MB**
   - Direct connection verified from Windows development workstation.

3. **LocalToNet Ingress Tunnel**:
   - Daemon binary: `localtonet`
   - Active egress endpoint: `k09oezeyib.localto.net:1983` -> `127.0.0.1:5000`
   - Public URL: `https://k09oezeyib.localto.net`

4. **Ephemeral Proot Chromium Engine**:
   - Container root: `proot-distro login alpine`
   - Browser binary: `/usr/bin/chromium-browser`
   - Active instances: 0 (ephemeral single-flight on demand; 0 orphan processes observed).

---

## 4. Key Limitations & Failure Modes

1. **Lack of Boot Persistence**: `com.termux.boot` is missing from Android. If the TECNO BG6 is power-cycled, Termux does not relaunch autonomously.
2. **Android Background Process Freeze**: Without `termux-wake-lock`, Android 13 aggressive power management suspends Termux network sockets when the screen locks. Wake lock must be continuously asserted.
3. **LocalToNet Free-Tier Landing Page**: Public requests without `localtonet-skip-warning` receive an HTML warning page.
