"""
NexusNode — MCP OAuth 2.0 Provider
Full RFC 6749, RFC 7636 (PKCE), and RFC 8414 OAuth 2.0 Authorization Server implementation.
Maps authorized client grants to the unified Agent Token / spark-agent capability architecture.
"""

import time
import json
import uuid
import secrets
import hashlib
import base64
import sqlite3
import hmac
from typing import Dict, Any, List, Optional, Tuple

from .errors import NexusAgentError
from .mcp_auth import hash_token, DEFAULT_SPARK_CAPABILITIES


class OAuthError(NexusAgentError):
    def __init__(self, error: str, description: str, status_code: int = 400):
        super().__init__(f"OAuth Error [{error}]: {description}")
        self.error = error
        self.description = description
        self.status_code = status_code

    def to_dict(self) -> Dict[str, Any]:
        return {
            "error": self.error,
            "error_description": self.description
        }


def init_oauth_tables(conn: sqlite3.Connection):
    """Initializes tables for OAuth 2.0 clients, codes, and tokens."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS oauth_clients (
            client_id TEXT PRIMARY KEY,
            client_secret_hash TEXT NOT NULL,
            client_name TEXT NOT NULL,
            redirect_uris TEXT NOT NULL,
            created_at REAL NOT NULL,
            revoked_at REAL
        );
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS oauth_authorization_codes (
            code_hash TEXT PRIMARY KEY,
            client_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            redirect_uri TEXT NOT NULL,
            scope TEXT NOT NULL,
            code_challenge TEXT,
            code_challenge_method TEXT,
            expires_at REAL NOT NULL,
            is_used INTEGER NOT NULL DEFAULT 0,
            created_at REAL NOT NULL,
            FOREIGN KEY (client_id) REFERENCES oauth_clients(client_id)
        );
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS oauth_tokens (
            token_id TEXT PRIMARY KEY,
            token_hash TEXT NOT NULL UNIQUE,
            token_type TEXT NOT NULL,
            client_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            principal TEXT NOT NULL DEFAULT 'spark-agent',
            scope TEXT NOT NULL,
            expires_at REAL NOT NULL,
            revoked_at REAL,
            refresh_token_id TEXT,
            created_at REAL NOT NULL,
            last_used_at REAL,
            FOREIGN KEY (client_id) REFERENCES oauth_clients(client_id)
        );
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_oauth_tokens_hash ON oauth_tokens(token_hash);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_oauth_codes_client ON oauth_authorization_codes(client_id);")


def verify_pkce(code_verifier: str, code_challenge: str, method: str) -> bool:
    """Verifies PKCE code_verifier against code_challenge according to RFC 7636."""
    if not code_verifier or not code_challenge:
        return False

    method = (method or "plain").upper()
    if method == "S256":
        digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
        computed = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
        return hmac.compare_digest(computed, code_challenge.rstrip("="))
    elif method == "PLAIN":
        return hmac.compare_digest(code_verifier, code_challenge)
    return False


class OAuthProvider:
    """Authoritative OAuth 2.0 Authorization Server Provider for NexusNode."""

    def __init__(self, conn_factory, default_capabilities: Optional[List[str]] = None):
        self.conn_factory = conn_factory
        self.default_capabilities = default_capabilities or list(DEFAULT_SPARK_CAPABILITIES)

    def register_client(
        self,
        client_id: str,
        client_secret: str,
        client_name: str,
        redirect_uris: List[str]
    ) -> Dict[str, Any]:
        """Registers or updates an OAuth 2.0 client."""
        secret_hash = hash_token(client_secret)
        now = time.time()
        conn = self.conn_factory()
        try:
            init_oauth_tables(conn)
            conn.execute("""
                INSERT OR REPLACE INTO oauth_clients (
                    client_id, client_secret_hash, client_name, redirect_uris, created_at, revoked_at
                ) VALUES (?, ?, ?, ?, ?, NULL)
            """, (
                client_id, secret_hash, client_name, json.dumps(redirect_uris), now
            ))
            conn.commit()
        finally:
            conn.close()

        return {
            "client_id": client_id,
            "client_name": client_name,
            "redirect_uris": redirect_uris,
            "created_at": now
        }

    def register_dynamic_client(self, client_name: str, redirect_uris: List[str]) -> Dict[str, Any]:
        """Registers a dynamic OAuth 2.0 client per RFC 7591."""
        client_id = f"gemini_client_{secrets.token_hex(8)}"
        client_secret = f"nexus_sec_{secrets.token_hex(24)}"
        self.register_client(
            client_id=client_id,
            client_secret=client_secret,
            client_name=client_name,
            redirect_uris=redirect_uris
        )
        return {
            "client_id": client_id,
            "client_secret": client_secret,
            "client_name": client_name,
            "redirect_uris": redirect_uris,
            "client_id_issued_at": int(time.time()),
            "client_secret_expires_at": 0,
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "client_secret_post"
        }


    def get_client(self, client_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves active OAuth client metadata."""
        conn = self.conn_factory()
        try:
            init_oauth_tables(conn)
            cur = conn.cursor()
            cur.execute("""
                SELECT client_id, client_secret_hash, client_name, redirect_uris, created_at, revoked_at
                FROM oauth_clients WHERE client_id = ?
            """, (client_id,))
            row = cur.fetchone()
            if not row or row[5] is not None:
                return None
            return {
                "client_id": row[0],
                "client_secret_hash": row[1],
                "client_name": row[2],
                "redirect_uris": json.loads(row[3]),
                "created_at": row[4],
                "revoked": False
            }
        finally:
            conn.close()

    def validate_redirect_uri(self, client_id: str, redirect_uri: str) -> bool:
        """Validates that redirect_uri is explicitly in the client's allowlist."""
        client = self.get_client(client_id)
        if not client:
            return False
        return redirect_uri in client["redirect_uris"]

    def validate_client_credentials(self, client_id: str, client_secret: str) -> bool:
        """Validates client_id and client_secret using constant-time comparison."""
        client = self.get_client(client_id)
        if not client:
            return False
        secret_hash = hash_token(client_secret)
        return hmac.compare_digest(secret_hash, client["client_secret_hash"])

    def create_authorization_code(
        self,
        client_id: str,
        user_id: str,
        redirect_uri: str,
        scope: str = "mcp",
        code_challenge: Optional[str] = None,
        code_challenge_method: Optional[str] = None,
        ttl_seconds: int = 300
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Creates a single-use authorization code (5 min default TTL).
        Returns (raw_code, metadata).
        """
        if not self.validate_redirect_uri(client_id, redirect_uri):
            raise OAuthError("invalid_request", f"Redirect URI '{redirect_uri}' is not allowlisted for this client.")

        raw_code = f"oauth_code_{secrets.token_urlsafe(32)}"
        code_h = hash_token(raw_code)
        now = time.time()
        expires_at = now + ttl_seconds

        conn = self.conn_factory()
        try:
            init_oauth_tables(conn)
            conn.execute("""
                INSERT INTO oauth_authorization_codes (
                    code_hash, client_id, user_id, redirect_uri, scope,
                    code_challenge, code_challenge_method, expires_at, is_used, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
            """, (
                code_h, client_id, user_id, redirect_uri, scope,
                code_challenge, code_challenge_method, expires_at, now
            ))
            conn.commit()
        finally:
            conn.close()

        metadata = {
            "client_id": client_id,
            "user_id": user_id,
            "redirect_uri": redirect_uri,
            "scope": scope,
            "expires_at": expires_at
        }
        return raw_code, metadata

    def exchange_authorization_code(
        self,
        client_id: str,
        code: str,
        redirect_uri: str,
        code_verifier: Optional[str] = None,
        access_ttl_seconds: int = 3600,
        refresh_ttl_seconds: int = 2592000  # 30 days
    ) -> Dict[str, Any]:
        """
        Exchanges authorization code for access and refresh tokens.
        Atomically enforces single-use semantics and PKCE validation.
        """
        if not code or not isinstance(code, str):
            raise OAuthError("invalid_request", "Missing authorization code.")

        code_h = hash_token(code)
        now = time.time()

        conn = self.conn_factory()
        try:
            init_oauth_tables(conn)
            cur = conn.cursor()
            cur.execute("""
                SELECT code_hash, client_id, user_id, redirect_uri, scope,
                       code_challenge, code_challenge_method, expires_at, is_used
                FROM oauth_authorization_codes WHERE code_hash = ?
            """, (code_h,))
            row = cur.fetchone()

            if not row:
                raise OAuthError("invalid_grant", "Invalid or unknown authorization code.")

            (stored_hash, c_id, user_id, stored_uri, scope,
             challenge, challenge_method, expires_at, is_used) = row

            if is_used:
                raise OAuthError("invalid_grant", "Authorization code has already been used.")

            if now > expires_at:
                raise OAuthError("invalid_grant", "Authorization code has expired.")

            if c_id != client_id:
                raise OAuthError("invalid_grant", "Client ID mismatch for authorization code.")

            if stored_uri != redirect_uri:
                raise OAuthError("invalid_grant", "Redirect URI mismatch.")

            # Enforce PKCE if code_challenge was provided
            if challenge:
                if not code_verifier:
                    raise OAuthError("invalid_grant", "PKCE code_verifier is required.")
                if not verify_pkce(code_verifier, challenge, challenge_method):
                    raise OAuthError("invalid_grant", "PKCE verification failed.")

            # Atomically mark code as used
            cur.execute("""
                UPDATE oauth_authorization_codes SET is_used = 1 WHERE code_hash = ? AND is_used = 0
            """, (code_h,))
            if cur.rowcount != 1:
                raise OAuthError("invalid_grant", "Concurrent authorization code replay detected.")

            # Generate Access Token
            raw_access = f"nexus_oat_{secrets.token_urlsafe(32)}"
            access_id = f"oatok_{uuid.uuid4().hex[:12]}"
            access_h = hash_token(raw_access)
            access_expires = now + access_ttl_seconds

            # Generate Refresh Token
            raw_refresh = f"nexus_ort_{secrets.token_urlsafe(32)}"
            refresh_id = f"ortok_{uuid.uuid4().hex[:12]}"
            refresh_h = hash_token(raw_refresh)
            refresh_expires = now + refresh_ttl_seconds

            # Store Access Token
            cur.execute("""
                INSERT INTO oauth_tokens (
                    token_id, token_hash, token_type, client_id, user_id,
                    principal, scope, expires_at, revoked_at, refresh_token_id, created_at, last_used_at
                ) VALUES (?, ?, 'access', ?, ?, 'spark-agent', ?, ?, NULL, ?, ?, NULL)
            """, (
                access_id, access_h, client_id, user_id, scope, access_expires, refresh_id, now
            ))

            # Store Refresh Token
            cur.execute("""
                INSERT INTO oauth_tokens (
                    token_id, token_hash, token_type, client_id, user_id,
                    principal, scope, expires_at, revoked_at, refresh_token_id, created_at, last_used_at
                ) VALUES (?, ?, 'refresh', ?, ?, 'spark-agent', ?, ?, NULL, NULL, ?, NULL)
            """, (
                refresh_id, refresh_h, client_id, user_id, scope, refresh_expires, now
            ))

            conn.commit()
        finally:
            conn.close()

        return {
            "access_token": raw_access,
            "token_type": "Bearer",
            "expires_in": access_ttl_seconds,
            "refresh_token": raw_refresh,
            "scope": scope
        }

    def refresh_access_token(
        self,
        client_id: str,
        refresh_token: str,
        access_ttl_seconds: int = 3600,
        refresh_ttl_seconds: int = 2592000
    ) -> Dict[str, Any]:
        """
        Refreshes an access token and performs refresh token rotation.
        """
        if not refresh_token or not isinstance(refresh_token, str):
            raise OAuthError("invalid_request", "Missing refresh token.")

        ref_h = hash_token(refresh_token)
        now = time.time()

        conn = self.conn_factory()
        try:
            init_oauth_tables(conn)
            cur = conn.cursor()
            cur.execute("""
                SELECT token_id, client_id, user_id, principal, scope, expires_at, revoked_at
                FROM oauth_tokens WHERE token_hash = ? AND token_type = 'refresh'
            """, (ref_h,))
            row = cur.fetchone()

            if not row:
                raise OAuthError("invalid_grant", "Invalid or unknown refresh token.")

            token_id, c_id, user_id, principal, scope, expires_at, revoked_at = row

            if revoked_at is not None:
                raise OAuthError("invalid_grant", "Refresh token has been revoked.")

            if now > expires_at:
                raise OAuthError("invalid_grant", "Refresh token has expired.")

            if c_id != client_id:
                raise OAuthError("invalid_grant", "Client ID mismatch for refresh token.")

            # Revoke old refresh token (rotation)
            cur.execute("UPDATE oauth_tokens SET revoked_at = ? WHERE token_id = ?", (now, token_id))

            # Generate new Access & Refresh tokens
            raw_access = f"nexus_oat_{secrets.token_urlsafe(32)}"
            access_id = f"oatok_{uuid.uuid4().hex[:12]}"
            access_h = hash_token(raw_access)
            access_expires = now + access_ttl_seconds

            raw_refresh = f"nexus_ort_{secrets.token_urlsafe(32)}"
            new_refresh_id = f"ortok_{uuid.uuid4().hex[:12]}"
            new_refresh_h = hash_token(raw_refresh)
            new_refresh_expires = now + refresh_ttl_seconds

            cur.execute("""
                INSERT INTO oauth_tokens (
                    token_id, token_hash, token_type, client_id, user_id,
                    principal, scope, expires_at, revoked_at, refresh_token_id, created_at, last_used_at
                ) VALUES (?, ?, 'access', ?, ?, ?, ?, ?, NULL, ?, ?, NULL)
            """, (
                access_id, access_h, client_id, user_id, principal, scope, access_expires, new_refresh_id, now
            ))

            cur.execute("""
                INSERT INTO oauth_tokens (
                    token_id, token_hash, token_type, client_id, user_id,
                    principal, scope, expires_at, revoked_at, refresh_token_id, created_at, last_used_at
                ) VALUES (?, ?, 'refresh', ?, ?, ?, ?, ?, NULL, NULL, ?, NULL)
            """, (
                new_refresh_id, new_refresh_h, client_id, user_id, principal, scope, new_refresh_expires, now
            ))

            conn.commit()
        finally:
            conn.close()

        return {
            "access_token": raw_access,
            "token_type": "Bearer",
            "expires_in": access_ttl_seconds,
            "refresh_token": raw_refresh,
            "scope": scope
        }

    def verify_access_token(self, raw_token: str) -> Optional[Dict[str, Any]]:
        """
        Validates an OAuth Bearer access token for MCP Gateway calls.
        Returns token metadata dictionary with capabilities, or None.
        """
        if not raw_token or not isinstance(raw_token, str):
            return None

        tok_h = hash_token(raw_token)
        now = time.time()

        conn = self.conn_factory()
        try:
            init_oauth_tables(conn)
            cur = conn.cursor()
            cur.execute("""
                SELECT token_id, client_id, user_id, principal, scope, expires_at, revoked_at
                FROM oauth_tokens WHERE token_hash = ? AND token_type = 'access'
            """, (tok_h,))
            row = cur.fetchone()

            if not row:
                return None

            token_id, client_id, user_id, principal, scope, expires_at, revoked_at = row

            if revoked_at is not None:
                return None

            if now > expires_at:
                return None

            # Update last_used_at
            cur.execute("UPDATE oauth_tokens SET last_used_at = ? WHERE token_id = ?", (now, token_id))
            conn.commit()

            return {
                "token_id": token_id,
                "client_id": client_id,
                "user_id": user_id,
                "principal": principal or "spark-agent",
                "capabilities": list(self.default_capabilities),
                "scope": scope,
                "expires_at": expires_at,
                "is_oauth": True
            }
        finally:
            conn.close()

    def revoke_token(self, token_id: str) -> bool:
        """Revokes an access or refresh token."""
        now = time.time()
        conn = self.conn_factory()
        try:
            init_oauth_tables(conn)
            cur = conn.cursor()
            cur.execute("UPDATE oauth_tokens SET revoked_at = ? WHERE token_id = ?", (now, token_id))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def revoke_client_tokens(self, client_id: str) -> int:
        """Revokes all active tokens for a specific OAuth client."""
        now = time.time()
        conn = self.conn_factory()
        try:
            init_oauth_tables(conn)
            cur = conn.cursor()
            cur.execute("UPDATE oauth_tokens SET revoked_at = ? WHERE client_id = ? AND revoked_at IS NULL", (now, client_id))
            conn.commit()
            return cur.rowcount
        finally:
            conn.close()
