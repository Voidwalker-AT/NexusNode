"""
NexusNode — Agent In-Memory Sliding-Window Rate Limiter
Prevents runaway agent execution loops and enforces per-principal and per-tool limits.
"""

import time
import threading
from typing import Dict, List, Tuple, Optional


class AgentRateLimiter:
    """Thread-safe sliding-window rate limiter for agent MCP invocations."""

    def __init__(
        self,
        default_principal_rpm: int = 60,
        default_tool_rpm: int = 30,
        tool_rpm_overrides: Optional[Dict[str, int]] = None
    ):
        self.default_principal_rpm = default_principal_rpm
        self.default_tool_rpm = default_tool_rpm
        if tool_rpm_overrides is not None:
            self.tool_rpm_overrides = dict(tool_rpm_overrides)
        else:
            self.tool_rpm_overrides = {
                "upes.get_attendance": 20,
                "upes.get_timetable": 20,
                "upes.get_next_classes": 30,
                "vault.search": 20,
                "vault.read": 40,
                "nexus.status": 60
            }
        self._lock = threading.Lock()
        # Maps principal -> list of timestamps
        self._principal_hits: Dict[str, List[float]] = {}
        # Maps (principal, tool_name) -> list of timestamps
        self._tool_hits: Dict[Tuple[str, str], List[float]] = {}

    def check_rate_limit(self, principal: str, tool_name: str) -> Tuple[bool, Optional[str], Optional[int]]:
        """
        Checks whether the invocation is allowed under current rate limits.
        Returns:
          (is_allowed: bool, rejection_reason: Optional[str], retry_after_seconds: Optional[int])
        """
        now = time.time()
        window_start = now - 60.0

        with self._lock:
            # 1. Clean & check principal limit
            p_hits = [t for t in self._principal_hits.get(principal, []) if t > window_start]
            if len(p_hits) >= self.default_principal_rpm:
                oldest = p_hits[0]
                retry_after = max(1, int(oldest + 60.0 - now))
                return False, f"Principal rate limit exceeded ({self.default_principal_rpm} req/min).", retry_after

            # 2. Clean & check tool limit
            tool_max = self.tool_rpm_overrides.get(tool_name, self.default_tool_rpm)
            t_key = (principal, tool_name)
            t_hits = [t for t in self._tool_hits.get(t_key, []) if t > window_start]
            if len(t_hits) >= tool_max:
                oldest = t_hits[0]
                retry_after = max(1, int(oldest + 60.0 - now))
                return False, f"Tool rate limit exceeded for '{tool_name}' ({tool_max} req/min).", retry_after

            # 3. Record invocation
            p_hits.append(now)
            t_hits.append(now)
            self._principal_hits[principal] = p_hits
            self._tool_hits[t_key] = t_hits

            return True, None, None

    def reset(self):
        """Clears all in-memory rate limit records (for testing)."""
        with self._lock:
            self._principal_hits.clear()
            self._tool_hits.clear()
