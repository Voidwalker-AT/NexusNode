"""
NexusNode — Ephemeral Chromium Runtime Manager for TECNO BG6
Manages process lifecycle, proot Alpine container execution, memory admission governance,
single-flight concurrency lock (MAX_BROWSER_JOBS=1), and process tree cleanup.
"""

import os
import sys
import time
import signal
import socket
import logging
import subprocess
import urllib.request
import urllib.error
from typing import Dict, Any, List, Optional, Tuple

from .cdp_client import CDPClient, get_browser_version, list_browser_targets, create_new_target, select_page_target

logger = logging.getLogger("NEXUS_CHROMIUM_RUNTIME")

# Production Flags - Derived strictly from Phase 4.1A empirical baseline
EXACT_CHROMIUM_FLAGS = [
    "--headless=new",
    "--no-sandbox",
    "--disable-gpu",
    "--disable-dev-shm-usage",
    "--disable-extensions",
    "--remote-debugging-address=127.0.0.1"
]

DEFAULT_DEBUGGING_PORT = 9222
MIN_MEM_AVAILABLE_MB = 800  # Initial admission threshold tuned from 1.62GB empirical floor
DEFAULT_WORKFLOW_TIMEOUT_SEC = 60.0


class BrowserUnavailableError(Exception):
    """Raised when system resources, memory governor, or runtime failures prevent launch."""
    pass


class ConcurrencyLockError(Exception):
    """Raised when another browser job is already active (MAX_BROWSER_JOBS=1)."""
    pass


# ==============================================================================
# Cross-Platform Single-Flight File Lock
# ==============================================================================

