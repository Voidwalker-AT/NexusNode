"""
NexusNode CLI — Local Configuration & Session Token Storage Manager
Handles server URL resolution, local client settings, and secure session persistence across OS platforms.
"""

import os
import sys
import json
import urllib.parse
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


def normalize_server_url(url_str: str) -> str:
    """
    Normalizes server URL string to a clean base origin with protocol scheme.
    Preserves LocalToNet queries or parameters if needed, but ensures standard URL root.
    """
    if not url_str:
        return ""
    clean = url_str.strip()
    if not clean.startswith("http://") and not clean.startswith("https://"):
        if "127.0.0.1" in clean or "localhost" in clean:
            clean = f"http://{clean}"
        else:
            clean = f"https://{clean}"

    # Remove trailing slash
    return clean.rstrip("/")


def resolve_server_url(cli_server: str = None, prompt_if_missing: bool = False) -> str | None:
    """
    Resolves the remote NexusNode server URL with strict precedence:
    1. CLI argument (--server or positional connect url)
    2. Environment variable (NEXUS_SERVER)
    3. Stored session file (last connected server)
    4. Stored config file (~/.config/nexusnode/config.json)
    5. Interactive prompt (if prompt_if_missing=True and stdin is a tty)
    """
    # 1. CLI parameter
    if cli_server and cli_server.strip():
        url = normalize_server_url(cli_server)
        cfg = load_config()
        cfg["server_url"] = url
        save_config(cfg)
        return url

    # 2. Environment Variable
    env_server = os.environ.get("NEXUS_SERVER")
    if env_server and env_server.strip():
        return normalize_server_url(env_server)

    # 3. Active/Saved Session
    sess = load_session()
    if sess and sess.get("server_url"):
        return normalize_server_url(sess.get("server_url"))

    # 4. Local Config File
    cfg = load_config()
    cfg_server = cfg.get("server_url")
    if cfg_server and str(cfg_server).strip():
        return normalize_server_url(str(cfg_server))

    # 5. Interactive prompt
    if prompt_if_missing:
        try:
            if sys.stdin.isatty():
                print("NexusNode Server URL has not been configured.")
                entered = input("Enter NexusNode Server URL (e.g. https://...): ").strip()
                if entered:
                    norm = normalize_server_url(entered)
                    cfg["server_url"] = norm
                    save_config(cfg)
                    return norm
        except (KeyboardInterrupt, EOFError):
            return None

    return None
