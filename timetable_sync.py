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
import logging
import math
import os
import secrets
import socket
import ssl
import struct
import time
import urllib.parse
import zoneinfo
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

import config

logger = logging.getLogger(__name__)

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
    meeting_link: str = ""
    source: str = "upes"
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_online(self) -> bool:
        """Determines if the session is conducted online (e.g. MS Teams / Virtual Classroom)."""
        if self.meeting_link.strip():
            return True
        r = self.room.strip().lower()
        return "team" in r or "online" in r or "virtual" in r

    @property
    def deterministic_hash(self) -> str:
        """Computes SHA-256 hash of normalized content fields to detect modifications."""
        norm_str = f"{self.course_name.strip()}|{self.course_code.strip()}|{self.date.strip()}|{self.start_time.strip()}|{self.end_time.strip()}|{self.room.strip()}|{self.faculty.strip()}|{self.meeting_link.strip()}|{1 if self.is_online else 0}"
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


WEEKDAY_MAP = {
    "monday": 0, "mon": 0, "m": 0, "1": 0,
    "tuesday": 1, "tue": 1, "tues": 1, "tu": 1, "2": 1,
    "wednesday": 2, "wed": 2, "w": 2, "3": 2,
    "thursday": 3, "thu": 3, "thur": 3, "thurs": 3, "th": 3, "4": 3,
    "friday": 4, "fri": 4, "f": 4, "5": 4,
    "saturday": 5, "sat": 5, "sa": 5, "6": 5,
    "sunday": 6, "sun": 6, "su": 6, "7": 6, "0": 6
}

WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _resolve_weekday_to_date(day_raw: Any, ref_date: Optional[datetime.date] = None, tz_name: str = config.TIMETABLE_TIMEZONE) -> Optional[str]:
    """Resolves a weekday name/abbreviation/index into a YYYY-MM-DD date for the active week in tz_name."""
    if day_raw is None:
        return None
    cleaned = str(day_raw).strip().lower()
    if not cleaned:
        return None

    target_weekday = None
    for k, v in WEEKDAY_MAP.items():
        if cleaned == k or cleaned.startswith(k) or f" {k}" in cleaned:
            target_weekday = v
            break

    if target_weekday is None:
        return None

    if ref_date is None:
        try:
            tz = zoneinfo.ZoneInfo(tz_name)
            now_dt = datetime.datetime.now(tz)
        except Exception:
            ist = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
            now_dt = datetime.datetime.now(ist)
        ref_date = now_dt.date()

    monday = ref_date - datetime.timedelta(days=ref_date.weekday())
    target_date = monday + datetime.timedelta(days=target_weekday)
    return target_date.strftime("%Y-%m-%d")


def normalize_upes_session(raw_item: Dict[str, Any], default_date: Optional[str] = None, ref_date: Optional[datetime.date] = None) -> Optional[TimetableSession]:
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
        raw_item.get("course_title") or
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

    # Check native UPES ModuleList if course_name is empty
    if not course_name and isinstance(raw_item.get("ModuleList"), list) and raw_item["ModuleList"]:
        for mod in raw_item["ModuleList"]:
            if isinstance(mod, dict):
                c_name = (mod.get("ModuleName") or mod.get("ModuleTitle") or mod.get("Name") or "").strip()
                if c_name:
                    course_name = c_name
                    if not course_code:
                        course_code = (mod.get("ModuleCode") or mod.get("Code") or "").strip()
                    break

    # 3. Extract date (YYYY-MM-DD) or resolve from weekday
    raw_date = (
        raw_item.get("SlotDate") or
        raw_item.get("slotDate") or
        raw_item.get("slot_date") or
        raw_item.get("date") or
        raw_item.get("day_date") or
        raw_item.get("session_date") or
        default_date or
        ""
    )

    date_str = _normalize_date_string(str(raw_date).strip()) if raw_date else None

    # If no explicit calendar date, check for weekday field
    if not date_str:
        day_raw = (
            raw_item.get("day") or
            raw_item.get("day_name") or
            raw_item.get("dayName") or
            raw_item.get("weekday") or
            raw_item.get("day_of_week") or
            raw_item.get("dayOfWeek") or
            raw_date
        )
        date_str = _resolve_weekday_to_date(day_raw, ref_date=ref_date)

    if not date_str:
        return None  # Cannot proceed without a valid date

    # 4. Extract start & end times
    start_time_raw = (
        raw_item.get("SlotStartTime") or
        raw_item.get("slotStartTime") or
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
        raw_item.get("SlotEndTime") or
        raw_item.get("slotEndTime") or
        raw_item.get("end_time") or
        raw_item.get("endTime") or
        raw_item.get("time_to") or
        raw_item.get("timeTo") or
        raw_item.get("to_time") or
        raw_item.get("toTime") or
        raw_item.get("end") or
        ""
    ).strip()

    # Handle combined time string like "09:00 - 10:00", "09:15 AM - 05:00 PM", "09:15 to 17:00"
    if not start_time_raw and not end_time_raw:
        slot_time = (raw_item.get("time") or raw_item.get("slot") or raw_item.get("timing") or raw_item.get("hours") or "").strip()
        for sep in (" - ", "-", " to ", " TO ", " – ", " — "):
            if sep in slot_time:
                t_parts = slot_time.split(sep, 1)
                start_time_raw = t_parts[0].strip()
                end_time_raw = t_parts[1].strip()
                break

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
        raw_item.get("classroom") or
        ""
    ).strip()

    # Check native UPES FloorPlanDetails
    if not room and isinstance(raw_item.get("FloorPlanDetails"), dict):
        fp = raw_item["FloorPlanDetails"]
        room = (fp.get("VenueName") or fp.get("VenueCode") or fp.get("RoomName") or "").strip()

    if not room:
        room = "TBD"

    # 6. Extract faculty / instructor
    faculty = (
        raw_item.get("faculty") or
        raw_item.get("faculty_name") or
        raw_item.get("facultyName") or
        raw_item.get("instructor") or
        raw_item.get("teacher") or
        raw_item.get("professor") or
        raw_item.get("faculty_initials") or
        ""
    ).strip()

    # Check native UPES TeacherList
    if not faculty and isinstance(raw_item.get("TeacherList"), list) and raw_item["TeacherList"]:
        t_names = [t.get("Name") or t.get("TeacherName") for t in raw_item["TeacherList"] if isinstance(t, dict) and (t.get("Name") or t.get("TeacherName"))]
        if t_names:
            faculty = ", ".join(t_names).strip()

    if not faculty:
        faculty = "TBD"

    # 7. Extract meeting link (MS Teams / virtual classroom link)
    meeting_link = (
        raw_item.get("MeetingLink") or
        raw_item.get("meeting_link") or
        raw_item.get("meetingLink") or
        raw_item.get("join_url") or
        raw_item.get("joinUrl") or
        raw_item.get("teams_link") or
        raw_item.get("teamsLink") or
        raw_item.get("online_link") or
        ""
    ).strip()

    if not meeting_link and isinstance(raw_item.get("FloorPlanDetails"), dict):
        fp = raw_item["FloorPlanDetails"]
        meeting_link = (fp.get("MeetingLink") or fp.get("meetingLink") or fp.get("JoinUrl") or fp.get("joinUrl") or "").strip()

    # 8. Extract or derive session ID
    session_id = (
        raw_item.get("session_id") or
        raw_item.get("sessionId") or
        raw_item.get("SessionId") or
        raw_item.get("id") or
        raw_item.get("slot_id") or
        raw_item.get("slotId") or
        raw_item.get("SlotId") or
        ""
    ).strip()

    if not session_id:
        # Compute deterministic content hash for identity
        id_material = f"{course_name}:{course_code}:{date_str}:{start_time}:{end_time}:{room}:{faculty}"
        session_id = f"upes_{hashlib.sha256(id_material.encode('utf-8')).hexdigest()[:16]}"

    return TimetableSession(
        course_name=course_name,
        course_code=course_code,
        date=date_str,
        start_time=start_time,
        end_time=end_time,
        room=room,
        faculty=faculty,
        session_id=session_id,
        meeting_link=meeting_link,
        source="upes",
        raw=raw_item
    )


