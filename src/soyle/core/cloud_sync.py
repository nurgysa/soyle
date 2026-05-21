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
import hashlib
import secrets
import socketserver
import threading
import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler
from queue import Empty, Queue
from urllib.parse import parse_qs, urlparse

import httpx
import keyring
import keyring.errors
import structlog

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

OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
OAUTH_REVOKE_URL = "https://oauth2.googleapis.com/revoke"

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


# ---- CloudSync coordinator --------------------------------------------------

SYNC_INTERVAL = timedelta(hours=24)


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

    # -- State predicates -----------------------------------------------------

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
                "q": f"name='{DRIVE_FILE_NAME}'",
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
