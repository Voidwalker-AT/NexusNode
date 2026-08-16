"""
NexusNode CLI — Windows PATH & Environment Manager
Safely and automatically registers the Python Scripts directory in Windows User PATH
(HKCU\\Environment\\Path) so that 'nexus' is immediately discoverable in command shells.
Requires zero administrator privileges and zero third-party dependencies.
"""
from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Optional


def get_candidate_scripts_dirs() -> List[str]:
    """Return all plausible Python Scripts directories where nexus.exe may reside."""
    dirs: List[str] = []

    # 1. sys.prefix/Scripts (standard venv or global install)
    prefix_scripts = os.path.abspath(os.path.join(sys.prefix, "Scripts"))
    if prefix_scripts not in dirs:
        dirs.append(prefix_scripts)

    # 2. LocalAppData Python Scripts (%LOCALAPPDATA%\\Programs\\Python\\PythonXY\\Scripts)
    local_appdata = os.environ.get("LOCALAPPDATA", "")
    if local_appdata:
        v_str = f"Python{sys.version_info.major}{sys.version_info.minor}"
        py_scripts = os.path.abspath(os.path.join(local_appdata, "Programs", "Python", v_str, "Scripts"))
        if py_scripts not in dirs:
            dirs.append(py_scripts)

    # 3. AppData Roaming Python Scripts (%APPDATA%\\Python\\PythonXY\\Scripts)
    appdata = os.environ.get("APPDATA", "")
    if appdata:
        v_str = f"Python{sys.version_info.major}{sys.version_info.minor}"
        user_scripts = os.path.abspath(os.path.join(appdata, "Python", v_str, "Scripts"))
        if user_scripts not in dirs:
            dirs.append(user_scripts)

    return dirs


def find_nexus_executable() -> Optional[str]:
    """Find the path to the installed nexus.exe or nexus script if it exists."""
    for d in get_candidate_scripts_dirs():
        exe_path = os.path.join(d, "nexus.exe")
        if os.path.isfile(exe_path):
            return exe_path
        script_path = os.path.join(d, "nexus")
        if os.path.isfile(script_path):
            return script_path
    return None


def is_directory_on_path(dir_path: str) -> bool:
    """Check if the given directory is present in the current PATH or HKCU PATH."""
    norm_target = os.path.normpath(dir_path).lower()

    # Check current process PATH
    for p in os.environ.get("PATH", "").split(os.pathsep):
        if p.strip() and os.path.normpath(p.strip()).lower() == norm_target:
            return True

    # Check HKCU\\Environment\\Path if on Windows
    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment", 0, winreg.KEY_READ) as key:
                hkcu_path, _ = winreg.QueryValueEx(key, "Path")
                for p in hkcu_path.split(";"):
                    if p.strip() and os.path.normpath(p.strip()).lower() == norm_target:
                        return True
        except Exception:
            pass

    return False


def ensure_windows_path(silent: bool = True) -> Dict[str, Any]:
    """
    Safely ensure the Python Scripts directory containing nexus.exe is in HKCU User PATH.
    Broadcasts WM_SETTINGCHANGE so new shells inherit the updated PATH immediately.
    """
    if sys.platform != "win32":
        return {"status": "skipped_non_windows", "added": []}

    try:
        import winreg
        import ctypes
    except ImportError:
        return {"status": "error_missing_modules", "added": []}

    # Find candidate directories to register
    exe_path = find_nexus_executable()
    target_dirs = get_candidate_scripts_dirs()
    if exe_path:
        exe_dir = os.path.dirname(exe_path)
        if exe_dir not in target_dirs:
            target_dirs.insert(0, exe_dir)

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment", 0, winreg.KEY_READ) as key:
            current_path, _ = winreg.QueryValueEx(key, "Path")
    except FileNotFoundError:
        current_path = ""
    except Exception:
        current_path = ""

    current_entries = [p.strip() for p in current_path.split(";") if p.strip()]
    normalized_existing = [os.path.normpath(p).lower() for p in current_entries]

    added: List[str] = []
    for d in target_dirs:
        # Only add directories that exist
        if os.path.isdir(d) and os.path.normpath(d).lower() not in normalized_existing:
            current_entries.append(d)
            normalized_existing.append(os.path.normpath(d).lower())
            added.append(d)

    if added:
        new_path_str = ";".join(current_entries)
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment", 0, winreg.KEY_SET_VALUE) as key:
                winreg.SetValueEx(key, "Path", 0, winreg.REG_EXPAND_SZ, new_path_str)

            # Broadcast WM_SETTINGCHANGE
            HWND_BROADCAST = 0xFFFF
            WM_SETTINGCHANGE = 0x001A
            SMTO_ABORTIFHUNG = 0x0002
            result = ctypes.c_long()
            ctypes.windll.user32.SendMessageTimeoutW(
                HWND_BROADCAST, WM_SETTINGCHANGE, 0, "Environment",
                SMTO_ABORTIFHUNG, 5000, ctypes.byref(result)
            )
            # Update current process os.environ["PATH"]
            os.environ["PATH"] = ";".join(added) + ";" + os.environ.get("PATH", "")

            if not silent:
                print(f"[OK] Added to Windows User PATH: {', '.join(added)}")
                print("[NOTE] Newly opened PowerShell/CMD windows will recognize 'nexus' automatically.")
            return {"status": "configured", "added": added, "nexus_exe": exe_path}
        except Exception as e:
            return {"status": "error_writing_registry", "error": str(e), "added": []}

    return {"status": "already_present", "added": [], "nexus_exe": exe_path}


def main() -> int:
    """CLI entry point for nexus-setup."""
    print("NexusNode CLI — Windows Environment & PATH Setup")
    print("-" * 50)
    result = ensure_windows_path(silent=False)
    exe = find_nexus_executable()
    if exe:
        print(f"Nexus Executable : {exe}")
    else:
        print("Nexus Executable : (not found in standard Scripts directories)")

    if result["status"] == "configured":
        print("[SUCCESS] Windows User PATH has been configured.")
        print("You can now open a new PowerShell or Command Prompt window and type 'nexus'.")
    elif result["status"] == "already_present":
        print("[OK] Python Scripts directory is already configured in Windows User PATH.")
        print("If 'nexus' is not recognized in your current shell, open a new shell window.")
    elif result["status"] == "skipped_non_windows":
        print("[INFO] Not running on Windows. PATH configuration is not required.")
    else:
        print(f"[WARNING] PATH setup status: {result['status']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
