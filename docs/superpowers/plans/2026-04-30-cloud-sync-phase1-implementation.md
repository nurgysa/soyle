# Cloud Sync Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Per-user constraint:** This project's owner uses explicit gates. Each `git commit` step here is staged work — confirm with the user (`коммить` gate) before running it.

**Goal:** Add Google Drive sync of `dictionary.toml` to Söyle, with PKCE OAuth, daily startup-check schedule, pure-union merge, and first-run-wizard discovery.

**Architecture:** A single new `CloudSync` class in `src/soyle/core/cloud_sync.py` owns OAuth, Drive REST, and sync state. `DictionaryStore` gains a pure `merge_with()` method. `Config` gains a `CloudSyncConfig` section. `SoyleApp` triggers `sync_now()` post-warm-up if scheduled. First-run wizard extends with a Drive step. Settings gets a Cloud Sync tab.

**Tech Stack:** Python 3.12, PySide6, httpx, keyring, Pydantic, tomli-w, stdlib (`secrets`, `hashlib`, `http.server`, `webbrowser`). No new pip deps. Tests: pytest, pytest-asyncio, respx, pytest-mock.

**Reference:** [docs/superpowers/specs/2026-04-30-cloud-sync-design.md](../specs/2026-04-30-cloud-sync-design.md)

---

## File structure

| File | Status | Responsibility |
|---|---|---|
| `src/soyle/core/cloud_sync.py` | **NEW** | `CloudSync` coordinator: OAuth, Drive REST, sync state |
| `src/soyle/core/dictionary.py` | modify | Add `merge_with()` pure method |
| `src/soyle/core/config.py` | modify | Add `CloudSyncConfig` Pydantic section + field on `Config` |
| `src/soyle/app.py` | modify | Instantiate `CloudSync`, trigger scheduled `sync_now`, extend wizard |
| `src/soyle/ui/settings.py` | modify | Add "Cloud Sync" tab |
| `tests/unit/test_cloud_sync.py` | **NEW** | Unit tests for `CloudSync` (~25-30 tests) |
| `tests/unit/test_dictionary.py` | modify | Add `merge_with` tests |
| `tests/unit/test_config.py` | modify | Add `CloudSyncConfig` tests |
| `docs/testing/cloud-sync-manual.md` | **NEW** | Manual test checklist for things unit tests can't cover |

---

## Task 1: `DictionaryStore.merge_with()` pure function

**Files:**
- Modify: `src/soyle/core/dictionary.py` (add method to `DictionaryStore`)
- Test: `tests/unit/test_dictionary.py` (extend existing file)

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_dictionary.py`:

```python
def test_merge_with_pure_union_dedupes(tmp_path: Path) -> None:
    """[A, B] + [B, C] = [A, B, C], no duplicates."""
    store = DictionaryStore(path=tmp_path / "dict.toml")
    store.save(["A", "B"])
    merged = store.merge_with(["B", "C"])
    assert merged == ["A", "B", "C"]


def test_merge_with_preserves_local_first_appearance_order(tmp_path: Path) -> None:
    """Local order is preserved; new remote terms appended at the end."""
    store = DictionaryStore(path=tmp_path / "dict.toml")
    store.save(["Zebra", "Apple", "Mango"])
    merged = store.merge_with(["Banana", "Apple"])
    assert merged == ["Zebra", "Apple", "Mango", "Banana"]


def test_merge_with_empty_local_returns_remote(tmp_path: Path) -> None:
    store = DictionaryStore(path=tmp_path / "dict.toml")
    merged = store.merge_with(["X", "Y"])
    assert merged == ["X", "Y"]


def test_merge_with_empty_remote_returns_local(tmp_path: Path) -> None:
    store = DictionaryStore(path=tmp_path / "dict.toml")
    store.save(["A", "B"])
    merged = store.merge_with([])
    assert merged == ["A", "B"]


def test_merge_with_diacritic_insensitive_dedup(tmp_path: Path) -> None:
    """Söyle and Soyle and SÖYLE collapse to one — first-typed wins.

    Mirrors the existing _normalize_key logic used in DictionaryStore.save().
    """
    store = DictionaryStore(path=tmp_path / "dict.toml")
    store.save(["Söyle"])
    merged = store.merge_with(["Soyle", "SÖYLE", "Astana"])
    assert merged == ["Söyle", "Astana"]


def test_merge_with_does_not_persist_to_disk(tmp_path: Path) -> None:
    """merge_with is pure: it returns the merged list but doesn't save."""
    path = tmp_path / "dict.toml"
    store = DictionaryStore(path=path)
    store.save(["A"])
    store.merge_with(["B", "C"])
    # Disk still has only "A"
    reloaded = DictionaryStore(path=path).load()
    assert reloaded == ["A"]
```

- [ ] **Step 2: Run tests to verify they fail**

```
uv run pytest tests/unit/test_dictionary.py -v -k merge_with
```

Expected: 6 tests fail with `AttributeError: 'DictionaryStore' object has no attribute 'merge_with'`

- [ ] **Step 3: Implement `merge_with`**

Add to `src/soyle/core/dictionary.py` inside `DictionaryStore` class (anywhere after `save()`, before `# ---- Internals ----`):

```python
    def merge_with(self, other_terms: list[str]) -> list[str]:
        """Pure-union merge: returns local + other deduplicated, NO disk write.

        Used by CloudSync to combine local and remote dictionary state.
        Order: local terms keep their original positions; other_terms
        contribute only those not already present (by diacritic-insensitive,
        case-insensitive key — same rule as save()).

        Pure function — does not call save(). Caller must persist if needed.
        """
        local = self.load()
        return _dedupe_preserving_order(list(local) + list(other_terms))
```

- [ ] **Step 4: Run tests to verify they pass**

```
uv run pytest tests/unit/test_dictionary.py -v -k merge_with
```

Expected: 6 passed.

- [ ] **Step 5: Run full suite + ruff**

```
uv run pytest tests/unit/ --tb=short
uv run ruff check src/soyle/core/dictionary.py tests/unit/test_dictionary.py
```

Expected: all green, ruff clean.

- [ ] **Step 6: Commit (after `коммить` gate)**

```bash
git add src/soyle/core/dictionary.py tests/unit/test_dictionary.py
git commit -m "$(cat <<'EOF'
feat(dictionary): add merge_with for cloud-sync union semantics

DictionaryStore.merge_with(other_terms) returns the deduplicated union
of local terms and other_terms, preserving local first-appearance order
and appending only new terms from other. Pure function — does not write
to disk; caller is responsible for save().

Reuses the existing _dedupe_preserving_order helper which is
diacritic-insensitive (Söyle, Soyle, SÖYLE collapse to one) — same rule
already enforced by save().

Foundation for CloudSync.sync_now() pure-union merge per
docs/superpowers/specs/2026-04-30-cloud-sync-design.md §4.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `CloudSyncConfig` Pydantic schema

**Files:**
- Modify: `src/soyle/core/config.py` (add new section model + field on `Config`)
- Test: `tests/unit/test_config.py` (extend existing file)

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_config.py`:

```python
from datetime import datetime, UTC

from soyle.core.config import CloudSyncConfig  # NEW import


def test_cloud_sync_config_defaults() -> None:
    cfg = CloudSyncConfig()
    assert cfg.last_synced_at is None


def test_config_has_cloud_sync_section() -> None:
    cfg = Config()
    assert cfg.cloud_sync is not None
    assert cfg.cloud_sync.last_synced_at is None


def test_cloud_sync_last_synced_at_roundtrips_via_toml(tmp_path: Path) -> None:
    """Datetime survives TOML save/load round-trip."""
    path = tmp_path / "config.toml"
    store = ConfigStore(config_path=path)
    cfg = store.load()
    when = datetime(2026, 4, 30, 12, 0, 0, tzinfo=UTC)
    cfg.cloud_sync.last_synced_at = when
    store.save(cfg)

    reloaded = ConfigStore(config_path=path).load()
    assert reloaded.cloud_sync.last_synced_at == when


def test_cloud_sync_config_rejects_unknown_field() -> None:
    """extra='forbid' contract per other config sections."""
    with pytest.raises(ValueError):
        CloudSyncConfig(unknown_field=42)
```

- [ ] **Step 2: Run tests to verify they fail**

```
uv run pytest tests/unit/test_config.py -v -k cloud_sync
```

Expected: 4 tests fail (ImportError on CloudSyncConfig).

- [ ] **Step 3: Implement `CloudSyncConfig`**

In `src/soyle/core/config.py`:

(a) Add the section model — place it after `BehaviorConfig` (around line 105):

```python
class CloudSyncConfig(BaseModel):
    """Per-device cloud sync state.

    Currently single-field: timestamp of the last successful sync. Used by
    CloudSync.should_run_scheduled() to determine whether the 24h interval
    has elapsed. Stored on disk so it survives Söyle restarts.
    """
    model_config = ConfigDict(extra="forbid")

    last_synced_at: datetime | None = None
```

(b) Add a `datetime` import at the top of `config.py` if not already present (it is — already imported as part of `from datetime import UTC, datetime`).

(c) Add the `cloud_sync` field to `Config` (around line 117):

```python
class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = 1
    hotkey: HotkeyConfig = Field(default_factory=HotkeyConfig)
    audio: AudioConfig = Field(default_factory=AudioConfig)
    whisper: WhisperConfig = Field(default_factory=WhisperConfig)
    postprocess: PostProcessConfig = Field(default_factory=PostProcessConfig)
    ui: UIConfig = Field(default_factory=UIConfig)
    behavior: BehaviorConfig = Field(default_factory=BehaviorConfig)
    cloud_sync: CloudSyncConfig = Field(default_factory=CloudSyncConfig)  # NEW
```

- [ ] **Step 4: Run tests to verify they pass**

```
uv run pytest tests/unit/test_config.py -v -k cloud_sync
```

Expected: 4 passed.

- [ ] **Step 5: Run full suite + ruff**

```
uv run pytest tests/unit/ --tb=short
uv run ruff check src/soyle/core/config.py tests/unit/test_config.py
```

Expected: all green.

- [ ] **Step 6: Commit (after `коммить` gate)**

