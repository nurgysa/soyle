"""Google Drive sync of dictionary.toml — Phase 1.

This module owns:
- OAuth 2.0 PKCE flow (no client_secret in distributable binary)
- Drive REST calls (httpx, no google-api-python-client dependency)
- Refresh token storage via keyring (Windows Credential Manager)
- Daily-cadence scheduled sync coordination

See docs/superpowers/specs/2026-04-30-cloud-sync-design.md for the
design rationale, locked decisions, and error-handling matrix.
"""
from __future__ import annotations

import base64
import contextlib
import enum
import hashlib
import json
import secrets
import socketserver
import threading
import tomllib
import uuid
import webbrowser
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler
from queue import Empty, Queue
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
import keyring
import keyring.errors
import structlog
import tomli_w

from soyle.core.config import ConfigStore
from soyle.core.dictionary import DictionaryStore
from soyle.core.errors import OAuthAuthRevokedError

# ---- PKCE helpers (RFC 7636) ------------------------------------------------

def _generate_code_verifier() -> str:
    """Cryptographically random PKCE code_verifier.

    Returns a 43-128 char URL-safe string per RFC 7636 §4.1. We pick 64
    bytes of entropy → ~86 chars after base64url, comfortably in range.
    """
    return secrets.token_urlsafe(64)


def _derive_code_challenge(verifier: str) -> str:
    """PKCE code_challenge for the S256 method.

    challenge = base64url(sha256(verifier)) without trailing '=' padding,
    per RFC 7636 §4.2. Google's token endpoint rejects challenges with
    padding.
    """
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


# ---- OAuth callback listener ------------------------------------------------

_BROWSER_THANK_YOU_PAGE = """\
<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>Söyle — авторизация завершена</title>
<style>
  body { font-family: system-ui, -apple-system, sans-serif; padding: 4em;
         text-align: center; color: #222; }
  h1 { font-weight: 400; }
</style>
</head>
<body>
<h1>Söyle подключён к Google Drive ✓</h1>
<p>Это окно можно закрыть.</p>
</body>
</html>
"""


