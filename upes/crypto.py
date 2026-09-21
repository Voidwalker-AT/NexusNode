"""
NexusNode — UPES Session Cryptography Provider
Provides authenticated AES-256-GCM encryption with strict HKDF domain separation:
Domain: nexusnode/upes/session/v1
Cryptographically isolated from credential storage (nexusnode/upes/credentials/v1).
"""

import json
import base64
import secrets
import logging
from typing import Optional, Dict, Any
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes

import config

logger = logging.getLogger("NEXUS_UPES_SESSION_CRYPTO")


class UpesSessionCrypto:
    """Authenticated AES-256-GCM encryption for UPES OAuth session material with dedicated HKDF domain."""

    DOMAIN_INFO = b"nexusnode/upes/session/v1"
    KDF_SALT = b"nexusnode_upes_session_aesgcm_salt_v1"

    @classmethod
    def _derive_key(cls) -> bytes:
        """Derives a dedicated 256-bit AES session key from SECRET_KEY using HKDF-SHA256."""
        secret_bytes = config.SECRET_KEY.encode("utf-8")
        hkdf = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=cls.KDF_SALT,
            info=cls.DOMAIN_INFO,
        )
        return hkdf.derive(secret_bytes)

    @classmethod
    def encrypt(cls, plaintext_dict: Dict[str, Any]) -> str:
        """Encrypts session bundle into URL-safe base64 string (12-byte nonce + ciphertext + 16-byte tag)."""
        key = cls._derive_key()
        aesgcm = AESGCM(key)
        nonce = secrets.token_bytes(12)
        payload = dict(plaintext_dict)
        payload["version"] = 1
        payload["domain"] = "nexusnode/upes/session/v1"
        payload_bytes = json.dumps(payload).encode("utf-8")
        ciphertext = aesgcm.encrypt(nonce, payload_bytes, None)
        combined = nonce + ciphertext
        return base64.urlsafe_b64encode(combined).decode("ascii")

    @classmethod
    def decrypt(cls, encrypted_str: str) -> Optional[Dict[str, Any]]:
        """Decrypts base64 string using AES-GCM and validates domain separation. Returns None on failure."""
        if not encrypted_str:
            return None
        try:
            combined = base64.urlsafe_b64decode(encrypted_str.encode("ascii"))
            if len(combined) < 28:  # 12-byte nonce + 16-byte GCM tag
                return None
            nonce = combined[:12]
            ciphertext = combined[12:]
            key = cls._derive_key()
            aesgcm = AESGCM(key)
            decrypted_bytes = aesgcm.decrypt(nonce, ciphertext, None)
            data = json.loads(decrypted_bytes.decode("utf-8"))
            if not isinstance(data, dict):
                return None
            # Validate domain envelope
            if data.get("domain") != "nexusnode/upes/session/v1":
                logger.warning("Decrypted session payload does not match expected cryptographic domain.")
                return None
            return data
        except Exception as e:
            logger.debug(f"Session decryption failed: {e}")
            return None
