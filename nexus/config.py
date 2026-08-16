"""
NexusNode CLI — Local Configuration & Session Token Storage Manager
Handles server URL resolution, local client settings, and secure session persistence across OS platforms.
"""

import os
import sys
import json
from pathlib import Path


def get_config_dir() -> Path:
    """Returns platform-appropriate configuration directory path."""
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            p = Path(appdata) / "nexusnode"
        else:
            p = Path.home() / ".config" / "nexusnode"
    else:
        # Linux, macOS, Termux, Android
        p = Path.home() / ".config" / "nexusnode"

    try:
        p.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return p


def get_config_file() -> Path:
    """Returns configuration file path: config.json."""
    return get_config_dir() / "config.json"


def get_session_file() -> Path:
    """Returns session file path: session.json."""
    return get_config_dir() / "session.json"


def load_config() -> dict:
    """Loads configuration dictionary from disk."""
    cfg_file = get_config_file()
    if cfg_file.exists():
        try:
            with open(cfg_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_config(data: dict) -> None:
    """Saves configuration dictionary to disk."""
    cfg_file = get_config_file()
    try:
        with open(cfg_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


def load_session() -> dict | None:
    """Loads active session data from disk if present."""
    sess_file = get_session_file()
    if sess_file.exists():
        try:
            with open(sess_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict) and "token" in data:
                    return data
        except Exception:
            return None
    return None


def save_session(session_data: dict) -> None:
    """Saves session data securely to disk with mode 0600 on POSIX platforms."""
    sess_file = get_session_file()
    try:
        with open(sess_file, "w", encoding="utf-8") as f:
            json.dump(session_data, f, indent=2)

        # Apply POSIX permission restriction (0600) where supported
        if sys.platform != "win32":
            try:
                os.chmod(sess_file, 0o600)
            except Exception:
                pass
    except Exception:
        pass


def clear_session() -> None:
    """Removes stored session data from disk."""
    sess_file = get_session_file()
    if sess_file.exists():
        try:
            sess_file.unlink()
        except Exception:
            pass


def resolve_server_url(cli_server: str = None, prompt_if_missing: bool = False) -> str | None:
    """
    Resolves the remote NexusNode server URL with strict precedence:
    1. CLI argument (--server)
    2. Environment variable (NEXUS_SERVER)
    3. Stored config file (~/.config/nexusnode/config.json)
    4. Interactive prompt (if prompt_if_missing=True and stdin is a tty)
    """
    # 1. CLI flag
    if cli_server and cli_server.strip():
        url = cli_server.strip().rstrip("/")
        # Update config cache if valid
        cfg = load_config()
        cfg["server_url"] = url
        save_config(cfg)
        return url

    # 2. Environment Variable
    env_server = os.environ.get("NEXUS_SERVER")
    if env_server and env_server.strip():
        return env_server.strip().rstrip("/")

    # 3. Local Config File
    cfg = load_config()
    cfg_server = cfg.get("server_url")
    if cfg_server and str(cfg_server).strip():
        return str(cfg_server).strip().rstrip("/")

    # 4. Interactive prompt
    if prompt_if_missing:
        try:
            if sys.stdin.isatty():
                print("NexusNode Server URL has not been configured.")
                entered = input("Enter NexusNode Server URL (e.g. https://...): ").strip().rstrip("/")
                if entered:
                    cfg["server_url"] = entered
                    save_config(cfg)
                    return entered
        except (KeyboardInterrupt, EOFError):
            return None

    return None
