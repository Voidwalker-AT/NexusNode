"""
NexusNode — Agent Authentication & Token Manager
Cryptographically secure token provisioning, verification, revocation, and capability enforcement.
"""

import time
import json
import uuid
import secrets
import hashlib
import sqlite3
import hmac
from typing import Dict, Any, List, Optional, Tuple

from .errors import NexusAgentError

DEFAULT_SPARK_CAPABILITIES: List[str] = [
    # Appliance Status
    "nexus.status.read",

    # UPES Semantic Tools
    "upes.auth.read",
    "upes.attendance.read",
    "upes.timetable.read",
    "upes.courses.read",
    "upes.attendance.calculate",
    "upes.punches.read",
    "upes.timetable.export",

    # LMS Semantic Tools (Phase 3.5 & 3.6A)
    "lms.courses.read",
    "lms.resources.read",
    "lms.resources.download",
    "lms.resource.download",
    "lms.assignments.read",
    "lms.submission.prepare",
    "lms.submission.request",
    "action.status.read",


    # Vault Tools (Read & Write)
    "vault.list",
    "vault.search",
    "vault.read",
    "vault.mkdir",
    "vault.create",
    "vault.write",
    "vault.rename",
    "vault.move",
    "vault.copy",
    "vault.archive.read",
    "vault.archive.extract",

    # Document Extraction & Creation (Phase 3.5)
    "document.extract",
    "document.create",

    # Browser Tools
    "browser.status.read",
    "browser.open",
    "browser.close",
    "browser.navigate",
    "browser.snapshot",
    "browser.screenshot",
    "browser.capture",
    "browser.click",
    "browser.type",
    "browser.press",
    "browser.upload",
    "browser.download",
]


class AgentAuthError(NexusAgentError):
    code = "AUTH_REQUIRED"


class AgentForbiddenError(NexusAgentError):
    code = "AUTH_DENIED"


def init_agent_auth_tables(conn: sqlite3.Connection):
    """Initializes normalized SQLite tables for agent token authentication."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agent_tokens (
            token_id TEXT PRIMARY KEY,
            principal TEXT NOT NULL,
            token_hash TEXT NOT NULL UNIQUE,
            capabilities TEXT NOT NULL,
            description TEXT,
            created_at REAL NOT NULL,
            expires_at REAL,
            revoked_at REAL,
            last_used_at REAL
        );
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_tokens_hash ON agent_tokens(token_hash);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_tokens_principal ON agent_tokens(principal);")


def hash_token(raw_token: str) -> str:
    """Computes SHA-256 hex digest of a high-entropy agent token."""
    return hashlib.sha256(raw_token.strip().encode("utf-8")).hexdigest()


class AgentTokenManager:
    """Manages persistent cryptographic agent tokens and capability checks."""

    def __init__(self, conn_factory):
        self.conn_factory = conn_factory

    def generate_token(
        self,
        principal: str = "spark-agent",
        capabilities: Optional[List[str]] = None,
        description: str = "Gemini Spark Agent Credential",
        ttl_seconds: Optional[float] = None
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Provisions a high-entropy cryptographically random agent token.
        Returns (raw_token, token_metadata).
        The raw token is returned ONCE and is never persisted to disk.
        """
        caps = capabilities if capabilities is not None else list(DEFAULT_SPARK_CAPABILITIES)
        token_id = f"agtok_{uuid.uuid4().hex[:12]}"
        raw_secret = secrets.token_urlsafe(32)  # 256-bit CSPRNG entropy
        raw_token = f"nexus_agent_{raw_secret}"
        tok_hash = hash_token(raw_token)
        now = time.time()
        expires_at = (now + ttl_seconds) if ttl_seconds else None

        conn = self.conn_factory()
        try:
            init_agent_auth_tables(conn)
            conn.execute("""
                INSERT INTO agent_tokens (
                    token_id, principal, token_hash, capabilities, description,
                    created_at, expires_at, revoked_at, last_used_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL)
            """, (
                token_id, principal, tok_hash, json.dumps(caps), description,
                now, expires_at
            ))
            conn.commit()
        finally:
            conn.close()

        metadata = {
            "token_id": token_id,
            "principal": principal,
            "capabilities": caps,
            "description": description,
            "created_at": now,
            "expires_at": expires_at,
            "revoked": False
        }
        return raw_token, metadata

    def verify_token(self, raw_token: str) -> Optional[Dict[str, Any]]:
        """
        Validates raw token against stored SHA-256 verifiers.
        Updates last_used_at upon successful verification.
        Returns token metadata dictionary or None if invalid/expired/revoked.
        """
        if not raw_token or not isinstance(raw_token, str):
            return None

        tok_hash = hash_token(raw_token)
        now = time.time()

        conn = self.conn_factory()
        try:
            conn.row_factory = sqlite3.Row
            init_agent_auth_tables(conn)
            cur = conn.cursor()
            cur.execute("""
                SELECT token_id, principal, token_hash, capabilities, description,
                       created_at, expires_at, revoked_at, last_used_at
                FROM agent_tokens
                WHERE token_hash = ?
            """, (tok_hash,))
            row = cur.fetchone()
            if not row:
                return None

            # Constant-time comparison
            if not hmac.compare_digest(row["token_hash"], tok_hash):
                return None

            # Check revocation
            if row["revoked_at"] is not None:
                return None

            # Check expiration
            if row["expires_at"] is not None and now > row["expires_at"]:
                return None

            # Update last_used_at
            conn.execute("UPDATE agent_tokens SET last_used_at = ? WHERE token_id = ?", (now, row["token_id"]))
            conn.commit()

            return {
                "token_id": row["token_id"],
                "principal": row["principal"],
                "capabilities": json.loads(row["capabilities"]),
                "description": row["description"],
                "created_at": row["created_at"],
                "expires_at": row["expires_at"],
                "last_used_at": now
            }
        finally:
            conn.close()

    def revoke_token(self, token_id: str) -> bool:
        """Revokes an agent token by token_id."""
        now = time.time()
        conn = self.conn_factory()
        try:
            init_agent_auth_tables(conn)
            cur = conn.cursor()
            cur.execute("""
                UPDATE agent_tokens
                SET revoked_at = ?
                WHERE token_id = ? AND revoked_at IS NULL
            """, (now, token_id))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def list_tokens(self, principal: Optional[str] = None) -> List[Dict[str, Any]]:
        """Lists metadata for registered agent tokens (excluding hashes)."""
        conn = self.conn_factory()
        try:
            conn.row_factory = sqlite3.Row
            init_agent_auth_tables(conn)
            cur = conn.cursor()
            query = "SELECT token_id, principal, capabilities, description, created_at, expires_at, revoked_at, last_used_at FROM agent_tokens"
            params = []
            if principal:
                query += " WHERE principal = ?"
                params.append(principal)
            query += " ORDER BY created_at DESC"
            cur.execute(query, tuple(params))
            
            res = []
            for r in cur.fetchall():
                res.append({
                    "token_id": r["token_id"],
                    "principal": r["principal"],
                    "capabilities": json.loads(r["capabilities"]),
                    "description": r["description"],
                    "created_at": r["created_at"],
                    "expires_at": r["expires_at"],
                    "revoked": r["revoked_at"] is not None,
                    "revoked_at": r["revoked_at"],
                    "last_used_at": r["last_used_at"]
                })
            return res
        finally:
            conn.close()

    def check_capability(self, token_meta: Dict[str, Any], required_capability: str) -> bool:
        """Verifies if token has the requested capability."""
        caps = token_meta.get("capabilities", [])
        if "*" in caps or "all" in caps:
            return True
        return required_capability in caps
