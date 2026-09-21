"""
NexusNode — UPES Credential Storage & Security Provider
Manages AES-256-GCM encrypted storage for UPES portal credentials.
Ensures plaintext passwords are never stored in SQLite, never logged, and never returned via APIs.
"""

import time
import json
import base64
import secrets
import sqlite3
import logging
from typing import Optional, Tuple, Dict, Any
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes

import config
from .models import IdentifierFormat, CredentialIdentity

logger = logging.getLogger("NEXUS_UPES_CREDENTIALS")


class UpesCredentialCrypto:
    """Authenticated AES-256-GCM encryption for UPES user credentials with HKDF domain separation."""

    DOMAIN_INFO = b"nexusnode/upes/credentials/v1"
    KDF_SALT = b"nexusnode_root_kdf_salt_v1"

    @classmethod
    def _derive_key(cls) -> bytes:
        """Derives a dedicated 256-bit AES key from SECRET_KEY using HKDF-SHA256."""
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
        """Encrypts credentials into URL-safe base64 string (12-byte nonce + ciphertext + 16-byte tag)."""
        key = cls._derive_key()
        aesgcm = AESGCM(key)
        nonce = secrets.token_bytes(12)
        payload = dict(plaintext_dict)
        payload["version"] = 1
        payload["domain"] = "nexusnode/upes/credentials/v1"
        payload_bytes = json.dumps(payload).encode("utf-8")
        ciphertext = aesgcm.encrypt(nonce, payload_bytes, None)
        combined = nonce + ciphertext
        return base64.urlsafe_b64encode(combined).decode("ascii")

    @classmethod
    def decrypt(cls, encrypted_str: str) -> Optional[Dict[str, Any]]:
        """Decrypts base64 string using AES-GCM and validates domain separation. Returns None on failure."""
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
            if data.get("domain") != "nexusnode/upes/credentials/v1":
                logger.warning("Decrypted credential payload does not match expected cryptographic domain.")
                return None
            return data
        except Exception:
            return None


def init_credential_tables(conn: sqlite3.Connection):
    """Initializes the encrypted credentials table."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS upes_user_credentials (
            user_id TEXT PRIMARY KEY,
            username_hint TEXT NOT NULL,
            encrypted_credentials TEXT NOT NULL,
            updated_at REAL NOT NULL
        );
    """)


