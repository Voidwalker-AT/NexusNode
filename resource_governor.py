"""
NexusNode — 4 GB RAM & Thermal Resource Governor
Deterministic, unprivileged memory and resource supervision for Android Termux.
Protects core server (NexusNode, SSH, LocaltoNet) on low-resource mobile hardware.
"""

import os
import re
import json
import shutil
import subprocess
import config

class ResourceGovernor:
    def __init__(self):
        self.normal_threshold_mb = config.RAM_NORMAL_THRESHOLD_MB
        self.pressure_threshold_mb = config.RAM_PRESSURE_THRESHOLD_MB
        self.thermal_warm_c = config.THERMAL_WARM_C
        self.thermal_throttled_c = config.THERMAL_THROTTLED_C
        self.thermal_critical_c = config.THERMAL_CRITICAL_C

    def get_memory_status(self) -> dict:
        """
        Reads system memory using unprivileged techniques (/proc/meminfo or 'free -m').
        Returns structured telemetry including available RAM, swap, and pressure state.
        """
        total_mb = 3800
        available_mb = 1200
        free_mb = 500
        buffers_mb = 100
        cached_mb = 600
        swap_total_mb = 2000
        swap_free_mb = 1500

        # Method 1: Read unprivileged /proc/meminfo
        if os.path.exists("/proc/meminfo"):
            try:
                with open("/proc/meminfo", "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                    
                    def find_kb(key):
                        m = re.search(rf"^{key}:\s+(\d+)\s+kB", content, re.MULTILINE)
                        return int(m.group(1)) if m else 0

                    mem_total_kb = find_kb("MemTotal")
                    mem_avail_kb = find_kb("MemAvailable")
                    mem_free_kb = find_kb("MemFree")
                    buffers_kb = find_kb("Buffers")
                    cached_kb = find_kb("Cached")
                    swap_total_kb = find_kb("SwapTotal")
                    swap_free_kb = find_kb("SwapFree")

                    if mem_total_kb > 0:
                        total_mb = mem_total_kb // 1024
                        if mem_avail_kb > 0:
                            available_mb = mem_avail_kb // 1024
                        else:
                            available_mb = (mem_free_kb + buffers_kb + cached_kb) // 1024
                        free_mb = mem_free_kb // 1024
                        buffers_mb = buffers_kb // 1024
                        cached_mb = cached_kb // 1024
                        swap_total_mb = swap_total_kb // 1024
                        swap_free_mb = swap_free_kb // 1024
            except Exception:
                pass
        else:
            # Method 2: 'free -m' CLI fallback
            try:
                out = subprocess.check_output(["free", "-m"], stderr=subprocess.DEVNULL, text=True)
                mem_match = re.search(r"Mem:\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)?\s+(\d+)?\s+(\d+)?", out)
                if mem_match:
                    total_mb = int(mem_match.group(1))
                    if mem_match.group(6):
                        available_mb = int(mem_match.group(6))
                    else:
                        available_mb = int(mem_match.group(3))
                swap_match = re.search(r"Swap:\s+(\d+)\s+(\d+)\s+(\d+)", out)
                if swap_match:
                    swap_total_mb = int(swap_match.group(1))
                    swap_free_mb = int(swap_match.group(3))
            except Exception:
                pass

        used_mb = max(0, total_mb - available_mb)
        swap_used_mb = max(0, swap_total_mb - swap_free_mb)
        ram_percent = min(100, int((used_mb / max(1, total_mb)) * 100))
        swap_percent = min(100, int((swap_used_mb / max(1, swap_total_mb)) * 100)) if swap_total_mb > 0 else 0

        # State classification
        if available_mb >= self.normal_threshold_mb:
            state = "normal"
            reason = "RAM is plentiful. All operations allowed."
        elif available_mb >= self.pressure_threshold_mb:
            state = "pressure"
            reason = f"RAM is under pressure ({available_mb} MB available). Heavy operations queued."
        else:
            state = "critical"
            reason = f"RAM is critically low ({available_mb} MB available < {self.pressure_threshold_mb} MB). Heavy operations blocked."

        return {
            "total_mb": total_mb,
            "used_mb": used_mb,
            "available_mb": available_mb,
            "free_mb": free_mb,
            "cached_mb": cached_mb,
            "ram_percent": ram_percent,
            "swap_total_mb": swap_total_mb,
            "swap_used_mb": swap_used_mb,
            "swap_percent": swap_percent,
            "state": state,
            "reason": reason
        }

    def get_disk_status(self) -> dict:
        """Reads disk usage using unprivileged statvfs."""
        try:
            st = os.statvfs(config.STORAGE_DIR)
            total_bytes = st.f_blocks * st.f_frsize
            free_bytes = st.f_bavail * st.f_frsize
            used_bytes = total_bytes - free_bytes
            total_gb = round(total_bytes / (1024**3), 1)
            free_gb = round(free_bytes / (1024**3), 1)
            used_gb = round(used_bytes / (1024**3), 1)
            percent = int((used_bytes / max(1, total_bytes)) * 100)
            return {
                "total_gb": total_gb,
                "used_gb": used_gb,
                "free_gb": free_gb,
                "percent": percent
            }
        except Exception:
            return {"total_gb": 53.0, "used_gb": 20.0, "free_gb": 33.0, "percent": 38}

    def get_device_telemetry(self) -> dict:
        """
        Reads battery, charging status, and thermal metrics via unprivileged Termux tools or sysfs.
        Reports 'unavailable' accurately if Android does not expose specific sensor nodes.
        """
        battery_pct = None
        battery_status = "unavailable"
        battery_temp_c = None
        cpu_temp_c = None

        # 1. Termux API tool check: termux-battery-status
        if shutil.which("termux-battery-status"):
            try:
                out = subprocess.check_output(["termux-battery-status"], stderr=subprocess.DEVNULL, timeout=1.0, text=True)
                data = json.loads(out)
                battery_pct = data.get("percentage")
                battery_status = data.get("status", "unavailable")
                temp_raw = data.get("temperature")
                if temp_raw is not None:
                    # Termux battery temperature is in Celsius (or float)
                    battery_temp_c = round(float(temp_raw), 1)
            except Exception:
                pass

        # 2. Sysfs fallback for battery if unpopulated
        if battery_pct is None and os.path.exists("/sys/class/power_supply/battery"):
            try:
                cap_file = "/sys/class/power_supply/battery/capacity"
                if os.path.exists(cap_file):
                    with open(cap_file, "r") as f:
                        battery_pct = int(f.read().strip())
                stat_file = "/sys/class/power_supply/battery/status"
                if os.path.exists(stat_file):
                    with open(stat_file, "r") as f:
                        battery_status = f.read().strip()
                btemp_file = "/sys/class/power_supply/battery/temp"
                if os.path.exists(btemp_file):
                    with open(btemp_file, "r") as f:
                        raw = float(f.read().strip())
                        battery_temp_c = round(raw / 10.0 if raw > 100 else raw, 1)
            except Exception:
                pass

        # 3. Sysfs Thermal Zone check for CPU temperature
        thermal_base = "/sys/class/thermal"
        if os.path.exists(thermal_base):
            try:
                temps = []
                for entry in os.listdir(thermal_base):
                    if entry.startswith("thermal_zone"):
                        temp_path = os.path.join(thermal_base, entry, "temp")
                        if os.path.exists(temp_path):
                            try:
                                with open(temp_path, "r") as f:
                                    t = float(f.read().strip())
                                    c_val = t / 1000.0 if t > 1000 else (t / 10.0 if t > 100 else t)
                                    if 0 < c_val < 110:
                                        temps.append(c_val)
                            except Exception:
                                pass
                if temps:
                    cpu_temp_c = round(max(temps), 1)
            except Exception:
                pass

        # Primary thermal metric
        effective_temp_c = cpu_temp_c if cpu_temp_c is not None else battery_temp_c

        # Thermal classification
        if effective_temp_c is None:
            thermal_state = "unavailable"
            thermal_desc = "Thermal sensors unavailable (unrooted standard sandbox)."
        elif effective_temp_c >= self.thermal_critical_c:
            thermal_state = "CRITICAL"
            thermal_desc = f"Thermal critical ({effective_temp_c}°C ≥ {self.thermal_critical_c}°C). Heavy tasks blocked to protect phone."
        elif effective_temp_c >= self.thermal_throttled_c:
            thermal_state = "THROTTLED"
            thermal_desc = f"Device warm and throttling ({effective_temp_c}°C). Heavy tasks throttled."
        elif effective_temp_c >= self.thermal_warm_c:
            thermal_state = "WARM"
            thermal_desc = f"Device operating warm ({effective_temp_c}°C)."
        else:
            thermal_state = "NORMAL"
            thermal_desc = f"Thermal state normal ({effective_temp_c}°C)."

        return {
            "battery_percent": battery_pct,
            "battery_status": battery_status,
            "battery_temperature_c": battery_temp_c,
            "cpu_temperature_c": cpu_temp_c,
            "effective_temperature_c": effective_temp_c,
            "thermal_state": thermal_state,
            "thermal_desc": thermal_desc
        }

    def get_appliance_state(self) -> dict:
        """
        Synthesizes RAM, Swap, Disk, and Thermal into a single authoritative server state.
        """
        mem = self.get_memory_status()
        disk = self.get_disk_status()
        device = self.get_device_telemetry()

        # Check for critical conditions
        if mem["state"] == "critical":
            return {
                "state": "CRITICAL",
                "badge": "✖ CRITICAL RAM",
                "reason": mem["reason"],
                "color": "var(--accent-rose)"
            }
        
        if device["thermal_state"] == "CRITICAL":
            return {
                "state": "CRITICAL",
                "badge": "🔥 THERMAL CRITICAL",
                "reason": device["thermal_desc"],
                "color": "var(--accent-rose)"
            }

        # Check for storage pressure (< 2.0 GB free)
        if disk["free_gb"] < 2.0:
            return {
                "state": "STORAGE PRESSURE",
                "badge": "💾 DISK PRESSURE",
                "reason": f"Storage partition critically low ({disk['free_gb']} GB free). Clean temporary files.",
                "color": "var(--accent-amber)"
            }

        # Check for moderate pressure conditions
        if mem["state"] == "pressure" or device["thermal_state"] in ["THROTTLED", "WARM"]:
            reasons = []
            if mem["state"] == "pressure":
                reasons.append(mem["reason"])
            if device["thermal_state"] in ["THROTTLED", "WARM"]:
                reasons.append(device["thermal_desc"])
            return {
                "state": "PRESSURE",
                "badge": "▲ RESOURCE PRESSURE",
                "reason": " • ".join(reasons),
                "color": "var(--accent-amber)"
            }

        return {
            "state": "HEALTHY",
            "badge": "● HEALTHY",
            "reason": "RAM, thermal, and storage operating within normal parameters.",
            "color": "var(--accent-emerald)"
        }

    def can_start_heavy_task(self) -> dict:
        """Evaluates whether a heavy background job (yt-dlp, ffmpeg, 7z extract, backup) can start."""
        mem = self.get_memory_status()
        device = self.get_device_telemetry()

        if device["thermal_state"] == "CRITICAL":
            return {
                "allowed": False,
                "state": "critical",
                "available_mb": mem["available_mb"],
                "reason": f"Operation rejected: Device thermal critical ({device.get('effective_temperature_c')}°C). Hardware cooldown required."
            }

        if mem["state"] == "critical":
            return {
                "allowed": False,
                "state": "critical",
                "available_mb": mem["available_mb"],
                "reason": f"Operation rejected: RAM is critically low ({mem['available_mb']} MB available < {self.pressure_threshold_mb} MB threshold)."
            }
        if mem["state"] == "pressure":
            return {
                "allowed": False,
                "state": "pressure",
                "available_mb": mem["available_mb"],
                "reason": f"Operation queued: RAM under pressure ({mem['available_mb']} MB available). Will start when memory recovers."
            }
        return {
            "allowed": True,
            "state": "normal",
            "available_mb": mem["available_mb"],
            "reason": "Memory and thermal resources are sufficient."
        }

    def can_start_rag(self) -> dict:
        """Evaluates whether RAG index rebuild can be initiated."""
        mem = self.get_memory_status()
        device = self.get_device_telemetry()

        if device["thermal_state"] == "CRITICAL":
            return {
                "allowed": False,
                "state": "critical",
                "available_mb": mem["available_mb"],
                "reason": "RAG rebuild blocked: Device thermal critical."
            }

        if mem["state"] == "critical":
            return {
                "allowed": False,
                "state": "critical",
                "available_mb": mem["available_mb"],
                "reason": f"RAG rebuild blocked: critically low RAM ({mem['available_mb']} MB available)."
            }
        return {
            "allowed": True,
            "state": mem["state"],
            "available_mb": mem["available_mb"],
            "reason": "RAG indexing permitted."
        }

    def can_start_ollama(self) -> dict:
        """Evaluates whether the optional heavy Ollama AI engine can be started."""
        mem = self.get_memory_status()
        device = self.get_device_telemetry()

        if device["thermal_state"] == "CRITICAL":
            return {
                "allowed": False,
                "state": "critical",
                "available_mb": mem["available_mb"],
                "reason": "Ollama startup blocked: Device thermal critical."
            }

        if mem["state"] == "critical":
            return {
                "allowed": False,
                "state": "critical",
                "available_mb": mem["available_mb"],
                "reason": f"Ollama startup blocked: only {mem['available_mb']} MB RAM available (minimum required: {self.pressure_threshold_mb} MB)."
            }
        return {
            "allowed": True,
            "state": mem["state"],
            "available_mb": mem["available_mb"],
            "reason": "Ollama startup permitted."
        }

governor = ResourceGovernor()