```bash
git add src/soyle/core/config.py tests/unit/test_config.py
git commit -m "$(cat <<'EOF'
feat(config): add CloudSyncConfig schema for sync state persistence

Phase 1 sync needs to remember the timestamp of the last successful
sync per-device, so should_run_scheduled() can decide whether 24h has
elapsed. Adds a [cloud_sync] section to Config with a single optional
datetime field, surviving TOML round-trip.

extra='forbid' matches other config sections — guards against typos in
hand-edited config.toml.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: PKCE crypto helpers

**Files:**
- Create: `src/soyle/core/cloud_sync.py` (new module — start with helpers)
- Create: `tests/unit/test_cloud_sync.py` (new test file)

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_cloud_sync.py`:

```python
"""Tests for CloudSync — Google Drive sync of dictionary.toml."""
from __future__ import annotations

import base64
import hashlib

import pytest

from soyle.core.cloud_sync import (
    _derive_code_challenge,
    _generate_code_verifier,
)


def test_code_verifier_is_url_safe_string_of_correct_length() -> None:
    verifier = _generate_code_verifier()
    # RFC 7636: verifier is 43-128 chars from [A-Z][a-z][0-9]-._~
    assert 43 <= len(verifier) <= 128
    allowed = set(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
    )
    assert all(c in allowed for c in verifier)


def test_code_verifier_is_random() -> None:
    """Two consecutive calls produce different verifiers."""
    a = _generate_code_verifier()
    b = _generate_code_verifier()
    assert a != b


def test_derive_code_challenge_is_sha256_base64url_of_verifier() -> None:
    """RFC 7636 §4.2: challenge = base64url(sha256(verifier)) without padding."""
    verifier = "test-verifier-known-value-1234567890abcdefABCDEF~_."
    expected_hash = hashlib.sha256(verifier.encode("ascii")).digest()
    expected = base64.urlsafe_b64encode(expected_hash).decode("ascii").rstrip("=")
    assert _derive_code_challenge(verifier) == expected


def test_derive_code_challenge_has_no_padding() -> None:
    """base64url with padding is not accepted by Google's token endpoint."""
    verifier = _generate_code_verifier()
    challenge = _derive_code_challenge(verifier)
    assert "=" not in challenge
```

- [ ] **Step 2: Run tests to verify they fail**

```
uv run pytest tests/unit/test_cloud_sync.py -v
```

Expected: 4 errors with `ModuleNotFoundError: No module named 'soyle.core.cloud_sync'`.

- [ ] **Step 3: Create `cloud_sync.py` with PKCE helpers**

Create `src/soyle/core/cloud_sync.py`:

```python
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
import hashlib
import secrets


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
```

- [ ] **Step 4: Run tests to verify they pass**

```
uv run pytest tests/unit/test_cloud_sync.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Ruff**

```
uv run ruff check src/soyle/core/cloud_sync.py tests/unit/test_cloud_sync.py
```

Expected: clean.

- [ ] **Step 6: Commit (after `коммить` gate)**

```bash
git add src/soyle/core/cloud_sync.py tests/unit/test_cloud_sync.py
git commit -m "$(cat <<'EOF'
feat(cloud_sync): add PKCE crypto helpers (RFC 7636)

New module src/soyle/core/cloud_sync.py for Phase 1 Google Drive sync.
Starts with the OAuth PKCE primitives: cryptographically-random
code_verifier (64 bytes via secrets.token_urlsafe) and code_challenge
(base64url(sha256(verifier)) without padding, as Google requires).

PKCE means the desktop binary doesn't need a client_secret — solves the
"how do you keep secrets in an open-source app" problem cleanly.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: OAuth callback HTTP listener

**Files:**
- Modify: `src/soyle/core/cloud_sync.py` (add listener class)
- Modify: `tests/unit/test_cloud_sync.py` (add listener tests)

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_cloud_sync.py`:

```python
import socket
import threading
from urllib.parse import urlparse, urlencode
from urllib.request import urlopen

from soyle.core.cloud_sync import _OAuthCallbackListener


def test_callback_listener_picks_free_port_above_1024() -> None:
    listener = _OAuthCallbackListener()
    listener.start()
    try:
        assert listener.port > 1024
        assert listener.redirect_uri == f"http://localhost:{listener.port}/callback"
    finally:
        listener.shutdown()


def test_callback_listener_captures_query_params() -> None:
    listener = _OAuthCallbackListener()
    listener.start()
    try:
        # Simulate browser hitting the redirect_uri
        params = {"code": "auth-code-123", "state": "xyz"}
        url = f"{listener.redirect_uri}?{urlencode(params)}"
        with urlopen(url, timeout=2) as resp:
            assert resp.status == 200

        result = listener.wait_for_callback(timeout=2)
        assert result == {"code": "auth-code-123", "state": "xyz"}
    finally:
        listener.shutdown()


def test_callback_listener_times_out_when_no_callback(monkeypatch) -> None:
    """If user never authorizes, wait_for_callback raises TimeoutError."""
    listener = _OAuthCallbackListener()
    listener.start()
    try:
        with pytest.raises(TimeoutError):
            listener.wait_for_callback(timeout=0.5)
    finally:
        listener.shutdown()


def test_callback_listener_returns_user_friendly_html() -> None:
    """Page shown in browser after callback — short Russian confirmation."""
    listener = _OAuthCallbackListener()
    listener.start()
    try:
        url = f"{listener.redirect_uri}?code=x"
        with urlopen(url, timeout=2) as resp:
            body = resp.read().decode("utf-8")
        assert "Söyle" in body
        # User can now close the browser tab
        assert "можно закрыть" in body.lower() or "can close" in body.lower()
    finally:
        listener.shutdown()
```

- [ ] **Step 2: Run tests to verify they fail**

```
uv run pytest tests/unit/test_cloud_sync.py -v -k callback_listener
```

Expected: 4 errors with `ImportError: cannot import name '_OAuthCallbackListener'`.

- [ ] **Step 3: Implement `_OAuthCallbackListener`**

Add to `src/soyle/core/cloud_sync.py`:

```python
import socketserver
import threading
from http.server import BaseHTTPRequestHandler
from queue import Empty, Queue
from urllib.parse import parse_qs, urlparse


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

            def do_GET(self) -> None:  # noqa: N802 (BaseHTTPRequestHandler API)
                parsed = urlparse(self.path)
                if parsed.path != "/callback":
                    self.send_response(404)
                    self.end_headers()
                    return
                params = {
                    k: v[0] for k, v in parse_qs(parsed.query).items() if v
                }
                # Best-effort enqueue; ignore if duplicate request after first.
                try:
                    listener._queue.put_nowait(params)
                except Exception:
                    pass
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
```

- [ ] **Step 4: Run tests to verify they pass**

```
uv run pytest tests/unit/test_cloud_sync.py -v -k callback_listener
```

Expected: 4 passed.

- [ ] **Step 5: Ruff**

```
uv run ruff check src/soyle/core/cloud_sync.py tests/unit/test_cloud_sync.py
```

Expected: clean.

- [ ] **Step 6: Commit (after `коммить` gate)**

```bash
git add src/soyle/core/cloud_sync.py tests/unit/test_cloud_sync.py
git commit -m "$(cat <<'EOF'
feat(cloud_sync): add localhost OAuth callback listener

Tiny stdlib-only HTTP server that picks a free port above 1024, captures
the ?code=... query from Google's OAuth redirect, and shows a Russian
"можно закрыть" confirmation page. Single-shot — serves one /callback
then waits for shutdown(). Daemon thread so it never blocks process
exit.

No google-auth or google-api-python-client dependency: ~70 lines of
http.server code.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Token endpoint exchange (`_exchange_code` and `_refresh_access_token`)

**Files:**
- Modify: `src/soyle/core/cloud_sync.py`
- Modify: `tests/unit/test_cloud_sync.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_cloud_sync.py`:

```python
import httpx
import respx

from soyle.core.cloud_sync import (
    OAUTH_TOKEN_URL,
    OAuthAuthRevokedError,
    _exchange_code_for_tokens,
    _refresh_access_token,
)


@pytest.mark.asyncio
@respx.mock
async def test_exchange_code_returns_refresh_and_access_tokens() -> None:
    respx.post(OAUTH_TOKEN_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "ya29.access",
                "refresh_token": "1//refresh",
                "expires_in": 3599,
                "scope": "https://www.googleapis.com/auth/drive.appdata",
                "token_type": "Bearer",
            },
        )
    )
    tokens = await _exchange_code_for_tokens(
        client_id="cid",
        code="auth-code",
        code_verifier="verifier",
        redirect_uri="http://localhost:1234/callback",
    )
    assert tokens.refresh_token == "1//refresh"
    assert tokens.access_token == "ya29.access"


@pytest.mark.asyncio
@respx.mock
async def test_refresh_access_token_returns_new_access() -> None:
    respx.post(OAUTH_TOKEN_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "ya29.refreshed",
                "expires_in": 3599,
                "token_type": "Bearer",
            },
        )
    )
    access = await _refresh_access_token(client_id="cid", refresh_token="1//refresh")
    assert access == "ya29.refreshed"


@pytest.mark.asyncio
@respx.mock
async def test_refresh_access_token_raises_revoked_on_invalid_grant() -> None:
    respx.post(OAUTH_TOKEN_URL).mock(
        return_value=httpx.Response(
            400,
            json={"error": "invalid_grant"},
        )
    )
    with pytest.raises(OAuthAuthRevokedError):
        await _refresh_access_token(client_id="cid", refresh_token="bad")


@pytest.mark.asyncio
@respx.mock
async def test_refresh_access_token_propagates_network_error() -> None:
    respx.post(OAUTH_TOKEN_URL).mock(side_effect=httpx.ConnectError("DNS"))
    with pytest.raises(httpx.ConnectError):
        await _refresh_access_token(client_id="cid", refresh_token="1//refresh")
```

- [ ] **Step 2: Run tests to verify they fail**

```
uv run pytest tests/unit/test_cloud_sync.py -v -k "exchange_code or refresh_access_token"
```

Expected: 4 errors (ImportError on missing names).

- [ ] **Step 3: Implement token endpoint functions**

Add to `src/soyle/core/cloud_sync.py`:

```python
from dataclasses import dataclass

import httpx


OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
OAUTH_REVOKE_URL = "https://oauth2.googleapis.com/revoke"


class OAuthAuthRevokedError(Exception):
    """Raised when Google reports the refresh token is no longer valid.

    Distinct from network/transient errors — the caller must clear local
    keyring state and prompt the user to re-authorize.
    """


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
    Other failures (network, 5xx) propagate as httpx exceptions for the
    caller to handle silently.
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
        if body.get("error") == "invalid_grant":
            raise OAuthAuthRevokedError(body.get("error_description", "revoked"))
    resp.raise_for_status()
    return resp.json()["access_token"]
```