class SingleFlightLock:
    """Non-blocking global browser lock enforcing MAX_BROWSER_JOBS=1."""

    def __init__(self, lock_path: Optional[str] = None):
        tmp = os.environ.get("TMPDIR", "/data/data/com.termux/files/usr/tmp")
        self.lock_path = lock_path or os.path.join(tmp, "nexusnode_browser_flight.lock")
        self._fd: Optional[int] = None
        self._file_obj = None

    def acquire(self) -> bool:
        os.makedirs(os.path.dirname(os.path.abspath(self.lock_path)), exist_ok=True)
        try:
            if sys.platform != "win32":
                import fcntl
                self._file_obj = open(self.lock_path, "w")
                fcntl.flock(self._file_obj.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                self._file_obj.write(f"{os.getpid()}:{time.time()}\n")
                self._file_obj.flush()
                return True
            else:
                import msvcrt
                self._file_obj = open(self.lock_path, "w")
                msvcrt.locking(self._file_obj.fileno(), msvcrt.LK_NBLCK, 1)
                self._file_obj.write(f"{os.getpid()}:{time.time()}\n")
                self._file_obj.flush()
                return True
        except (IOError, BlockingIOError, PermissionError, OSError) as e:
            self.release()
            raise ConcurrencyLockError(f"Browser runtime is busy. Concurrency=1 enforced. ({e})") from e

    def release(self):
        if self._file_obj:
            try:
                if sys.platform != "win32":
                    import fcntl
                    fcntl.flock(self._file_obj.fileno(), fcntl.LOCK_UN)
                else:
                    import msvcrt
                    try:
                        self._file_obj.seek(0)
                        msvcrt.locking(self._file_obj.fileno(), msvcrt.LK_UNLCK, 1)
                    except Exception:
                        pass
                self._file_obj.close()
            except Exception:
                pass
            self._file_obj = None

        if os.path.exists(self.lock_path):
            try:
                os.remove(self.lock_path)
            except Exception:
                pass


# ==============================================================================
# System Memory Introspection & Admission Governor
# ==============================================================================

def read_system_meminfo() -> Dict[str, int]:
    """Reads /proc/meminfo on Linux/Android appliances, returning MB."""
    info: Dict[str, int] = {}
    if not os.path.exists("/proc/meminfo"):
        return {"MemAvailable": 2048, "MemTotal": 4096}  # Fallback for dev/Windows

    try:
        with open("/proc/meminfo", "r") as f:
            for line in f:
                parts = line.split(":")
                if len(parts) == 2:
                    k = parts[0].strip()
                    val_kb = parts[1].strip().split()[0]
                    info[k] = int(val_kb) // 1024
    except Exception as e:
        logger.warning(f"Failed to read /proc/meminfo: {e}")
    return info


def read_zram_used_mb() -> int:
    """Reads /proc/swaps to calculate ZRAM usage in MB."""
    if not os.path.exists("/proc/swaps"):
        return 0
    used_mb = 0
    try:
        with open("/proc/swaps", "r") as f:
            for line in f.readlines()[1:]:
                parts = line.split()
                if len(parts) >= 4 and "zram" in parts[0]:
                    used_mb += int(parts[3]) // 1024
    except Exception:
        pass
    return used_mb


def find_system_chromium_pids() -> List[int]:
    """Scans /proc for all running chromium or proot processes."""
    pids: List[int] = []
    if not os.path.exists("/proc"):
        return pids

    my_pid = os.getpid()
    try:
        for entry in os.listdir("/proc"):
            if entry.isdigit():
                pid = int(entry)
                if pid == my_pid:
                    continue
                try:
                    with open(f"/proc/{pid}/cmdline", "rb") as f:
                        cmd = f.read().decode("latin1", errors="ignore")
                        if "chromium" in cmd or "proot" in cmd:
                            pids.append(pid)
                except Exception:
                    continue
    except Exception:
        pass
    return pids


def get_process_tree_rss_mb(pids: List[int]) -> int:
    """Calculates summed VmRSS for a list of PIDs."""
    total_rss = 0
    for pid in pids:
        try:
            with open(f"/proc/{pid}/status", "r") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        total_rss += int(line.split()[1]) // 1024
                        break
        except Exception:
            continue
    return total_rss


class MemoryAdmissionGovernor:
    """Evaluates appliance health and enforces browser admission thresholds."""

    def __init__(self, min_available_mb: int = MIN_MEM_AVAILABLE_MB):
        self.min_available_mb = min_available_mb

    def check_admission(self) -> Dict[str, Any]:
        meminfo = read_system_meminfo()
        mem_avail = meminfo.get("MemAvailable", 0)
        zram_used = read_zram_used_mb()

        # Telemetry
        telemetry = {
            "mem_available_mb": mem_avail,
            "zram_used_mb": zram_used,
            "admission_allowed": mem_avail >= self.min_available_mb,
            "threshold_mb": self.min_available_mb
        }

        if mem_avail < self.min_available_mb:
            raise BrowserUnavailableError(
                f"BROWSER_RESOURCE_PRESSURE: System MemAvailable is {mem_avail} MB, below safety threshold {self.min_available_mb} MB."
            )

        return telemetry


# ==============================================================================
# Ephemeral Chromium Runtime Manager
# ==============================================================================

class EphemeralChromiumRuntime:
    """
    Manages the lifecycle of a dedicated, ephemeral Chromium process tree.
    Guarantees:
      - Max 1 active instance
      - Memory admission gate
      - Port binding to 127.0.0.1
      - True page target selection (ignoring extensions)
      - Hard timeout watchdog
      - Clean process group teardown with zero orphaned processes
    """

    def __init__(
        self,
        port: int = DEFAULT_DEBUGGING_PORT,
        workflow_timeout_sec: float = DEFAULT_WORKFLOW_TIMEOUT_SEC,
        governor: Optional[MemoryAdmissionGovernor] = None
    ):
        self.port = port
        self.workflow_timeout_sec = workflow_timeout_sec
        self.governor = governor or MemoryAdmissionGovernor()
        self.lock = SingleFlightLock()
        self.proc: Optional[subprocess.Popen] = None
        self.cdp_client: Optional[CDPClient] = None
        self.active_page_target: Optional[Dict[str, Any]] = None
        self.profile_path: Optional[str] = None
        self.start_time: float = 0.0
        self.cold_start_ms: int = 0
        self.initial_mem_available_mb: int = 0
        self.peak_mem_available_mb: int = 0

    def cleanup_stale_processes(self):
        """Kills any lingering orphan Chromium processes from previous runs."""
        pids = find_system_chromium_pids()
        if pids:
            logger.info(f"Cleaning up {len(pids)} stale Chromium / proot processes.")
            for pid in pids:
                try:
                    os.kill(pid, signal.SIGKILL)
                except Exception:
                    pass
            time.sleep(0.1)

    def launch(self, user_data_dir: str) -> "EphemeralChromiumRuntime":
        """
        Runs admission check, acquires global lock, and spawns Chromium.
        """
        # 1. Clean stale processes
        self.cleanup_stale_processes()

        # 2. Admission Check
        admission = self.governor.check_admission()
        self.initial_mem_available_mb = admission.get("mem_available_mb", 0)

        # 3. Acquire Concurrency Lock
        self.lock.acquire()

        self.profile_path = user_data_dir
        self.start_time = time.time()

        # 4. Build command line
        # Check if proot-distro is installed (production on TECNO BG6)
        is_termux = os.path.exists("/data/data/com.termux/files/usr/bin/proot-distro")

        cmd: List[str] = []
        if is_termux:
            cmd = [
                "proot-distro", "login", "alpine", "--",
                "chromium-browser",
                f"--remote-debugging-port={self.port}",
                f"--user-data-dir={user_data_dir}"
            ] + EXACT_CHROMIUM_FLAGS
        else:
            # Fallback for dev / tests on other machines
            browser_bin = "chromium" if sys.platform != "win32" else "chrome"
            # If chrome not in path, use dummy or mock
            cmd = [
                browser_bin,
                f"--remote-debugging-port={self.port}",
                f"--user-data-dir={user_data_dir}"
            ] + EXACT_CHROMIUM_FLAGS

        logger.info(f"Spawning Chromium on port {self.port} with profile {user_data_dir}")

        preexec = os.setsid if hasattr(os, "setsid") else None

        try:
            self.proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                preexec_fn=preexec
            )
        except Exception as e:
            self.shutdown()
            raise BrowserUnavailableError(f"Failed to spawn Chromium process: {e}") from e

        # 5. Wait for readiness on port 9222
        ready = False
        version_info = None
        for _ in range(100):  # 10.0s max wait
            try:
                version_info = get_browser_version(port=self.port, timeout=0.3)
                if version_info and "Browser" in version_info:
                    ready = True
                    break
            except Exception:
                time.sleep(0.05)

        if not ready:
            self.shutdown()
            raise BrowserUnavailableError(f"Chromium failed to become ready on port {self.port} within 10s.")

        self.cold_start_ms = int((time.time() - self.start_time) * 1000)
        logger.info(f"Chromium ready in {self.cold_start_ms} ms. Version: {version_info.get('Browser')}")

        # 6. Select Page Target (Enforcing Type == 'page' Regression Filter)
        targets = list_browser_targets(port=self.port)
        page_target = select_page_target(targets)

        if not page_target:
            # Create fresh page if only background targets exist
            page_target = create_new_target(port=self.port, url="about:blank")

        if not page_target or not page_target.get("webSocketDebuggerUrl"):
            self.shutdown()
            raise BrowserUnavailableError("Could not acquire a valid page target over CDP.")

        self.active_page_target = page_target
        ws_url = page_target["webSocketDebuggerUrl"]

        # 7. Connect CDP Client
        self.cdp_client = CDPClient(ws_url=ws_url, timeout=15.0)

        # Enable core domains
        self.cdp_client.call("Page.enable")
        self.cdp_client.call("Runtime.enable")
        self.cdp_client.call("DOM.enable")

        return self

    def check_watchdog(self):
        """Verifies session has not exceeded hard workflow timeout."""
        if self.start_time > 0 and (time.time() - self.start_time) > self.workflow_timeout_sec:
            logger.warning(f"Workflow timeout ({self.workflow_timeout_sec}s) exceeded. Forcing shutdown.")
            self.shutdown()
            raise BrowserUnavailableError(f"Browser job exceeded hard timeout of {self.workflow_timeout_sec}s.")

    def shutdown(self) -> int:
        """
        Gracefully closes CDP and terminates process group.
        Verifies 0 orphaned processes remain.
        Releases single-flight lock.
        Returns shutdown duration in ms.
        """
        t0 = time.time()

        # 1. Close CDP connection & browser
        if self.cdp_client:
            try:
                self.cdp_client.call("Browser.close", timeout=2.0)
            except Exception:
                pass
            try:
                self.cdp_client.close()
            except Exception:
                pass
            self.cdp_client = None

        # 2. Terminate process group
        if self.proc:
            try:
                if hasattr(os, "killpg") and hasattr(os, "getpgid"):
                    os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
                else:
                    self.proc.terminate()
            except Exception:
                pass

        # 3. Wait up to 2.0s for clean exit
        wait_start = time.time()
        while time.time() - wait_start < 2.0:
            pids = find_system_chromium_pids()
            if not pids:
                break
            time.sleep(0.05)

        # 4. Force kill if still lingering
        pids = find_system_chromium_pids()
        if pids:
            for pid in pids:
                try:
                    os.kill(pid, signal.SIGKILL)
                except Exception:
                    pass

        self.proc = None
        self.active_page_target = None
        self.start_time = 0.0

        # 5. Release Lock
        self.lock.release()

        shutdown_ms = int((time.time() - t0) * 1000)
        logger.info(f"Chromium shutdown completed in {shutdown_ms} ms. Orphan count: {len(find_system_chromium_pids())}")
        return shutdown_ms
