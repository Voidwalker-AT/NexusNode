"""
NexusNode — UPES Timetable to Google Calendar Synchronization Module
Provides:
1. Normalized Timetable Data Model & tolerant UPES JSON parser.
2. Authenticated AES-GCM OAuth Token storage at rest.
3. CSRF-safe Google OAuth 2.0 flow & auto-refreshing Calendar client.
4. Database-backed distributed lease locks & strict idempotent event mapping.
5. Unified TimetableService for 3-hour scheduler and manual REST triggers.
"""

import base64
import datetime
import hashlib
import json
import os
import secrets
import time
import zoneinfo
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import requests
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

import config

# ==============================================================================
# 1. NORMALIZED TIMETABLE DATA MODEL & TOLERANT PARSER
# ==============================================================================

@dataclass
class TimetableSession:
    """Canonical representation of a timetable class or lab session."""
    course_name: str
    course_code: str
    date: str              # YYYY-MM-DD
    start_time: str        # HH:MM or HH:MM:SS
    end_time: str          # HH:MM or HH:MM:SS
    room: str
    faculty: str
    session_id: str
    source: str = "upes"
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def deterministic_hash(self) -> str:
        """Computes SHA-256 hash of normalized content fields to detect modifications."""
        norm_str = f"{self.course_name.strip()}|{self.course_code.strip()}|{self.date.strip()}|{self.start_time.strip()}|{self.end_time.strip()}|{self.room.strip()}|{self.faculty.strip()}"
        return hashlib.sha256(norm_str.encode("utf-8")).hexdigest()

    def get_start_iso(self, tz_name: str = config.TIMETABLE_TIMEZONE) -> str:
        """Returns ISO 8601 string for event start with timezone offset."""
        return _format_iso_datetime(self.date, self.start_time, tz_name)

    def get_end_iso(self, tz_name: str = config.TIMETABLE_TIMEZONE) -> str:
        """Returns ISO 8601 string for event end with timezone offset."""
        return _format_iso_datetime(self.date, self.end_time, tz_name)


def _format_iso_datetime(date_str: str, time_str: str, tz_name: str) -> str:
    """Combines YYYY-MM-DD and HH:MM(:SS) into an ISO 8601 string with timezone."""
    time_cleaned = time_str.strip()
    parts = time_cleaned.split(":")
    hour = int(parts[0])
    minute = int(parts[1]) if len(parts) > 1 else 0
    second = int(parts[2]) if len(parts) > 2 else 0

    d_parts = [int(p) for p in date_str.strip().split("-")]
    dt = datetime.datetime(d_parts[0], d_parts[1], d_parts[2], hour, minute, second)

    try:
        tz = zoneinfo.ZoneInfo(tz_name)
        dt_tz = dt.replace(tzinfo=tz)
        return dt_tz.isoformat()
    except Exception:
        # Fallback to IST (+05:30) if zoneinfo lookup fails
        ist = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
        return dt.replace(tzinfo=ist).isoformat()


def normalize_upes_session(raw_item: Dict[str, Any], default_date: Optional[str] = None) -> Optional[TimetableSession]:
    """
    Tolerantly extracts and normalizes a UPES timetable session from a JSON dict.
    Returns None if mandatory fields cannot be parsed.
    """
    if not isinstance(raw_item, dict):
        return None

    # 1. Extract course / subject name
    course_name = (
        raw_item.get("course_name") or
        raw_item.get("courseName") or
        raw_item.get("subject") or
        raw_item.get("subject_name") or
        raw_item.get("subjectName") or
        raw_item.get("title") or
        raw_item.get("name") or
        raw_item.get("course") or
        ""
    ).strip()

    # 2. Extract course code
    course_code = (
        raw_item.get("course_code") or
        raw_item.get("courseCode") or
        raw_item.get("subject_code") or
        raw_item.get("subjectCode") or
        raw_item.get("code") or
        ""
    ).strip()

    # 3. Extract date (YYYY-MM-DD)
    raw_date = (
        raw_item.get("date") or
        raw_item.get("slot_date") or
        raw_item.get("slotDate") or
        raw_item.get("day_date") or
        raw_item.get("session_date") or
        default_date or
        ""
    ).strip()

    date_str = _normalize_date_string(raw_date)
    if not date_str:
        return None  # Cannot proceed without a valid date

    # 4. Extract start & end times
    start_time_raw = (
        raw_item.get("start_time") or
        raw_item.get("startTime") or
        raw_item.get("time_from") or
        raw_item.get("timeFrom") or
        raw_item.get("from_time") or
        raw_item.get("fromTime") or
        raw_item.get("start") or
        ""
    ).strip()

    end_time_raw = (
        raw_item.get("end_time") or
        raw_item.get("endTime") or
        raw_item.get("time_to") or
        raw_item.get("timeTo") or
        raw_item.get("to_time") or
        raw_item.get("toTime") or
        raw_item.get("end") or
        ""
    ).strip()

    # Handle combined time string like "09:00 - 10:00" or "09:00-10:00" or "09:00 AM - 10:00 AM"
    if not start_time_raw and not end_time_raw:
        slot_time = (raw_item.get("time") or raw_item.get("slot") or raw_item.get("timing") or "").strip()
        if "-" in slot_time:
            t_parts = slot_time.split("-")
            start_time_raw = t_parts[0].strip()
            end_time_raw = t_parts[1].strip()

    start_time = _normalize_time_string(start_time_raw)
    end_time = _normalize_time_string(end_time_raw)

    if not start_time or not end_time or not course_name:
        return None

    # 5. Extract room / venue
    room = (
        raw_item.get("room") or
        raw_item.get("room_no") or
        raw_item.get("roomNo") or
        raw_item.get("room_number") or
        raw_item.get("venue") or
        raw_item.get("location") or
        raw_item.get("class_room") or
        "TBD"
    ).strip()

    # 6. Extract faculty / instructor
    faculty = (
        raw_item.get("faculty") or
        raw_item.get("faculty_name") or
        raw_item.get("facultyName") or
        raw_item.get("instructor") or
        raw_item.get("teacher") or
        raw_item.get("professor") or
        "TBD"
    ).strip()

    # 7. Extract or derive session ID
    session_id = (
        raw_item.get("session_id") or
        raw_item.get("sessionId") or
        raw_item.get("id") or
        raw_item.get("slot_id") or
        raw_item.get("slotId") or
        ""
    ).strip()

    if not session_id:
        # Generate deterministic session id from primary components
        raw_key = f"{course_name}_{course_code}_{start_time}_{end_time}_{room}"
        session_id = hashlib.md5(raw_key.encode("utf-8")).hexdigest()[:16]

    return TimetableSession(
        course_name=course_name,
        course_code=course_code,
        date=date_str,
        start_time=start_time,
        end_time=end_time,
        room=room,
        faculty=faculty,
        session_id=session_id,
        source="upes",
        raw=raw_item
    )