- [ ] **Step 4: Run tests to verify they pass**

```
uv run pytest tests/unit/test_cloud_sync.py -v -k "exchange_code or refresh_access_token"
```

Expected: 4 passed.

- [ ] **Step 5: Ruff**

```
uv run ruff check src/soyle/core/cloud_sync.py tests/unit/test_cloud_sync.py
```

- [ ] **Step 6: Commit (after `коммить` gate)**

```bash
git add src/soyle/core/cloud_sync.py tests/unit/test_cloud_sync.py
git commit -m "$(cat <<'EOF'
feat(cloud_sync): add OAuth token exchange and refresh

Two stdlib + httpx functions for the Google OAuth token endpoint:

  _exchange_code_for_tokens(...)  → returns _TokenPair after PKCE auth
  _refresh_access_token(...)      → trades refresh_token for access_token

Distinguishes "auth revoked" (raise OAuthAuthRevokedError; caller must
clear keyring + prompt re-auth) from transient network failures
(propagate httpx exceptions; caller silences and retries).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Token storage via keyring (`_TokenStore`)

**Files:**
- Modify: `src/soyle/core/cloud_sync.py`
- Modify: `tests/unit/test_cloud_sync.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_cloud_sync.py`:

```python
from soyle.core.cloud_sync import _TokenStore, KEYRING_SERVICE, KEYRING_USERNAME


def test_token_store_save_and_load(mocker) -> None:
    backing: dict[tuple[str, str], str] = {}
    mocker.patch(
        "soyle.core.cloud_sync.keyring.set_password",
        side_effect=lambda s, u, p: backing.update({(s, u): p}),
    )
    mocker.patch(
        "soyle.core.cloud_sync.keyring.get_password",
        side_effect=lambda s, u: backing.get((s, u)),
    )

    store = _TokenStore()
    assert store.load() is None

    store.save("1//refresh-token-abc")
    assert store.load() == "1//refresh-token-abc"
    assert backing[(KEYRING_SERVICE, KEYRING_USERNAME)] == "1//refresh-token-abc"


def test_token_store_clear(mocker) -> None:
    deletions: list[tuple[str, str]] = []
    mocker.patch(
        "soyle.core.cloud_sync.keyring.delete_password",
        side_effect=lambda s, u: deletions.append((s, u)),
    )

    store = _TokenStore()
    store.clear()
    assert deletions == [(KEYRING_SERVICE, KEYRING_USERNAME)]


def test_token_store_clear_swallows_not_found(mocker) -> None:
    """Deleting a non-existent token is a no-op, not an error."""
    import keyring.errors

    mocker.patch(
        "soyle.core.cloud_sync.keyring.delete_password",
        side_effect=keyring.errors.PasswordDeleteError("no such pw"),
    )

    store = _TokenStore()
    store.clear()  # must not raise
```

- [ ] **Step 2: Run tests to verify they fail**

```
uv run pytest tests/unit/test_cloud_sync.py -v -k token_store
```

Expected: 3 errors (ImportError on `_TokenStore`).

- [ ] **Step 3: Implement `_TokenStore`**

Add to `src/soyle/core/cloud_sync.py`:

```python
import contextlib

import keyring
import keyring.errors


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
```

- [ ] **Step 4: Run tests to verify they pass**

```
uv run pytest tests/unit/test_cloud_sync.py -v -k token_store
```

Expected: 3 passed.

- [ ] **Step 5: Ruff + commit (after `коммить` gate)**

```
uv run ruff check src/soyle/core/cloud_sync.py tests/unit/test_cloud_sync.py
git add src/soyle/core/cloud_sync.py tests/unit/test_cloud_sync.py
git commit -m "$(cat <<'EOF'
feat(cloud_sync): add keyring-backed token storage

_TokenStore wraps the (service="Söyle Cloud", username="google-refresh-token")
keyring entry. Mirrors ConfigStore's clear_api_key pattern: swallows
PasswordDeleteError on clear() so disconnect is idempotent.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: `CloudSync` class skeleton + state predicates

**Files:**
- Modify: `src/soyle/core/cloud_sync.py`
- Modify: `tests/unit/test_cloud_sync.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_cloud_sync.py`:

```python
from datetime import datetime, timedelta, UTC

from soyle.core.cloud_sync import CloudSync


@pytest.fixture
def cloud_sync(tmp_path, mocker):
    """A CloudSync wired to in-memory keyring and a tmp config/dict store."""
    from soyle.core.config import ConfigStore
    from soyle.core.dictionary import DictionaryStore

    backing: dict[tuple[str, str], str] = {}
    mocker.patch(
        "soyle.core.cloud_sync.keyring.set_password",
        side_effect=lambda s, u, p: backing.update({(s, u): p}),
    )
    mocker.patch(
        "soyle.core.cloud_sync.keyring.get_password",
        side_effect=lambda s, u: backing.get((s, u)),
    )
    mocker.patch(
        "soyle.core.cloud_sync.keyring.delete_password",
        side_effect=lambda s, u: backing.pop((s, u), None),
    )

    cfg_store = ConfigStore(config_path=tmp_path / "config.toml")
    dict_store = DictionaryStore(path=tmp_path / "dict.toml")
    return CloudSync(
        dict_store=dict_store,
        config_store=cfg_store,
        client_id="test-client-id.apps.googleusercontent.com",
    )


def test_is_connected_false_when_no_token(cloud_sync) -> None:
    assert cloud_sync.is_connected is False


def test_is_connected_true_after_token_saved(cloud_sync) -> None:
    cloud_sync._token_store.save("1//some-refresh")
    assert cloud_sync.is_connected is True


def test_last_synced_at_reads_from_config(cloud_sync) -> None:
    when = datetime(2026, 4, 30, 10, 0, 0, tzinfo=UTC)
    cfg = cloud_sync._config_store.load()
    cfg.cloud_sync.last_synced_at = when
    cloud_sync._config_store.save(cfg)

    assert cloud_sync.last_synced_at == when


def test_should_run_scheduled_false_when_disconnected(cloud_sync) -> None:
    # No token; even if last_synced_at is ancient, should not run
    cfg = cloud_sync._config_store.load()
    cfg.cloud_sync.last_synced_at = datetime(2020, 1, 1, tzinfo=UTC)
    cloud_sync._config_store.save(cfg)
    assert cloud_sync.should_run_scheduled() is False


def test_should_run_scheduled_false_when_recently_synced(cloud_sync) -> None:
    cloud_sync._token_store.save("1//refresh")
    cfg = cloud_sync._config_store.load()
    cfg.cloud_sync.last_synced_at = datetime.now(UTC) - timedelta(hours=12)
    cloud_sync._config_store.save(cfg)
    assert cloud_sync.should_run_scheduled() is False


def test_should_run_scheduled_true_after_24h(cloud_sync) -> None:
    cloud_sync._token_store.save("1//refresh")
    cfg = cloud_sync._config_store.load()
    cfg.cloud_sync.last_synced_at = datetime.now(UTC) - timedelta(hours=25)
    cloud_sync._config_store.save(cfg)
    assert cloud_sync.should_run_scheduled() is True


def test_should_run_scheduled_true_when_never_synced(cloud_sync) -> None:
    """Connected but last_synced_at=None → first sync should run."""
    cloud_sync._token_store.save("1//refresh")
    assert cloud_sync.should_run_scheduled() is True
```

- [ ] **Step 2: Run tests to verify they fail**

```
uv run pytest tests/unit/test_cloud_sync.py -v -k "is_connected or last_synced or should_run_scheduled"
```

Expected: 7 errors (`CloudSync` missing).

- [ ] **Step 3: Implement `CloudSync` skeleton**

Add to `src/soyle/core/cloud_sync.py`:

```python
from datetime import datetime, timedelta, UTC

from soyle.core.config import ConfigStore
from soyle.core.dictionary import DictionaryStore


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
```

- [ ] **Step 4: Run tests to verify they pass**

```
uv run pytest tests/unit/test_cloud_sync.py -v -k "is_connected or last_synced or should_run_scheduled"
```

Expected: 7 passed.

- [ ] **Step 5: Ruff + commit (after `коммить` gate)**

```
uv run ruff check src/soyle/core/cloud_sync.py tests/unit/test_cloud_sync.py
git add src/soyle/core/cloud_sync.py tests/unit/test_cloud_sync.py
git commit -m "$(cat <<'EOF'
feat(cloud_sync): add CloudSync coordinator with state predicates

Skeleton for the Phase 1 sync class. Constructor takes injected
DictionaryStore + ConfigStore + client_id (the latter to be baked into
src/soyle/app.py at integration time).

Three predicates:
  - is_connected    : refresh token present in keyring
  - last_synced_at  : datetime | None from config.cloud_sync
  - should_run_scheduled : True iff connected AND ≥24h elapsed (or never)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Drive REST primitives — `_drive_get_dictionary`

**Files:**
- Modify: `src/soyle/core/cloud_sync.py`
- Modify: `tests/unit/test_cloud_sync.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_cloud_sync.py`:

```python
from soyle.core.cloud_sync import (
    DRIVE_API_BASE,
    DRIVE_FILE_NAME,
    DriveCorruptedError,
    _drive_get_dictionary,
)


@pytest.mark.asyncio
@respx.mock
async def test_drive_get_returns_empty_when_file_missing() -> None:
    """First-ever sync — no file in App Data folder yet."""
    respx.get(f"{DRIVE_API_BASE}/files").mock(
        return_value=httpx.Response(200, json={"files": []})
    )
    terms, etag = await _drive_get_dictionary(access_token="ya29.x")
    assert terms == []
    assert etag is None


@pytest.mark.asyncio
@respx.mock
async def test_drive_get_returns_terms_and_etag() -> None:
    """File exists — fetch metadata then content, parse TOML."""
    file_id = "drive-file-id-abc"
    respx.get(f"{DRIVE_API_BASE}/files").mock(
        return_value=httpx.Response(
            200,
            json={"files": [{"id": file_id, "name": DRIVE_FILE_NAME}]},
        )
    )
    respx.get(f"{DRIVE_API_BASE}/files/{file_id}").mock(
        return_value=httpx.Response(
            200,
            content=b'version = 1\nterms = ["Söyle", "Astana"]\n',
            headers={"ETag": '"etag-1"'},
        )
    )
    terms, etag = await _drive_get_dictionary(access_token="ya29.x")
    assert terms == ["Söyle", "Astana"]
    assert etag == '"etag-1"'


