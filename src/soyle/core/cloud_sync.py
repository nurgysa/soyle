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
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler
from queue import Empty, Queue
from urllib.parse import parse_qs, urlparse

import httpx
import structlog

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