def _normalize_date_string(date_raw: str) -> Optional[str]:
    """Parses various date formats (YYYY-MM-DD, DD/MM/YYYY, DD-MM-YYYY, ISO) into YYYY-MM-DD."""
    if not date_raw:
        return None
    date_raw = date_raw.strip().split("T")[0]  # Strip time component if ISO

    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%d.%m.%Y", "%B %d, %Y", "%b %d, %Y"):
        try:
            dt = datetime.datetime.strptime(date_raw, fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _normalize_time_string(time_raw: str) -> Optional[str]:
    """Parses time strings like '09:00', '9:00 AM', '14:30:00' into HH:MM:SS."""
    if not time_raw:
        return None
    time_raw = time_raw.strip().upper()

    for fmt in ("%H:%M:%S", "%H:%M", "%I:%M %p", "%I:%M%p", "%I %p", "%H"):
        try:
            dt = datetime.datetime.strptime(time_raw, fmt)
            return dt.strftime("%H:%M:00")
        except ValueError:
            continue
    return None


def parse_timetable_json(json_data: Any) -> Tuple[List[TimetableSession], List[str]]:
    """
    Parses a UPES timetable payload (string, dict, list) into a list of normalized sessions.
    Returns (valid_sessions, error_messages).
    """
    errors: List[str] = []
    sessions: List[TimetableSession] = []

    if isinstance(json_data, str):
        try:
            json_data = json.loads(json_data)
        except Exception as e:
            return [], [f"Malformed JSON syntax: {str(e)}"]

    raw_items: List[Dict[str, Any]] = []

    if isinstance(json_data, list):
        raw_items = json_data
    elif isinstance(json_data, dict):
        # Could be { "sessions": [...] } or { "timetable": [...] } or { "data": [...] } or date-keyed { "2026-08-19": [...] }
        if "sessions" in json_data and isinstance(json_data["sessions"], list):
            raw_items = json_data["sessions"]
        elif "timetable" in json_data and isinstance(json_data["timetable"], list):
            raw_items = json_data["timetable"]
        elif "data" in json_data and isinstance(json_data["data"], list):
            raw_items = json_data["data"]
        else:
            # Check if keys are dates
            for key, val in json_data.items():
                if isinstance(val, list):
                    date_norm = _normalize_date_string(key)
                    for item in val:
                        if isinstance(item, dict):
                            item_copy = dict(item)
                            if date_norm and "date" not in item_copy:
                                item_copy["date"] = date_norm
                            raw_items.append(item_copy)
                elif isinstance(val, dict):
                    raw_items.append(val)

    if not raw_items:
        return [], ["No session items found in timetable structure."]

    if len(raw_items) > config.TIMETABLE_MAX_SESSIONS:
        return [], [f"Timetable exceeds maximum allowed sessions ({config.TIMETABLE_MAX_SESSIONS})."]

    for idx, item in enumerate(raw_items):
        try:
            session = normalize_upes_session(item)
            if session:
                sessions.append(session)
            else:
                errors.append(f"Skipped invalid session at index {idx}: missing required course name, date, or start/end time.")
        except Exception as e:
            errors.append(f"Error parsing session at index {idx}: {str(e)}")

    return sessions, errors


# ==============================================================================
# 2. TOKEN CRYPTOGRAPHY (AUTHENTICATED AES-GCM AT REST)
# ==============================================================================

class OAuthTokenCrypto:
    """Authenticated AES-GCM encryption for storing Google OAuth tokens at rest."""

    @classmethod
    def _derive_key(cls) -> bytes:
        """Derives a 256-bit AES key from NEXUS_SECRET_KEY using PBKDF2-HMAC-SHA256."""
        secret_bytes = config.SECRET_KEY.encode("utf-8")
        salt = b"nexusnode_google_oauth_aesgcm_salt_v1"
        return hashlib.pbkdf2_hmac("sha256", secret_bytes, salt, 100000, 32)

    @classmethod
    def encrypt(cls, plaintext_dict: Dict[str, Any]) -> str:
        """Encrypts token dictionary into URL-safe base64 string (12-byte nonce + ciphertext + 16-byte tag)."""
        key = cls._derive_key()
        aesgcm = AESGCM(key)
        nonce = secrets.token_bytes(12)
        payload_bytes = json.dumps(plaintext_dict).encode("utf-8")
        ciphertext = aesgcm.encrypt(nonce, payload_bytes, None)
        combined = nonce + ciphertext
        return base64.urlsafe_b64encode(combined).decode("ascii")

    @classmethod
    def decrypt(cls, encrypted_str: str) -> Optional[Dict[str, Any]]:
        """Decrypts base64 string using AES-GCM. Returns None on tampering or corruption."""
        try:
            combined = base64.urlsafe_b64decode(encrypted_str.encode("ascii"))
            if len(combined) < 28:  # 12-byte nonce + 16-byte GCM tag
                return None
            nonce = combined[:12]
            ciphertext = combined[12:]
            key = cls._derive_key()
            aesgcm = AESGCM(key)
            decrypted_bytes = aesgcm.decrypt(nonce, ciphertext, None)
            return json.loads(decrypted_bytes.decode("utf-8"))
        except Exception:
            return None


# ==============================================================================
# 3. GOOGLE CALENDAR API CLIENT & OAUTH 2.0
# ==============================================================================

class GoogleCalendarError(Exception):
    """Base exception for Google Calendar operations."""
    def __init__(self, message: str, status_code: int = 500, retryable: bool = False):
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


class GoogleCalendarClient:
    """Official REST API client for Google Calendar with OAuth 2.0 auto-refresh and exponential backoff."""

    def __init__(self, token_data: Dict[str, Any], user_id: str, on_token_refresh=None):
        self.token_data = dict(token_data)
        self.user_id = user_id
        self.on_token_refresh = on_token_refresh

    @classmethod
    def get_authorization_url(cls, state: str) -> str:
        """Generates Google OAuth 2.0 consent URL with CSRF state token."""
        params = {
            "client_id": config.GOOGLE_CLIENT_ID,
            "redirect_uri": config.GOOGLE_REDIRECT_URI,
            "response_type": "code",
            "scope": config.GOOGLE_CALENDAR_SCOPE,
            "access_type": "offline",
            "prompt": "consent",
            "state": state
        }
        query = "&".join(f"{k}={requests.utils.quote(str(v))}" for k, v in params.items())
        return f"{config.GOOGLE_AUTH_URI}?{query}"

    @classmethod
    def exchange_code_for_tokens(cls, code: str) -> Dict[str, Any]:
        """Exchanges authorization code for access and refresh tokens."""
        if not config.GOOGLE_CLIENT_ID or not config.GOOGLE_CLIENT_SECRET:
            raise GoogleCalendarError("Google OAuth credentials are not configured on server.", status_code=500)

        payload = {
            "code": code,
            "client_id": config.GOOGLE_CLIENT_ID,
            "client_secret": config.GOOGLE_CLIENT_SECRET,
            "redirect_uri": config.GOOGLE_REDIRECT_URI,
            "grant_type": "authorization_code"
        }

        resp = requests.post(config.GOOGLE_TOKEN_URI, data=payload, timeout=15)
        if resp.status_code != 200:
            err_msg = "OAuth token exchange failed."
            try:
                err_json = resp.json()
                err_msg = err_json.get("error_description") or err_json.get("error") or err_msg
            except Exception:
                pass
            raise GoogleCalendarError(err_msg, status_code=resp.status_code)

        data = resp.json()
        expires_in = data.get("expires_in", 3600)
        token_data = {
            "access_token": data.get("access_token"),
            "refresh_token": data.get("refresh_token"),
            "token_type": data.get("token_type", "Bearer"),
            "expires_at": time.time() + expires_in,
            "scope": data.get("scope", "")
        }
        return token_data

    def refresh_access_token(self) -> str:
        """Uses refresh_token to acquire a fresh access_token."""
        refresh_token = self.token_data.get("refresh_token")
        if not refresh_token:
            raise GoogleCalendarError("No refresh token available. User must re-authenticate.", status_code=401)

        payload = {
            "client_id": config.GOOGLE_CLIENT_ID,
            "client_secret": config.GOOGLE_CLIENT_SECRET,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token"
        }

        resp = requests.post(config.GOOGLE_TOKEN_URI, data=payload, timeout=15)
        if resp.status_code != 200:
            raise GoogleCalendarError("Failed to refresh Google OAuth access token. Refresh token may be revoked.", status_code=401)

        data = resp.json()
        self.token_data["access_token"] = data.get("access_token")
        self.token_data["expires_at"] = time.time() + data.get("expires_in", 3600)

        if self.on_token_refresh:
            self.on_token_refresh(self.user_id, self.token_data)

        return self.token_data["access_token"]

    def _ensure_valid_token(self):
        """Refreshes access token if within 60 seconds of expiry."""
        expires_at = self.token_data.get("expires_at", 0)
        if time.time() >= (expires_at - 60):
            self.refresh_access_token()

    def _request(self, method: str, path: str, json_body: Optional[Dict[str, Any]] = None, params: Optional[Dict[str, Any]] = None) -> requests.Response:
        """Executes authenticated HTTP request to Google Calendar API with retry/backoff."""
        self._ensure_valid_token()
        url = f"{config.GOOGLE_CALENDAR_API_BASE}{path}"

        max_attempts = 3
        backoff = 1.0

        for attempt in range(1, max_attempts + 1):
            headers = {
                "Authorization": f"Bearer {self.token_data.get('access_token')}",
                "Content-Type": "application/json",
                "Accept": "application/json"
            }
            try:
                resp = requests.request(method, url, headers=headers, json=json_body, params=params, timeout=20)

                # If token expired unexpectedly, refresh once and retry
                if resp.status_code == 401 and attempt < max_attempts:
                    self.refresh_access_token()
                    continue

                # Rate limited or server error -> backoff and retry
                if resp.status_code in (429, 500, 502, 503, 504) and attempt < max_attempts:
                    time.sleep(backoff)
                    backoff *= 2.0
                    continue

                if not (200 <= resp.status_code < 300):
                    err_text = "Google Calendar API error"
                    try:
                        err_text = resp.json().get("error", {}).get("message", err_text)
                    except Exception:
                        err_text = resp.text[:200]
                    raise GoogleCalendarError(err_text, status_code=resp.status_code, retryable=(resp.status_code >= 500))

                return resp

            except requests.RequestException as e:
                if attempt < max_attempts:
                    time.sleep(backoff)
                    backoff *= 2.0
                    continue
                raise GoogleCalendarError(f"Network error connecting to Google Calendar: {str(e)}", status_code=503, retryable=True)

        raise GoogleCalendarError("Max retries exceeded for Google Calendar request.", status_code=504)

    def list_calendars(self) -> List[Dict[str, Any]]:
        """Lists user's Google Calendars."""
        resp = self._request("GET", "/users/me/calendarList")
        items = resp.json().get("items", [])
        return [{"id": c.get("id"), "summary": c.get("summary"), "primary": c.get("primary", False)} for c in items]

    def create_event(self, calendar_id: str, session: TimetableSession, user_id: str) -> Dict[str, Any]:
        """Creates a Google Calendar event marked as NexusNode-managed."""
        body = self._build_event_body(session, user_id)
        resp = self._request("POST", f"/calendars/{requests.utils.quote(calendar_id)}/events", json_body=body)
        return resp.json()

    def update_event(self, calendar_id: str, event_id: str, session: TimetableSession, user_id: str) -> Dict[str, Any]:
        """Updates an existing Google Calendar event."""
        body = self._build_event_body(session, user_id)
        resp = self._request("PUT", f"/calendars/{requests.utils.quote(calendar_id)}/events/{requests.utils.quote(event_id)}", json_body=body)
        return resp.json()

    def delete_event(self, calendar_id: str, event_id: str) -> bool:
        """Deletes a managed Google Calendar event."""
        try:
            self._request("DELETE", f"/calendars/{requests.utils.quote(calendar_id)}/events/{requests.utils.quote(event_id)}")
            return True
        except GoogleCalendarError as e:
            if e.status_code == 404 or e.status_code == 410:
                # Already deleted on Google Calendar
                return True
            raise

    def _build_event_body(self, session: TimetableSession, user_id: str) -> Dict[str, Any]:
        """Formats the Google Calendar event payload with extended ownership properties."""
        summary = session.course_name
        if session.course_code:
            summary = f"[{session.course_code}] {session.course_name}"

        description = (
            f"Course: {session.course_name}\n"
            f"Code: {session.course_code or 'N/A'}\n"
            f"Faculty: {session.faculty}\n"
            f"Room: {session.room}\n"
            f"Source: UPES Timetable\n"
            f"Managed by: NexusNode"
        )

        return {
            "summary": summary,
            "location": session.room,
            "description": description,
            "start": {
                "dateTime": session.get_start_iso(),
                "timeZone": config.TIMETABLE_TIMEZONE
            },
            "end": {
                "dateTime": session.get_end_iso(),
                "timeZone": config.TIMETABLE_TIMEZONE
            },
            "extendedProperties": {
                "private": {
                    "nexusnode_managed": "true",
                    "nexusnode_user_id": user_id,
                    "nexusnode_session_id": session.session_id,
                    "nexusnode_date": session.date
                }
            }
        }


# ==============================================================================
# 4. DATABASE HELPERS & DISTRIBUTED SYNCHRONIZATION LEASE LOCK
# ==============================================================================

def init_timetable_tables(conn):
    """Initializes tables for Google OAuth tokens, event mappings, sync locks, and history."""
    # 1. Google OAuth Token Vault
    conn.execute("""
        CREATE TABLE IF NOT EXISTS google_oauth_tokens (
            user_id TEXT PRIMARY KEY,
            encrypted_token_data TEXT NOT NULL,
            calendar_id TEXT DEFAULT 'primary',
            connected_email TEXT,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        );
    """)

    # 2. OAuth State Tokens for CSRF protection
    conn.execute("""
        CREATE TABLE IF NOT EXISTS google_oauth_states (
            state_token TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            created_at REAL NOT NULL,
            expires_at REAL NOT NULL
        );
    """)

    # 3. Deterministic Event Mappings
    conn.execute("""
        CREATE TABLE IF NOT EXISTS timetable_events_map (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            source_session_id TEXT NOT NULL,
            source_date TEXT NOT NULL,
            google_calendar_id TEXT NOT NULL,
            google_event_id TEXT NOT NULL,
            source_hash TEXT NOT NULL,
            summary TEXT,
            start_time TEXT,
            end_time TEXT,
            last_synced_at REAL NOT NULL,
            status TEXT NOT NULL DEFAULT 'synced'
        );
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_timetable_map_user_date ON timetable_events_map (user_id, source_date);")

    # 4. Ingested User Timetable Payloads
    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_timetables (
            user_id TEXT PRIMARY KEY,
            raw_json TEXT NOT NULL,
            updated_at REAL NOT NULL
        );
    """)

    # 5. Synchronization Locks (Distributed DB Lease)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS timetable_sync_locks (
            user_id TEXT PRIMARY KEY,
            locked_at REAL NOT NULL,
            expires_at REAL NOT NULL,
            lock_token TEXT NOT NULL
        );
    """)

    # 6. Synchronization History & Diagnostics
    conn.execute("""
        CREATE TABLE IF NOT EXISTS timetable_sync_history (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            timestamp REAL NOT NULL,
            sessions_seen INTEGER NOT NULL,
            created_count INTEGER NOT NULL,
            updated_count INTEGER NOT NULL,
            deleted_count INTEGER NOT NULL,
            unchanged_count INTEGER NOT NULL,
            error_count INTEGER NOT NULL,
            status TEXT NOT NULL,
            details TEXT
        );
    """)


class DatabaseSyncLease:
    """Acquires a database-backed distributed lock with automatic expiration to prevent duplicate concurrent runs."""

    def __init__(self, conn_factory, user_id: str, timeout_seconds: int = config.TIMETABLE_LOCK_TIMEOUT_SECONDS):
        self.conn_factory = conn_factory
        self.user_id = user_id
        self.timeout_seconds = timeout_seconds
        self.lock_token = secrets.token_hex(16)
        self.acquired = False

    def acquire(self) -> bool:
        now = time.time()
        expires = now + self.timeout_seconds
        conn = self.conn_factory()
        try:
            # Delete expired locks for this user
            conn.execute("DELETE FROM timetable_sync_locks WHERE user_id = ? AND expires_at <= ?", (self.user_id, now))
            # Try to insert new lock
            try:
                conn.execute(
                    "INSERT INTO timetable_sync_locks (user_id, locked_at, expires_at, lock_token) VALUES (?, ?, ?, ?)",
                    (self.user_id, now, expires, self.lock_token)
                )
                conn.commit()
                self.acquired = True
                return True
            except Exception:
                return False
        finally:
            conn.close()

    def release(self):
        if not self.acquired:
            return
        conn = self.conn_factory()
        try:
            conn.execute("DELETE FROM timetable_sync_locks WHERE user_id = ? AND lock_token = ?", (self.user_id, self.lock_token))
            conn.commit()
        finally:
            conn.close()
            self.acquired = False

    def __enter__(self):
        if not self.acquire():
            raise RuntimeError(f"Could not acquire synchronization lease for user '{self.user_id}'. Another sync is in progress.")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()


# ==============================================================================
# 5. TIMETABLE SYNCHRONIZER ENGINE (IDEMPOTENCY & DELTAS)
# ==============================================================================

class TimetableSynchronizer:
    """Reconciles normalized TimetableSession items against Google Calendar and SQLite mappings."""

    def __init__(self, conn_factory, user_id: str, calendar_client: GoogleCalendarClient, calendar_id: str = "primary"):
        self.conn_factory = conn_factory
        self.user_id = user_id
        self.calendar_client = calendar_client
        self.calendar_id = calendar_id

    def synchronize(self, sessions: List[TimetableSession]) -> Dict[str, Any]:
        """
        Executes idempotent reconciliation:
        1. Compares sessions against timetable_events_map.
        2. Dispatches CREATE, UPDATE, or NO-OP.
        3. Identifies vanished sessions in active date window and dispatches DELETE.
        """
        created = 0
        updated = 0
        unchanged = 0
        deleted = 0
        errors: List[str] = []

        now = time.time()
        current_map: Dict[str, Dict[str, Any]] = {}

        # 1. Fetch existing mapping
        conn = self.conn_factory()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT id, source_session_id, source_date, google_calendar_id, google_event_id, source_hash, status FROM timetable_events_map WHERE user_id = ? AND status = 'synced'",
                (self.user_id,)
            )
            for row in cur.fetchall():
                key = f"{row[1]}:{row[2]}"  # session_id:date
                current_map[key] = {
                    "id": row[0],
                    "session_id": row[1],
                    "date": row[2],
                    "calendar_id": row[3],
                    "event_id": row[4],
                    "hash": row[5]
                }
        finally:
            conn.close()

        seen_keys = set()

        # 2. Process incoming sessions
        for session in sessions:
            key = f"{session.session_id}:{session.date}"
            seen_keys.add(key)
            session_hash = session.deterministic_hash

            if key not in current_map:
                # CREATE
                try:
                    g_event = self.calendar_client.create_event(self.calendar_id, session, self.user_id)
                    g_event_id = g_event.get("id")

                    map_id = f"{self.user_id}:{session.session_id}:{session.date}"
                    summary = session.course_name
                    c = self.conn_factory()
                    try:
                        c.execute("""
                            INSERT OR REPLACE INTO timetable_events_map
                            (id, user_id, source_session_id, source_date, google_calendar_id, google_event_id, source_hash, summary, start_time, end_time, last_synced_at, status)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'synced')
                        """, (map_id, self.user_id, session.session_id, session.date, self.calendar_id, g_event_id, session_hash, summary, session.start_time, session.end_time, now))
                        c.commit()
                    finally:
                        c.close()

                    created += 1
                except Exception as e:
                    errors.append(f"Failed to create event for session '{session.course_name}' on {session.date}: {str(e)}")

            else:
                existing = current_map[key]
                if existing["hash"] == session_hash:
                    # NO-OP: Unchanged
                    unchanged += 1
                else:
                    # UPDATE: Course, room, or time modified
                    try:
                        self.calendar_client.update_event(existing["calendar_id"], existing["event_id"], session, self.user_id)
                        summary = session.course_name
                        c = self.conn_factory()
                        try:
                            c.execute("""
                                UPDATE timetable_events_map
                                SET source_hash = ?, summary = ?, start_time = ?, end_time = ?, last_synced_at = ?
                                WHERE id = ?
                            """, (session_hash, summary, session.start_time, session.end_time, now, existing["id"]))
                            c.commit()
                        finally:
                            c.close()

                        updated += 1
                    except Exception as e:
                        errors.append(f"Failed to update event for session '{session.course_name}' on {session.date}: {str(e)}")

        # 3. Handle Deletions for disappeared sessions within the timetable dates range
        if sessions:
            dates = [s.date for s in sessions]
            min_date = min(dates)
            max_date = max(dates)

            for key, existing in current_map.items():
                if existing["date"] >= min_date and existing["date"] <= max_date and key not in seen_keys:
                    try:
                        self.calendar_client.delete_event(existing["calendar_id"], existing["event_id"])
                        c = self.conn_factory()
                        try:
                            c.execute("UPDATE timetable_events_map SET status = 'cancelled', last_synced_at = ? WHERE id = ?", (now, existing["id"]))
                            c.commit()
                        finally:
                            c.close()

                        deleted += 1
                    except Exception as e:
                        errors.append(f"Failed to delete event '{existing['event_id']}' for vanished session on {existing['date']}: {str(e)}")

        status_label = "success" if not errors else ("partial" if (created or updated or unchanged or deleted) else "failed")

        # 4. Record history entry
        history_id = f"sync_{int(now * 1000)}_{secrets.token_hex(4)}"
        c = self.conn_factory()
        try:
            c.execute("""
                INSERT INTO timetable_sync_history
                (id, user_id, timestamp, sessions_seen, created_count, updated_count, deleted_count, unchanged_count, error_count, status, details)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                history_id, self.user_id, now, len(sessions),
                created, updated, deleted, unchanged, len(errors),
                status_label, json.dumps({"errors": errors[:10]})
            ))
            c.commit()
        finally:
            c.close()

        return {
            "sessions_seen": len(sessions),
            "created": created,
            "updated": updated,
            "deleted": deleted,
            "unchanged": unchanged,
            "errors": errors,
            "status": status_label,
            "timestamp": now
        }


