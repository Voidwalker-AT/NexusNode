# 05. Configuration Reference

**Status:** VERIFIED CURRENT  
**Scope:** Central Application & Environment Configuration Dictionary  
**Last verified:** 2026-09-20  
**Evidence basis:** [`config.py`](file:///E:/Workspace/Active/server/config.py), [`.env.example`](file:///E:/Workspace/Active/server/.env.example), live appliance configuration  

---

## 1. Storage & Database Configuration

| Variable Name | Purpose | Default Value | Required? | Secret? | Runtime Changeable? | Source |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `NEXUS_STORAGE_DIR` | Base directory for databases, backups, and user vault storage | `BASE_DIR/storage_vault` | No | No | No | Env / Default |
| `DB_FILE` / `DB_PATH` | Path to the authoritative unified SQLite database | `STORAGE_DIR/nexus_unified.db` | Yes | No | No | Code / Constant |
| `NEXUS_BACKUP_DIR` | Directory where database snapshots and system backups are saved | `STORAGE_DIR/backups` | No | No | No | Env / Default |
| `NEXUS_AGENT_VAULT_ROOT` | Root filesystem directory for isolated tenant vault storage | `STORAGE_DIR/user_files` | No | No | No | Env / Default |
| `NEXUS_RAG_DB_FILE` | SQLite database for FTS5 RAG inverted search index [LEGACY] | `STORAGE_DIR/rag_vault.db` | No | No | No | Env / Default |

> [!IMPORTANT]
> **Authoritative Database Resolution**:
> The production database is strictly `storage_vault/nexus_unified.db`. Any `.db` files located directly in the server root (e.g. `nexus_unified.db`) are development remnants and must not be treated as production state.

---

## 2. Server, Ports & Ingress Configuration

| Variable Name | Purpose | Default Value | Required? | Secret? | Runtime Changeable? | Source |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `NEXUS_PORT` | HTTP port for the Waitress WSGI application | `5000` | No | No | No | Env / Default |
| `NEXUS_HOST` | Network interface binding | `0.0.0.0` | No | No | No | Env / Default |
| `NEXUS_SSH_PORT` | SSH port for Termux administration | `8022` | No | No | No | Env / Default |
| `LOCALTONET_URL` | Public HTTPS tunnel endpoint assigned by LocalToNet | `https://k09oezeyib.localto.net` | No | No | Yes | Env / Live Probe |

---

## 3. Security, Authentication & Session Configuration

| Variable Name | Purpose | Default Value | Required? | Secret? | Runtime Changeable? | Source |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `NEXUS_SECRET_KEY` | Master cryptographic key for session signing and credential encryption | Auto-generated in `.nexus_secret` | Yes | **YES** | No | Env / Secret File |
| `NEXUS_SESSION_TTL` | Web session token lifetime in seconds | `604800` (7 days) | No | No | Yes | Env / Default |
| `NEXUS_LOCKOUT_THRESHOLD` | Max consecutive failed login attempts before IP/user lockout | `5` | No | No | Yes | Env / Default |
| `NEXUS_LOCKOUT_DURATION` | Account and IP lockout duration in seconds | `600` (10 minutes) | No | No | Yes | Env / Default |
| `NEXUS_PASSWORD_KDF_ITERATIONS` | PBKDF2-HMAC-SHA256 iteration count for password verification | `100000` | No | No | No | Env / Default |

---

## 4. Model Context Protocol (MCP) Configuration

| Variable Name | Purpose | Default Value | Required? | Secret? | Runtime Changeable? | Source |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `NEXUS_MCP_ENABLED` | Master feature toggle for the external MCP gateway | `true` | No | No | Yes | Env / Default |
| `MCP_CATALOG_MODE` | Active external tool catalog mode (`semantic` \| `legacy`) | `semantic` | No | No | Yes | Env / Default |
| `MCP_CATALOG_VERSION` | Identifier for the semantic tool catalog schema | `nexus-semantic-v1` | No | No | No | Code / Constant |
| `NEXUS_MCP_RATE_LIMIT` | Global requests-per-minute limit per authenticated MCP client | `60` | No | No | Yes | Env / Default |
| `NEXUS_MCP_TIMEOUT_DEFAULT` | Default timeout in seconds for executing an individual MCP tool | `15.0` | No | No | Yes | Env / Default |
| `MCP_PROTOCOL_VERSION` | Authoritative protocol version string negotiated with clients | `2026-07-28` | Yes | No | No | Code / Constant |
| `MCP_SUPPORTED_PROTOCOL_VERSIONS` | List of supported backwards-compatible protocol versions | `["2026-07-28", "2024-11-05", ...]` | Yes | No | No | Code / Constant |

---

## 5. Hardware Memory Governor & Admission Thresholds

| Variable Name | Purpose | Default Value | Required? | Secret? | Runtime Changeable? | Source |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `NEXUS_RAM_NORMAL_MB` | System `MemAvailable` floor for normal, unthrottled operations | `1000` MB | No | No | Yes | Env / Default |
| `NEXUS_RAM_PRESSURE_MB` | System `MemAvailable` threshold triggering task throttling | `600` MB | No | No | Yes | Env / Default |
| `NEXUS_BROWSER_LOCAL_MIN_RAM_MB` | Minimum `MemAvailable` required to admit an ephemeral Chromium launch | `500` MB | Yes | No | Yes | Env / Default |
| `NEXUS_MAX_HEAVY_CONCURRENCY` | Maximum concurrent heavy background tasks permitted | `1` | Yes | No | No | Env / Default |
| `NEXUS_THERMAL_WARM_C` | Battery temperature threshold for logging thermal warnings | `42` °C | No | No | Yes | Env / Default |
| `NEXUS_THERMAL_CRITICAL_C` | Battery temperature threshold triggering automated task pause | `55` °C | No | No | Yes | Env / Default |

---

## 6. Academic Engine & UPES Integration Configuration

| Variable Name | Purpose | Default Value | Required? | Secret? | Runtime Changeable? | Source |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `TIMETABLE_SYNC_INTERVAL_SECONDS` | Interval between automated timetable synchronization passes | `10800` (3 hours) | No | No | Yes | Env / Default |
| `TIMETABLE_TIMEZONE` | Timezone for parsing and reconciling academic timestamps | `Asia/Kolkata` | No | No | No | Env / Default |
| `UPES_TIMETABLE_API_URL` | Upstream endpoint for fetching student schedule JSON | `https://myupes-beta.upes.ac.in/apigateway/api/timetable` | Yes | No | No | Env / Default |
| `UPES_SSO_LOGIN_URL` | Upstream WebSSO OAuth2 token endpoint | `https://myupes-beta.upes.ac.in/sso/api/account/oauth2/token` | Yes | No | No | Env / Default |
| `UPES_SSO_CLIENT_ID` | Client ID for UPES OAuth2 token exchange | `3` | Yes | No | No | Code / Env |
| `UPES_SSO_CLIENT_SECRET` | Client secret for UPES OAuth2 token exchange | `[REDACTED_CLIENT_SECRET]` | Yes | **YES** | No | Code / Env |
| `UPES_REQUEST_TIMEOUT_SECONDS` | Network timeout for upstream UPES HTTP requests | `20` seconds | No | No | Yes | Env / Default |
| `TIMETABLE_LOCK_TIMEOUT_SECONDS`| Mutex timeout for timetable synchronization passes | `300` seconds | No | No | No | Env / Default |

---

## 7. Google Calendar Integration Configuration

| Variable Name | Purpose | Default Value | Required? | Secret? | Runtime Changeable? | Source |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `GOOGLE_CLIENT_ID` | GCP OAuth 2.0 Client ID for appliance Google Calendar sync | `[REDACTED_CLIENT_ID]` | Yes | No | Yes (DB/Env) | Env / DB App Config |
| `GOOGLE_CLIENT_SECRET` | GCP OAuth 2.0 Client Secret | `[REDACTED_CLIENT_SECRET]` | Yes | **YES** | Yes (DB/Env) | Env / DB App Config |
| `GOOGLE_REDIRECT_URI` | OAuth 2.0 callback URL registered in GCP Console | `http://localhost:5000/api/auth/google/callback` | Yes | No | Yes | Env / DB App Config |
| `GOOGLE_CALENDAR_SCOPE` | OAuth scopes requested for managing student class events | `https://www.googleapis.com/auth/calendar.events` | Yes | No | No | Code / Constant |

---

## 8. Ephemeral Browser Runtime Configuration

| Variable Name | Purpose | Default Value | Required? | Secret? | Runtime Changeable? | Source |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `CHROME_CDP_HOST` | Loopback host where Chromium exposes Chrome DevTools Protocol | `127.0.0.1` | Yes | No | No | Code / Env |
| `CHROME_CDP_PORT` | Remote debugging port for Chromium CDP socket | `9222` | Yes | No | No | Code / Env |
| `UPES_CDP_TIMEOUT_SECONDS` | Maximum wait time for CDP socket readiness after launch | `5` seconds | No | No | Yes | Env / Default |
| `UPES_BROWSER_BRIDGE_ENABLED` | Feature flag allowing fallback to headless browser | `true` | No | No | Yes | Env / Default |
| `NEXUS_TASK_TIMEOUT` | Hard watchdog kill timeout for ephemeral browser executions | `30` seconds | Yes | No | Yes | Env / Default |

---

## 9. Legacy / Deprecated Configuration (Cataloged for Phase 4.2B Audit)

The following settings remain in `config.py` for backward compatibility with older test suites but are **inactive in production**:
- `NEXUS_OLLAMA_PORT` / `OLLAMA_HOST`: Inactive. Local Ollama is decommissioned (ADR-002).
- `NEXUS_OLLAMA_AUTO_START` / `NEXUS_OLLAMA_AUTO_RESTART`: Inactive. Defaults to `false`.
- `NEXUS_CTX_NORMAL` / `NEXUS_CTX_PRESSURE` / `NEXUS_CTX_CRITICAL`: Inactive. Used by legacy Ollama model loader.
- `NEXUS_PINCHTAB_ENABLED` / `NEXUS_PINCHTAB_URL`: Inactive. Windows PinchTab is replaced by on-device Chromium (ADR-001).