@pytest.mark.asyncio
@respx.mock
async def test_drive_get_raises_corrupted_on_invalid_toml() -> None:
    """Garbled TOML in Drive → distinct error so caller can backup-rename."""
    file_id = "id-x"
    respx.get(f"{DRIVE_API_BASE}/files").mock(
        return_value=httpx.Response(200, json={"files": [{"id": file_id}]})
    )
    respx.get(f"{DRIVE_API_BASE}/files/{file_id}").mock(
        return_value=httpx.Response(200, content=b"not valid toml [")
    )
    with pytest.raises(DriveCorruptedError) as exc_info:
        await _drive_get_dictionary(access_token="ya29.x")
    assert exc_info.value.file_id == file_id
```

- [ ] **Step 2: Run tests to verify they fail**

```
uv run pytest tests/unit/test_cloud_sync.py -v -k drive_get
```

Expected: 3 errors (missing names).

- [ ] **Step 3: Implement Drive GET helpers**

Add to `src/soyle/core/cloud_sync.py`:

```python
import tomllib


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
```

- [ ] **Step 4: Run tests to verify they pass**

```
uv run pytest tests/unit/test_cloud_sync.py -v -k drive_get
```

Expected: 3 passed.

- [ ] **Step 5: Ruff + commit (after `коммить` gate)**

```
uv run ruff check src/soyle/core/cloud_sync.py tests/unit/test_cloud_sync.py
git add src/soyle/core/cloud_sync.py tests/unit/test_cloud_sync.py
git commit -m "$(cat <<'EOF'
feat(cloud_sync): add Drive GET with ETag and corruption detection

Two-step Drive GET: list App Data folder filtered by name, then download
content. Returns (terms, etag) or ([], None) for first-ever sync.
Distinguishes DriveCorruptedError (broken TOML, caller renames) from
httpx errors (network/5xx, caller silences).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Drive REST primitives — `_drive_put_dictionary` + `_drive_rename_corrupted`

**Files:**
- Modify: `src/soyle/core/cloud_sync.py`
- Modify: `tests/unit/test_cloud_sync.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_cloud_sync.py`:

```python
from soyle.core.cloud_sync import (
    DriveConcurrentWriteError,
    _drive_put_dictionary,
    _drive_rename_corrupted,
)


@pytest.mark.asyncio
@respx.mock
async def test_drive_put_creates_new_file_when_no_id() -> None:
    """First sync: no existing file → multipart create."""
    respx.post(f"{DRIVE_API_BASE.replace('drive/v3', 'upload/drive/v3')}/files").mock(
        return_value=httpx.Response(200, json={"id": "new-file-id"})
    )
    new_id = await _drive_put_dictionary(
        access_token="ya29.x", file_id=None, etag=None, terms=["A", "B"]
    )
    assert new_id == "new-file-id"


@pytest.mark.asyncio
@respx.mock
async def test_drive_put_updates_existing_with_etag() -> None:
    """Subsequent sync: file_id known, If-Match guard set."""
    file_id = "existing-id"
    upload_url = f"{DRIVE_API_BASE.replace('drive/v3', 'upload/drive/v3')}/files/{file_id}"
    route = respx.patch(upload_url).mock(
        return_value=httpx.Response(200, json={"id": file_id})
    )
    same_id = await _drive_put_dictionary(
        access_token="ya29.x", file_id=file_id, etag='"abc"', terms=["A"]
    )
    assert same_id == file_id
    assert route.called
    sent_request = route.calls[0].request
    assert sent_request.headers.get("If-Match") == '"abc"'


@pytest.mark.asyncio
@respx.mock
async def test_drive_put_raises_concurrent_write_on_412() -> None:
    """ETag mismatch → caller re-reads and retries."""
    file_id = "x"
    upload_url = f"{DRIVE_API_BASE.replace('drive/v3', 'upload/drive/v3')}/files/{file_id}"
    respx.patch(upload_url).mock(
        return_value=httpx.Response(412, json={"error": "precondition"})
    )
    with pytest.raises(DriveConcurrentWriteError):
        await _drive_put_dictionary(
            access_token="ya29.x", file_id=file_id, etag='"stale"', terms=["A"]
        )


@pytest.mark.asyncio
@respx.mock
async def test_drive_rename_corrupted_appends_timestamp() -> None:
    """Corrupted file gets renamed to dictionary.toml.broken-<ts> then uploads
    proceed."""
    file_id = "broken-id"
    route = respx.patch(f"{DRIVE_API_BASE}/files/{file_id}").mock(
        return_value=httpx.Response(200, json={"id": file_id})
    )
    await _drive_rename_corrupted(access_token="ya29.x", file_id=file_id)
    assert route.called
    body = route.calls[0].request.content.decode("utf-8")
    assert "dictionary.toml.broken-" in body
```

- [ ] **Step 2: Run tests to verify they fail**

```
uv run pytest tests/unit/test_cloud_sync.py -v -k "drive_put or drive_rename"
```

Expected: 4 errors.

- [ ] **Step 3: Implement Drive write helpers**

Add to `src/soyle/core/cloud_sync.py`:

```python
import json

import tomli_w


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
            files = {
                "metadata": ("metadata", json.dumps(metadata), "application/json"),
                "media": (DRIVE_FILE_NAME, body, "application/toml"),
            }
            resp = await client.post(
                f"{DRIVE_UPLOAD_BASE}/files",
                params={"uploadType": "multipart"},
                files=files,
            )
            resp.raise_for_status()
            return resp.json()["id"]

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
        return resp.json().get("id", file_id)


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
```

- [ ] **Step 4: Run tests to verify they pass**

```
uv run pytest tests/unit/test_cloud_sync.py -v -k "drive_put or drive_rename"
```

Expected: 4 passed.

- [ ] **Step 5: Ruff + commit (after `коммить` gate)**

```
uv run ruff check src/soyle/core/cloud_sync.py tests/unit/test_cloud_sync.py
git add src/soyle/core/cloud_sync.py tests/unit/test_cloud_sync.py
git commit -m "$(cat <<'EOF'
feat(cloud_sync): add Drive PUT with ETag guard + corruption rename

_drive_put_dictionary: multipart create when file_id=None, PATCH with
If-Match when updating. Raises DriveConcurrentWriteError on 412 so
sync_now can re-read and retry.

_drive_rename_corrupted: archives broken-TOML files as
dictionary.toml.broken-<UTC-ts> before uploading replacement, mirroring
ConfigStore._backup_broken.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: `CloudSync.sync_now()` — the merge cycle

**Files:**
- Modify: `src/soyle/core/cloud_sync.py`
- Modify: `tests/unit/test_cloud_sync.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_cloud_sync.py`:

```python
from soyle.core.cloud_sync import SyncOutcome, SyncResult


@pytest.mark.asyncio
@respx.mock
async def test_sync_now_uploads_local_when_remote_empty(cloud_sync) -> None:
    """First-ever sync from a device with terms — pure upload."""
    cloud_sync._token_store.save("1//refresh")
    cloud_sync._dict_store.save(["Söyle", "Astana"])

    respx.post(OAUTH_TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "ya29.x"})
    )
    respx.get(f"{DRIVE_API_BASE}/files").mock(
        return_value=httpx.Response(200, json={"files": []})  # empty remote
    )
    respx.post(f"{DRIVE_UPLOAD_BASE}/files").mock(
        return_value=httpx.Response(200, json={"id": "new-id"})
    )

    result = await cloud_sync.sync_now()
    assert result.outcome is SyncOutcome.OK
    assert result.added_remote == 2
    assert result.added_local == 0
    assert cloud_sync.last_synced_at is not None


@pytest.mark.asyncio
@respx.mock
async def test_sync_now_downloads_remote_when_local_empty(cloud_sync) -> None:
    """New device — pulls existing backup."""
    cloud_sync._token_store.save("1//refresh")

    respx.post(OAUTH_TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "ya29.x"})
    )
    respx.get(f"{DRIVE_API_BASE}/files").mock(
        return_value=httpx.Response(
            200, json={"files": [{"id": "id-1", "name": DRIVE_FILE_NAME}]}
        )
    )
    respx.get(f"{DRIVE_API_BASE}/files/id-1").mock(
        return_value=httpx.Response(
            200,
            content=b'version = 1\nterms = ["X", "Y"]\n',
            headers={"ETag": '"e1"'},
        )
    )
    # No upload needed — local now matches remote after merge.

    result = await cloud_sync.sync_now()
    assert result.outcome is SyncOutcome.OK
    assert result.added_local == 2
    assert cloud_sync._dict_store.load() == ["X", "Y"]


@pytest.mark.asyncio
@respx.mock
async def test_sync_now_unions_when_both_have_unique_terms(cloud_sync) -> None:
    cloud_sync._token_store.save("1//refresh")
    cloud_sync._dict_store.save(["A", "B"])

    respx.post(OAUTH_TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "ya29.x"})
    )
    respx.get(f"{DRIVE_API_BASE}/files").mock(
        return_value=httpx.Response(
            200, json={"files": [{"id": "id-x"}]}
        )
    )
    respx.get(f"{DRIVE_API_BASE}/files/id-x").mock(
        return_value=httpx.Response(
            200,
            content=b'version = 1\nterms = ["B", "C"]\n',
            headers={"ETag": '"e1"'},
        )
    )
    respx.patch(f"{DRIVE_UPLOAD_BASE}/files/id-x").mock(
        return_value=httpx.Response(200, json={"id": "id-x"})
    )

    result = await cloud_sync.sync_now()
    assert result.outcome is SyncOutcome.OK
    assert result.added_local == 1   # got "C"
    assert result.added_remote == 1  # uploaded "A"
    assert cloud_sync._dict_store.load() == ["A", "B", "C"]