# ==============================================================================
# 6. UNIFIED TIMETABLE SERVICE
# ==============================================================================

class TimetableService:
    """Service facade connecting storage, OAuth, parsing, synchronizer, and scheduler."""

    def __init__(self, conn_factory):
        self.conn_factory = conn_factory

    def save_oauth_tokens(self, user_id: str, token_data: Dict[str, Any], calendar_id: str = "primary", email: Optional[str] = None):
        """Encrypts and persists Google OAuth tokens."""
        encrypted = OAuthTokenCrypto.encrypt(token_data)
        now = time.time()
        conn = self.conn_factory()
        try:
            conn.execute("""
                INSERT OR REPLACE INTO google_oauth_tokens
                (user_id, encrypted_token_data, calendar_id, connected_email, created_at, updated_at)
                VALUES (?, ?, ?, ?, COALESCE((SELECT created_at FROM google_oauth_tokens WHERE user_id = ?), ?), ?)
            """, (user_id, encrypted, calendar_id, email, user_id, now, now))
            conn.commit()
        finally:
            conn.close()

    def get_oauth_tokens(self, user_id: str) -> Optional[Tuple[Dict[str, Any], str, Optional[str]]]:
        """Returns (token_data, calendar_id, connected_email) for user_id or None if not connected."""
        conn = self.conn_factory()
        try:
            cur = conn.cursor()
            cur.execute("SELECT encrypted_token_data, calendar_id, connected_email FROM google_oauth_tokens WHERE user_id = ?", (user_id,))
            row = cur.fetchone()
            if not row:
                return None
            token_data = OAuthTokenCrypto.decrypt(row[0])
            if not token_data:
                return None
            return token_data, row[1] or "primary", row[2]
        finally:
            conn.close()

    def disconnect_google(self, user_id: str) -> bool:
        """Removes stored tokens for user_id without touching local timetable files."""
        conn = self.conn_factory()
        try:
            conn.execute("DELETE FROM google_oauth_tokens WHERE user_id = ?", (user_id,))
            conn.commit()
            return True
        finally:
            conn.close()

    def create_oauth_state(self, user_id: str) -> str:
        """Generates a CSRF state token valid for 10 minutes."""
        token = secrets.token_urlsafe(32)
        now = time.time()
        expires = now + 600
        conn = self.conn_factory()
        try:
            conn.execute("DELETE FROM google_oauth_states WHERE expires_at <= ?", (now,))
            conn.execute("INSERT INTO google_oauth_states (state_token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)", (token, user_id, now, expires))
            conn.commit()
            return token
        finally:
            conn.close()

    def validate_and_consume_state(self, state_token: str) -> Optional[str]:
        """Validates CSRF state token and consumes it (one-time use). Returns user_id or None."""
        if not state_token:
            return None
        now = time.time()
        conn = self.conn_factory()
        try:
            cur = conn.cursor()
            cur.execute("SELECT user_id, expires_at FROM google_oauth_states WHERE state_token = ?", (state_token,))
            row = cur.fetchone()
            if not row or row[1] < now:
                return None
            user_id = row[0]
            conn.execute("DELETE FROM google_oauth_states WHERE state_token = ?", (state_token,))
            conn.commit()
            return user_id
        finally:
            conn.close()

    def upload_timetable(self, user_id: str, raw_json_str: str) -> Tuple[bool, str, int]:
        """Validates, stores, and caches user's uploaded UPES timetable JSON."""
        sessions, errors = parse_timetable_json(raw_json_str)
        if not sessions and errors:
            return False, f"Invalid timetable data: {'; '.join(errors)}", 0

        now = time.time()
        conn = self.conn_factory()
        try:
            conn.execute("""
                INSERT OR REPLACE INTO user_timetables (user_id, raw_json, updated_at)
                VALUES (?, ?, ?)
            """, (user_id, raw_json_str, now))
            conn.commit()
        finally:
            conn.close()

        # Also save to storage_vault/upes_timetable.json as persistent backup if admin or single-user
        try:
            with open(config.UPES_TIMETABLE_JSON_PATH, "w", encoding="utf-8") as f:
                f.write(raw_json_str)
        except Exception:
            pass

        return True, "Timetable stored successfully.", len(sessions)

    def load_timetable_sessions(self, user_id: str) -> Tuple[List[TimetableSession], List[str]]:
        """Loads timetable sessions from user's DB record or vault file fallback."""
        raw_json = None
        conn = self.conn_factory()
        try:
            cur = conn.cursor()
            cur.execute("SELECT raw_json FROM user_timetables WHERE user_id = ?", (user_id,))
            row = cur.fetchone()
            if row:
                raw_json = row[0]
        finally:
            conn.close()

        if not raw_json and os.path.exists(config.UPES_TIMETABLE_JSON_PATH):
            try:
                with open(config.UPES_TIMETABLE_JSON_PATH, "r", encoding="utf-8") as f:
                    raw_json = f.read()
            except Exception:
                pass

        if not raw_json:
            return [], ["No timetable data found. Upload UPES timetable JSON first."]

        return parse_timetable_json(raw_json)

    def sync_user_timetable(self, user_id: str, force_calendar_id: Optional[str] = None) -> Dict[str, Any]:
        """Executes full synchronization pipeline for a given user under a lease lock."""
        # 1. Check OAuth connection
        oauth_info = self.get_oauth_tokens(user_id)
        if not oauth_info:
            return {
                "status": "error",
                "message": "Google Calendar is not connected. Authorize Google account first.",
                "sessions_seen": 0, "created": 0, "updated": 0, "deleted": 0, "unchanged": 0,
                "errors": ["Google account not connected"]
            }

        token_data, default_cal_id, email = oauth_info
        calendar_id = force_calendar_id or default_cal_id or "primary"

        # 2. Acquire Distributed Lease Lock
        lease = DatabaseSyncLease(self.conn_factory, user_id)
        if not lease.acquire():
            return {
                "status": "locked",
                "message": f"Synchronization already running for user '{user_id}'.",
                "sessions_seen": 0, "created": 0, "updated": 0, "deleted": 0, "unchanged": 0,
                "errors": ["Sync lock active"]
            }

        try:
            # 3. Load Sessions
            sessions, load_errs = self.load_timetable_sessions(user_id)
            if not sessions:
                return {
                    "status": "empty",
                    "message": "No valid timetable sessions to synchronize.",
                    "sessions_seen": 0, "created": 0, "updated": 0, "deleted": 0, "unchanged": 0,
                    "errors": load_errs
                }

            # 4. Instantiate API Client with callback to update refreshed token
            def on_refresh(u_id, new_tokens):
                self.save_oauth_tokens(u_id, new_tokens, calendar_id, email)

            client = GoogleCalendarClient(token_data, user_id, on_token_refresh=on_refresh)

            # 5. Synchronize
            synchronizer = TimetableSynchronizer(self.conn_factory, user_id, client, calendar_id)
            result = synchronizer.synchronize(sessions)
            result["connected_email"] = email
            result["calendar_id"] = calendar_id
            return result

        finally:
            lease.release()

    def sync_all_active_users(self) -> Dict[str, Any]:
        """Called every 3 hours by SchedulerDaemon to synchronize all users with connected Google accounts."""
        conn = self.conn_factory()
        users_to_sync = []
        try:
            cur = conn.cursor()
            cur.execute("SELECT DISTINCT user_id FROM google_oauth_tokens")
            users_to_sync = [r[0] for r in cur.fetchall()]
        finally:
            conn.close()

        summaries = {}
        for uid in users_to_sync:
            try:
                summaries[uid] = self.sync_user_timetable(uid)
            except Exception as e:
                summaries[uid] = {"status": "failed", "errors": [str(e)]}

        return summaries

    def get_user_status(self, user_id: str) -> Dict[str, Any]:
        """Returns sanitized telemetry/status for user's timetable sync."""
        oauth_info = self.get_oauth_tokens(user_id)
        is_connected = oauth_info is not None
        calendar_id = oauth_info[1] if oauth_info else None
        connected_email = oauth_info[2] if oauth_info else None

        last_sync = None
        conn = self.conn_factory()
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT timestamp, sessions_seen, created_count, updated_count, deleted_count, unchanged_count, error_count, status, details
                FROM timetable_sync_history
                WHERE user_id = ?
                ORDER BY timestamp DESC LIMIT 1
            """, (user_id,))
            row = cur.fetchone()
            if row:
                details_obj = {}
                try:
                    details_obj = json.loads(row[8]) if row[8] else {}
                except Exception:
                    pass
                last_sync = {
                    "timestamp": row[0],
                    "sessions_seen": row[1],
                    "created": row[2],
                    "updated": row[3],
                    "deleted": row[4],
                    "unchanged": row[5],
                    "errors_count": row[6],
                    "status": row[7],
                    "recent_errors": details_obj.get("errors", [])
                }
        finally:
            conn.close()

        # Check next scheduled run from scheduled_jobs
        next_run = None
        interval_seconds = config.TIMETABLE_SYNC_INTERVAL_SECONDS
        enabled = True
        try:
            conn = self.conn_factory()
            cur = conn.cursor()
            cur.execute("SELECT next_run, enabled, interval_seconds FROM scheduled_jobs WHERE id = 'job_timetable_sync'")
            jrow = cur.fetchone()
            if jrow:
                next_run = jrow[0]
                enabled = bool(jrow[1])
                interval_seconds = jrow[2]
            conn.close()
        except Exception:
            pass

        return {
            "google_connected": is_connected,
            "connected_email": connected_email,
            "calendar_id": calendar_id,
            "scheduled_enabled": enabled,
            "sync_interval_seconds": interval_seconds,
            "next_scheduled_run": next_run,
            "last_sync": last_sync
        }
