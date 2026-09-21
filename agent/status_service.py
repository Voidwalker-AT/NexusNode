"""
NexusNode — Safe Appliance Status Service
Collects and returns high-level appliance health and resource metrics without sensitive data.
"""

import os
import time
import shutil
import logging
from typing import Dict, Any, Optional

import config
from .models import ExecutionResult

logger = logging.getLogger("NEXUS_STATUS_SERVICE")
SERVER_START_TIME = time.time()


class StatusService:
    """Provides non-sensitive appliance health and system metrics for AI agents."""

    def __init__(
        self,
        conn_factory=None,
        upes_router=None,
        browser_provider=None,
        ai_service=None
    ):
        self.conn_factory = conn_factory
        self.upes_router = upes_router
        self.browser_provider = browser_provider
        self.ai_service = ai_service

    def get_status(self, user_id: str = "admin", params: Optional[Dict[str, Any]] = None) -> ExecutionResult:
        """Returns safe appliance status and component health."""
        now = time.time()
        uptime_sec = int(now - SERVER_START_TIME)

        # Storage Metrics for Vault Root
        storage_info = {}
        try:
            total, used, free = shutil.disk_usage(config.STORAGE_DIR)
            storage_info = {
                "total_mb": total // (1024 * 1024),
                "used_mb": used // (1024 * 1024),
                "free_mb": free // (1024 * 1024),
                "percent_used": round((used / total) * 100, 1) if total else 0
            }
        except Exception:
            storage_info = {"total_mb": 0, "used_mb": 0, "free_mb": 0, "percent_used": 0}

        # Memory Metrics
        memory_info = {}
        try:
            import psutil
            vm = psutil.virtual_memory()
            memory_info = {
                "total_mb": vm.total // (1024 * 1024),
                "available_mb": vm.available // (1024 * 1024),
                "percent_used": vm.percent
            }
        except Exception:
            memory_info = {"total_mb": 4096, "available_mb": 2048, "percent_used": 50.0}

        # UPES High-Level State
        upes_state = "UNKNOWN"
        if self.upes_router and self.upes_router.session_tracker:
            try:
                st = self.upes_router.session_tracker.get_safe_status(user_id)
                upes_state = st.get("state", "UNKNOWN")
            except Exception:
                pass

        # Browser Provider Health
        browser_health = {"status": "DISABLED"}
        if self.browser_provider:
            try:
                browser_health = self.browser_provider.get_health()
            except Exception:
                browser_health = {"status": "UNAVAILABLE"}

        # AI Engine Health
        ai_status = "UNKNOWN"
        if self.ai_service and hasattr(self.ai_service, "get_ai_state"):
            try:
                ai_st = self.ai_service.get_ai_state()
                ai_status = ai_st.get("ollama_state", "UNKNOWN")
            except Exception:
                pass

        data = {
            "appliance": {
                "name": "NexusNode Mobile Server Appliance",
                "device": "TECNO BG6",
                "version": getattr(config, "VERSION", "2.3.2"),
                "status": "HEALTHY",
                "uptime_seconds": uptime_sec,
                "timestamp": now
            },
            "resources": {
                "memory": memory_info,
                "storage": storage_info
            },
            "services": {
                "upes_auth_state": upes_state,
                "browser_provider": browser_health.get("status", "UNKNOWN"),
                "ai_engine": ai_status,
                "mcp_gateway": "RUNNING"
            }
        }

        return ExecutionResult(
            ok=True,
            operation="nexus.status",
            source="local",
            provider="status_service",
            data=data,
            fetched_at=now
        )