@pytest.mark.asyncio
@respx.mock
async def test_sync_now_skips_writes_when_already_in_sync(cloud_sync) -> None:
    cloud_sync._token_store.save("1//refresh")
    cloud_sync._dict_store.save(["A", "B"])

    respx.post(OAUTH_TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "ya29.x"})
    )
    respx.get(f"{DRIVE_API_BASE}/files").mock(
        return_value=httpx.Response(
            200, json={"files": [{"id": "id-1"}]}
        )
    )
    respx.get(f"{DRIVE_API_BASE}/files/id-1").mock(
        return_value=httpx.Response(
            200,
            content=b'version = 1\nterms = ["A", "B"]\n',
            headers={"ETag": '"e1"'},
        )
    )
    upload_route = respx.patch(f"{DRIVE_UPLOAD_BASE}/files/id-1").mock(
        return_value=httpx.Response(200, json={"id": "id-1"})
    )

    result = await cloud_sync.sync_now()
    assert result.outcome is SyncOutcome.OK
    assert result.added_local == 0
    assert result.added_remote == 0
    assert not upload_route.called  # no PUT — already in sync


@pytest.mark.asyncio
@respx.mock
async def test_sync_now_returns_NETWORK_on_connect_error(cloud_sync) -> None:
    """Transient network error — silent fallback, no token clear."""
    cloud_sync._token_store.save("1//refresh")
    respx.post(OAUTH_TOKEN_URL).mock(side_effect=httpx.ConnectError("DNS"))

    result = await cloud_sync.sync_now()
    assert result.outcome is SyncOutcome.NETWORK
    assert cloud_sync.is_connected is True  # token still there
    assert cloud_sync.last_synced_at is None  # didn't update timestamp


@pytest.mark.asyncio
@respx.mock
async def test_sync_now_returns_AUTH_REVOKED_and_clears_keyring(cloud_sync) -> None:
    cloud_sync._token_store.save("1//bad")
    respx.post(OAUTH_TOKEN_URL).mock(
        return_value=httpx.Response(400, json={"error": "invalid_grant"})
    )

    result = await cloud_sync.sync_now()
    assert result.outcome is SyncOutcome.AUTH_REVOKED
    assert cloud_sync.is_connected is False  # token cleared


@pytest.mark.asyncio
@respx.mock
async def test_sync_now_handles_corrupted_remote_with_rename_and_upload(
    cloud_sync,
) -> None:
    cloud_sync._token_store.save("1//refresh")
    cloud_sync._dict_store.save(["A"])

    respx.post(OAUTH_TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "ya29.x"})
    )
    respx.get(f"{DRIVE_API_BASE}/files").mock(
        return_value=httpx.Response(
            200, json={"files": [{"id": "broken"}]}
        )
    )
    respx.get(f"{DRIVE_API_BASE}/files/broken").mock(
        return_value=httpx.Response(200, content=b"not toml [[[")
    )
    rename_route = respx.patch(f"{DRIVE_API_BASE}/files/broken").mock(
        return_value=httpx.Response(200, json={"id": "broken"})
    )
    create_route = respx.post(f"{DRIVE_UPLOAD_BASE}/files").mock(
        return_value=httpx.Response(200, json={"id": "new-id"})
    )

    result = await cloud_sync.sync_now()
    assert result.outcome is SyncOutcome.OK  # corruption recovered transparently
    assert rename_route.called
    assert create_route.called  # fresh upload of local


@pytest.mark.asyncio
@respx.mock
async def test_sync_now_retries_on_412_concurrent_write(cloud_sync) -> None:
    """ETag mismatch → re-read + re-merge + re-write."""
    cloud_sync._token_store.save("1//refresh")
    cloud_sync._dict_store.save(["A"])

    respx.post(OAUTH_TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "ya29.x"})
    )
    # First read: shows ETag e1.
    list_route = respx.get(f"{DRIVE_API_BASE}/files").mock(
        return_value=httpx.Response(200, json={"files": [{"id": "x"}]})
    )
    get_route = respx.get(f"{DRIVE_API_BASE}/files/x").mock(
        side_effect=[
            httpx.Response(
                200, content=b'version=1\nterms=["B"]\n', headers={"ETag": '"e1"'}
            ),
            httpx.Response(
                200, content=b'version=1\nterms=["B","C"]\n', headers={"ETag": '"e2"'}
            ),
        ]
    )
    patch_route = respx.patch(f"{DRIVE_UPLOAD_BASE}/files/x").mock(
        side_effect=[
            httpx.Response(412, json={"error": "precondition"}),  # first try fails
            httpx.Response(200, json={"id": "x"}),  # retry succeeds
        ]
    )

    result = await cloud_sync.sync_now()
    assert result.outcome is SyncOutcome.OK
    assert get_route.call_count == 2
    assert patch_route.call_count == 2
    # Final local state: A + B + C
    assert cloud_sync._dict_store.load() == ["A", "B", "C"]
```

- [ ] **Step 2: Run tests to verify they fail**

```
uv run pytest tests/unit/test_cloud_sync.py -v -k sync_now
```

Expected: 8 errors (`sync_now` missing).

- [ ] **Step 3: Implement `sync_now()` and `SyncOutcome`/`SyncResult`**

Add to `src/soyle/core/cloud_sync.py`:

```python
import enum
import logging

import structlog


_log = structlog.get_logger(__name__)


class SyncOutcome(enum.Enum):
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


class CloudSync:
    # ... existing __init__ + properties ...

    async def sync_now(self) -> SyncResult:
        """Idempotent merge cycle. See spec §6.2."""
        refresh_token = self._token_store.load()
        if refresh_token is None:
            return SyncResult(outcome=SyncOutcome.NOT_CONNECTED)

        # 1. Refresh access token.
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

    async def _sync_with_token(self, access: str) -> SyncResult:
        # 2. Read remote.
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

        # 3. Merge (pure union).
        local = self._dict_store.load()
        merged = self._dict_store.merge_with(remote)
        added_local = len(merged) - len(local)
        added_remote = len(merged) - len(remote)

        # 4. Persist locally if changed.
        if merged != local:
            self._dict_store.save(merged)

        # 5. Upload if remote differs from merged.
        if merged != remote:
            try:
                await _drive_put_dictionary(
                    access_token=access, file_id=file_id, etag=etag, terms=merged,
                )
            except DriveConcurrentWriteError:
                _log.info("cloud_sync_concurrent_write_detected")
                # Idempotent retry — our local now has merged terms; next
                # call sees latest remote, unions in any new ones, succeeds.
                return await self._sync_with_token(access)
            except (httpx.ConnectError, httpx.ReadError, httpx.TimeoutException):
                _log.warning("cloud_sync_network_error", phase="drive_put")
                return SyncResult(outcome=SyncOutcome.NETWORK)
            except httpx.HTTPStatusError as exc:
                return self._classify_drive_error(exc, phase="drive_put")

        # 6. Update last_synced_at.
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
        """Helper: re-list to find the file_id, since _drive_get_dictionary
        returns terms but not the id. Returns None if file doesn't exist."""
        headers = {"Authorization": f"Bearer {access_token}"}
        async with httpx.AsyncClient(timeout=10.0, headers=headers) as client:
            resp = await client.get(
                f"{DRIVE_API_BASE}/files",
                params={
                    "spaces": "appDataFolder",
                    "q": f"name='{DRIVE_FILE_NAME}'",
                    "fields": "files(id)",
                },
            )
        resp.raise_for_status()
        files = resp.json().get("files", [])
        return files[0]["id"] if files else None

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

        _log.error("cloud_sync_unexpected", phase=phase, status=status, reason=reason)
        return SyncResult(
            outcome=SyncOutcome.UNEXPECTED, error_detail=f"{status}: {reason}"
        )
```

> **Note:** the `_lookup_file_id` helper duplicates listing logic with `_drive_get_dictionary`. A small follow-up refactor (Task 10.5 if needed) could fold them. For Phase 1 the duplication is acceptable — clearer test boundaries.

- [ ] **Step 4: Run tests to verify they pass**

```
uv run pytest tests/unit/test_cloud_sync.py -v -k sync_now
```

Expected: 8 passed.

- [ ] **Step 5: Run full suite + ruff**

```
uv run pytest tests/unit/ --tb=short
uv run ruff check src/soyle/core/cloud_sync.py tests/unit/test_cloud_sync.py
```

- [ ] **Step 6: Commit (after `коммить` gate)**

```bash
git add src/soyle/core/cloud_sync.py tests/unit/test_cloud_sync.py
git commit -m "$(cat <<'EOF'
feat(cloud_sync): implement sync_now merge cycle

Pure-union round-trip: refresh access_token → read remote → merge with
local → write merged if changed → update last_synced_at. Idempotent —
running it again on a converged state is a no-op except timestamp bump.

Error matrix per spec §7.1:
  network/timeout      → SyncOutcome.NETWORK    (silent, no toast)
  invalid_grant        → SyncOutcome.AUTH_REVOKED, keyring cleared
  storageQuotaExceeded → SyncOutcome.QUOTA
  appSuspended         → SyncOutcome.APP_SUSPENDED
  5xx                  → SyncOutcome.NETWORK   (caller silences)
  corrupted TOML       → rename-and-upload-fresh, return OK
  412 concurrent write → idempotent retry

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: OAuth orchestration — `begin_oauth_flow` + `complete_oauth_flow`

**Files:**
- Modify: `src/soyle/core/cloud_sync.py`
- Modify: `tests/unit/test_cloud_sync.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_cloud_sync.py`:

```python
@pytest.mark.asyncio
@respx.mock
async def test_begin_oauth_flow_returns_auth_url_and_starts_listener(
    cloud_sync, mocker
) -> None:
    mocker.patch("soyle.core.cloud_sync.webbrowser.open")
    auth_url = await cloud_sync.begin_oauth_flow()

    assert auth_url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "client_id=test-client-id" in auth_url
    assert "code_challenge=" in auth_url
    assert "code_challenge_method=S256" in auth_url
    assert "scope=https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fdrive.appdata" in auth_url
    assert "access_type=offline" in auth_url
    assert "prompt=consent" in auth_url
    assert "redirect_uri=http%3A%2F%2Flocalhost%3A" in auth_url

    # listener has been started (port assigned)
    assert cloud_sync._oauth_listener is not None
    assert cloud_sync._oauth_listener.port > 1024


@pytest.mark.asyncio
@respx.mock
async def test_complete_oauth_flow_exchanges_code_and_stores_token(
    cloud_sync, mocker
) -> None:
    mocker.patch("soyle.core.cloud_sync.webbrowser.open")
    await cloud_sync.begin_oauth_flow()

    respx.post(OAUTH_TOKEN_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "ya29.x",
                "refresh_token": "1//refresh-stored",
                "token_type": "Bearer",
                "expires_in": 3599,
            },
        )
    )

    # Simulate Google redirecting to localhost
    callback_url = f"{cloud_sync._oauth_listener.redirect_uri}?code=AUTH_CODE_X"
    from urllib.request import urlopen
    threading.Thread(
        target=lambda: urlopen(callback_url, timeout=2), daemon=True
    ).start()

    await cloud_sync.complete_oauth_flow()

    assert cloud_sync.is_connected is True
    assert cloud_sync._token_store.load() == "1//refresh-stored"
```

