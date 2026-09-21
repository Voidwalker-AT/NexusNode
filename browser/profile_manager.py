"""
NexusNode — Browser Profile Management & Tenant Isolation
Manages EPHEMERAL and TENANT_PERSISTENT Chromium user-data directories.
Strictly isolates tenant profiles and ensures credential material is excluded from Vault listings.
"""

import os
import re
import shutil
import time
import uuid
import logging
from enum import Enum
from typing import Optional, Dict, Any

logger = logging.getLogger("NEXUS_PROFILE_MGR")


class ProfileType(Enum):
    EPHEMERAL = "ephemeral"
    TENANT_PERSISTENT = "tenant_persistent"


class ProfileSecurityError(Exception):
    """Raised on unauthorized cross-tenant profile access or path traversal."""
    pass


class ProfileManager:
    """
    Manages browser profile lifecycles, directory allocation, path sanitization,
    and cleanup.
    """

    def __init__(self, base_vault_dir: Optional[str] = None, tmp_dir: Optional[str] = None):
        if base_vault_dir:
            self.base_profiles_dir = os.path.realpath(os.path.join(base_vault_dir, "browser_profiles"))
        else:
            # Default to storage_vault/browser_profiles
            server_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            self.base_profiles_dir = os.path.realpath(os.path.join(server_dir, "storage_vault", "browser_profiles"))

        self.tmp_dir = os.path.realpath(tmp_dir or os.environ.get("TMPDIR", "/data/data/com.termux/files/usr/tmp"))
        os.makedirs(self.base_profiles_dir, exist_ok=True)
        os.makedirs(self.tmp_dir, exist_ok=True)

    def _sanitize_identifier(self, identifier: str) -> str:
        """Sanitizes user_id or provider name to prevent path traversal."""
        if not identifier or not isinstance(identifier, str):
            raise ProfileSecurityError("Invalid empty identifier.")
        cleaned = re.sub(r"[^a-zA-Z0-9_\-\.]", "_", identifier.strip())
        if ".." in cleaned or cleaned.startswith(".") or cleaned.startswith("/"):
            raise ProfileSecurityError(f"Path traversal detected in identifier '{identifier}'.")
        return cleaned

    def allocate_profile(
        self,
        profile_type: ProfileType = ProfileType.EPHEMERAL,
        user_id: Optional[str] = None,
        provider: str = "default"
    ) -> str:
        """
        Allocates a browser profile directory.
        Returns the absolute path to the user-data directory.
        """
        if profile_type == ProfileType.EPHEMERAL:
            unique_name = f"eph_prof_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"
            profile_path = os.path.realpath(os.path.join(self.tmp_dir, unique_name))
            os.makedirs(profile_path, exist_ok=True)
            return profile_path

        elif profile_type == ProfileType.TENANT_PERSISTENT:
            if not user_id:
                raise ProfileSecurityError("user_id is required for TENANT_PERSISTENT profiles.")

            safe_uid = self._sanitize_identifier(user_id)
            safe_provider = self._sanitize_identifier(provider)

            user_profile_dir = os.path.realpath(os.path.join(self.base_profiles_dir, safe_uid, safe_provider))

            # Strict containment check
            expected_prefix = os.path.realpath(os.path.join(self.base_profiles_dir, safe_uid))
            if not user_profile_dir.startswith(expected_prefix):
                raise ProfileSecurityError(f"Path traversal attempted: {user_profile_dir} escapes {expected_prefix}")

            os.makedirs(user_profile_dir, exist_ok=True)
            return user_profile_dir

        raise ValueError(f"Unknown profile type: {profile_type}")

    def cleanup_profile(self, profile_path: str, profile_type: ProfileType = ProfileType.EPHEMERAL):
        """
        Cleans up profile storage.
        Ephemeral profiles are recursively removed.
        Persistent profiles are preserved.
        """
        if not profile_path or not os.path.exists(profile_path):
            return

        real_path = os.path.realpath(profile_path)

        if profile_type == ProfileType.EPHEMERAL:
            # Verify profile is in TMPDIR before deleting
            if real_path.startswith(self.tmp_dir):
                try:
                    shutil.rmtree(real_path, ignore_errors=True)
                    logger.debug(f"Purged ephemeral profile: {real_path}")
                except Exception as e:
                    logger.warning(f"Failed to delete ephemeral profile {real_path}: {e}")
            else:
                logger.warning(f"Refusing to delete ephemeral profile outside tmp_dir: {real_path}")

        elif profile_type == ProfileType.TENANT_PERSISTENT:
            # Clean up transient lock files and crash reports within persistent profile
            lock_files = ["SingletonLock", "SingletonSocket", "SingletonCookie"]
            for lf in lock_files:
                target = os.path.join(real_path, lf)
                if os.path.exists(target) or os.path.islink(target):
                    try:
                        os.remove(target)
                    except Exception:
                        pass

    def is_vault_protected_path(self, path: str) -> bool:
        """
        Returns True if path points inside browser profiles directory.
        Used by Vault tools to prevent exposing browser sessions / credentials.
        """
        if not path:
            return False
        real_target = os.path.realpath(path)
        return real_target.startswith(self.base_profiles_dir)