class _OAuthCallbackListener:
    """Tiny localhost HTTP server that captures the OAuth redirect.

    Lifecycle:
        listener = _OAuthCallbackListener()
        listener.start()             # picks free port, starts thread
        # ... open browser to auth URL using listener.redirect_uri ...
        params = listener.wait_for_callback(timeout=120)
        listener.shutdown()

    Single-shot: serves exactly one /callback request, then waits to be
    shut down. If the browser sends multiple requests (favicon, etc.)
    they're 404'd quickly.
    """

    def __init__(self) -> None:
        self._queue: Queue[dict[str, str]] = Queue(maxsize=1)
        self._server: socketserver.TCPServer | None = None
        self._thread: threading.Thread | None = None
        self.port: int = 0

    @property
    def redirect_uri(self) -> str:
        return f"http://localhost:{self.port}/callback"

    def start(self) -> None:
        listener = self  # for closure

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args: object) -> None:
                pass  # suppress stderr noise

            def do_GET(self) -> None:
                parsed = urlparse(self.path)
                if parsed.path != "/callback":
                    self.send_response(404)
                    self.end_headers()
                    return
                params = {
                    k: v[0] for k, v in parse_qs(parsed.query).items() if v
                }
                # Best-effort enqueue; ignore if duplicate request after first.
                with contextlib.suppress(Exception):
                    listener._queue.put_nowait(params)
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(_BROWSER_THANK_YOU_PAGE.encode("utf-8"))

        # Bind to port 0 → OS assigns a free port above 1024.
        self._server = socketserver.TCPServer(("127.0.0.1", 0), Handler)
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(
            target=self._server.serve_forever, name="soyle-oauth-callback",
            daemon=True,
        )
        self._thread.start()

    def wait_for_callback(self, timeout: float = 120.0) -> dict[str, str]:
        try:
            return self._queue.get(timeout=timeout)
        except Empty:
            raise TimeoutError(
                f"OAuth callback not received within {timeout}s"
            ) from None

    def shutdown(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None


# ---- OAuth token endpoint ---------------------------------------------------

OAUTH_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
OAUTH_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
DRIVE_APPDATA_SCOPE = "https://www.googleapis.com/auth/drive.appdata"

_log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class _TokenPair:
    access_token: str
    refresh_token: str


async def _exchange_code_for_tokens(
    *,
    client_id: str,
    code: str,
    code_verifier: str,
    redirect_uri: str,
) -> _TokenPair:
    """Exchange OAuth auth code for refresh + access tokens. PKCE flow.

    No client_secret is sent — PKCE replaces it with the code_verifier.
    """
    payload = {
        "client_id": client_id,
        "code": code,
        "code_verifier": code_verifier,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(OAUTH_TOKEN_URL, data=payload)
    resp.raise_for_status()
    body = resp.json()
    return _TokenPair(
        access_token=body["access_token"],
        refresh_token=body["refresh_token"],
    )


async def _refresh_access_token(*, client_id: str, refresh_token: str) -> str:
    """Trade a refresh_token for a fresh access_token.

    Raises OAuthAuthRevokedError if Google reports the refresh token is
    no longer valid (user revoked from Google account settings, etc.).
    Other failures (network, 5xx, non-invalid_grant 4xx) propagate as
    httpx exceptions for the caller to handle silently. Non-invalid_grant
    4xx responses are logged with their structured error code so
    misconfigured-client-id incidents (e.g. invalid_client) are
    distinguishable from token-revocation in logs.
    """
    payload = {
        "client_id": client_id,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(OAUTH_TOKEN_URL, data=payload)
    if resp.status_code == 400:
        body = resp.json() if resp.content else {}
        error_code = body.get("error")
        if error_code == "invalid_grant":
            raise OAuthAuthRevokedError(body.get("error_description", "revoked"))
        # Non-revocation 4xx: log structured error before letting httpx raise.
        _log.warning(
            "oauth_token_endpoint_4xx",
            error_code=error_code,
            error_description=body.get("error_description"),
        )
    resp.raise_for_status()
    # resp.json() returns Any (httpx's typing); narrow explicitly so the
    # caller doesn't propagate Any through subsequent f-strings or logs.
    access_token: str = resp.json()["access_token"]
    return access_token


# ---- Refresh-token storage (keyring) ----------------------------------------

KEYRING_SERVICE = "Söyle Cloud"
KEYRING_USERNAME = "google-refresh-token"


class _TokenStore:
    """Thin wrapper around keyring for the OAuth refresh token.

    Encapsulates the (service, username) tuple and the
    PasswordDeleteError-swallowing pattern used for ConfigStore's
    clear_api_key. Mirrors the established Söyle keyring convention —
    one entry per (service, username) pair.
    """

    def load(self) -> str | None:
        return keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME)

    def save(self, refresh_token: str) -> None:
        keyring.set_password(KEYRING_SERVICE, KEYRING_USERNAME, refresh_token)

    def clear(self) -> None:
        with contextlib.suppress(keyring.errors.PasswordDeleteError):
            keyring.delete_password(KEYRING_SERVICE, KEYRING_USERNAME)


# ---- Device identity --------------------------------------------------------

# APP_NAME is imported from config to keep keyring service names in one place.
# Distinct service ("Söyle Cloud") is for OAuth refresh token; device-id uses
# APP_NAME ("Söyle") with username "device-id" so the two don't collide and
# either can be cleared independently.
from soyle.core.config import APP_NAME as _APP_NAME  # noqa: E402

_DEVICE_ID_KEYRING_USERNAME = "device-id"

# Two-stage cache for the case where keyring is unavailable:
# - _DEVICE_ID_LAST_KNOWN: last value we successfully READ from keyring
#   this process. Reused on transient read failures so usage stays in
#   a single bucket even when the backend flaps.
# - _DEVICE_ID_FALLBACK: cold-start fallback used when we've NEVER had
#   a successful read (keyring was broken from the very first call).
# When keyring recovers and we read a real ID, that real ID becomes
# the last-known and subsequent failures stop using the cold-start
# fallback — graceful upgrade.
_DEVICE_ID_FALLBACK: str | None = None
_DEVICE_ID_LAST_KNOWN: str | None = None


def _device_id() -> str:
    """Stable per-machine UUID. Generated on first call, persisted in
    Windows Credential Manager under (APP_NAME, "device-id"). Survives
    config wipes; new machine = new ID by definition.

    Used by usage.py per-device buckets to attribute LLM cost/requests
    to the device that recorded them, so cross-device merge avoids
    double-counting on the same date.

    Degrades gracefully on keyring failure: if the credential backend
    is unavailable, locked, or unconfigured (KeyringError or any
    subclass), reuses the last-known real ID from this process if one
    was ever read successfully; otherwise falls back to a
    process-lifetime in-memory UUID. Usage recording still works; one
    warning is logged on the first cold-start fallback.
    """
    global _DEVICE_ID_FALLBACK, _DEVICE_ID_LAST_KNOWN

    try:
        existing = keyring.get_password(_APP_NAME, _DEVICE_ID_KEYRING_USERNAME)
    except keyring.errors.KeyringError as exc:
        # Prefer last-known real ID over minting a fresh fallback —
        # avoids splitting usage across buckets during transient outages.
        if _DEVICE_ID_LAST_KNOWN is not None:
            return _DEVICE_ID_LAST_KNOWN
        if _DEVICE_ID_FALLBACK is None:
            _DEVICE_ID_FALLBACK = str(uuid.uuid4())
            _log.warning(
                "device_id_keyring_unavailable_using_fallback",
                error=str(exc),
                error_type=type(exc).__name__,
            )
        return _DEVICE_ID_FALLBACK

    if existing:
        # Successful read — remember it so transient failures don't
        # split the session into a different bucket.
        _DEVICE_ID_LAST_KNOWN = existing
        return existing

    # Fresh device — mint and try to persist.
    new_id = str(uuid.uuid4())
    try:
        keyring.set_password(_APP_NAME, _DEVICE_ID_KEYRING_USERNAME, new_id)
    except keyring.errors.KeyringError as exc:
        # Write blocked — keep the cache in sync with what we return.
        # If _DEVICE_ID_FALLBACK was already established earlier (read
        # outage path), we return that pre-existing value; the just-minted
        # new_id is discarded. Mirror the return value into
        # _DEVICE_ID_LAST_KNOWN so a subsequent read failure returns the
        # same fallback (per-session device-ID consistency).
        if _DEVICE_ID_FALLBACK is None:
            _DEVICE_ID_FALLBACK = new_id
            _log.warning(
                "device_id_keyring_write_failed_using_fallback",
                error=str(exc),
                error_type=type(exc).__name__,
            )
        _DEVICE_ID_LAST_KNOWN = _DEVICE_ID_FALLBACK
        return _DEVICE_ID_FALLBACK
    # Persisted successfully — also cache for read-fail recovery.
    _DEVICE_ID_LAST_KNOWN = new_id
    return new_id


# ---- Phase 2: Config deny-list + dotted-path helpers ------------------------

# Dotted paths from Config root that are NEVER synced — these stay per-device.
# Format matches Pydantic model_dump keys: top-level section + dot + field,
# or just the section name to skip the entire section.
_CONFIG_DENY_LIST: frozenset[str] = frozenset({
    "version",                 # schema metadata, not a user preference
    "audio.device",            # mic name differs per machine
    "whisper.model",           # GPU tier dictates which preset is usable
    "whisper.device",          # cuda/cpu/auto — hardware-bound
    "whisper.compute_type",    # int8/float16 — GPU-dependent
    "behavior.autostart",      # often true on one machine, false on another
    "behavior.inject_method",  # clipboard/keystroke — per-app workarounds vary
    "ui.theme",                # monitor-dependent preference
    "cloud_sync",              # entire section: per-device last_synced_at state
})


def _get_dotted(data: dict[str, object], path: str) -> object:
    """Look up `path` in `data` ("foo.bar.baz"); return None if missing."""
    parts = path.split(".")
    current: object = data
    for part in parts:
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _set_dotted(data: dict[str, object], path: str, value: object) -> None:
    """Set `path` in `data` to `value`. Creates intermediate dicts."""
    parts = path.split(".")
    cursor: dict[str, object] = data
    for part in parts[:-1]:
        next_level = cursor.get(part)
        if not isinstance(next_level, dict):
            next_level = {}
            cursor[part] = next_level
        cursor = next_level
    cursor[parts[-1]] = value


def _del_dotted(data: dict[str, object], path: str) -> None:
    """Remove `path` from `data` if present; silent no-op otherwise."""
    parts = path.split(".")
    cursor: dict[str, object] = data
    for part in parts[:-1]:
        next_level = cursor.get(part)
        if not isinstance(next_level, dict):
            return
        cursor = next_level
    cursor.pop(parts[-1], None)


# ---- CloudSync coordinator --------------------------------------------------

SYNC_INTERVAL = timedelta(hours=24)
MAX_SYNC_RETRIES = 3  # cap on 412 (concurrent-write) retries per sync_now()

# Marker substring shipped in app.py's _GOOGLE_CLIENT_ID before a real GCP
# Desktop OAuth Client ID is plugged in. Used by is_configured for fail-fast
# guarding (codex P1 follow-up on PR #16) — without this, begin_oauth_flow
# would silently send users to a Google page that 4xx's with invalid_client.
_PLACEHOLDER_CLIENT_ID_MARKER = "REPLACE_WITH_"


class SyncOutcome(enum.Enum):
    """Terminal states of a sync_now() invocation. UI maps these to
    user-visible toasts (or silence, for transient NETWORK)."""

    OK = "ok"
    NETWORK = "network_error"
    AUTH_REVOKED = "auth_revoked"
    QUOTA = "quota_exceeded"
    APP_SUSPENDED = "app_suspended"
    NOT_CONNECTED = "not_connected"
    UNEXPECTED = "unexpected"


@dataclass(frozen=True)
class SyncResult:
    outcome: SyncOutcome
    added_local: int = 0
    added_remote: int = 0
    error_detail: str | None = None


@dataclass(frozen=True)
class RestoreOption:
    """Metadata about an existing Drive backup, surfaced to the wizard.

    Returned by detect_existing_backup() when the user reconnects on a new
    device and we need to ask "restore this backup, or start fresh?".
    """

    term_count: int
    last_modified: datetime


class CloudSync:
    """Coordinator for Google Drive sync of dictionary.toml.

    Public API per docs/superpowers/specs/2026-04-30-cloud-sync-design.md §5.1.
    """

    def __init__(
        self,
        *,
        dict_store: DictionaryStore,
        config_store: ConfigStore,
        client_id: str,
    ) -> None:
        self._dict_store = dict_store
        self._config_store = config_store
        self._client_id = client_id
        self._token_store = _TokenStore()
        self._oauth_listener: _OAuthCallbackListener | None = None
        self._oauth_verifier: str | None = None

    # -- State predicates -----------------------------------------------------

    @property
    def is_configured(self) -> bool:
        """True if a real OAuth client_id has been wired in.

        False means the placeholder from app.py is still in effect — all
        Google OAuth/refresh calls would 4xx with invalid_client.
        """
        return _PLACEHOLDER_CLIENT_ID_MARKER not in self._client_id

    @property
    def is_connected(self) -> bool:
        """True if a refresh token is stored in keyring."""
        return self._token_store.load() is not None

    @property
    def last_synced_at(self) -> datetime | None:
        """Timestamp of the last successful sync, or None if never."""
        return self._config_store.load().cloud_sync.last_synced_at

    def should_run_scheduled(self) -> bool:
        """True if connected AND >=24h since last sync (or never synced)."""
        if not self.is_connected:
            return False
        last = self.last_synced_at
        if last is None:
            return True
        return datetime.now(UTC) - last >= SYNC_INTERVAL

    # -- OAuth orchestration --------------------------------------------------

    async def begin_oauth_flow(self) -> str:
        """Generate PKCE pair, start listener, open browser, return auth URL.

        Two-phase API: this call kicks off the OAuth dance (verifier,
        listener, browser). The caller then awaits complete_oauth_flow()
        to block until Google redirects to localhost. The auth URL is
        returned mainly for testability — production code already opened
        it in the browser via webbrowser.open.

        Raises:
            RuntimeError: client_id is the placeholder. Fail-fast here so
                the Settings UI gets a clear error instead of routing the
                user to Google's "OAuth client was not found" page.
        """
        if not self.is_configured:
            raise RuntimeError(
                "Google OAuth client_id is not configured (still the "
                "placeholder). Set a real Desktop OAuth Client ID in "
                "_GOOGLE_CLIENT_ID before connecting to Drive."
            )
        verifier = _generate_code_verifier()
        challenge = _derive_code_challenge(verifier)
        listener = _OAuthCallbackListener()
        listener.start()

        params = {
            "client_id": self._client_id,
            "redirect_uri": listener.redirect_uri,
            "response_type": "code",
            "scope": DRIVE_APPDATA_SCOPE,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "access_type": "offline",
            "prompt": "consent",
        }
        auth_url = f"{OAUTH_AUTH_URL}?{urlencode(params)}"

        self._oauth_verifier = verifier
        self._oauth_listener = listener

        webbrowser.open(auth_url)
        return auth_url

    async def complete_oauth_flow(self, *, timeout: float = 120.0) -> None:
        """Wait for the localhost callback, exchange the code, store refresh token.

        Raises:
            RuntimeError: begin_oauth_flow() not called, or user denied
                consent (Google redirected with ?error=...).
            TimeoutError: user didn't authorize within the timeout.
            httpx.HTTPError: token endpoint failure.
        """
        if self._oauth_listener is None or self._oauth_verifier is None:
            raise RuntimeError(
                "begin_oauth_flow() must be called before complete_oauth_flow()"
            )
        try:
            params = self._oauth_listener.wait_for_callback(timeout=timeout)
            if "error" in params:
                raise RuntimeError(f"OAuth denied: {params['error']}")
            tokens = await _exchange_code_for_tokens(
                client_id=self._client_id,
                code=params["code"],
                code_verifier=self._oauth_verifier,
                redirect_uri=self._oauth_listener.redirect_uri,
            )
            self._token_store.save(tokens.refresh_token)
            _log.info("cloud_sync_connected")
        finally:
            self._oauth_listener.shutdown()
            self._oauth_listener = None
            self._oauth_verifier = None

    # -- Connection lifecycle -------------------------------------------------

    async def detect_existing_backup(self) -> RestoreOption | None:
        """Probe Drive App Data for dictionary.toml; return metadata if present.

        Returns None if no backup exists OR not connected (callers handle
        these the same way: just enable sync going forward, no restore
        prompt). Transient errors (network, token revocation) also resolve
        to None — the wizard's restore prompt is best-effort UI, not a
        correctness gate.
        """
        refresh_token = self._token_store.load()
        if refresh_token is None:
            return None
        try:
            access = await _refresh_access_token(
                client_id=self._client_id, refresh_token=refresh_token,
            )
        except (OAuthAuthRevokedError, httpx.HTTPError):
            return None

        headers = {"Authorization": f"Bearer {access}"}
        async with httpx.AsyncClient(timeout=15.0, headers=headers) as client:
            list_resp = await client.get(
                f"{DRIVE_API_BASE}/files",
                params={
                    "spaces": "appDataFolder",
                    # trashed=false: same defensive guard as
                    # _drive_get_dictionary / _lookup_file_id (PR #11) —
                    # without it, Drive returns user-trashed files and
                    # detection resolves to the wrong dictionary.toml.
                    "q": f"name='{DRIVE_FILE_NAME}' and trashed=false",
                    "fields": "files(id,modifiedTime)",
                },
            )
            list_resp.raise_for_status()
            files = list_resp.json().get("files", [])
            if not files:
                return None
            file_id = files[0]["id"]
            modified_iso = files[0].get("modifiedTime", "")

            content_resp = await client.get(
                f"{DRIVE_API_BASE}/files/{file_id}", params={"alt": "media"},
            )
            content_resp.raise_for_status()

        try:
            parsed = tomllib.loads(content_resp.content.decode("utf-8"))
            terms = parsed.get("terms", [])
            term_count = len(terms) if isinstance(terms, list) else 0
        except (tomllib.TOMLDecodeError, UnicodeDecodeError):
            term_count = 0

        # Drive emits RFC 3339 with a trailing Z; fromisoformat needs
        # +00:00 on Python <3.11 and accepts both on 3.11+. Normalize for
        # portability either way.
        normalized = modified_iso.replace("Z", "+00:00")
        last_modified = (
            datetime.fromisoformat(normalized) if normalized else datetime.now(UTC)
        )

        return RestoreOption(term_count=term_count, last_modified=last_modified)

    async def disconnect(self) -> None:
        """Revoke token at Google, clear keyring, reset last_synced_at.

        Local dictionary.toml on disk is intentionally preserved — the
        user can reconnect later (same account or different) without
        losing their dictionary. Revoke is best-effort: a 4xx/network
        failure doesn't block clearing local state, otherwise an
        already-invalid token would trap the user in "connected" forever.
        """
        refresh_token = self._token_store.load()
        if refresh_token is not None:
            with contextlib.suppress(httpx.HTTPError):
                async with httpx.AsyncClient(timeout=10.0) as client:
                    await client.post(
                        OAUTH_REVOKE_URL, params={"token": refresh_token},
                    )
        self._token_store.clear()
        cfg = self._config_store.load()
        cfg.cloud_sync.last_synced_at = None
        self._config_store.save(cfg)
        _log.info("cloud_sync_disconnected")

    # -- Sync entry point -----------------------------------------------------

    async def sync_now(self) -> SyncResult:
        """Idempotent merge cycle. See spec §6.2."""
        refresh_token = self._token_store.load()
        if refresh_token is None:
            return SyncResult(outcome=SyncOutcome.NOT_CONNECTED)

        try:
            access = await _refresh_access_token(
                client_id=self._client_id, refresh_token=refresh_token
            )
        except OAuthAuthRevokedError:
            self._token_store.clear()
            _log.warning("cloud_sync_auth_revoked")
            return SyncResult(outcome=SyncOutcome.AUTH_REVOKED)
        except (httpx.ConnectError, httpx.ReadError, httpx.TimeoutException):
            _log.warning("cloud_sync_network_error", phase="token_refresh")
            return SyncResult(outcome=SyncOutcome.NETWORK)
        except httpx.HTTPStatusError as exc:
            return self._classify_drive_error(exc, phase="token_refresh")

        return await self._sync_with_token(access)

    async def _sync_with_token(self, access: str, _attempt: int = 0) -> SyncResult:
        # Read remote (and look up file_id for the eventual write).
        try:
            remote, etag = await _drive_get_dictionary(access_token=access)
            file_id = await self._lookup_file_id(access)
        except DriveCorruptedError as corrupted:
            _log.warning("cloud_sync_corrupted_remote", file_id=corrupted.file_id)
            await _drive_rename_corrupted(
                access_token=access, file_id=corrupted.file_id
            )
            remote, etag, file_id = [], None, None
        except (httpx.ConnectError, httpx.ReadError, httpx.TimeoutException):
            _log.warning("cloud_sync_network_error", phase="drive_get")
            return SyncResult(outcome=SyncOutcome.NETWORK)
        except httpx.HTTPStatusError as exc:
            return self._classify_drive_error(exc, phase="drive_get")

        # Pure-union merge.
        local = self._dict_store.load()
        merged = self._dict_store.merge_with(remote)
        added_local = len(merged) - len(local)
        added_remote = len(merged) - len(remote)

        # Persist locally if changed.
        if merged != local:
            self._dict_store.save(merged)

        # Upload if remote differs from merged.
        if merged != remote:
            try:
                await _drive_put_dictionary(
                    access_token=access,
                    file_id=file_id,
                    etag=etag,
                    terms=merged,
                )
            except DriveConcurrentWriteError:
                # Idempotent retry — local now has merged terms; the next
                # round-trip sees latest remote, unions in any new terms,
                # and writes with a fresh etag. Bounded so a sustained
                # multi-device race can't recurse into RecursionError.
                if _attempt + 1 >= MAX_SYNC_RETRIES:
                    _log.warning(
                        "cloud_sync_concurrent_write_max_retries",
                        attempts=_attempt + 1,
                    )
                    return SyncResult(outcome=SyncOutcome.NETWORK)
                _log.info(
                    "cloud_sync_concurrent_write_detected", attempt=_attempt + 1,
                )
                return await self._sync_with_token(access, _attempt + 1)
            except (httpx.ConnectError, httpx.ReadError, httpx.TimeoutException):
                _log.warning("cloud_sync_network_error", phase="drive_put")
                return SyncResult(outcome=SyncOutcome.NETWORK)
            except httpx.HTTPStatusError as exc:
                return self._classify_drive_error(exc, phase="drive_put")

        # Stamp success.
        cfg = self._config_store.load()
        cfg.cloud_sync.last_synced_at = datetime.now(UTC)
        self._config_store.save(cfg)
        _log.info(
            "cloud_sync_ok",
            added_local=added_local,
            added_remote=added_remote,
            total_terms=len(merged),
        )
        return SyncResult(
            outcome=SyncOutcome.OK,
            added_local=added_local,
            added_remote=added_remote,
        )

    async def _lookup_file_id(self, access_token: str) -> str | None:
        """Re-list to find the file_id (since _drive_get_dictionary returns
        terms but not id). Returns None if file doesn't exist."""
        headers = {"Authorization": f"Bearer {access_token}"}
        async with httpx.AsyncClient(timeout=10.0, headers=headers) as client:
            resp = await client.get(
                f"{DRIVE_API_BASE}/files",
                params={
                    "spaces": "appDataFolder",
                    # trashed=false: see _drive_get_dictionary for rationale.
                    "q": f"name='{DRIVE_FILE_NAME}' and trashed=false",
                    "fields": "files(id)",
                },
            )
        resp.raise_for_status()
        files = resp.json().get("files", [])
        if not files:
            return None
        file_id: str = files[0]["id"]
        return file_id

    @staticmethod
    def _classify_drive_error(
        exc: httpx.HTTPStatusError, *, phase: str,
    ) -> SyncResult:
        status = exc.response.status_code
        body = exc.response.json() if exc.response.content else {}
        reason = body.get("error", {}).get("errors", [{}])[0].get("reason", "")

        if status == 403 and reason == "storageQuotaExceeded":
            _log.warning("cloud_sync_quota_exceeded", phase=phase)
            return SyncResult(outcome=SyncOutcome.QUOTA)
        if status == 403 and reason == "appSuspended":
            _log.error("cloud_sync_app_suspended", phase=phase)
            return SyncResult(outcome=SyncOutcome.APP_SUSPENDED)
        if 500 <= status < 600:
            _log.warning("cloud_sync_5xx", phase=phase, status=status)
            return SyncResult(outcome=SyncOutcome.NETWORK)

        _log.error(
            "cloud_sync_unexpected", phase=phase, status=status, reason=reason,
        )
        return SyncResult(
            outcome=SyncOutcome.UNEXPECTED, error_detail=f"{status}: {reason}",
        )


# ---- Drive REST primitives --------------------------------------------------

DRIVE_API_BASE = "https://www.googleapis.com/drive/v3"
DRIVE_FILE_NAME = "dictionary.toml"


class DriveCorruptedError(Exception):
    """Raised when the file in Drive App Data has invalid TOML.

    Carries file_id so the caller can rename the broken file out of the
    way before uploading the local replacement.
    """

    def __init__(self, file_id: str, original: Exception) -> None:
        super().__init__(f"Drive content not valid TOML (file_id={file_id})")
        self.file_id = file_id
        self.original = original


async def _drive_get_dictionary(
    *, access_token: str
) -> tuple[list[str], str | None]:
    """Fetch dictionary.toml from Drive App Data folder.

    Returns:
        (terms, etag) — terms is empty list if file doesn't exist yet;
        etag is None in that case, otherwise the strong ETag header value
        for use in subsequent If-Match write.

    Raises:
        DriveCorruptedError: file exists but content isn't valid TOML.
        httpx.HTTPError: network or 5xx; caller silences for transients.
    """
    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient(timeout=15.0, headers=headers) as client:
        # 1. List files in App Data folder filtered by name.
        list_resp = await client.get(
            f"{DRIVE_API_BASE}/files",
            params={
                "spaces": "appDataFolder",
                # trashed=false excludes user-deleted-but-not-purged files;
                # without it, files.list returns trashed items by default and
                # files[0] can resolve to the wrong dictionary.toml.
                "q": f"name='{DRIVE_FILE_NAME}' and trashed=false",
                "fields": "files(id,name,modifiedTime)",
            },
        )
        list_resp.raise_for_status()
        files = list_resp.json().get("files", [])
        if not files:
            return [], None

        file_id = files[0]["id"]

        # 2. Download content + capture ETag.
        get_resp = await client.get(
            f"{DRIVE_API_BASE}/files/{file_id}",
            params={"alt": "media"},
        )
        get_resp.raise_for_status()
        etag = get_resp.headers.get("ETag")

    try:
        parsed = tomllib.loads(get_resp.content.decode("utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise DriveCorruptedError(file_id, exc) from exc

    raw_terms = parsed.get("terms", [])
    if not isinstance(raw_terms, list):
        return [], etag
    return [str(t).strip() for t in raw_terms if str(t).strip()], etag


# ---- Drive REST primitives: write helpers -----------------------------------

DRIVE_UPLOAD_BASE = "https://www.googleapis.com/upload/drive/v3"


class DriveConcurrentWriteError(Exception):
    """Raised on 412 Precondition Failed — another device wrote first.

    Caller (sync_now) should re-read remote state and retry the merge.
    """


def _serialize_terms(terms: list[str]) -> bytes:
    """Encode a term list as the same TOML shape DictionaryStore writes."""
    return tomli_w.dumps({"version": 1, "terms": terms}).encode("utf-8")


async def _drive_put_dictionary(
    *,
    access_token: str,
    file_id: str | None,
    etag: str | None,
    terms: list[str],
) -> str:
    """Upload dictionary.toml to Drive App Data. Creates if file_id is None,
    updates with If-Match guard otherwise.

    Returns the file_id (new or same).

    Raises:
        DriveConcurrentWriteError: 412 on update; caller re-reads + retries.
        httpx.HTTPError: other transport / 5xx errors.
    """
    body = _serialize_terms(terms)
    headers = {"Authorization": f"Bearer {access_token}"}

    async with httpx.AsyncClient(timeout=20.0, headers=headers) as client:
        if file_id is None:
            # Multipart create — metadata + media in one request.
            metadata = {
                "name": DRIVE_FILE_NAME,
                "parents": ["appDataFolder"],
            }
            metadata_bytes = json.dumps(metadata).encode("utf-8")
            files = {
                "metadata": ("metadata", metadata_bytes, "application/json"),
                "media": (DRIVE_FILE_NAME, body, "application/toml"),
            }
            resp = await client.post(
                f"{DRIVE_UPLOAD_BASE}/files",
                params={"uploadType": "multipart"},
                files=files,
            )
            resp.raise_for_status()
            new_id: str = resp.json()["id"]
            return new_id

        # Update existing — PATCH content with If-Match guard.
        update_headers = {"Content-Type": "application/toml"}
        if etag is not None:
            update_headers["If-Match"] = etag
        resp = await client.patch(
            f"{DRIVE_UPLOAD_BASE}/files/{file_id}",
            params={"uploadType": "media"},
            content=body,
            headers=update_headers,
        )
        if resp.status_code == 412:
            raise DriveConcurrentWriteError(
                f"ETag mismatch for file {file_id}; another device wrote first"
            )
        resp.raise_for_status()
        returned_id: str = resp.json().get("id", file_id)
        return returned_id


async def _drive_rename_corrupted(*, access_token: str, file_id: str) -> None:
    """Rename a Drive file to dictionary.toml.broken-<UTC-timestamp>.

    Mirrors ConfigStore._backup_broken's pattern: don't delete corrupt
    data; archive it so the user (or future debugging) can recover.
    """
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    new_name = f"{DRIVE_FILE_NAME}.broken-{ts}"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=10.0, headers=headers) as client:
        resp = await client.patch(
            f"{DRIVE_API_BASE}/files/{file_id}",
            content=json.dumps({"name": new_name}),
        )
        resp.raise_for_status()