- [ ] **Step 2: Run tests to verify they fail**

```
uv run pytest tests/unit/test_cloud_sync.py -v -k oauth_flow
```

Expected: 2 errors.

- [ ] **Step 3: Implement OAuth orchestration**

Add to `src/soyle/core/cloud_sync.py`:

```python
import webbrowser
from urllib.parse import urlencode


OAUTH_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
DRIVE_APPDATA_SCOPE = "https://www.googleapis.com/auth/drive.appdata"


class CloudSync:
    # ... existing methods ...

    async def begin_oauth_flow(self) -> str:
        """Generate PKCE pair, start listener, open browser, return auth URL.

        The auth URL is also returned for testability — production code
        opens it via webbrowser, but tests can inspect.
        """
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

        # Stash for complete_oauth_flow.
        self._oauth_verifier = verifier
        self._oauth_listener = listener

        webbrowser.open(auth_url)
        return auth_url

    async def complete_oauth_flow(self, *, timeout: float = 120.0) -> None:
        """Wait for callback, exchange code, persist refresh_token.

        Raises:
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
```

Also update `__init__` to declare the lazy fields:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```
uv run pytest tests/unit/test_cloud_sync.py -v -k oauth_flow
```

Expected: 2 passed.

- [ ] **Step 5: Ruff + commit (after `коммить` gate)**

```
uv run ruff check src/soyle/core/cloud_sync.py tests/unit/test_cloud_sync.py
git add src/soyle/core/cloud_sync.py tests/unit/test_cloud_sync.py
git commit -m "$(cat <<'EOF'
feat(cloud_sync): add begin/complete OAuth PKCE flow

begin_oauth_flow: generates verifier+challenge, starts localhost
listener, opens browser to Google consent screen, returns auth URL.

complete_oauth_flow: waits for /callback, exchanges code for tokens,
stores refresh_token in keyring, shuts down listener. Default 120s
timeout — user has 2 minutes to click through Google's consent.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 12: `detect_existing_backup()` + `disconnect()`

**Files:**
- Modify: `src/soyle/core/cloud_sync.py`
- Modify: `tests/unit/test_cloud_sync.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_cloud_sync.py`:

```python
from soyle.core.cloud_sync import RestoreOption


@pytest.mark.asyncio
@respx.mock
async def test_detect_existing_backup_returns_none_when_no_file(cloud_sync) -> None:
    cloud_sync._token_store.save("1//refresh")
    respx.post(OAUTH_TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "ya29.x"})
    )
    respx.get(f"{DRIVE_API_BASE}/files").mock(
        return_value=httpx.Response(200, json={"files": []})
    )
    result = await cloud_sync.detect_existing_backup()
    assert result is None


@pytest.mark.asyncio
@respx.mock
async def test_detect_existing_backup_returns_metadata(cloud_sync) -> None:
    cloud_sync._token_store.save("1//refresh")
    respx.post(OAUTH_TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "ya29.x"})
    )
    respx.get(f"{DRIVE_API_BASE}/files").mock(
        return_value=httpx.Response(
            200,
            json={
                "files": [
                    {
                        "id": "id-1",
                        "name": "dictionary.toml",
                        "modifiedTime": "2026-04-29T10:00:00.000Z",
                    }
                ]
            },
        )
    )
    respx.get(f"{DRIVE_API_BASE}/files/id-1").mock(
        return_value=httpx.Response(
            200, content=b'version=1\nterms=["A","B","C"]\n',
        )
    )

    result = await cloud_sync.detect_existing_backup()
    assert result is not None
    assert isinstance(result, RestoreOption)
    assert result.term_count == 3
    assert result.last_modified.isoformat().startswith("2026-04-29T10:00:00")


@pytest.mark.asyncio
@respx.mock
async def test_disconnect_revokes_and_clears_state(cloud_sync) -> None:
    cloud_sync._token_store.save("1//refresh")
    cfg = cloud_sync._config_store.load()
    cfg.cloud_sync.last_synced_at = datetime.now(UTC)
    cloud_sync._config_store.save(cfg)

    revoke_route = respx.post(OAUTH_REVOKE_URL).mock(
        return_value=httpx.Response(200)
    )
    await cloud_sync.disconnect()

    assert cloud_sync.is_connected is False
    assert cloud_sync.last_synced_at is None
    assert revoke_route.called


@pytest.mark.asyncio
@respx.mock
async def test_disconnect_swallows_revoke_errors(cloud_sync) -> None:
    """Revoke might 400 on already-invalid token; clear local state anyway."""
    cloud_sync._token_store.save("1//refresh")
    respx.post(OAUTH_REVOKE_URL).mock(
        return_value=httpx.Response(400, json={"error": "invalid_token"})
    )
    await cloud_sync.disconnect()  # must not raise
    assert cloud_sync.is_connected is False
```

- [ ] **Step 2: Run tests to verify they fail**

```
uv run pytest tests/unit/test_cloud_sync.py -v -k "detect_existing or disconnect"
```

Expected: 4 errors.

- [ ] **Step 3: Implement `RestoreOption`, `detect_existing_backup`, `disconnect`**

Add to `src/soyle/core/cloud_sync.py`:

```python
@dataclass(frozen=True)
class RestoreOption:
    """Metadata about an existing Drive backup, returned to the wizard."""
    term_count: int
    last_modified: datetime