class UpesCredentialProvider:
    """Provides internal access to encrypted UPES credentials for direct-HTTP login."""

    def __init__(self, conn_factory):
        self.conn_factory = conn_factory

    def has_credentials(self, user_id: str = "admin") -> bool:
        """Checks whether valid credentials are configured for user."""
        conn = self.conn_factory()
        try:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM upes_user_credentials WHERE user_id = ?", (user_id,))
            return cur.fetchone()[0] > 0
        finally:
            conn.close()

    def get_credentials(self, user_id: str = "admin") -> Optional[Tuple[str, str]]:
        """
        Internal only: Decrypts and returns (username, password) for direct-HTTP authentication.
        NEVER expose the return value of this method to REST APIs, logs, or LLM contexts.
        """
        conn = self.conn_factory()
        try:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("SELECT encrypted_credentials FROM upes_user_credentials WHERE user_id = ?", (user_id,))
            row = cur.fetchone()
            if not row:
                return None

            data = UpesCredentialCrypto.decrypt(row["encrypted_credentials"])
            if not data or not isinstance(data, dict):
                logger.warning(f"Failed to decrypt credentials for user '{user_id}'.")
                return None

            username = data.get("username")
            password = data.get("password")
            if username and password:
                return str(username), str(password)
            return None
        finally:
            conn.close()

    def get_credential_identity(self, user_id: str = "admin") -> CredentialIdentity:
        """
        Layer 1: Returns safe non-secret credential identity metadata.
        Never returns or decrypts passwords.
        """
        conn = self.conn_factory()
        try:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("SELECT username_hint FROM upes_user_credentials WHERE user_id = ?", (user_id,))
            row = cur.fetchone()
            if not row or not row["username_hint"]:
                return CredentialIdentity(
                    user_id=user_id,
                    configured_format=IdentifierFormat.UNKNOWN,
                    username_hint=None,
                    expected_format=IdentifierFormat.FULL_EMAIL,
                    mismatch=False
                )
            return CredentialIdentity.from_hint_or_username(user_id, row["username_hint"])
        finally:
            conn.close()

    def get_credential_status(self, user_id: str = "admin") -> Dict[str, Any]:
        """
        Returns safe, sanitized metadata about stored credentials.
        Guarantees that plaintext passwords and encrypted blobs are NEVER returned.
        """
        conn = self.conn_factory()
        try:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("SELECT username_hint, updated_at FROM upes_user_credentials WHERE user_id = ?", (user_id,))
            row = cur.fetchone()
            if not row:
                return {
                    "user_id": user_id,
                    "configured": False,
                    "username_hint": None,
                    "updated_at": None,
                    "password_stored": False,
                    "expected_identifier_format": IdentifierFormat.FULL_EMAIL.value,
                    "configured_identifier_format": IdentifierFormat.UNKNOWN.value,
                    "identifier_mismatch": False
                }

            hint = row["username_hint"]
            identity = CredentialIdentity.from_hint_or_username(user_id, hint)

            return {
                "user_id": user_id,
                "configured": True,
                "username_hint": hint,
                "updated_at": row["updated_at"],
                "has_stored_credentials": True,
                "expected_identifier_format": identity.expected_format.value,
                "configured_identifier_format": identity.configured_format.value,
                "identifier_mismatch": identity.mismatch,
                "warning": "Configured identifier appears to be SAP ID format, expected FULL_EMAIL (e.g. USER.12345@stu.upes.ac.in)" if identity.mismatch else None
            }
        finally:
            conn.close()

    def save_credentials(self, user_id: str, username: str, password: str) -> Dict[str, Any]:
        """
        Encrypts and stores UPES credentials.
        Returns safe metadata.
        """
        if not username or not password:
            raise ValueError("Username and password must not be empty.")

        username_str = str(username).strip()
        password_str = str(password).strip()

        # Mask username hint:
        if "@" in username_str:
            parts = username_str.split("@", 1)
            u_part = parts[0]
            domain_part = parts[1]
            masked_u = u_part[:3] + "***" if len(u_part) > 3 else "***"
            hint = f"{masked_u}@{domain_part}"
        elif len(username_str) > 6:
            hint = username_str[:4] + "***" + username_str[-3:]
        else:
            hint = "***" + username_str[-2:] if len(username_str) >= 2 else "***"

        payload = {
            "username": username_str,
            "password": password_str,
            "updated_at": time.time()
        }
        encrypted = UpesCredentialCrypto.encrypt(payload)

        now = time.time()
        conn = self.conn_factory()
        try:
            conn.execute("""
                INSERT INTO upes_user_credentials (user_id, username_hint, encrypted_credentials, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username_hint = excluded.username_hint,
                    encrypted_credentials = excluded.encrypted_credentials,
                    updated_at = excluded.updated_at
            """, (user_id, hint, encrypted, now))
            conn.commit()
        finally:
            conn.close()

        logger.info(f"UPES credentials stored securely for user '{user_id}' (hint: {hint}).")
        return {
            "configured": True,
            "user_id": user_id,
            "username_hint": hint,
            "updated_at": now,
            "has_stored_credentials": True
        }

    def delete_credentials(self, user_id: str) -> bool:
        """Deletes encrypted credentials for user."""
        conn = self.conn_factory()
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM upes_user_credentials WHERE user_id = ?", (user_id,))
            conn.commit()
            deleted = cur.rowcount > 0
            if deleted:
                logger.info(f"UPES credentials removed for user '{user_id}'.")
            return deleted
        finally:
            conn.close()
