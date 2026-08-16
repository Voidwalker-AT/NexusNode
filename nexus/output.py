"""
NexusNode CLI — Terminal Output & Table Formatting Utilities
Zero-dependency compact table formatter, byte/time formatters, and JSON serialization.
"""

import sys
import json
import datetime


def print_json(data: any):
    """Prints serialized JSON to stdout with 2-space indentation."""
    print(json.dumps(data, indent=2, default=str))


def print_error(msg: str):
    """Prints formatted error message to stderr."""
    print(f"[!] Error: {msg}", file=sys.stderr)


def print_success(msg: str):
    """Prints formatted success message to stdout."""
    print(f"[+] {msg}")


def print_warning(msg: str):
    """Prints formatted warning message to stderr."""
    print(f"[*] Warning: {msg}", file=sys.stderr)


def print_info(msg: str):
    """Prints informational message to stdout."""
    print(f"[-] {msg}")


def format_bytes(b: int | float | None) -> str:
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


def format_duration(seconds: float | int | None) -> str:
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
        return f"{mins}m {secs}s"
    else:
        hrs = s // 3600
        mins = (s % 3600) // 60
        return f"{hrs}h {mins}m"


def format_timestamp(ts: float | int | str | None) -> str:
    """Formats unix timestamp or ISO string into readable date string."""
    if not ts:
        return "N/A"
    if isinstance(ts, (int, float)):
        try:
            return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return str(ts)
    if isinstance(ts, str):
        # Truncate ISO T/Z for readability if desired
        return ts.replace("T", " ").replace("Z", "")
    return str(ts)


def print_table(headers: list[str], rows: list[list[any]], empty_message: str = "No records found."):
    """
    Renders an aligned ASCII table to stdout with column dividers.
    """
    if not rows:
        print(empty_message)
        return

    # Convert all cells to strings
    str_rows = [[str(cell if cell is not None else "") for cell in row] for row in rows]
    str_headers = [str(h) for h in headers]

    # Calculate column widths
    col_widths = [len(h) for h in str_headers]
    for row in str_rows:
        for idx, cell in enumerate(row):
            if idx < len(col_widths):
                col_widths[idx] = max(col_widths[idx], len(cell))
            else:
                col_widths.append(len(cell))

    # Format header line
    header_line = "  ".join(f"{h:<{col_widths[i]}}" for i, h in enumerate(str_headers))
    sep_line = "  ".join("-" * col_widths[i] for i in range(len(str_headers)))

    print()
    print(header_line)
    print(sep_line)
    for row in str_rows:
        # Pad row if missing columns
        padded = row + [""] * (len(str_headers) - len(row))
        print("  ".join(f"{cell:<{col_widths[i]}}" for i, cell in enumerate(padded[:len(str_headers)])))
    print()