def _normalize_date_string(date_raw: str) -> Optional[str]:
    """Parses various date formats (YYYY-MM-DD, YYYY-Mon-DD, DD/MM/YYYY, DD-MM-YYYY, ISO) into YYYY-MM-DD."""
    if not date_raw:
        return None
    date_raw = str(date_raw).strip().split("T")[0]  # Strip time component if ISO

    for fmt in ("%Y-%m-%d", "%Y-%b-%d", "%Y-%B-%d", "%d-%b-%Y", "%d-%B-%Y", "%d %b %Y", "%d %B %Y", "%B %d, %Y", "%b %d, %Y", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%d.%m.%Y"):
        try:
            dt = datetime.datetime.strptime(date_raw, fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def get_rolling_two_week_window(ref_dt: Optional[Any] = None) -> Tuple[datetime.date, datetime.date, datetime.date, datetime.date]:
    """
    Calculates dynamic (week1_start, week1_end, week2_start, week2_end) in Asia/Kolkata timezone.
    Week 1 = Current Monday through Sunday
    Week 2 = Immediately following Monday through Sunday
    """
    if ref_dt is None:
        ist = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
        ref_dt = datetime.datetime.now(ist)
    if isinstance(ref_dt, datetime.datetime):
        today = ref_dt.date()
    elif isinstance(ref_dt, datetime.date):
        today = ref_dt
    else:
        today = datetime.date.today()

    w1_start = today - datetime.timedelta(days=today.weekday())
    w1_end = w1_start + datetime.timedelta(days=6)
    w2_start = w1_start + datetime.timedelta(days=7)
    w2_end = w1_start + datetime.timedelta(days=13)
    return w1_start, w1_end, w2_start, w2_end


def filter_sessions_by_window(sessions: List[TimetableSession], start_date: datetime.date, end_date: datetime.date) -> List[TimetableSession]:
    """Filters a list of TimetableSession objects to only those falling within [start_date, end_date] inclusive."""
    filtered: List[TimetableSession] = []
    for s in sessions:
        try:
            s_dt = datetime.datetime.strptime(s.date, "%Y-%m-%d").date()
            if start_date <= s_dt <= end_date:
                filtered.append(s)
        except Exception:
            continue
    return sorted(filtered, key=lambda x: (x.date, x.start_time))


def _normalize_time_string(time_raw: str) -> Optional[str]:
    """Parses time strings like '09:00', '9:00 AM', '14:30:00', '2026-08-19T09:15:00' into HH:MM:SS."""
    if not time_raw:
        return None
    time_raw = str(time_raw).strip().upper()
    if "T" in time_raw:
        time_raw = time_raw.split("T", 1)[1]
    elif " " in time_raw and ("-" in time_raw.split(" ", 1)[0] or "/" in time_raw.split(" ", 1)[0]):
        parts = time_raw.split(" ")
        time_raw = " ".join(parts[1:])

    for fmt in ("%H:%M:%S", "%H:%M", "%I:%M %p", "%I:%M%p", "%I %p", "%I:%M:%S %p", "%I:%M:%S%p", "%H"):
        try:
            dt = datetime.datetime.strptime(time_raw, fmt)
            return dt.strftime("%H:%M:00")
        except ValueError:
            continue
    return None


def parse_timetable_json(json_data: Any, ref_date: Optional[datetime.date] = None) -> Tuple[List[TimetableSession], List[str]]:
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
        if "sessions" in json_data and isinstance(json_data["sessions"], list):
            raw_items = json_data["sessions"]
        elif "timetable" in json_data and isinstance(json_data["timetable"], list):
            raw_items = json_data["timetable"]
        elif "data" in json_data and isinstance(json_data["data"], list):
            raw_items = json_data["data"]
        else:
            # Check if keys are weekdays or dates (e.g. {"Wednesday": [...], "Thursday": [...]})
            for key, val in json_data.items():
                if isinstance(val, list):
                    date_norm = _normalize_date_string(key)
                    if not date_norm:
                        date_norm = _resolve_weekday_to_date(key, ref_date=ref_date)
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
            session = normalize_upes_session(item, ref_date=ref_date)
            if session:
                sessions.append(session)
            else:
                errors.append(f"Skipped invalid session at index {idx}: missing required course name, date/day, or start/end time.")
        except Exception as e:
            errors.append(f"Error parsing session at index {idx}: {str(e)}")

    return sessions, errors


# ==============================================================================
# 1B. NATIVE UPES CURRICULUM SCHEDULING API CLIENT
# ==============================================================================

def decode_jwt_expiration(token: str) -> Optional[float]:
    """
    Extracts expiration timestamp (exp claim) from an unencrypted JWT token payload.
    Does not verify cryptographic signature; used strictly for local expiry pre-checks.
    """
    if not token or not isinstance(token, str):
        return None
    try:
        parts = token.strip().split(".")
        if len(parts) != 3:
            return None
        payload_b64 = parts[1]
        rem = len(payload_b64) % 4
        if rem > 0:
            payload_b64 += "=" * (4 - rem)
        payload_bytes = base64.urlsafe_b64decode(payload_b64.encode("ascii"))
        payload_json = json.loads(payload_bytes.decode("utf-8"))
        exp = payload_json.get("exp")
        if exp is not None and isinstance(exp, (int, float)):
            return float(exp)
    except Exception:
        pass
    return None


def fetch_upes_timetable(token: str, student_code: str, api_url: Optional[str] = None) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    """
    Executes authenticated HTTP POST to UPES Curriculum Scheduling API.
    Returns (raw_items_list, error_message).
    """
    if not token or not str(token).strip():
        return None, "auth_required: UPES session token is missing. Please authenticate via portal."
    if not student_code or not str(student_code).strip():
        return None, "missing_student_code: UPES student/SAP ID is not configured."

    url = (api_url or config.UPES_TIMETABLE_API_URL or "https://myupes-beta.upes.ac.in/apigateway/api/timetable").strip()
    student_code_clean = str(student_code).strip()
    headers = {
        "Authorization": f"Bearer {token.strip()}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
        "x-applicationname": "connectportal",
        "x-requestfrom": "web",
        "x-studentuniqueid": student_code_clean,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    payload = {
        "ActivityCode": "student",
        "TimeTableContextDetails": {
            "StudentCode": student_code_clean
        }
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=config.UPES_REQUEST_TIMEOUT_SECONDS)
        if resp.status_code in (401, 403):
            return None, "auth_required: UPES authentication expired / login required."
        if resp.status_code != 200:
            return None, f"http_error_{resp.status_code}: UPES API responded with HTTP {resp.status_code}"

        try:
            data = resp.json()
        except Exception as e:
            return None, f"invalid_json: Failed to parse UPES response JSON: {str(e)}"

        # Response may be a list directly or wrapped in an object
        if isinstance(data, list):
            return data, None
        elif isinstance(data, dict):
            for k in ("data", "items", "timetable", "sessions", "TimeTable", "Data"):
                if k in data and isinstance(data[k], list):
                    return data[k], None
            return [data], None

        return None, "empty_response: UPES returned non-list data."

    except requests.Timeout:
        return None, "network_timeout: Request to UPES API timed out."
    except requests.RequestException as e:
        return None, f"network_error: Failed to connect to UPES API: {str(e)}"


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

        location = session.room
        meeting_link = getattr(session, "meeting_link", "").strip()
        if meeting_link:
            room_lower = session.room.lower()
            if "team" in room_lower or "online" in room_lower or "virtual" in room_lower:
                location = meeting_link
            else:
                location = f"{session.room} ({meeting_link})"

        desc_lines = [
            f"Course: {session.course_name}",
            f"Code: {session.course_code or 'N/A'}",
            f"Faculty: {session.faculty}",
            f"Room: {session.room}"
        ]
        if meeting_link:
            desc_lines.append(f"MS Teams Link: {meeting_link}")
        desc_lines.extend([
            "Source: UPES Timetable",
            "Managed by: NexusNode"
        ])
        description = "\n".join(desc_lines)

        payload = {
            "summary": summary,
            "location": location,
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
        if session.is_online:
            payload["colorId"] = "4"  # Flamingo / Pink in Google Calendar palette
        return payload


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

    # 7. Authenticated UPES Portal Sessions (with Session Bundle & Headless Rotation)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS upes_auth_sessions (
            user_id TEXT PRIMARY KEY,
            encrypted_access_token TEXT NOT NULL,
            student_code TEXT NOT NULL,
            api_url TEXT,
            expires_at REAL,
            encrypted_refresh_token TEXT,
            encrypted_cookies TEXT,
            cookie_expires_at REAL,
            credential_generation INTEGER NOT NULL DEFAULT 1,
            last_refresh_at REAL,
            last_refresh_status TEXT,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        );
    """)
    for col_def in [
        "expires_at REAL",
        "encrypted_refresh_token TEXT",
        "encrypted_cookies TEXT",
        "cookie_expires_at REAL",
        "credential_generation INTEGER NOT NULL DEFAULT 1",
        "last_refresh_at REAL",
        "last_refresh_status TEXT"
    ]:
        try:
            conn.execute(f"ALTER TABLE upes_auth_sessions ADD COLUMN {col_def};")
        except Exception:
            pass

    # 8. Attendance Punch Records & Logs
    conn.execute("""
        CREATE TABLE IF NOT EXISTS attendance_punches (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            session_id TEXT,
            course_name TEXT NOT NULL,
            course_code TEXT NOT NULL,
            punch_date TEXT NOT NULL,
            punch_time TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'present',
            room TEXT,
            notes TEXT,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            UNIQUE(user_id, course_code, punch_date, punch_time)
        );
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_punches_user_date ON attendance_punches (user_id, punch_date);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_punches_user_course ON attendance_punches (user_id, course_code);")


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
# 6. UPES BROWSER SESSION BRIDGE & SESSION BROKER
# ==============================================================================

def cdp_websocket_command(ws_url: str, method: str, params: Optional[Dict[str, Any]] = None, timeout: float = 5.0) -> Optional[Dict[str, Any]]:
    """
    Pure Python standard-library implementation of a WebSocket command client for Chrome DevTools Protocol (CDP).
    Supports arbitrary CDP domains (Runtime, Network, Storage, etc.).
    Requires zero external dependencies. Works across standard Python, Termux, Windows, and Linux.
    """
    if not ws_url or not isinstance(ws_url, str):
        return None

    try:
        parsed = urllib.parse.urlparse(ws_url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or (443 if parsed.scheme == "wss" else 80)
        path = parsed.path or "/"

        sock = socket.create_connection((host, port), timeout=timeout)
        if parsed.scheme == "wss":
            context = ssl.create_default_context()
            sock = context.wrap_socket(sock, server_hostname=host)

        try:
            # 1. Handshake
            sec_key = base64.b64encode(secrets.token_bytes(16)).decode("ascii")
            req = (
                f"GET {path} HTTP/1.1\r\n"
                f"Host: {host}:{port}\r\n"
                f"Upgrade: websocket\r\n"
                f"Connection: Upgrade\r\n"
                f"Sec-WebSocket-Key: {sec_key}\r\n"
                f"Sec-WebSocket-Version: 13\r\n\r\n"
            )
            sock.sendall(req.encode("ascii"))

            # Read handshake response
            resp_bytes = b""
            sock.settimeout(timeout)
            while b"\r\n\r\n" not in resp_bytes:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                resp_bytes += chunk

            if not resp_bytes.startswith(b"HTTP/1.1 101"):
                return None

            # 2. Construct and send masked text frame
            payload = json.dumps({
                "id": int(time.time() * 1000) % 1000000,
                "method": method,
                "params": params or {}
            }).encode("utf-8")

            frame = bytearray([0x81])
            pay_len = len(payload)
            mask_key = secrets.token_bytes(4)

            if pay_len <= 125:
                frame.append(0x80 | pay_len)
            elif pay_len <= 65535:
                frame.append(0x80 | 126)
                frame.extend(struct.pack("!H", pay_len))
            else:
                frame.append(0x80 | 127)
                frame.extend(struct.pack("!Q", pay_len))

            frame.extend(mask_key)
            frame.extend(bytearray(b ^ mask_key[i % 4] for i, b in enumerate(payload)))
            sock.sendall(frame)

            # 3. Read response frame
            raw_hdr = sock.recv(2)
            if len(raw_hdr) < 2:
                return None

            b2 = raw_hdr[1]
            is_masked = (b2 & 0x80) != 0
            frame_len = b2 & 0x7F

            if frame_len == 126:
                frame_len = struct.unpack("!H", sock.recv(2))[0]
            elif frame_len == 127:
                frame_len = struct.unpack("!Q", sock.recv(8))[0]

            resp_mask = sock.recv(4) if is_masked else None
            data_bytes = bytearray()
            while len(data_bytes) < frame_len:
                chunk = sock.recv(min(4096, frame_len - len(data_bytes)))
                if not chunk:
                    break
                data_bytes.extend(chunk)

            if resp_mask:
                data_bytes = bytearray(b ^ resp_mask[i % 4] for i, b in enumerate(data_bytes))

            resp_json = json.loads(data_bytes.decode("utf-8", errors="ignore"))
            return resp_json
        finally:
            sock.close()
    except Exception:
        return None


def cdp_websocket_evaluate(ws_url: str, expression: str, timeout: float = 5.0) -> Optional[Dict[str, Any]]:
    """Evaluates a JavaScript expression in the context of the target page using CDP WebSocket."""
    return cdp_websocket_command(ws_url, "Runtime.evaluate", {
        "expression": expression,
        "returnByValue": True,
        "awaitPromise": True
    }, timeout=timeout)


class UpesSessionJournal:
    """
    Encrypted Write-Ahead Recovery Journal for UPES Session Credential Rotation.
    Guarantees crash-consistency across the network boundary between remote token rotation
    and local database persistence.
    """

    @classmethod
    def get_journal_path(cls) -> str:
        vault_dir = getattr(config, "STORAGE_VAULT_DIR", "storage_vault")
        os.makedirs(vault_dir, exist_ok=True)
        return os.path.join(vault_dir, ".upes_session_journal.enc")

    @classmethod
    def write_journal(cls, user_id: str, generation: int, session_bundle: Dict[str, Any]) -> bool:
        """Atomically writes an encrypted journal entry before database commit."""
        try:
            journal_path = cls.get_journal_path()
            tmp_path = journal_path + f".{secrets.token_hex(4)}.tmp"

            payload = {
                "user_id": user_id,
                "generation": generation,
                "timestamp": time.time(),
                "bundle": session_bundle
            }
            encrypted = OAuthTokenCrypto.encrypt(payload)
            if not encrypted:
                return False

            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(encrypted)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except Exception:
                    pass

            if hasattr(os, "chmod") and os.name != "nt":
                try:
                    os.chmod(tmp_path, 0o600)
                except Exception:
                    pass

            os.replace(tmp_path, journal_path)
            return True
        except Exception as e:
            logger.warning(f"[AUTH_JOURNAL] Failed to write recovery journal: {e}")
            return False

    @classmethod
    def recover_and_replay_journal(cls, service: 'TimetableService', target_user_id: Optional[str] = None) -> Optional[str]:
        """
        Inspects for an uncommitted recovery journal, validates integrity and required fields,
        replays newer credentials into SQLite, and cleans up the journal.
        """
        journal_path = cls.get_journal_path()
        if not os.path.exists(journal_path):
            return None

        try:
            with open(journal_path, "r", encoding="utf-8") as f:
                encrypted = f.read().strip()

            if not encrypted:
                cls.cleanup_journal()
                return None

            payload = OAuthTokenCrypto.decrypt(encrypted)
            if not isinstance(payload, dict):
                logger.warning("[AUTH_JOURNAL] Malformed/undecryptable journal detected. Cleaning up.")
                cls.cleanup_journal()
                return None

            user_id = payload.get("user_id")
            journal_gen = payload.get("generation", 1)
            bundle = payload.get("bundle", {})

            if not user_id or not isinstance(bundle, dict):
                logger.warning("[AUTH_JOURNAL] Journal missing user_id or bundle. Discarding.")
                cls.cleanup_journal()
                return None

            # Case D: If target_user_id specified and differs, do not replay for another user
            if target_user_id and user_id != target_user_id:
                logger.info(f"[AUTH_JOURNAL] Journal belongs to user '{user_id}', ignoring for target '{target_user_id}'.")
                return None

            # Case E: Journal must contain valid, non-empty access_token and refresh_token
            access_tok = bundle.get("access_token")
            refresh_tok = bundle.get("refresh_token")
            if not access_tok or not refresh_tok or not isinstance(access_tok, str) or not isinstance(refresh_tok, str):
                logger.warning("[AUTH_JOURNAL] Journal contains incomplete/missing token fields. Discarding.")
                cls.cleanup_journal()
                return None

            # Check existing generation in DB
            existing = service.get_full_upes_session(user_id)
            current_gen = existing.get("credential_generation", 0) if existing else 0

            # Case A vs Case B: Replay only if journal is newer or equal
            if journal_gen >= current_gen:
                service.save_upes_session(
                    user_id=user_id,
                    access_token=access_tok,
                    student_code=bundle.get("student_code", ""),
                    api_url=bundle.get("api_url"),
                    expires_at=bundle.get("expires_at"),
                    refresh_token=refresh_tok,
                    cookies=bundle.get("cookies"),
                    cookie_expires_at=bundle.get("cookie_expires_at"),
                    credential_generation=journal_gen,
                    last_refresh_at=payload.get("timestamp", time.time()),
                    last_refresh_status="recovered_from_journal"
                )
                logger.info(f"[AUTH_JOURNAL] Successfully replayed recovered session journal (gen {journal_gen}) for user '{user_id}'.")
            else:
                logger.info(f"[AUTH_JOURNAL] Discarding stale journal (gen {journal_gen} < db gen {current_gen}).")

            cls.cleanup_journal()
            return user_id
        except Exception as e:
            logger.warning(f"[AUTH_JOURNAL] Error during journal recovery: {e}")
            cls.cleanup_journal()
            return None

    @classmethod
    def cleanup_journal(cls):
        """Safely removes the journal file."""
        try:
            journal_path = cls.get_journal_path()
            if os.path.exists(journal_path):
                os.remove(journal_path)
        except Exception:
            pass


class UpesBrowserSessionBridge:
    """
    Connects to local Chrome / Chromium instance via Chrome DevTools Protocol (CDP),
    locates open UPES portal tabs, and securely extracts the active session bundle
    (access token, refresh token, student UUID, and idp_session_info SSO cookie)
    without requiring manual copy-pasting.
    """

    def __init__(self, timetable_service: 'TimetableService'):
        self.service = timetable_service
        self.host = getattr(config, "CHROME_CDP_HOST", "127.0.0.1")
        self.port = getattr(config, "CHROME_CDP_PORT", 9222)
        self.host_pattern = getattr(config, "UPES_PORTAL_HOST_PATTERN", "myupes-beta.upes.ac.in")
        self.timeout = getattr(config, "UPES_CDP_TIMEOUT_SECONDS", 5)
        self.last_check_timestamp = None
        self.last_check_status = "not_checked"

    @property
    def cdp_url(self) -> str:
        return f"http://{self.host}:{self.port}/json"

    def is_cdp_available(self) -> bool:
        """Checks if Chrome remote debugging port is reachable."""
        try:
            r = requests.get(self.cdp_url, timeout=self.timeout)
            return r.status_code == 200
        except Exception:
            return False

    def list_browser_targets(self) -> List[Dict[str, Any]]:
        """Retrieves list of active page targets from CDP."""
        try:
            r = requests.get(self.cdp_url, timeout=self.timeout)
            if r.status_code == 200:
                return [t for t in r.json() if t.get("type") == "page"]
        except Exception:
            pass
        return []

    def find_upes_target(self) -> Optional[Dict[str, Any]]:
        """Scans open browser tabs for the authenticated UPES portal."""
        targets = self.list_browser_targets()
        for t in targets:
            url = t.get("url", "")
            title = t.get("title", "")
            if self.host_pattern in url or "UPES" in title or "Connect Portal" in title or "OnePortal" in title:
                return t
        return None

    def evaluate_in_target(self, target: Dict[str, Any], js_expression: str) -> Optional[Any]:
        """Evaluates a JavaScript expression in the context of the target page using CDP WebSocket."""
        ws_url = target.get("webSocketDebuggerUrl")
        if not ws_url:
            return None

        resp = cdp_websocket_evaluate(ws_url, js_expression, timeout=self.timeout)
        if resp and isinstance(resp, dict):
            res_obj = resp.get("result", {})
            val_obj = res_obj.get("result", {})
            return val_obj.get("value")
        return None

    def acquire_session_from_browser(self, user_id: str) -> Optional[Tuple[str, str, str, Optional[float]]]:
        """
        Attempts to acquire an authenticated UPES session bundle from the running browser.
        Extracts access token, refresh token, student UUID, and the idp_session_info SSO cookie.
        Persists the complete session bundle encrypted into SQLite.
        """
        self.last_check_timestamp = time.time()
        if not getattr(config, "UPES_BROWSER_BRIDGE_ENABLED", True):
            self.last_check_status = "bridge_disabled"
            return None

        if not self.is_cdp_available():
            self.last_check_status = "cdp_unavailable"
            return None

        target = self.find_upes_target()
        if not target:
            self.last_check_status = "upes_tab_not_found"
            return None

        ws_url = target.get("webSocketDebuggerUrl")

        # 1. Extract session tokens and student metadata from page storage
        js_extract = """
        (() => {
            try {
                let jwtRaw = null;
                let studentRaw = null;
                let refreshTokenRaw = null;

                const scan = (store) => {
                    if (!store) return;
                    for (let i = 0; i < store.length; i++) {
                        const k = store.key(i);
                        const v = store.getItem(k);
                        if (!v) continue;
                        try {
                            const p = JSON.parse(v);
                            if (p && typeof p === 'object') {
                                if (p.Identity && p.Identity.AccessToken) {
                                    jwtRaw = v;
                                    if (p.Identity.RefreshToken) refreshTokenRaw = p.Identity.RefreshToken;
                                } else if (p.access_token) {
                                    jwtRaw = v;
                                    if (p.refresh_token) refreshTokenRaw = p.refresh_token;
                                }
                                if (p.StudentId) studentRaw = p.StudentId;
                                else if (p.StudentCode) studentRaw = p.StudentCode;
                            }
                        } catch(e) {}
                        if (!jwtRaw && (k === 'tyX72z6Su' || (v && v.startsWith('eyJ') && v.includes('.')))) {
                            jwtRaw = v;
                        }
                        if (!studentRaw && (k === 'eseiYEpHnSfrsJ' || k.startsWith('eseiYEpHnSfrsJ'))) {
                            studentRaw = v;
                        }
                    }
                };

                scan(sessionStorage);
                scan(localStorage);

                return JSON.stringify({ jwt: jwtRaw, student: studentRaw, refresh: refreshTokenRaw });
            } catch (e) {
                return JSON.stringify({ error: e.toString() });
            }
        })()
        """
        eval_result = self.evaluate_in_target(target, js_extract)
        if not eval_result:
            self.last_check_status = "session_eval_failed"
            return None

        try:
            data = json.loads(eval_result) if isinstance(eval_result, str) else eval_result
        except Exception:
            self.last_check_status = "invalid_eval_json"
            return None

        if not isinstance(data, dict):
            self.last_check_status = "invalid_eval_data"
            return None

        jwt_raw = data.get("jwt")
        if not jwt_raw:
            self.last_check_status = "no_jwt_in_session"
            return None

        access_token = None
        refresh_token = data.get("refresh")
        if isinstance(jwt_raw, str):
            try:
                jwt_obj = json.loads(jwt_raw)
                if isinstance(jwt_obj, dict):
                    access_token = jwt_obj.get("Identity", {}).get("AccessToken") or jwt_obj.get("access_token")
                    if not refresh_token:
                        refresh_token = jwt_obj.get("Identity", {}).get("RefreshToken") or jwt_obj.get("refresh_token")
            except Exception:
                access_token = jwt_raw.strip()
        elif isinstance(jwt_raw, dict):
            access_token = jwt_raw.get("Identity", {}).get("AccessToken") or jwt_raw.get("access_token")
            if not refresh_token:
                refresh_token = jwt_raw.get("Identity", {}).get("RefreshToken") or jwt_raw.get("refresh_token")

        if not access_token:
            self.last_check_status = "access_token_missing"
            return None

        # Extract student UUID
        student_code = None
        student_raw = data.get("student")
        if student_raw:
            try:
                st_obj = json.loads(student_raw) if isinstance(student_raw, str) else student_raw
                if isinstance(st_obj, dict):
                    student_code = st_obj.get("StudentCode") or st_obj.get("StudentUniqueId") or st_obj.get("student_uuid")
            except Exception:
                student_code = str(student_raw).strip()

        if not student_code:
            existing = self.service.get_full_upes_session(user_id)
            if existing and existing.get("student_code"):
                student_code = existing["student_code"]
            elif getattr(config, "UPES_STUDENT_CODE", None):
                student_code = config.UPES_STUDENT_CODE

        if not student_code:
            self.last_check_status = "student_code_unresolved"
            return None

        expires_at = decode_jwt_expiration(access_token)
        now = time.time()
        if expires_at and now >= (expires_at - 300) and not refresh_token:
            self.last_check_status = "browser_session_expired"
            return None

        # 2. Extract ONLY required idp_session_info cookie via CDP
        cookies_dict = None
        cookie_expires_at = None
        if ws_url:
            cookie_cmd_resp = cdp_websocket_command(ws_url, "Network.getCookies", {"urls": ["https://myupes-beta.upes.ac.in"]}, timeout=self.timeout)
            if cookie_cmd_resp and isinstance(cookie_cmd_resp, dict):
                c_list = cookie_cmd_resp.get("result", {}).get("cookies", [])
                for c in c_list:
                    if c.get("name") == "idp_session_info":
                        cookies_dict = {"idp_session_info": c.get("value")}
                        exp = c.get("expires", 0)
                        cookie_expires_at = exp if exp > 0 else None
                        break

        # 3. Persist newly acquired session bundle encrypted via AES-GCM
        self.service.save_upes_session(
            user_id=user_id,
            access_token=access_token,
            student_code=student_code,
            api_url=config.UPES_TIMETABLE_API_URL,
            expires_at=expires_at,
            refresh_token=refresh_token,
            cookies=cookies_dict,
            cookie_expires_at=cookie_expires_at,
            credential_generation=1,
            last_refresh_at=now,
            last_refresh_status="browser_acquired"
        )

        self.last_check_status = "acquired_successfully"
        return access_token, student_code, config.UPES_TIMETABLE_API_URL, expires_at


class UpesSessionBroker:
    """
    Session Broker abstraction for UPES Portal.
    Coordinates between encrypted stored sessions, headless token refresh,
    and UpesBrowserSessionBridge fallback. Implements robust crash-recovery journal protection.
    """

    def __init__(self, timetable_service: 'TimetableService'):
        self.service = timetable_service
        self.browser_bridge = UpesBrowserSessionBridge(timetable_service)

    def get_session_status(self, user_id: str) -> Dict[str, Any]:
        """Returns comprehensive non-sensitive session health status, generation, and TTLs."""
        # Recover uncommitted journal if present
        UpesSessionJournal.recover_and_replay_journal(self.service, user_id)

        full = self.service.get_full_upes_session(user_id)
        browser_avail = self.browser_bridge.is_cdp_available()
        browser_tab = self.browser_bridge.find_upes_target() is not None if browser_avail else False

        if not full or not full.get("access_token"):
            return {
                "configured": False,
                "status": "not_configured",
                "auth_status": "NOT_CONFIGURED",
                "access_token_available": False,
                "access_token_expires_at": None,
                "access_token_ttl_seconds": 0,
                "expires_at": None,
                "ttl_seconds": 0,
                "refresh_token_available": False,
                "sso_cookie_available": False,
                "sso_cookie_expires_at": None,
                "sso_cookie_ttl_seconds": 0,
                "credential_generation": 0,
                "last_refresh_at": None,
                "last_refresh_status": None,
                "browser_bridge_available": browser_avail,
                "browser_available": browser_avail,
                "browser_authenticated": browser_tab,
                "student_code_masked": None,
                "last_bridge_status": self.browser_bridge.last_check_status
            }

        now = time.time()
        expires_at = full.get("expires_at")
        access_ttl = max(0, int(expires_at - now)) if expires_at else None
        is_access_valid = (expires_at is None or now < (expires_at - 300))

        has_refresh = bool(full.get("refresh_token"))
        cookies = full.get("cookies") or {}
        has_cookie = bool(cookies.get("idp_session_info"))
        cookie_exp = full.get("cookie_expires_at")
        cookie_ttl = max(0, int(cookie_exp - now)) if cookie_exp else 0
        is_cookie_valid = (cookie_exp is None or now < (cookie_exp - 60))

        if is_access_valid:
            auth_status = "ACTIVE"
        elif has_refresh and has_cookie and is_cookie_valid:
            auth_status = "REFRESH_AVAILABLE"
        elif browser_tab:
            auth_status = "REACQUISITION_AVAILABLE"
        else:
            auth_status = "AUTH_REQUIRED"

        student_code = full.get("student_code", "")
        masked_student = (student_code[:3] + "***") if len(student_code) > 4 else "***"

        return {
            "configured": True,
            "status": "active" if (expires_at is None or now < expires_at) else "expired",
            "auth_status": auth_status,
            "access_token_available": bool(full.get("access_token")),
            "access_token_expires_at": expires_at,
            "access_token_ttl_seconds": access_ttl or 0,
            "expires_at": expires_at,
            "ttl_seconds": access_ttl,
            "refresh_token_available": has_refresh,
            "sso_cookie_available": has_cookie,
            "sso_cookie_expires_at": cookie_exp,
            "sso_cookie_ttl_seconds": cookie_ttl,
            "credential_generation": full.get("credential_generation", 1),
            "last_refresh_at": full.get("last_refresh_at"),
            "last_refresh_status": full.get("last_refresh_status"),
            "browser_bridge_available": browser_avail,
            "browser_available": browser_avail,
            "browser_authenticated": browser_tab,
            "student_code_masked": masked_student,
            "last_bridge_status": self.browser_bridge.last_check_status
        }

    def refresh_upes_session_headless(self, user_id: str) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """
        Executes unattended headless token refresh against UPES SSO gateway using the persisted
        encrypted refresh token and idp_session_info cookie.
        Guarantees single-use token rotation persistence and write-ahead recovery journal protection.
        """
        UpesSessionJournal.recover_and_replay_journal(self.service, user_id)

        full_session = self.service.get_full_upes_session(user_id)
        if not full_session or not full_session.get("access_token"):
            return False, "no_session", None

        refresh_token = full_session.get("refresh_token")
        cookies = full_session.get("cookies") or {}
        cookie_val = cookies.get("idp_session_info")
        cookie_expires_at = full_session.get("cookie_expires_at")
        student_code = full_session.get("student_code", "")
        api_url = full_session.get("api_url") or config.UPES_TIMETABLE_API_URL
        current_gen = full_session.get("credential_generation", 1)

        if not refresh_token:
            return False, "refresh_unavailable_no_refresh_token", None

        if not cookie_val:
            return False, "refresh_unavailable_no_sso_cookie", None

        now = time.time()
        if cookie_expires_at is not None and now >= (cookie_expires_at - 60):
            return False, "sso_cookie_expired", None

        refresh_url = f"https://myupes-beta.upes.ac.in/sso/user/oauth2/refresh-token?q={secrets.token_hex(10)}"
        client_secret = getattr(config, "UPES_CLIENT_SECRET", "ku7GUMtyT8er51rTfTc7HC")
        client_id = getattr(config, "UPES_CLIENT_ID", 3)

        payload = {
            "ClientId": client_id,
            "ClientSecret": client_secret,
            "RefreshToken": refresh_token
        }
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/plain, */*"
        }
        req_cookies = {
            "idp_session_info": cookie_val
        }

        try:
            resp = requests.post(refresh_url, json=payload, headers=headers, cookies=req_cookies, timeout=15)
        except Exception as e:
            logger.warning(f"[AUTH_REFRESH] Headless refresh network error: {e}")
            return False, f"network_error: {str(e)}", None

        if resp.status_code != 200:
            logger.warning(f"[AUTH_REFRESH] Headless refresh HTTP {resp.status_code}")
            return False, f"http_{resp.status_code}", None

        try:
            resp_data = resp.json()
        except Exception:
            return False, "invalid_json_response", None

        payload_status = resp_data.get("StatusCode")
        if payload_status != 200:
            msg = resp_data.get("Message", "failed to refresh token")
            logger.warning(f"[AUTH_REFRESH] Headless refresh rejected by server (StatusCode={payload_status}): {msg}")
            return False, f"rejected_{payload_status}: {msg}", None

        token_info = (resp_data.get("Item") or {}).get("tokenInfo") or {}
        new_access = token_info.get("accessToken")
        new_refresh = token_info.get("refreshToken")

        if not new_access or not new_refresh:
            return False, "missing_tokens_in_response", None

        new_expires_at = decode_jwt_expiration(new_access)
        new_gen = current_gen + 1

        new_bundle = {
            "access_token": new_access,
            "student_code": student_code,
            "api_url": api_url,
            "expires_at": new_expires_at,
            "refresh_token": new_refresh,
            "cookies": {"idp_session_info": cookie_val},
            "cookie_expires_at": cookie_expires_at,
            "credential_generation": new_gen
        }

        # 1. Write-Ahead Journal BEFORE SQLite Commit
        UpesSessionJournal.write_journal(user_id, new_gen, new_bundle)

        # 2. Commit to SQLite
        self.service.save_upes_session(
            user_id=user_id,
            access_token=new_access,
            student_code=student_code,
            api_url=api_url,
            expires_at=new_expires_at,
            refresh_token=new_refresh,
            cookies={"idp_session_info": cookie_val},
            cookie_expires_at=cookie_expires_at,
            credential_generation=new_gen,
            last_refresh_at=now,
            last_refresh_status="success"
        )

        # 3. Clean up Journal
        UpesSessionJournal.cleanup_journal()
        logger.info(f"[AUTH_REFRESH] Headless token refresh succeeded (gen {new_gen}) for user '{user_id}'.")

        summary = {
            "status": "success",
            "credential_generation": new_gen,
            "expires_at": new_expires_at,
            "ttl_seconds": max(0, int(new_expires_at - now)) if new_expires_at else 0
        }
        return True, "refreshed_successfully", summary

    def resolve_session(self, user_id: str) -> Tuple[Optional[Tuple[str, str, str, Optional[float]]], Optional[str]]:
        """
        Authoritative state machine resolving UPES authentication for user_id.

        Resolution Flow:
          1. Replay any uncommitted recovery journal
          2. Check stored session:
             - If access token valid (TTL >= 300s or unexpired) -> ACTIVE
             - If access token near expiry or expired:
                 - If refresh_token + unexpired SSO cookie -> Execute headless refresh
                 - If headless refresh succeeds -> ACTIVE
                 - If headless refresh fails -> Fallback to browser bridge
          3. Browser bridge fallback (if local Chrome available) -> ACTIVE
          4. If all fail -> AUTH_REQUIRED
        """
        now = time.time()
        UpesSessionJournal.recover_and_replay_journal(self.service, user_id)

        full = self.service.get_full_upes_session(user_id)
        if full and full.get("access_token"):
            expires_at = full.get("expires_at")
            has_refresh = bool(full.get("refresh_token"))
            cookie_val = (full.get("cookies") or {}).get("idp_session_info")
            cookie_exp = full.get("cookie_expires_at")

            # 1. Active token with safe margin (> 5 mins) or unexpired/opaque token
            if expires_at is None or now < (expires_at - 300):
                return (full["access_token"], full.get("student_code", ""), full.get("api_url") or config.UPES_TIMETABLE_API_URL, expires_at), None

            # 2. JWT near expiry or expired; attempt headless refresh if refresh token and unexpired cookie exist
            if has_refresh and cookie_val and (cookie_exp is None or now < (cookie_exp - 60)):
                success, msg, summary = self.refresh_upes_session_headless(user_id)
                if success:
                    refreshed = self.service.get_full_upes_session(user_id)
                    if refreshed and refreshed.get("access_token"):
                        return (refreshed["access_token"], refreshed.get("student_code", ""), refreshed.get("api_url") or config.UPES_TIMETABLE_API_URL, refreshed.get("expires_at")), None
                logger.info(f"[AUTH_BROKER] Headless refresh attempt ({msg}); attempting browser fallback.")

        # 3. Fallback to browser session bridge if available
        acquired = self.browser_bridge.acquire_session_from_browser(user_id)
        if acquired:
            return acquired, None

        # 4. All resolution paths exhausted
        bridge_hint = self.browser_bridge.last_check_status
        return None, f"auth_required: UPES session expired or unavailable (Bridge: {bridge_hint}). Interactive portal login required."

    def execute_with_retry(self, user_id: str, api_fn: Callable[[str, str], Tuple[Any, Optional[str]]]) -> Tuple[Any, Optional[str]]:
        """
        Executes an authenticated UPES API function with automatic single-retry on 401/auth invalidation.
        """
        session_tuple, err = self.resolve_session(user_id)
        if err or not session_tuple:
            return None, err

        token, student_code, _, _ = session_tuple
        data, err = api_fn(token, student_code)

        if err and "auth_required" in err:
            logger.info(f"[AUTH_BROKER] Received auth_required from API. Attempting single refresh/reacquisition retry...")
            full = self.service.get_full_upes_session(user_id)
            if full and full.get("refresh_token") and (full.get("cookies") or {}).get("idp_session_info"):
                succ, _, _ = self.refresh_upes_session_headless(user_id)
                if not succ:
                    self.browser_bridge.acquire_session_from_browser(user_id)
            else:
                self.browser_bridge.acquire_session_from_browser(user_id)

            session_tuple, err = self.resolve_session(user_id)
            if err or not session_tuple:
                return None, err
            token, student_code, _, _ = session_tuple
            data, err = api_fn(token, student_code)

        return data, err

    def fetch_timetable_json(self, user_id: str) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
        """
        Retrieves raw timetable JSON for a given user from UPES API Gateway.
        Coordinates authentication through resolve_session and execute_with_retry.
        """
        def _call(token, student_code):
            full = self.service.get_full_upes_session(user_id)
            api_url = full.get("api_url") if full else config.UPES_TIMETABLE_API_URL
            return fetch_upes_timetable(token, student_code, api_url)

        return self.execute_with_retry(user_id, _call)


class TimetableService:
    """Service facade connecting storage, OAuth, parsing, synchronizer, and scheduler."""

    def __init__(self, conn_factory):
        self.conn_factory = conn_factory
        self.session_broker = UpesSessionBroker(self)

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

        try:
            with open(config.UPES_TIMETABLE_JSON_PATH, "w", encoding="utf-8") as f:
                f.write(raw_json_str)
        except Exception:
            pass

        return True, "Timetable stored successfully.", len(sessions)

    def save_upes_session(
        self,
        user_id: str,
        access_token: str,
        student_code: str,
        api_url: Optional[str] = None,
        expires_at: Optional[float] = None,
        refresh_token: Optional[str] = None,
        cookies: Optional[Dict[str, Any]] = None,
        cookie_expires_at: Optional[float] = None,
        credential_generation: int = 1,
        last_refresh_at: Optional[float] = None,
        last_refresh_status: Optional[str] = None
    ):
        """Encrypts and persists complete UPES portal session bundle."""
        token_clean = access_token.strip() if access_token else ""
        enc_access = OAuthTokenCrypto.encrypt({"access_token": token_clean})
        enc_refresh = OAuthTokenCrypto.encrypt({"refresh_token": refresh_token.strip()}) if refresh_token else None
        enc_cookies = OAuthTokenCrypto.encrypt(cookies) if cookies else None
        now = time.time()

        if expires_at is None and token_clean:
            expires_at = decode_jwt_expiration(token_clean)

        conn = self.conn_factory()
        try:
            conn.execute("""
                INSERT OR REPLACE INTO upes_auth_sessions
                (user_id, encrypted_access_token, student_code, api_url, expires_at,
                 encrypted_refresh_token, encrypted_cookies, cookie_expires_at,
                 credential_generation, last_refresh_at, last_refresh_status,
                 created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        COALESCE((SELECT created_at FROM upes_auth_sessions WHERE user_id = ?), ?), ?)
            """, (
                user_id, enc_access, student_code.strip() if student_code else "", api_url, expires_at,
                enc_refresh, enc_cookies, cookie_expires_at,
                credential_generation, last_refresh_at, last_refresh_status,
                user_id, now, now
            ))
            conn.commit()
        finally:
            conn.close()

    def get_full_upes_session(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves and decrypts complete UPES session bundle without leaking credentials."""
        conn = self.conn_factory()
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT encrypted_access_token, student_code, api_url, expires_at,
                       encrypted_refresh_token, encrypted_cookies, cookie_expires_at,
                       credential_generation, last_refresh_at, last_refresh_status,
                       created_at, updated_at
                FROM upes_auth_sessions WHERE user_id = ?
            """, (user_id,))
            row = cur.fetchone()
            if not row:
                return None

            access_data = OAuthTokenCrypto.decrypt(row[0]) if row[0] else None
            access_token = access_data.get("access_token") if access_data else None

            refresh_data = OAuthTokenCrypto.decrypt(row[4]) if row[4] else None
            refresh_token = refresh_data.get("refresh_token") if refresh_data else None

            cookies_data = OAuthTokenCrypto.decrypt(row[5]) if row[5] else None
            cookies = cookies_data if isinstance(cookies_data, dict) else None

            return {
                "user_id": user_id,
                "access_token": access_token,
                "student_code": row[1] or "",
                "api_url": row[2] or config.UPES_TIMETABLE_API_URL,
                "expires_at": row[3],
                "refresh_token": refresh_token,
                "cookies": cookies,
                "cookie_expires_at": row[6],
                "credential_generation": row[7] or 1,
                "last_refresh_at": row[8],
                "last_refresh_status": row[9],
                "created_at": row[10],
                "updated_at": row[11]
            }
        finally:
            conn.close()

    def get_upes_session(self, user_id: str) -> Optional[Tuple[str, str, str, Optional[float]]]:
        """Backwards-compatible accessor returning (access_token, student_code, api_url, expires_at)."""
        full = self.get_full_upes_session(user_id)
        if full and full.get("access_token"):
            return full["access_token"], full["student_code"], full["api_url"], full["expires_at"]

        # Fallback to config environment variables if configured
        if config.UPES_ACCESS_TOKEN and config.UPES_STUDENT_CODE:
            exp = decode_jwt_expiration(config.UPES_ACCESS_TOKEN)
            return config.UPES_ACCESS_TOKEN, config.UPES_STUDENT_CODE, config.UPES_TIMETABLE_API_URL, exp

        return None

    def delete_upes_session(self, user_id: str) -> bool:
        """Removes stored UPES portal session credentials and recovery journal."""
        UpesSessionJournal.cleanup_journal()
        conn = self.conn_factory()
        try:
            conn.execute("DELETE FROM upes_auth_sessions WHERE user_id = ?", (user_id,))
            conn.commit()
            return True
        finally:
            conn.close()

    def fetch_and_store_upes_timetable(self, user_id: str) -> Tuple[bool, str, int]:
        """
        Fetches live timetable from UPES API using stored session, validates, and updates local database.
        Returns (success: bool, message: str, count: int).
        """
        raw_items, err = self.session_broker.fetch_timetable_json(user_id)
        now = time.time()

        if err or raw_items is None:
            conn = self.conn_factory()
            status_label = "auth_required" if "auth_required" in (err or "") else "fetch_failed"
            try:
                conn.execute("""
                    INSERT INTO timetable_sync_history
                    (id, user_id, timestamp, sessions_seen, created_count, updated_count, deleted_count, unchanged_count, error_count, status, details)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    f"upes_fetch_{int(now)}_{secrets.token_hex(4)}",
                    user_id, now, 0, 0, 0, 0, 0, 1, status_label,
                    json.dumps({"error": err or "Failed to fetch from UPES API"})
                ))
                conn.commit()
            finally:
                conn.close()
            return False, f"UPES Fetch Failed: {err}", 0

        # Validate that sessions parse correctly
        sessions, parse_errs = parse_timetable_json(raw_items)
        if not sessions and parse_errs:
            return False, f"Malformed UPES Timetable Data: {'; '.join(parse_errs)}", 0

        if not sessions:
            return False, "UPES API returned empty timetable payload; preserved existing schedule.", 0

        # Persist the newly fetched raw JSON
        raw_json_str = json.dumps(raw_items)
        return self.upload_timetable(user_id, raw_json_str)

    def load_timetable_sessions(self, user_id: str, rolling_two_weeks: bool = True) -> Tuple[List[TimetableSession], List[str]]:
        """
        Loads timetable sessions from user's DB record or vault file fallback.
        When rolling_two_weeks=True (default), filters sessions to the dynamic two-week window
        [current week Monday, next week Sunday] in Asia/Kolkata timezone.
        """
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
            return [], ["No timetable data found. Upload or authenticate UPES timetable first."]

        sessions, errors = parse_timetable_json(raw_json)
        if rolling_two_weeks and sessions:
            w1_start, _, _, w2_end = get_rolling_two_week_window()
            two_week_sessions = filter_sessions_by_window(sessions, w1_start, w2_end)
            return two_week_sessions, errors

        return sessions, errors

    def sync_user_timetable(self, user_id: str, force_calendar_id: Optional[str] = None) -> Dict[str, Any]:
        """Executes full synchronization pipeline for a given user under a lease lock."""
        # 1. Acquire Distributed Lease Lock
        lease = DatabaseSyncLease(self.conn_factory, user_id)
        if not lease.acquire():
            return {
                "status": "locked",
                "message": f"Synchronization already running for user '{user_id}'.",
                "sessions_seen": 0, "created": 0, "updated": 0, "deleted": 0, "unchanged": 0,
                "errors": ["Sync lock active"]
            }

        try:
            # 2. If UPES portal session is configured, attempt live fetch & store
            fetch_msg = ""
            upes_session = self.get_upes_session(user_id)
            if upes_session:
                fetch_success, fetch_msg, _ = self.fetch_and_store_upes_timetable(user_id)

            # 3. Check OAuth connection
            oauth_info = self.get_oauth_tokens(user_id)
            if not oauth_info:
                return {
                    "status": "error",
                    "message": "Google Calendar is not connected. Authorize Google account first.",
                    "sessions_seen": 0, "created": 0, "updated": 0, "deleted": 0, "unchanged": 0,
                    "errors": ["Google account not connected"],
                    "upes_fetch_status": fetch_msg or "UPES session not configured"
                }

            token_data, default_cal_id, email = oauth_info
            calendar_id = force_calendar_id or default_cal_id or "primary"

            # 4. Load Sessions (authoritative local database)
            sessions, load_errs = self.load_timetable_sessions(user_id)
            if not sessions:
                return {
                    "status": "empty",
                    "message": "No valid timetable sessions to synchronize.",
                    "sessions_seen": 0, "created": 0, "updated": 0, "deleted": 0, "unchanged": 0,
                    "errors": load_errs,
                    "upes_fetch_status": fetch_msg
                }

            # 5. Instantiate API Client with callback to update refreshed token
            def on_refresh(u_id, new_tokens):
                self.save_oauth_tokens(u_id, new_tokens, calendar_id, email)

            client = GoogleCalendarClient(token_data, user_id, on_token_refresh=on_refresh)

            # 6. Synchronize with Google Calendar
            synchronizer = TimetableSynchronizer(self.conn_factory, user_id, client, calendar_id)
            result = synchronizer.synchronize(sessions)
            result["connected_email"] = email
            result["calendar_id"] = calendar_id
            result["upes_fetch_status"] = fetch_msg or "OK"
            return result

        finally:
            lease.release()

    def sync_all_active_users(self) -> Dict[str, Any]:
        """Called every 3 hours by SchedulerDaemon to synchronize all users with connected Google accounts or UPES sessions."""
        conn = self.conn_factory()
        users_to_sync = set()
        try:
            cur = conn.cursor()
            cur.execute("SELECT DISTINCT user_id FROM google_oauth_tokens")
            for r in cur.fetchall():
                users_to_sync.add(r[0])
            cur.execute("SELECT DISTINCT user_id FROM upes_auth_sessions")
            for r in cur.fetchall():
                users_to_sync.add(r[0])
            if config.UPES_ACCESS_TOKEN and config.UPES_STUDENT_CODE:
                users_to_sync.add("admin")
        finally:
            conn.close()

        summaries = {}
        for uid in sorted(users_to_sync):
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

        upes_session = self.get_upes_session(user_id)
        upes_configured = upes_session is not None
        student_code_display = ""
        if upes_session and upes_session[1]:
            sc = upes_session[1]
            student_code_display = sc[:3] + "***" if len(sc) > 4 else "***"

        last_sync = None
        last_upes_fetch = None
        conn = self.conn_factory()
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT timestamp, sessions_seen, created_count, updated_count, deleted_count, unchanged_count, error_count, status, details
                FROM timetable_sync_history
                WHERE user_id = ?
                ORDER BY timestamp DESC LIMIT 5
            """, (user_id,))
            rows = cur.fetchall()
            for row in rows:
                if row[7] == "fetch_failed" and not last_upes_fetch:
                    last_upes_fetch = {"timestamp": row[0], "status": "failed"}
                elif row[7] != "fetch_failed" and not last_sync:
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

        broker_status = self.session_broker.get_session_status(user_id)
        bridge = self.session_broker.browser_bridge

        return {
            "upes_configured": upes_configured,
            "auth_status": broker_status.get("auth_status", "NOT_CONFIGURED"),
            "access_token_available": broker_status.get("access_token_available", False),
            "access_token_expires_at": broker_status.get("access_token_expires_at"),
            "access_token_ttl_seconds": broker_status.get("access_token_ttl_seconds", 0),
            "refresh_token_available": broker_status.get("refresh_token_available", False),
            "sso_cookie_available": broker_status.get("sso_cookie_available", False),
            "sso_cookie_expires_at": broker_status.get("sso_cookie_expires_at"),
            "sso_cookie_ttl_seconds": broker_status.get("sso_cookie_ttl_seconds", 0),
            "credential_generation": broker_status.get("credential_generation", 1),
            "last_refresh_at": broker_status.get("last_refresh_at"),
            "last_refresh_status": broker_status.get("last_refresh_status"),
            "browser_available": broker_status.get("browser_bridge_available", False),
            "browser_authenticated": broker_status.get("browser_authenticated", False),
            "authorization_available": broker_status.get("auth_status") in ("ACTIVE", "REFRESH_AVAILABLE"),
            "authorization_expires_at": broker_status.get("access_token_expires_at"),
            "authorization_ttl_seconds": broker_status.get("access_token_ttl_seconds"),
            "upes_token_expires_at": broker_status.get("access_token_expires_at"),
            "upes_token_expired": broker_status.get("auth_status") not in ("ACTIVE", "REFRESH_AVAILABLE"),
            "upes_token_ttl_seconds": broker_status.get("access_token_ttl_seconds"),
            "last_browser_session_check": bridge.last_check_timestamp,
            "last_bridge_status": bridge.last_check_status,
            "upes_student_code_masked": student_code_display,
            "upes_api_url": config.UPES_TIMETABLE_API_URL,
            "google_connected": is_connected,
            "connected_email": connected_email,
            "google_email": connected_email,
            "calendar_id": calendar_id,
            "google_calendar_id": calendar_id,
            "sync_interval_seconds": interval_seconds,
            "sync_enabled": enabled,
            "scheduled_enabled": enabled,
            "next_sync_run": next_run,
            "next_scheduled_run": next_run,
            "last_sync": last_sync,
            "last_upes_fetch": last_upes_fetch
        }

    def record_punch(
        self,
        user_id: str,
        course_name: str,
        course_code: str,
        punch_date: str,
        punch_time: str,
        status: str = "present",
        room: str = "",
        session_id: str = "",
        notes: str = ""
    ) -> Dict[str, Any]:
        """Records or updates an attendance punch for a user session."""
        punch_id = f"pnch_{secrets.token_hex(8)}"
        now = time.time()
        conn = self.conn_factory()
        try:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO attendance_punches (
                    id, user_id, session_id, course_name, course_code,
                    punch_date, punch_time, status, room, notes, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, course_code, punch_date, punch_time) DO UPDATE SET
                    status = excluded.status,
                    notes = excluded.notes,
                    room = excluded.room,
                    updated_at = excluded.updated_at
            """, (
                punch_id, user_id, session_id, course_name, course_code,
                punch_date, punch_time, status, room, notes, now, now
            ))
            conn.commit()
            return {
                "id": punch_id,
                "user_id": user_id,
                "course_name": course_name,
                "course_code": course_code,
                "punch_date": punch_date,
                "punch_time": punch_time,
                "status": status,
                "room": room,
                "notes": notes,
                "updated_at": now
            }
        finally:
            conn.close()

    def get_punches(
        self,
        user_id: str,
        course_code: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        limit: int = 200
    ) -> List[Dict[str, Any]]:
        """Retrieves recorded attendance punches ordered by date and time descending."""
        conn = self.conn_factory()
        try:
            cur = conn.cursor()
            query = "SELECT id, user_id, session_id, course_name, course_code, punch_date, punch_time, status, room, notes, created_at, updated_at FROM attendance_punches WHERE user_id = ?"
            params = [user_id]
            if course_code:
                query += " AND course_code = ?"
                params.append(course_code)
            if date_from:
                query += " AND punch_date >= ?"
                params.append(date_from)
            if date_to:
                query += " AND punch_date <= ?"
                params.append(date_to)
            query += " ORDER BY punch_date DESC, punch_time DESC LIMIT ?"
            params.append(limit)

            cur.execute(query, params)
            rows = cur.fetchall()
            return [
                {
                    "id": r[0],
                    "user_id": r[1],
                    "session_id": r[2],
                    "course_name": r[3],
                    "course_code": r[4],
                    "punch_date": r[5],
                    "punch_time": r[6],
                    "status": r[7],
                    "room": r[8],
                    "notes": r[9],
                    "created_at": r[10],
                    "updated_at": r[11]
                }
                for r in rows
            ]
        finally:
            conn.close()

    def delete_punch(self, user_id: str, punch_id: str) -> bool:
        """Deletes an attendance punch record."""
        conn = self.conn_factory()
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM attendance_punches WHERE id = ? AND user_id = ?", (punch_id, user_id))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def get_attendance_analytics(self, user_id: str, ref_datetime: Optional[datetime.datetime] = None) -> Dict[str, Any]:
        """
        Computes detailed attendance metrics, 75% bunk calculations, and today's schedule for user.
        Uses full semester scheduled sessions (384 slots) and actual punch logs.
        """
        tz_name = config.TIMETABLE_TIMEZONE
        try:
            tz = zoneinfo.ZoneInfo(tz_name)
            now_dt = ref_datetime if ref_datetime else datetime.datetime.now(tz)
        except Exception:
            ist = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
            now_dt = ref_datetime if ref_datetime else datetime.datetime.now(ist)

        today_str = now_dt.strftime("%Y-%m-%d")
        now_time_str = now_dt.strftime("%H:%M:%S")

        # 1. Load all semester sessions (384 sessions)
        all_sessions, _ = self.load_timetable_sessions(user_id, rolling_two_weeks=False)

        # 2. Query all punches for user
        punches = self.get_punches(user_id, limit=2000)
        punch_map = {}
        for p in punches:
            punch_map[f"{p['course_code']}:{p['punch_date']}"] = p
            if p.get("session_id"):
                punch_map[f"{p['session_id']}:{p['punch_date']}"] = p

        # 3. Group sessions by course
        courses_dict: Dict[str, Dict[str, Any]] = {}
        for s in all_sessions:
            c_key = s.course_code or s.course_name
            if c_key not in courses_dict:
                courses_dict[c_key] = {
                    "course_code": s.course_code,
                    "course_name": s.course_name,
                    "faculty": s.faculty,
                    "room": s.room,
                    "sessions": []
                }
            courses_dict[c_key]["sessions"].append(s)

        # 4. Compute per-course metrics
        subject_reports = []
        overall_total = 0
        overall_conducted = 0
        overall_attended = 0
        overall_safe_bunks = 0
        critical_count = 0

        for c_key, c_info in sorted(courses_dict.items(), key=lambda x: x[1]["course_name"]):
            sess_list = c_info["sessions"]
            sess_list.sort(key=lambda s: (s.date, s.start_time))

            total_classes = len(sess_list)
            conducted_classes = 0
            remaining_classes = 0
            attended_classes = 0
            next_session = None

            for s in sess_list:
                is_past = False
                if s.date < today_str:
                    is_past = True
                elif s.date == today_str and s.start_time <= now_time_str:
                    is_past = True

                if is_past:
                    conducted_classes += 1
                    p_entry = punch_map.get(f"{s.course_code}:{s.date}") or punch_map.get(f"{s.session_id}:{s.date}")
                    if p_entry and p_entry["status"] == "present":
                        attended_classes += 1
                else:
                    remaining_classes += 1
                    if not next_session:
                        next_session = {
                            "date": s.date,
                            "start_time": s.start_time,
                            "end_time": s.end_time,
                            "room": s.room,
                            "meeting_link": getattr(s, "meeting_link", ""),
                            "faculty": s.faculty
                        }

            # Attendance percentage
            if conducted_classes > 0:
                pct = round((attended_classes / conducted_classes) * 100.0, 1)
            else:
                pct = 100.0

            # 75% Bunk calculation across the entire semester
            max_allowed_absences = math.floor(0.25 * total_classes)
            current_absences = max(0, conducted_classes - attended_classes)
            safe_bunks_remaining = max(0, max_allowed_absences - current_absences)

            # Classes needed to recover to 75% if currently below 75%
            catchup_needed = 0
            if pct < 75.0 and conducted_classes > 0:
                catchup_needed = max(0, math.ceil(3 * conducted_classes - 4 * attended_classes))

            status_badge = "safe"
            if pct < 75.0:
                status_badge = "critical"
                critical_count += 1
            elif pct < 80.0:
                status_badge = "warning"

            overall_total += total_classes
            overall_conducted += conducted_classes
            overall_attended += attended_classes
            overall_safe_bunks += safe_bunks_remaining

            subject_reports.append({
                "course_code": c_info["course_code"],
                "course_name": c_info["course_name"],
                "faculty": c_info["faculty"],
                "room": c_info["room"],
                "total_classes": total_classes,
                "conducted_classes": conducted_classes,
                "remaining_classes": remaining_classes,
                "attended_classes": attended_classes,
                "missed_classes": current_absences,
                "attendance_percentage": pct,
                "safe_bunks_remaining": safe_bunks_remaining,
                "max_allowed_absences": max_allowed_absences,
                "catchup_needed": catchup_needed,
                "status": status_badge,
                "next_session": next_session
            })

        # 5. Today's classes
        today_classes = []
        for s in all_sessions:
            if s.date == today_str:
                p_entry = punch_map.get(f"{s.course_code}:{s.date}") or punch_map.get(f"{s.session_id}:{s.date}")
                today_classes.append({
                    "session_id": s.session_id,
                    "course_name": s.course_name,
                    "course_code": s.course_code,
                    "start_time": s.start_time,
                    "end_time": s.end_time,
                    "room": s.room,
                    "faculty": s.faculty,
                    "meeting_link": getattr(s, "meeting_link", ""),
                    "is_online": getattr(s, "is_online", False),
                    "punched": p_entry is not None,
                    "punch_status": p_entry["status"] if p_entry else None,
                    "punch_id": p_entry["id"] if p_entry else None,
                    "punch_time": p_entry["punch_time"] if p_entry else None
                })
        today_classes.sort(key=lambda x: x["start_time"])

        overall_pct = round((overall_attended / overall_conducted) * 100.0, 1) if overall_conducted > 0 else 100.0

        return {
            "user_id": user_id,
            "as_of_date": today_str,
            "as_of_time": now_time_str,
            "overall": {
                "total_classes": overall_total,
                "conducted_classes": overall_conducted,
                "attended_classes": overall_attended,
                "missed_classes": max(0, overall_conducted - overall_attended),
                "attendance_percentage": overall_pct,
                "total_safe_bunks": overall_safe_bunks,
                "critical_subjects": critical_count,
                "total_subjects": len(subject_reports)
            },
            "subjects": subject_reports,
            "today_classes": today_classes,
            "recent_punches": punches[:50]
        }
