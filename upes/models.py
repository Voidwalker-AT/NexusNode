"""
NexusNode — UPES Authentication & Session Domain Models
Defines explicit typed models for the 5 distinct authentication layers:
1. Credential Identity (Safe metadata, no secrets)
2. Credential Secret Provider (Interface)
3. IdP Session (SSO Cookies & IdP State)
4. OAuth Session (Access Token & Refresh Material)
5. Resolved Student Identity (UUID, SAP ID, Academic Profile)
"""

import time
import re
from enum import Enum
from typing import Optional, Dict, Any
from dataclasses import dataclass, field


class IdentifierFormat(str, Enum):
    FULL_EMAIL = "FULL_EMAIL"
    NUMERIC_SAP_ID = "NUMERIC_SAP_ID"
    UNKNOWN = "UNKNOWN"

    @classmethod
    def detect(cls, identifier: Optional[str]) -> "IdentifierFormat":
        if not identifier:
            return cls.UNKNOWN
        s = identifier.strip()
        if "@" in s:
            return cls.FULL_EMAIL
        if re.match(r"^[0-9*]{8,11}$", s):
            return cls.NUMERIC_SAP_ID
        return cls.UNKNOWN


class AutonomyLevel(str, Enum):
    LEVEL_0_NONE = "LEVEL_0_NONE"
    LEVEL_1_TOKEN_ONLY = "LEVEL_1_TOKEN_ONLY"
    LEVEL_2_IDP_REFRESH = "LEVEL_2_IDP_REFRESH"
    LEVEL_3_INDEPENDENT_REFRESH = "LEVEL_3_INDEPENDENT_REFRESH"
    LEVEL_4_RESTART_SURVIVED = "LEVEL_4_RESTART_SURVIVED"
    LEVEL_5_LONG_DURATION = "LEVEL_5_LONG_DURATION"

    # Semantic Aliases
    LEVEL_0_INTERACTION_REQUIRED = "LEVEL_0_NONE"
    LEVEL_1_ACCESS_TOKEN_ONLY = "LEVEL_1_TOKEN_ONLY"
    LEVEL_2_OAUTH_REFRESHABLE = "LEVEL_2_IDP_REFRESH"
    LEVEL_3_IDP_RENEWABLE = "LEVEL_3_INDEPENDENT_REFRESH"
    LEVEL_4_BROWSER_SESSION_RENEWABLE = "LEVEL_4_RESTART_SURVIVED"
    LEVEL_5_FULL_AUTONOMOUS_CHAIN = "LEVEL_5_LONG_DURATION"


@dataclass(frozen=True)
class CredentialIdentity:
    """Layer 1: Safe non-secret credential identity metadata."""
    user_id: str
    configured_format: IdentifierFormat
    username_hint: Optional[str]
    expected_format: IdentifierFormat = IdentifierFormat.FULL_EMAIL
    mismatch: bool = False

    @classmethod
    def from_hint_or_username(cls, user_id: str, hint_or_username: Optional[str]) -> "CredentialIdentity":
        fmt = IdentifierFormat.detect(hint_or_username)
        mismatch = (fmt != IdentifierFormat.FULL_EMAIL and fmt != IdentifierFormat.UNKNOWN)
        return cls(
            user_id=user_id,
            configured_format=fmt,
            username_hint=hint_or_username,
            expected_format=IdentifierFormat.FULL_EMAIL,
            mismatch=mismatch
        )


@dataclass
class IdpSession:
    """Layer 3: IdP SSO Session & Browser State."""
    session_id: Optional[str] = None
    remember_session: Optional[str] = None
    cookie_expires_at: Optional[float] = None
    cookies: Dict[str, str] = field(default_factory=dict)

    def is_valid(self, now: Optional[float] = None, margin: float = 60.0) -> bool:
        t = now if now is not None else time.time()
        if not self.session_id and "idp_session_info" not in self.cookies:
            return False
        if self.cookie_expires_at is None:
            return True
        return t < (self.cookie_expires_at - margin)


@dataclass
class OAuthAccessToken:
    """Layer 4a: OAuth Access Token & Validity."""
    access_token: str
    expires_at: float
    token_type: str = "Bearer"
    scope: str = "openid"

    def is_valid(self, now: Optional[float] = None, margin: float = 300.0) -> bool:
        t = now if now is not None else time.time()
        return t < (self.expires_at - margin)

    def ttl_seconds(self, now: Optional[float] = None) -> int:
        t = now if now is not None else time.time()
        return max(0, int(self.expires_at - t))


@dataclass
class OAuthRefreshToken:
    """Layer 4b: OAuth Refresh Material & Generation Tracking."""
    refresh_token: Optional[str] = None
    client_id: int = 3
    generation: int = 1
    last_rotated_at: Optional[float] = None


@dataclass
class ResolvedStudentIdentity:
    """Layer 5: Resolved Academic Student Profile."""
    student_id: str  # UUID (e.g. 3a678d8e-8817-41e6-b1a8-5a3ec6ee4948)
    global_id: str   # SAP ID (e.g. 590011794)
    user_id: int     # Internal SLCM integer user ID (e.g. 30054)
    email: str
    display_name: str = ""
    campus_code: str = ""
    course_code: str = ""

    def to_safe_dict(self) -> Dict[str, Any]:
        masked_uuid = self.student_id[:4] + "***" + self.student_id[-4:] if len(self.student_id) > 8 else "***"
        masked_sap = self.global_id[:3] + "***" + self.global_id[-3:] if len(self.global_id) > 6 else "***"
        masked_email = self.email.split("@")[0][:3] + "***@" + self.email.split("@")[-1] if "@" in self.email else "***"
        return {
            "student_id_masked": masked_uuid,
            "global_id_masked": masked_sap,
            "email_masked": masked_email,
            "display_name": self.display_name,
            "campus_code": self.campus_code,
            "course_code": self.course_code,
        }


@dataclass
class UpesAuthSessionBundle:
    """Encapsulates the complete decrypted runtime session bundle."""
    user_id: str
    access_token: OAuthAccessToken
    refresh_token: OAuthRefreshToken
    idp_session: IdpSession
    student_identity: ResolvedStudentIdentity
    api_url: str = "https://myupes-beta.upes.ac.in/apigateway/api/timetable"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    last_refresh_status: str = "initial_import"