class CloudSync:
    # ... existing methods ...

    async def detect_existing_backup(self) -> RestoreOption | None:
        """Probe Drive App Data for dictionary.toml; return metadata if present.

        Returns None if no backup exists OR not connected (callers handle
        these the same way: just enable sync going forward, no restore).
        """
        refresh_token = self._token_store.load()
        if refresh_token is None:
            return None
        try:
            access = await _refresh_access_token(
                client_id=self._client_id, refresh_token=refresh_token
            )
        except (OAuthAuthRevokedError, httpx.HTTPError):
            return None

        headers = {"Authorization": f"Bearer {access}"}
        async with httpx.AsyncClient(timeout=15.0, headers=headers) as client:
            list_resp = await client.get(
                f"{DRIVE_API_BASE}/files",
                params={
                    "spaces": "appDataFolder",
                    "q": f"name='{DRIVE_FILE_NAME}'",
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
                f"{DRIVE_API_BASE}/files/{file_id}", params={"alt": "media"}
            )
            content_resp.raise_for_status()

        try:
            parsed = tomllib.loads(content_resp.content.decode("utf-8"))
            terms = parsed.get("terms", [])
            term_count = len(terms) if isinstance(terms, list) else 0
        except (tomllib.TOMLDecodeError, UnicodeDecodeError):
            term_count = 0

        # Drive returns RFC 3339 timestamps; datetime.fromisoformat handles
        # the typical "2026-04-29T10:00:00.000Z" format on Python 3.11+.
        # Normalize trailing Z to +00:00 for older Python compatibility.
        normalized = modified_iso.replace("Z", "+00:00")
        last_modified = datetime.fromisoformat(normalized) if normalized else datetime.now(UTC)

        return RestoreOption(term_count=term_count, last_modified=last_modified)

    async def disconnect(self) -> None:
        """Revoke token at Google, clear keyring, reset last_synced_at.

        Local data (dictionary.toml on disk) is preserved so the user can
        reconnect later without losing anything.
        """
        refresh_token = self._token_store.load()
        if refresh_token is not None:
            with contextlib.suppress(httpx.HTTPError):
                async with httpx.AsyncClient(timeout=10.0) as client:
                    await client.post(
                        OAUTH_REVOKE_URL, params={"token": refresh_token}
                    )
        self._token_store.clear()
        cfg = self._config_store.load()
        cfg.cloud_sync.last_synced_at = None
        self._config_store.save(cfg)
        _log.info("cloud_sync_disconnected")
```

- [ ] **Step 4: Run tests to verify they pass**

```
uv run pytest tests/unit/test_cloud_sync.py -v -k "detect_existing or disconnect"
```

Expected: 4 passed.

- [ ] **Step 5: Ruff + commit (after `коммить` gate)**

```
uv run ruff check src/soyle/core/cloud_sync.py tests/unit/test_cloud_sync.py
git add src/soyle/core/cloud_sync.py tests/unit/test_cloud_sync.py
git commit -m "$(cat <<'EOF'
feat(cloud_sync): add detect_existing_backup and disconnect

detect_existing_backup: probe App Data for dictionary.toml metadata;
returns RestoreOption(term_count, last_modified) for the wizard's
restore prompt, or None if no backup.

disconnect: revoke token at Google (best-effort, swallows errors so
already-invalid tokens don't block clearing), clear keyring, reset
last_synced_at. Local dictionary.toml is intentionally NOT touched.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 13: Wire `CloudSync` into `SoyleApp` lifecycle

**Files:**
- Modify: `src/soyle/app.py`

This is integration glue — no separate test file is added (CloudSync's behavior is exhaustively unit-tested; here we just confirm the wiring compiles and starts).

- [ ] **Step 1: Add CloudSync construction**

In `src/soyle/app.py`, near the other store/manager constructions in `SoyleApp.__init__` (around line 87-95):

```python
from soyle.core.cloud_sync import CloudSync, SyncOutcome


# ... inside SoyleApp.__init__, AFTER self._dict_store and self._store ...

# Hardcoded client_id from the Söyle Google Cloud project (Desktop app
# type, PKCE-only — no client_secret needed in the binary). Created in
# console.cloud.google.com under the project owner's account.
_GOOGLE_CLIENT_ID = "REPLACE_WITH_REAL_CLIENT_ID.apps.googleusercontent.com"

self._cloud_sync = CloudSync(
    dict_store=self._dict_store,
    config_store=self._store,
    client_id=_GOOGLE_CLIENT_ID,
)
```

> **Action item for the maintainer (out-of-band):** create a Google Cloud project under the `nurgysa` Google account, configure an OAuth 2.0 Client ID of type "Desktop app", enable the Drive API, request the `drive.appdata` scope. Replace `REPLACE_WITH_REAL_CLIENT_ID` with the actual ID before merging this commit. The client_id is **not a secret** — distributing it in source is the documented Google pattern for installed apps.

- [ ] **Step 2: Trigger scheduled sync after warm-up**

In `SoyleApp.start()` (or wherever `warm_up_transcriber` is called — find via grep), AFTER warm-up completes:

```python
if self._cloud_sync.should_run_scheduled():
    QTimer.singleShot(0, self._kick_scheduled_sync)
```

Add the helper method:

```python
def _kick_scheduled_sync(self) -> None:
    """Run cloud sync in a worker thread; surface only ACTION_REQUIRED toasts.

    Per spec §7: silent on transient failures, toast only when user must
    re-connect (auth revoked) or address a quota/suspension issue.
    """
    def runner() -> SyncOutcome:
        return asyncio.run(self._cloud_sync.sync_now()).outcome

    # Reuse the QThreadPool pattern from _InferenceJob — keep Qt main
    # thread responsive.
    runnable = _AsyncRunnable(
        coro=lambda: self._cloud_sync.sync_now(),
        on_done=self._handle_sync_outcome,
    )
    QThreadPool.globalInstance().start(runnable)


def _handle_sync_outcome(self, result: "SyncResult") -> None:
    """QueuedConnection-safe handler for sync completion."""
    from soyle.core.cloud_sync import SyncOutcome
    if result.outcome is SyncOutcome.AUTH_REVOKED:
        self._tray.toast(
            "Söyle",
            "Google Drive отключён. Подключи заново в Settings.",
            level="warning",
        )
    elif result.outcome is SyncOutcome.QUOTA:
        self._tray.toast(
            "Söyle",
            "Google Drive переполнен. Освободи место или disconnect.",
            level="warning",
        )
    elif result.outcome is SyncOutcome.APP_SUSPENDED:
        self._tray.toast(
            "Söyle — Google заблокировал приложение",
            "Контакт: andasbek.nurgysa@gmail.com",
            level="critical",
        )
    # NETWORK / OK / NOT_CONNECTED → silent.
```

You'll also need a small `_AsyncRunnable` adapter (or use existing patterns from `_InferenceJob`) to wrap an async coroutine into a `QRunnable`. If `_InferenceJob` is already a usable template, mirror its shape — see [app.py:41-72](../../../src/soyle/app.py).

- [ ] **Step 3: Reload dictionary into Transcriber/PostProcess after sync**

In `_handle_sync_outcome`, on `SyncOutcome.OK` if `result.added_local > 0`, refresh the in-memory hint:

```python
if result.outcome is SyncOutcome.OK and result.added_local > 0:
    self._transcriber.set_initial_prompt(self._dict_store.as_whisper_prompt())
    self._postprocess.set_dictionary_hint(self._dict_store.as_llm_instruction())
    self._tray.toast(
        "Söyle", f"Sync: добавлено {result.added_local} терминов.", level="info"
    )
```

- [ ] **Step 4: Smoke test**

```
uv run pytest tests/unit/ --tb=short
uv run python -c "from soyle.app import SoyleApp; print('imports OK')"
```

Expected: all unit tests still pass; import succeeds.

- [ ] **Step 5: Manual launch sanity**

```
uv run soyle
```

Verify Söyle starts without error. Without a real `client_id` it won't actually sync — that's expected. Watch logs for `cloud_sync_*` events.

- [ ] **Step 6: Commit (after `коммить` gate)**

```bash
git add src/soyle/app.py
git commit -m "$(cat <<'EOF'
feat(app): wire CloudSync into SoyleApp lifecycle

Instantiates CloudSync alongside other stores in SoyleApp.__init__.
After warm-up, if should_run_scheduled() is True, fires sync_now() on
a worker thread (mirroring _InferenceJob pattern). On completion:
- AUTH_REVOKED / QUOTA / APP_SUSPENDED → toast (warning/critical)
- OK with added_local > 0 → refresh Transcriber/PostProcess prompts +
  info toast
- NETWORK / NOT_CONNECTED / OK with no changes → silent

Includes a placeholder _GOOGLE_CLIENT_ID constant — must be replaced
with the real ID from the Söyle Google Cloud project before this
commit lands.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 14: First-run wizard — Drive sync prompt + restore flow

**Files:**
- Modify: `src/soyle/app.py` (extend `_show_first_run_wizard`)
- Test: manual (UI-driven; unit-testing modal dialogs is impractical, document in manual test plan instead)

- [ ] **Step 1: Extend the wizard**

In `src/soyle/app.py`, replace the current `_show_first_run_wizard` body with a sequence:

```python
def _show_first_run_wizard(self) -> None:
    self._show_settings()
    if self._settings_window is not None:
        self._settings_window.focus_api_key_setup()
    self._tray.toast(
        "Добро пожаловать в Söyle",
        "Вставьте OpenRouter API-ключ, чтобы включить полировку. "
        "Без ключа можно работать — получите сырую транскрипцию.",
    )
    log.info("first_run_wizard_shown")

    # New: offer Drive sync after a short delay so the user has time to
    # see the API key field (the original primary CTA).
    QTimer.singleShot(2000, self._offer_drive_sync_step)


def _offer_drive_sync_step(self) -> None:
    """Show a non-modal toast inviting the user to connect Drive.

    We use a toast + Settings flow rather than a blocking modal so the
    user can dismiss it by ignoring. Settings → Cloud Sync tab is where
    the actual Connect button lives (Task 15).
    """
    self._tray.toast(
        "Söyle — Cloud Sync",
        "Подключи Google Drive в Settings → Cloud Sync, чтобы синхронизировать "
        "словарь между устройствами и иметь backup.",
        level="info",
    )
```

> **Why a toast and not a modal:** modal dialogs in Qt during first-run mid-warm-up create focus-stealing race conditions with the Settings window we already opened. A toast is more polite and matches the existing `_show_first_run_wizard` style (which is already toast-based).

- [ ] **Step 2: Restore prompt after Connect button click**

The actual restore prompt fires from the Settings tab when the user clicks "Connect" — handled in Task 15. Here we just ensure `_show_settings` still works.

- [ ] **Step 3: Verify wizard still shows**

```
# Wipe config to trigger first-run again
rm "C:/Users/nurgisa/AppData/Roaming/Soyle/config.toml"
uv run soyle
# Verify: API key toast, then 2s later the Cloud Sync toast.
```

- [ ] **Step 4: Commit (after `коммить` gate)**

```bash
git add src/soyle/app.py
git commit -m "$(cat <<'EOF'
feat(app): extend first-run wizard with Drive sync invitation

Adds a second toast 2 seconds after the API-key prompt: "Подключи Google
Drive в Settings → Cloud Sync, чтобы синхронизировать словарь между
устройствами и иметь backup." Non-modal, dismissible by ignoring.

Settings → Cloud Sync tab (Task 15) hosts the Connect button + restore
flow. Modal dialogs during warm-up cause focus issues; toast pattern
matches existing wizard style.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 15: Settings UI — "Cloud Sync" tab

**Files:**
- Modify: `src/soyle/ui/settings.py` (add new tab)

- [ ] **Step 1: Add the tab building method**

Find the existing `_build_postprocess_tab` in `src/soyle/ui/settings.py` (around line 225) and add a new sibling method `_build_cloud_sync_tab` immediately after it. Then in `__init__` (or wherever tabs are added), include the new tab in the tab widget. Concrete code:

```python
def _build_cloud_sync_tab(self) -> QWidget:
    w = QWidget()
    layout = QVBoxLayout(w)

    # Status row
    self._cs_status_label = QLabel(self._cloud_sync_status_text())
    layout.addWidget(self._cs_status_label)

    # Last-sync timestamp
    self._cs_last_synced_label = QLabel(self._cloud_sync_last_synced_text())
    self._cs_last_synced_label.setStyleSheet("color: #888;")
    layout.addWidget(self._cs_last_synced_label)

    layout.addSpacing(16)

    # Action buttons — visibility depends on connection state.
    btn_row = QHBoxLayout()
    self._cs_connect_btn = QPushButton("Подключить Google Drive")
    self._cs_connect_btn.clicked.connect(self._on_cloud_sync_connect)

    self._cs_sync_now_btn = QPushButton("Sync now")
    self._cs_sync_now_btn.clicked.connect(self._on_cloud_sync_sync_now)

    self._cs_disconnect_btn = QPushButton("Disconnect")
    self._cs_disconnect_btn.clicked.connect(self._on_cloud_sync_disconnect)

    btn_row.addWidget(self._cs_connect_btn)
    btn_row.addWidget(self._cs_sync_now_btn)
    btn_row.addWidget(self._cs_disconnect_btn)
    btn_row.addStretch()
    layout.addLayout(btn_row)

    layout.addStretch()
    self._refresh_cloud_sync_buttons()
    return w


def _cloud_sync_status_text(self) -> str:
    if self._cloud_sync.is_connected:
        return "✓ Подключено к Google Drive"
    return "Не подключено"


def _cloud_sync_last_synced_text(self) -> str:
    last = self._cloud_sync.last_synced_at
    if last is None:
        return "Последняя синхронизация: никогда"
    # Format as local time, short.
    local = last.astimezone()
    return f"Последняя синхронизация: {local.strftime('%Y-%m-%d %H:%M')}"


def _refresh_cloud_sync_buttons(self) -> None:
    connected = self._cloud_sync.is_connected
    self._cs_connect_btn.setVisible(not connected)
    self._cs_sync_now_btn.setVisible(connected)
    self._cs_disconnect_btn.setVisible(connected)


def _on_cloud_sync_connect(self) -> None:
    """Kick off OAuth flow in a worker; on completion, offer restore."""
    # Reuse the same async-to-thread pattern as _kick_scheduled_sync.
    # Show progress toast while the browser is open.
    self._tray.toast(
        "Söyle — Cloud Sync",
        "Открыл браузер для авторизации в Google. Подтверди и вернись.",
        level="info",
    )
    runnable = _AsyncRunnable(
        coro=self._connect_and_maybe_restore,
        on_done=self._handle_connect_done,
    )
    QThreadPool.globalInstance().start(runnable)


async def _connect_and_maybe_restore(self) -> "RestoreOption | None":
    await self._cloud_sync.begin_oauth_flow()
    await self._cloud_sync.complete_oauth_flow()
    # Now check for existing backup.
    return await self._cloud_sync.detect_existing_backup()


def _handle_connect_done(
    self, result: "RestoreOption | None | Exception",
) -> None:
    if isinstance(result, Exception):
        self._tray.toast(
            "Söyle — Cloud Sync",
            f"Не удалось подключить Drive: {type(result).__name__}.",
            level="warning",
        )
        return
    self._refresh_cloud_sync_buttons()
    self._cs_status_label.setText(self._cloud_sync_status_text())
    if result is None:
        self._tray.toast(
            "Söyle — Cloud Sync", "Подключено. Backup начнётся автоматически.",
        )
        return
    # Restore prompt — modal QMessageBox is fine here; user already
    # interacted with the Connect button so focus context is clear.
    box = QMessageBox(self)
    box.setWindowTitle("Söyle — найден backup")
    box.setText(
        f"В Google Drive найден backup словаря: {result.term_count} терминов "
        f"(обновлён {result.last_modified.strftime('%Y-%m-%d')}).\n\n"
        f"Восстановить?"
    )
    box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
    if box.exec() == QMessageBox.Yes:
        self._on_cloud_sync_sync_now()


def _on_cloud_sync_sync_now(self) -> None:
    runnable = _AsyncRunnable(
        coro=self._cloud_sync.sync_now,
        on_done=self._handle_sync_now_done,
    )
    QThreadPool.globalInstance().start(runnable)


def _handle_sync_now_done(self, result) -> None:
    from soyle.core.cloud_sync import SyncOutcome
    if isinstance(result, Exception):
        self._tray.toast(
            "Söyle — Cloud Sync", f"Sync error: {result}", level="warning",
        )
        return
    if result.outcome is SyncOutcome.OK:
        self._cs_last_synced_label.setText(self._cloud_sync_last_synced_text())
        self._tray.toast(
            "Söyle",
            f"Sync OK. Локально +{result.added_local}, в Drive +{result.added_remote}.",
        )
    # Other outcomes are already handled by the SoyleApp-level handler;
    # in Settings we just refresh the timestamp label.


def _on_cloud_sync_disconnect(self) -> None:
    runnable = _AsyncRunnable(
        coro=self._cloud_sync.disconnect,
        on_done=lambda _: self._refresh_cloud_sync_buttons(),
    )
    QThreadPool.globalInstance().start(runnable)
```

- [ ] **Step 2: Register the tab**

Find where `_build_postprocess_tab` is added to a `QTabWidget` (search for `addTab`). Add immediately after:

```python
self._tabs.addTab(self._build_cloud_sync_tab(), "Cloud Sync")
```

- [ ] **Step 3: Inject `CloudSync` into `SettingsWindow`**

`SettingsWindow.__init__` already takes `store` and `tray`. Add `cloud_sync`:

```python
def __init__(
    self,
    *,
    cfg: Config,
    store: ConfigStore,
    dict_store: DictionaryStore,
    cloud_sync: CloudSync,  # NEW
    tray: TrayIcon,
    parent: QWidget | None = None,
) -> None:
    ...
    self._cloud_sync = cloud_sync
    ...
```

In `app.py` where `SettingsWindow` is instantiated, pass `cloud_sync=self._cloud_sync`.

- [ ] **Step 4: Manual smoke test**

```
uv run soyle
```

Open Settings → switch to Cloud Sync tab. Verify:
- "Не подключено" status shown
- "Последняя синхронизация: никогда" subtitle shown
- "Подключить Google Drive" button visible; the other two hidden
- Clicking Connect (after putting a real client_id in) opens browser to Google's consent

- [ ] **Step 5: Commit (after `коммить` gate)**

```bash
git add src/soyle/ui/settings.py src/soyle/app.py
git commit -m "$(cat <<'EOF'
feat(ui): add Cloud Sync tab to Settings

New tab with status label, last-synced timestamp, and Connect / Sync
now / Disconnect buttons (visibility depends on connection state).
Connect kicks off the OAuth PKCE flow on a worker thread; if a backup
exists in Drive, prompts a modal to restore it.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 16: Manual test plan documentation

**Files:**
- Create: `docs/testing/cloud-sync-manual.md`

- [ ] **Step 1: Write the manual test plan**

Create the file with this content:

```markdown
# Cloud Sync — Manual Test Plan (Phase 1)

These checks supplement the unit-test suite (`tests/unit/test_cloud_sync.py`).
They cover behaviors that depend on real OAuth, real Drive, real Windows,
or real PyInstaller bundles — none of which are practical to automate.

## Pre-conditions

- Real Google account with Drive enabled and quota < 100% used.
- Söyle's `_GOOGLE_CLIENT_ID` set to a Desktop-app OAuth client in the
  `nurgysa` Google Cloud project, with Drive API enabled and `drive.appdata`
  scope registered.
- Test machine: Windows 10/11 x64.

## Checklist

### A. Fresh OAuth flow

- [ ] Wipe state: delete `%APPDATA%\Soyle\config.toml`, `dictionary.toml`,
      and any `Söyle Cloud` Credential Manager entry.
- [ ] Launch Söyle (`uv run soyle`).
- [ ] First-run wizard shows API-key toast + Cloud Sync toast.
- [ ] Open Settings → Cloud Sync. Click **Подключить Google Drive**.
- [ ] Browser opens to `accounts.google.com/...`. Verify:
  - App name shown is "Söyle" (from Google Cloud project config).
  - Scope shown is "View and manage its own configuration data in your
    Google Drive" (the `drive.appdata` scope's user-visible label).
- [ ] Authorize. Browser shows "Söyle подключён к Google Drive ✓"
      confirmation page.
- [ ] Settings tab updates: status flips to "✓ Подключено", buttons
      change to Sync now + Disconnect.

### B. First-ever upload (no backup yet)

- [ ] Add a few terms via Settings → Dictionary tab (e.g. "Söyle",
      "Astana", "OpenRouter").
- [ ] Click **Sync now**.
- [ ] Watch `%APPDATA%\Soyle\logs\soyle.log` for `cloud_sync_ok` event
      with `added_remote=3, added_local=0`.
- [ ] In Google Drive web UI, confirm App Data folder is NOT visible in
      "My Drive" (it shouldn't be — that's the whole point of `drive.appdata`).
- [ ] Disconnect. Reconnect. Verify restore prompt appears with "3 терминов".

### C. Cross-device restore

- [ ] On a SECOND Windows machine (or VM, or after wiping `%APPDATA%\Soyle`):
- [ ] Launch Söyle, first-run wizard fires.
- [ ] Settings → Cloud Sync → Connect with the SAME Google account.
- [ ] Restore prompt appears: "В Google Drive найден backup словаря: N
      терминов".
- [ ] Click Yes. Toast confirms restoration. Settings → Dictionary tab
      shows the terms.

### D. Daily-cadence trigger

- [ ] With `last_synced_at` < 24h ago: launch Söyle → no auto-sync (nothing
      in logs about `cloud_sync_*`).
- [ ] Manually edit `config.toml` to set `last_synced_at` to 30 hours ago.
- [ ] Re-launch Söyle → log shows `cloud_sync_ok` automatically after warm-up.

### E. Auth revoked

- [ ] Go to https://myaccount.google.com/permissions.
- [ ] Find Söyle. Click "Remove access".
- [ ] Wait ~1 minute, then in Söyle click Sync now.
- [ ] Toast appears: "Google Drive отключён. Подключи заново в Settings."
- [ ] Settings tab status flips to "Не подключено". Buttons change.

### F. Edge cases

- [ ] **Browser closed without authorizing:** click Connect, close the
      browser tab without clicking Authorize. After 120s a generic error
      toast should appear; Söyle stays usable.
- [ ] **Network down at sync time:** disable network, click Sync now.
      No toast (silent). `soyle.log` shows `cloud_sync_network_error`.
      Re-enable network, click Sync now → succeeds.
- [ ] **PyInstaller-built binary** (after `scripts/build_installer.py`):
      verify firewall doesn't pop a warning when the localhost listener
      starts.

## Out of scope

- Multi-account switching (Phase 4 feature).
- Real-time propagation (Phase 3).
- Encryption beyond Google's defaults (Phase 3+).
```

- [ ] **Step 2: Commit (after `коммить` gate)**

```bash
git add docs/testing/cloud-sync-manual.md
git commit -m "$(cat <<'EOF'
docs(cloud_sync): add manual test plan for Phase 1

Covers behaviors not automatable: real OAuth consent screen, Drive web
UI verification, cross-device restore, auth-revoked toast, network
failures, and PyInstaller firewall behavior.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Self-review

After writing all 16 tasks, I checked the plan against the spec:

**1. Spec coverage:** Every spec section has a task.
- §4 design decisions → locked into the architecture (Task 7+) and config (Task 2)
- §5 architecture & components → Tasks 3-12, 13, 15
- §6 data flow (OAuth, sync, restore, disconnect) → Tasks 11, 10, 12, 12
- §7 error handling matrix → Task 10's tests + classification helper
- §8 testing strategy → covered by per-task TDD steps + Task 16 (manual)
- §9 future phases → out of scope here, by design

**2. Placeholder scan:** Removed all "TBD"/"TODO" patterns. The only
intentional remainder is `_GOOGLE_CLIENT_ID = "REPLACE_WITH_REAL_CLIENT_ID..."`
in Task 13, flagged with an explicit out-of-band action item for the
maintainer (creating the Google Cloud project happens in a browser, not
in code).

**3. Type consistency:** Verified `_TokenPair`, `RestoreOption`,
`SyncResult`, `SyncOutcome` named consistently across tasks. Method
signatures match between definition (Task 7) and call sites (Tasks
10-15). `_oauth_listener` and `_oauth_verifier` declared in Task 11's
__init__ update.

**4. Dependency order:** Tasks build incrementally — each can be
shipped/committed independently leaving the codebase tested and working.
Task N requires only Tasks 1..N-1 plus the spec.

---

**Total:** 16 tasks, ~25-30 unit tests, 0 new pip dependencies, ~1500 lines
of new code split across 1 new module + 4 modified files. Estimated
effort: 13-15 hours of focused work.
