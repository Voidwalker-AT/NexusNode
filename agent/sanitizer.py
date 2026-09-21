"""
NexusNode — MCP Output Sanitizer & Defense-in-Depth Privacy Filter
Scans outgoing agent responses to prevent accidental token or credential leakage.
"""

import re
from typing import Any, Dict, List, Union

# Common high-entropy token/key patterns
_JWT_PATTERN = re.compile(r"eyJ[A-Za-z0-9-_=]+\.eyJ[A-Za-z0-9-_=]+\.[A-Za-z0-9-_.+/=]+")
_SECRET_KEY_PATTERN = re.compile(r"(?i)(password|secret|auth_token|refresh_token|idp_session_info|cookie_val)[\"']?\s*[:=]\s*[\"']?([A-Za-z0-9-_+=/]{8,})[\"']?")
_BLOCKED_KEYS = {
    "password", "encrypted_password", "access_token", "encrypted_access_token",
    "refresh_token", "encrypted_refresh_token", "idp_session_info", "encrypted_cookies",
    "auth_token", "secret", "secret_key", "client_secret"
}


def sanitize_text(text: str) -> str:
    """Redacts potential JWTs or sensitive key-value pairs from text."""
    if not isinstance(text, str):
        return text
    
    # Redact JWT tokens
    sanitized = _JWT_PATTERN.sub("[REDACTED_JWT_TOKEN]", text)
    # Redact sensitive assignment pairs
    sanitized = _SECRET_KEY_PATTERN.sub(r'\1: "[REDACTED_SECRET]"', sanitized)
    return sanitized


def sanitize_data(data: Any) -> Any:
    """Recursively traverses dictionaries, lists, and primitives to redact sensitive fields."""
    if isinstance(data, dict):
        cleaned = {}
        for k, v in data.items():
            if str(k).lower() in _BLOCKED_KEYS:
                cleaned[k] = "[REDACTED_SECRET]"
            else:
                cleaned[k] = sanitize_data(v)
        return cleaned
    elif isinstance(data, list):
        return [sanitize_data(item) for item in data]
    elif isinstance(data, str):
        return sanitize_text(data)
    else:
        return data
