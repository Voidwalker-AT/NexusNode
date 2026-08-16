from __future__ import annotations

import os
import re
import sys
import json
import datetime
from typing import Any, Dict, List, Optional, Tuple, Union

# --- Color Configuration & State ---
_COLOR_OVERRIDE = None

# ANSI Escape Sequences
_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"

_RED = "\033[31m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_BLUE = "\033[34m"
_MAGENTA = "\033[35m"
_CYAN = "\033[36m"
_WHITE = "\033[37m"

_BRIGHT_RED = "\033[91m"
_BRIGHT_GREEN = "\033[92m"
_BRIGHT_YELLOW = "\033[93m"
_BRIGHT_BLUE = "\033[94m"
_BRIGHT_MAGENTA = "\033[95m"
_BRIGHT_CYAN = "\033[96m"
_BRIGHT_WHITE = "\033[97m"

# Windows VT Processing initialization
if sys.platform == "win32":
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        hOut = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_ulong()
        if kernel32.GetConsoleMode(hOut, ctypes.byref(mode)):
            kernel32.SetConsoleMode(hOut, mode.value | 0x0004)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
    except Exception:
        pass


def is_color_enabled() -> bool:
    """Returns True if ANSI terminal colors should be emitted."""
    global _COLOR_OVERRIDE
    if _COLOR_OVERRIDE is not None:
        return _COLOR_OVERRIDE

    # Check environment variables
    if "NO_COLOR" in os.environ or "NEXUS_NO_COLOR" in os.environ:
        return False

    # Check if stdout is an interactive terminal
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


def set_color_enabled(enabled: bool):
    """Explicitly enable or disable color output."""
    global _COLOR_OVERRIDE
    _COLOR_OVERRIDE = bool(enabled)


def strip_ansi(text: str) -> str:
    """Removes all ANSI escape codes from string."""
    return re.sub(r"\x1b\[[0-9;]*m", "", str(text))


def visible_len(text: str) -> int:
    """Calculates visible display length of a string excluding ANSI escape sequences."""
    return len(strip_ansi(text))


def colorize(text: any, color_code: str, bold: bool = False) -> str:
    """Applies ANSI color code if colors are enabled, else returns plain text."""
    s = str(text)
    if not is_color_enabled():
        return s
    prefix = (color_code + _BOLD) if bold else color_code
    return f"{prefix}{s}{_RESET}"


def cyan(text: any, bold: bool = False) -> str:
    return colorize(text, _BRIGHT_CYAN, bold=bold)


def green(text: any, bold: bool = False) -> str:
    return colorize(text, _BRIGHT_GREEN, bold=bold)


def yellow(text: any, bold: bool = False) -> str:
    return colorize(text, _BRIGHT_YELLOW, bold=bold)


def red(text: any, bold: bool = False) -> str:
    return colorize(text, _BRIGHT_RED, bold=bold)


def blue(text: any, bold: bool = False) -> str:
    return colorize(text, _BRIGHT_BLUE, bold=bold)


def magenta(text: any, bold: bool = False) -> str:
    return colorize(text, _BRIGHT_MAGENTA, bold=bold)


def white(text: any, bold: bool = False) -> str:
    return colorize(text, _BRIGHT_WHITE, bold=bold)


def dim(text: any) -> str:
    return colorize(text, _DIM, bold=False)


def bold(text: any) -> str:
    return colorize(text, _BOLD, bold=False)


def colorize_status(status_str: any) -> str:
    """Applies standard semantic colors based on status/state keywords."""
    if status_str is None:
        return dim("--")
    s = str(status_str).strip()
    upper = s.upper()

    if upper in ["HEALTHY", "RUNNING", "COMPLETED", "CONNECTED", "ONLINE", "OK", "ACTIVE", "SUCCESS", "TRUE"]:
        return green(s, bold=True)
    elif upper in ["QUEUED", "POST_PROCESSING", "STARTING", "DOWNLOADING", "IDLE", "WARN", "WARNING", "PENDING", "CANCELLING"]:
        return yellow(s, bold=False)
    elif upper in ["FAILED", "CANCELLED", "ERROR", "CRITICAL", "OFFLINE", "STOPPED", "DISABLED", "LOCKED", "UNHEALTHY", "FALSE"]:
        return red(s, bold=True)
    elif upper in ["VERIFYING"]:
        return cyan(s, bold=True)
    elif upper in ["UNAVAILABLE", "N/A", "NONE", "--"]:
        return dim(s)
    else:
        return s


# --- Standard Output Helpers ---

def print_json(data: any):
    """Prints serialized JSON to stdout with 2-space indentation."""
    print(json.dumps(data, indent=2, default=str))


def print_error(msg: str):
    """Prints formatted error message to stderr with red [ERROR] prefix."""
    tag = red("[ERROR]", bold=True)
    print(f"{tag} {msg}", file=sys.stderr)


def print_success(msg: str):
    """Prints formatted success message to stdout with green [OK] prefix."""
    tag = green("[OK]", bold=True)
    print(f"{tag} {msg}")


def print_warning(msg: str):
    """Prints formatted warning message to stderr with yellow [WARN] prefix."""
    tag = yellow("[WARN]", bold=True)
    print(f"{tag} {msg}", file=sys.stderr)


def print_info(msg: str):
    """Prints informational message to stdout with cyan [INFO] prefix."""
    tag = cyan("[INFO]", bold=True)
    print(f"{tag} {msg}")


def print_banner():
    """Prints the compact, polished NexusNode application banner in Nexus Cyan."""
    unicode_banner = (
        "╔════════════════════════════════════════════════════╗\n"
        "║                  N E X U S N O D E                 ║\n"
        "║             MOBILE SERVER APPLIANCE                ║\n"
        "╚════════════════════════════════════════════════════╝"
    )
    ascii_banner = (
        "+----------------------------------------------------+\n"
        "|                  N E X U S N O D E                 |\n"
        "|             MOBILE SERVER APPLIANCE                |\n"
        "+----------------------------------------------------+"
    )
    banner_text = unicode_banner
    if sys.platform == "win32":
        enc = getattr(sys.stdout, "encoding", "") or ""
        if "utf" not in enc.lower():
            banner_text = ascii_banner

    if is_color_enabled():
        try:
            lines = banner_text.splitlines()
            for i, line in enumerate(lines):
                if i == 0 or i == len(lines) - 1:
                    print(cyan(line))
                elif "N E X U S N O D E" in line:
                    border = "║" if banner_text == unicode_banner else "|"
                    print(cyan(border) + white("                  N E X U S N O D E                 ", bold=True) + cyan(border))
                else:
                    border = "║" if banner_text == unicode_banner else "|"
                    print(cyan(border) + dim("             MOBILE SERVER APPLIANCE                ") + cyan(border))
        except UnicodeEncodeError:
            for line in ascii_banner.splitlines():
                print(cyan(line))
    else:
        try:
            print(banner_text)
        except UnicodeEncodeError:
            print(ascii_banner)


def print_step(name: str, status: str = "OK", total_width: int = 24):
    """Prints aligned connection progress step (e.g. 'Endpoint ............. OK')."""
    dots_count = max(2, total_width - len(name))
    dots = dim("." * dots_count) if is_color_enabled() else "." * dots_count
    status_colored = colorize_status(status) if is_color_enabled() else status
    try:
        print(f"{name} {dots} {status_colored}")
    except UnicodeEncodeError:
        print(f"{name} {'.' * dots_count} {strip_ansi(status_colored)}")


def print_panel(title: str, items: List[Tuple[str, str]], width: int = 40):
    """Prints a clean key-value panel block."""
    print()
    print(cyan(title, bold=True) if is_color_enabled() else title)
    try:
        print(dim("─" * width) if is_color_enabled() else "─" * width)
    except UnicodeEncodeError:
        print(dim("-" * width) if is_color_enabled() else "-" * width)

    for k, v in items:
        k_str = f"{k:<12}"
        try:
            print(f"{k_str}: {v}")
        except UnicodeEncodeError:
            print(f"{k_str}: {strip_ansi(v)}")
    print()


def format_bytes(b: Optional[Union[int, float]]) -> str:
    """Formats numeric bytes into human-readable unit string."""
    if b is None:
        return "0 B"
    try:
        n = float(b)
    except (ValueError, TypeError):
        return "0 B"

    if n < 1024:
        return f"{int(n)} B"
    elif n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    elif n < 1024 * 1024 * 1024:
        return f"{n / (1024 * 1024):.1f} MB"
    elif n < 1024 * 1024 * 1024 * 1024:
        return f"{n / (1024 * 1024 * 1024):.2f} GB"
    else:
        return f"{n / (1024 * 1024 * 1024 * 1024):.2f} TB"


def format_duration(seconds: Optional[Union[float, int]]) -> str:
    """Formats seconds into human-readable duration."""
    if seconds is None:
        return "0s"
    try:
        s = int(seconds)
    except (ValueError, TypeError):
        return "0s"

    if s < 60:
        return f"{s}s"
    elif s < 3600:
        mins = s // 60
        secs = s % 60
        return f"{mins:02d}:{secs:02d}"
    else:
        hrs = s // 3600
        mins = (s % 3600) // 60
        secs = s % 60
        return f"{hrs:02d}:{mins:02d}:{secs:02d}"


def format_timestamp(ts: Optional[Union[float, int, str]]) -> str:
    """Formats unix timestamp or ISO string into readable date string."""
    if not ts:
        return "N/A"
    if isinstance(ts, (int, float)):
        try:
            return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return str(ts)
    if isinstance(ts, str):
        return ts.replace("T", " ").replace("Z", "")
    return str(ts)


def print_table(headers: List[str], rows: List[List[Any]], empty_message: str = "No records found."):
    """
    Renders an aligned ASCII table to stdout with ANSI-aware column width calculation.
    """
    if not rows:
        print(empty_message)
        return

    # Convert all cells to strings
    str_rows = [[str(cell if cell is not None else "") for cell in row] for row in rows]
    str_headers = [str(h) for h in headers]

    # Calculate column widths using visible character lengths (ignoring ANSI escape codes)
    col_widths = [visible_len(h) for h in str_headers]
    for row in str_rows:
        for idx, cell in enumerate(row):
            vlen = visible_len(cell)
            if idx < len(col_widths):
                col_widths[idx] = max(col_widths[idx], vlen)
            else:
                col_widths.append(vlen)

    # Format header line
    colored_headers = []
    for i, h in enumerate(str_headers):
        padding = col_widths[i] - visible_len(h)
        h_str = cyan(h, bold=True) if is_color_enabled() else h
        colored_headers.append(h_str + (" " * padding))

    header_line = "  ".join(colored_headers)
    sep_line = "  ".join("-" * col_widths[i] for i in range(len(str_headers)))
    if is_color_enabled():
        sep_line = dim(sep_line)

    print()
    print(header_line)
    print(sep_line)
    for row in str_rows:
        # Pad row if missing columns
        padded = row + [""] * (len(str_headers) - len(row))
        formatted_cells = []
        for i, cell in enumerate(padded[:len(str_headers)]):
            padding = col_widths[i] - visible_len(cell)
            formatted_cells.append(cell + (" " * padding))
        print("  ".join(formatted_cells))
    print()
