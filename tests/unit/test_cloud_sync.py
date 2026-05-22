"""Tests for CloudSync — Google Drive sync of dictionary.toml."""
from __future__ import annotations

import base64
import hashlib
import threading
import uuid as _uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode
from urllib.request import urlopen

import httpx
import pytest
import respx

from soyle.core.cloud_sync import (
    DRIVE_API_BASE,
    DRIVE_FILE_NAME,
    DRIVE_UPLOAD_BASE,
    KEYRING_SERVICE,
    KEYRING_USERNAME,
    OAUTH_REVOKE_URL,
    OAUTH_TOKEN_URL,
    CloudSync,
    DriveConcurrentWriteError,
    DriveCorruptedError,
    RestoreOption,
    SyncOutcome,
    _derive_code_challenge,
    _drive_get_dictionary,
    _drive_put_dictionary,
    _drive_rename_corrupted,
    _exchange_code_for_tokens,
    _generate_code_verifier,
    _OAuthCallbackListener,
    _refresh_access_token,
    _TokenStore,
)
from soyle.core.errors import OAuthAuthRevokedError


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


def test_callback_listener_times_out_when_no_callback() -> None:
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


@pytest.mark.asyncio
@respx.mock
async def test_exchange_code_never_sends_client_secret() -> None:
    """PKCE security contract: the binary must NOT ship a client_secret.

    A regression that adds client_secret to the payload would silently
    ship undetected by other tests. This test captures the actual POST
    body and asserts the field is absent — locking the contract.
    """
    from urllib.parse import parse_qsl

    route = respx.post(OAUTH_TOKEN_URL).mock(
        return_value=httpx.Response(
            200, json={"access_token": "x", "refresh_token": "y"}
        )
    )
    await _exchange_code_for_tokens(
        client_id="cid",
        code="auth-code",
        code_verifier="verifier-value",
        redirect_uri="http://localhost:1234/callback",
    )
    sent_body = dict(parse_qsl(route.calls.last.request.content.decode("utf-8")))
    assert "client_secret" not in sent_body
    # Verify code_verifier IS sent (the PKCE replacement for client_secret).
    assert sent_body["code_verifier"] == "verifier-value"


@pytest.mark.asyncio
@respx.mock
async def test_refresh_access_token_never_sends_client_secret() -> None:
    """Same PKCE contract on the refresh path."""
    from urllib.parse import parse_qsl

    route = respx.post(OAUTH_TOKEN_URL).mock(
        return_value=httpx.Response(
            200, json={"access_token": "x"}
        )
    )
    await _refresh_access_token(client_id="cid", refresh_token="1//refresh")
    sent_body = dict(parse_qsl(route.calls.last.request.content.decode("utf-8")))
    assert "client_secret" not in sent_body


@pytest.mark.asyncio
@respx.mock
async def test_refresh_access_token_logs_structured_error_for_non_invalid_grant_4xx() -> None:
    """Non-invalid_grant 4xx must surface the structured error code in logs.

    Without this, debugging a misconfigured-client-id incident
    (`error=invalid_client`) is indistinguishable from a generic 400 in
    soyle.log.
    """
    respx.post(OAUTH_TOKEN_URL).mock(
        return_value=httpx.Response(
            400,
            json={"error": "invalid_client", "error_description": "wrong client"},
        )
    )
    # Using mocker isn't necessary — we just assert the httpx.HTTPStatusError
    # propagates with the body still inspectable via .response.
    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        await _refresh_access_token(client_id="cid", refresh_token="1//refresh")
    # The body remains accessible for downstream debugging.
    assert exc_info.value.response.json()["error"] == "invalid_client"


# ---- _TokenStore (Task 6) ---------------------------------------------------


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


# ---- CloudSync skeleton + state predicates (Task 7) -------------------------


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


def test_is_configured_true_for_real_client_id(cloud_sync) -> None:
    """Real-looking client_id (the test fixture's value) → is_configured True."""
    assert cloud_sync.is_configured is True


def test_is_configured_false_for_placeholder(tmp_path, mocker) -> None:
    """The literal placeholder shipped in app.py → is_configured False.

    Guards against codex P1 on PR #16: with the placeholder, all Google
    OAuth calls fail with invalid_client. Detect it explicitly so the
    Settings UI can surface a clear error instead of routing the user
    to a confused Google consent page.
    """
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
    cs = CloudSync(
        dict_store=DictionaryStore(path=tmp_path / "dict.toml"),
        config_store=ConfigStore(config_path=tmp_path / "config.toml"),
        client_id="REPLACE_WITH_REAL_CLIENT_ID.apps.googleusercontent.com",
    )
    assert cs.is_configured is False


@pytest.mark.asyncio
async def test_begin_oauth_flow_rejects_placeholder_client_id(
    tmp_path, mocker,
) -> None:
    """begin_oauth_flow must fail-fast with a clear error, not open the
    browser to a Google page that says 'OAuth client was not found'."""
    from soyle.core.config import ConfigStore
    from soyle.core.dictionary import DictionaryStore

    mocker.patch("soyle.core.cloud_sync.webbrowser.open")
    backing: dict[tuple[str, str], str] = {}
    mocker.patch(
        "soyle.core.cloud_sync.keyring.set_password",
        side_effect=lambda s, u, p: backing.update({(s, u): p}),
    )
    mocker.patch(
        "soyle.core.cloud_sync.keyring.get_password",
        side_effect=lambda s, u: backing.get((s, u)),
    )
    cs = CloudSync(
        dict_store=DictionaryStore(path=tmp_path / "dict.toml"),
        config_store=ConfigStore(config_path=tmp_path / "config.toml"),
        client_id="REPLACE_WITH_REAL_CLIENT_ID.apps.googleusercontent.com",
    )
    with pytest.raises(RuntimeError, match="not configured"):
        await cs.begin_oauth_flow()


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


# ---- Drive REST primitives: GET (Task 8) ------------------------------------


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
            content=b'version = 1\nterms = ["S\xc3\xb6yle", "Astana"]\n',
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


@pytest.mark.asyncio
@respx.mock
async def test_drive_get_excludes_trashed_files() -> None:
    """Drive files.list returns trashed items by default — must exclude them.

    Without `trashed=false`, a trashed dictionary.toml (user deleted in Drive
    UI but still in Trash) can be returned ahead of the live file, leading
    sync to read/update the wrong file and produce stale or corrupted state.
    """
    route = respx.get(f"{DRIVE_API_BASE}/files").mock(
        return_value=httpx.Response(200, json={"files": []})
    )
    await _drive_get_dictionary(access_token="ya29.x")
    assert route.called
    q_param = route.calls[0].request.url.params.get("q")
    assert q_param is not None
    assert "trashed=false" in q_param
    # Filename predicate must remain — exclusion is additive, not a replacement.
    assert f"name='{DRIVE_FILE_NAME}'" in q_param


# ---- Drive REST primitives: PUT + rename (Task 9) ---------------------------


@pytest.mark.asyncio
@respx.mock
async def test_drive_put_creates_new_file_when_no_id() -> None:
    """First sync: no existing file → multipart create."""
    respx.post(
        f"{DRIVE_API_BASE.replace('drive/v3', 'upload/drive/v3')}/files"
    ).mock(return_value=httpx.Response(200, json={"id": "new-file-id"}))
    new_id = await _drive_put_dictionary(
        access_token="ya29.x", file_id=None, etag=None, terms=["A", "B"]
    )
    assert new_id == "new-file-id"


@pytest.mark.asyncio
@respx.mock
async def test_drive_put_updates_existing_with_etag() -> None:
    """Subsequent sync: file_id known, If-Match guard set."""
    file_id = "existing-id"
    upload_url = (
        f"{DRIVE_API_BASE.replace('drive/v3', 'upload/drive/v3')}/files/{file_id}"
    )
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
    upload_url = (
        f"{DRIVE_API_BASE.replace('drive/v3', 'upload/drive/v3')}/files/{file_id}"
    )
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


# ---- sync_now() merge cycle (Task 10) ---------------------------------------


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
        return_value=httpx.Response(200, json={"files": []})
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
        return_value=httpx.Response(200, json={"files": [{"id": "id-x"}]})
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
        return_value=httpx.Response(200, json={"files": [{"id": "id-1"}]})
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
async def test_sync_now_returns_network_on_connect_error(cloud_sync) -> None:
    """Transient network error — silent fallback, no token clear."""
    cloud_sync._token_store.save("1//refresh")
    respx.post(OAUTH_TOKEN_URL).mock(side_effect=httpx.ConnectError("DNS"))

    result = await cloud_sync.sync_now()
    assert result.outcome is SyncOutcome.NETWORK
    assert cloud_sync.is_connected is True  # token still there
    assert cloud_sync.last_synced_at is None  # didn't update timestamp


@pytest.mark.asyncio
@respx.mock
async def test_sync_now_returns_auth_revoked_and_clears_keyring(cloud_sync) -> None:
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
        return_value=httpx.Response(200, json={"files": [{"id": "broken"}]})
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
    respx.get(f"{DRIVE_API_BASE}/files").mock(
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


@pytest.mark.asyncio
@respx.mock
async def test_sync_now_bounds_412_retries_to_avoid_recursion(cloud_sync) -> None:
    """Repeated 412s must not recurse without bound — fall back to NETWORK.

    Without a cap, two devices racing on writes can keep producing 412s and
    push Python past its recursion limit (RecursionError terminates sync
    instead of returning a controlled outcome). Bounded retry: after
    MAX_SYNC_RETRIES attempts we surrender silently and the next scheduled
    cycle retries naturally.
    """
    from soyle.core.cloud_sync import MAX_SYNC_RETRIES

    cloud_sync._token_store.save("1//refresh")
    cloud_sync._dict_store.save(["A"])

    respx.post(OAUTH_TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "ya29.x"})
    )
    respx.get(f"{DRIVE_API_BASE}/files").mock(
        return_value=httpx.Response(200, json={"files": [{"id": "x"}]})
    )
    respx.get(f"{DRIVE_API_BASE}/files/x").mock(
        return_value=httpx.Response(
            200,
            content=b'version=1\nterms=["B"]\n',
            headers={"ETag": '"e1"'},
        )
    )
    patch_route = respx.patch(f"{DRIVE_UPLOAD_BASE}/files/x").mock(
        return_value=httpx.Response(412, json={"error": "precondition"})
    )

    result = await cloud_sync.sync_now()
    assert result.outcome is SyncOutcome.NETWORK
    # Attempts == MAX (initial + retries up to the cap).
    assert patch_route.call_count == MAX_SYNC_RETRIES


@pytest.mark.asyncio
@respx.mock
async def test_lookup_file_id_excludes_trashed_files(cloud_sync) -> None:
    """Defensive guard: _lookup_file_id must filter trashed too.

    The same bug pattern PR #11 fixed in _drive_get_dictionary applies here:
    listing without `trashed=false` can return a trashed dictionary.toml and
    cause sync to update the wrong file. Pin the query shape.
    """
    route = respx.get(f"{DRIVE_API_BASE}/files").mock(
        return_value=httpx.Response(200, json={"files": []})
    )
    result = await cloud_sync._lookup_file_id("ya29.x")
    assert result is None
    assert route.called
    q_param = route.calls[0].request.url.params.get("q")
    assert q_param is not None
    assert "trashed=false" in q_param
    assert f"name='{DRIVE_FILE_NAME}'" in q_param


# ---- OAuth orchestration: begin_oauth_flow + complete_oauth_flow -----------


@pytest.mark.asyncio
@respx.mock
async def test_begin_oauth_flow_returns_auth_url_and_starts_listener(
    cloud_sync, mocker,
) -> None:
    mocker.patch("soyle.core.cloud_sync.webbrowser.open")
    auth_url = await cloud_sync.begin_oauth_flow()
    try:
        assert auth_url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
        assert "client_id=test-client-id" in auth_url
        assert "code_challenge=" in auth_url
        assert "code_challenge_method=S256" in auth_url
        assert (
            "scope=https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fdrive.appdata"
            in auth_url
        )
        assert "access_type=offline" in auth_url
        assert "prompt=consent" in auth_url
        assert "redirect_uri=http%3A%2F%2Flocalhost%3A" in auth_url

        # listener has been started (port assigned)
        assert cloud_sync._oauth_listener is not None
        assert cloud_sync._oauth_listener.port > 1024
    finally:
        if cloud_sync._oauth_listener is not None:
            cloud_sync._oauth_listener.shutdown()


@pytest.mark.asyncio
@respx.mock
async def test_complete_oauth_flow_exchanges_code_and_stores_token(
    cloud_sync, mocker,
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
    callback_url = (
        f"{cloud_sync._oauth_listener.redirect_uri}?code=AUTH_CODE_X"
    )
    threading.Thread(
        target=lambda: urlopen(callback_url, timeout=2), daemon=True,
    ).start()

    await cloud_sync.complete_oauth_flow()

    assert cloud_sync.is_connected is True
    assert cloud_sync._token_store.load() == "1//refresh-stored"


# ---- detect_existing_backup + disconnect -----------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_detect_existing_backup_returns_none_when_no_file(
    cloud_sync,
) -> None:
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
            200, content=b'version = 1\nterms = ["A", "B", "C"]\n',
        )
    )

    result = await cloud_sync.detect_existing_backup()
    assert result is not None
    assert isinstance(result, RestoreOption)
    assert result.term_count == 3
    assert result.last_modified.isoformat().startswith("2026-04-29T10:00:00")


@pytest.mark.asyncio
@respx.mock
async def test_detect_existing_backup_excludes_trashed_files(cloud_sync) -> None:
    """Defensive guard mirroring _drive_get_dictionary (fixed in PR #11):
    without trashed=false, Drive returns user-trashed-but-not-purged
    backups and detection resolves to the wrong file.
    """
    cloud_sync._token_store.save("1//refresh")
    respx.post(OAUTH_TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "ya29.x"})
    )
    route = respx.get(f"{DRIVE_API_BASE}/files").mock(
        return_value=httpx.Response(200, json={"files": []})
    )
    await cloud_sync.detect_existing_backup()
    assert route.called
    q_param = route.calls[0].request.url.params.get("q")
    assert q_param is not None
    assert "trashed=false" in q_param
    assert f"name='{DRIVE_FILE_NAME}'" in q_param


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


# ---- Device identity ----

def test_device_id_generated_on_first_call_when_keyring_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """First call generates a UUID and persists it to keyring."""
    from soyle.core import cloud_sync as cs

    stored: dict[tuple[str, str], str] = {}
    monkeypatch.setattr(
        cs.keyring, "get_password",
        lambda service, user: stored.get((service, user)),
    )
    monkeypatch.setattr(
        cs.keyring, "set_password",
        lambda service, user, pwd: stored.__setitem__((service, user), pwd),
    )

    result = cs._device_id()

    # Full canonical UUID4 format check (validates all 4 dashes + version byte)
    assert _uuid.UUID(result).version == 4
    assert stored == {("Söyle", "device-id"): result}


def test_device_id_persisted_across_restarts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Second call returns the same UUID from keyring — no regeneration."""
    from soyle.core import cloud_sync as cs

    stored: dict[tuple[str, str], str] = {
        ("Söyle", "device-id"): "11111111-2222-3333-4444-555555555555",
    }
    monkeypatch.setattr(
        cs.keyring, "get_password",
        lambda service, user: stored.get((service, user)),
    )
    set_calls = []
    monkeypatch.setattr(
        cs.keyring, "set_password",
        lambda service, user, pwd: set_calls.append((service, user, pwd)),
    )

    result = cs._device_id()

    assert result == "11111111-2222-3333-4444-555555555555"
    assert set_calls == []


# ---- Device identity: keyring failure fallback ----

def test_device_id_falls_back_to_process_uuid_when_get_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """KeyringError on get_password → in-memory fallback UUID, no crash."""
    from soyle.core import cloud_sync as cs

    def raising_get(service: str, user: str) -> str | None:
        raise cs.keyring.errors.KeyringError("backend unavailable")

    monkeypatch.setattr(cs.keyring, "get_password", raising_get)
    monkeypatch.setattr(cs, "_DEVICE_ID_FALLBACK", None)  # reset cache
    monkeypatch.setattr(cs, "_DEVICE_ID_LAST_KNOWN", None)

    result = cs._device_id()

    # Valid UUID4 — fallback succeeded
    assert _uuid.UUID(result).version == 4


def test_device_id_falls_back_to_process_uuid_when_set_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """KeyringError on set_password → in-memory fallback UUID, no crash."""
    from soyle.core import cloud_sync as cs

    monkeypatch.setattr(
        cs.keyring, "get_password",
        lambda service, user: None,  # nothing stored
    )

    def raising_set(service: str, user: str, pwd: str) -> None:
        raise cs.keyring.errors.KeyringError("backend write-locked")

    monkeypatch.setattr(cs.keyring, "set_password", raising_set)
    monkeypatch.setattr(cs, "_DEVICE_ID_FALLBACK", None)
    monkeypatch.setattr(cs, "_DEVICE_ID_LAST_KNOWN", None)

    result = cs._device_id()
    assert _uuid.UUID(result).version == 4


def test_device_id_fallback_is_stable_within_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two calls under keyring failure return the SAME fallback UUID
    — usage tracking stays consistent within a single Söyle run."""
    from soyle.core import cloud_sync as cs

    def raising_get(service: str, user: str) -> str | None:
        raise cs.keyring.errors.KeyringError("backend unavailable")

    monkeypatch.setattr(cs.keyring, "get_password", raising_get)
    monkeypatch.setattr(cs, "_DEVICE_ID_FALLBACK", None)
    monkeypatch.setattr(cs, "_DEVICE_ID_LAST_KNOWN", None)

    first = cs._device_id()
    second = cs._device_id()
    assert first == second  # cached after first call


def test_device_id_no_keyring_error_subclass_also_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """NoKeyringError (subclass of KeyringError) should also trigger fallback,
    not crash."""
    from soyle.core import cloud_sync as cs

    def raising_get(service: str, user: str) -> str | None:
        raise cs.keyring.errors.NoKeyringError("no backend configured")

    monkeypatch.setattr(cs.keyring, "get_password", raising_get)
    monkeypatch.setattr(cs, "_DEVICE_ID_FALLBACK", None)
    monkeypatch.setattr(cs, "_DEVICE_ID_LAST_KNOWN", None)

    result = cs._device_id()
    assert _uuid.UUID(result).version == 4


# ---- Device identity: transient-failure consistency ----

def test_device_id_returns_last_known_after_transient_keyring_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same process: successful read → transient KeyringError → must
    return the SAME real ID, not mint a new fallback."""
    from soyle.core import cloud_sync as cs

    real_id = "11111111-2222-3333-4444-555555555555"
    call_count = {"n": 0}

    def flaky_get(service: str, user: str) -> str | None:
        call_count["n"] += 1
        if call_count["n"] == 1:
            return real_id  # first call succeeds
        raise cs.keyring.errors.KeyringError("transient")  # rest fail

    monkeypatch.setattr(cs.keyring, "get_password", flaky_get)
    monkeypatch.setattr(cs, "_DEVICE_ID_FALLBACK", None)
    monkeypatch.setattr(cs, "_DEVICE_ID_LAST_KNOWN", None)

    first = cs._device_id()  # successful read
    second = cs._device_id()  # transient failure
    third = cs._device_id()  # still failing

    assert first == real_id
    assert second == real_id  # reused last-known, NOT a fresh UUID
    assert third == real_id


def test_device_id_cold_start_fallback_replaced_by_real_id_when_keyring_recovers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cold start with broken keyring → fallback used. Once keyring
    recovers and we read a real ID, subsequent failures must return
    the REAL id, not the original cold-start fallback."""
    from soyle.core import cloud_sync as cs

    real_id = "11111111-2222-3333-4444-555555555555"
    call_count = {"n": 0}

    def staged_get(service: str, user: str) -> str | None:
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise cs.keyring.errors.KeyringError("cold start fail")
        if call_count["n"] == 2:
            return real_id  # recovered
        raise cs.keyring.errors.KeyringError("flaky again")

    monkeypatch.setattr(cs.keyring, "get_password", staged_get)
    monkeypatch.setattr(cs, "_DEVICE_ID_FALLBACK", None)
    monkeypatch.setattr(cs, "_DEVICE_ID_LAST_KNOWN", None)

    cold_fallback = cs._device_id()  # cold-start fallback minted
    recovered = cs._device_id()       # real ID seen
    after_recovery_fail = cs._device_id()  # keyring fails again

    assert _uuid.UUID(cold_fallback).version == 4
    assert recovered == real_id
    # After we saw a real ID, transient failures use the real ID,
    # NOT the original cold-start fallback.
    assert after_recovery_fail == real_id
    assert after_recovery_fail != cold_fallback


def test_device_id_set_failure_path_also_populates_last_known(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If a fresh device mints a UUID and set_password fails, the
    minted ID becomes both the fallback AND the last-known so that
    a subsequent read-fail returns the same value."""
    from soyle.core import cloud_sync as cs

    monkeypatch.setattr(
        cs.keyring, "get_password",
        lambda service, user: None,  # never persisted
    )

    def raising_set(service: str, user: str, pwd: str) -> None:
        raise cs.keyring.errors.KeyringError("write blocked")

    monkeypatch.setattr(cs.keyring, "set_password", raising_set)
    monkeypatch.setattr(cs, "_DEVICE_ID_FALLBACK", None)
    monkeypatch.setattr(cs, "_DEVICE_ID_LAST_KNOWN", None)

    first = cs._device_id()
    # Now make get_password fail too, so we hit the read-fail path
    def raising_get(service: str, user: str) -> str | None:
        raise cs.keyring.errors.KeyringError("now read-broken")
    monkeypatch.setattr(cs.keyring, "get_password", raising_get)

    second = cs._device_id()
    assert second == first  # stable across both failure paths


def test_device_id_set_failure_preserves_active_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When _DEVICE_ID_FALLBACK is already set from an earlier read
    outage and the set-fail path runs with a different new_id, the
    function must return the existing fallback AND keep the cache in
    sync. A subsequent read failure must return the SAME fallback,
    not the unreturned new_id from the set-fail branch."""
    from soyle.core import cloud_sync as cs

    # Simulate: earlier read failure already established _DEVICE_ID_FALLBACK
    monkeypatch.setattr(cs, "_DEVICE_ID_FALLBACK", "fallback-A")
    monkeypatch.setattr(cs, "_DEVICE_ID_LAST_KNOWN", None)

    # First call: get_password returns None (recovered backend but empty
    # keyring), set_password fails — the set-fail branch runs with a new_id
    # that is NOT returned (we return the pre-existing fallback instead).
    monkeypatch.setattr(cs.keyring, "get_password", lambda s, u: None)

    def raising_set(service: str, user: str, pwd: str) -> None:
        raise cs.keyring.errors.KeyringError("write blocked")

    monkeypatch.setattr(cs.keyring, "set_password", raising_set)

    first = cs._device_id()
    assert first == "fallback-A"

    # Second call: keyring fails on read — must STILL return "fallback-A",
    # not the new_id minted (and discarded) in the set-fail path on the
    # first call.
    def raising_get(service: str, user: str) -> str | None:
        raise cs.keyring.errors.KeyringError("read fail")

    monkeypatch.setattr(cs.keyring, "get_password", raising_get)

    second = cs._device_id()
    assert second == "fallback-A"
    assert second == first


# ---- Task 4: deny-list + dotted-path helpers ----

def test_config_deny_list_contains_expected_device_local_paths() -> None:
    from soyle.core import cloud_sync as cs
    expected = {
        "version",
        "audio.device",
        "whisper.model",
        "whisper.device",
        "whisper.compute_type",
        "behavior.autostart",
        "behavior.inject_method",
        "ui.theme",
        "cloud_sync",
    }
    assert frozenset(expected) == cs._CONFIG_DENY_LIST


def test_get_dotted_returns_value_at_nested_path() -> None:
    from soyle.core.cloud_sync import _get_dotted
    data = {"hotkey": {"combination": "right alt", "mode": "push_to_talk"}}
    assert _get_dotted(data, "hotkey.combination") == "right alt"


def test_get_dotted_returns_top_level_value_for_single_segment() -> None:
    from soyle.core.cloud_sync import _get_dotted
    data = {"version": 1, "hotkey": {"combination": "right alt"}}
    assert _get_dotted(data, "version") == 1


def test_get_dotted_returns_none_when_path_missing() -> None:
    from soyle.core.cloud_sync import _get_dotted
    data = {"hotkey": {"combination": "right alt"}}
    assert _get_dotted(data, "audio.device") is None
    assert _get_dotted(data, "hotkey.nonexistent") is None


def test_set_dotted_creates_intermediate_dicts_when_missing() -> None:
    from soyle.core.cloud_sync import _set_dotted
    data: dict = {}
    _set_dotted(data, "audio.device", "default")
    assert data == {"audio": {"device": "default"}}


def test_set_dotted_overwrites_existing_value() -> None:
    from soyle.core.cloud_sync import _set_dotted
    data: dict = {"audio": {"device": "old"}}
    _set_dotted(data, "audio.device", "new")
    assert data["audio"]["device"] == "new"


def test_set_dotted_handles_top_level_path() -> None:
    from soyle.core.cloud_sync import _set_dotted
    data: dict = {"hotkey": {"combination": "alt"}}
    _set_dotted(data, "version", 2)
    assert data["version"] == 2


def test_del_dotted_removes_leaf_value() -> None:
    from soyle.core.cloud_sync import _del_dotted
    data: dict = {"audio": {"device": "default", "sample_rate": 16000}}
    _del_dotted(data, "audio.device")
    assert data == {"audio": {"sample_rate": 16000}}


def test_del_dotted_removes_entire_section_when_path_is_section_root() -> None:
    """Deleting 'cloud_sync' removes the whole [cloud_sync] section."""
    from soyle.core.cloud_sync import _del_dotted
    data: dict = {
        "hotkey": {"combination": "alt"},
        "cloud_sync": {"last_synced_at": "2026-05-22T10:00:00+00:00"},
    }
    _del_dotted(data, "cloud_sync")
    assert "cloud_sync" not in data
    assert "hotkey" in data


def test_del_dotted_silent_when_path_missing() -> None:
    """No-op (no exception) if the path doesn't exist."""
    from soyle.core.cloud_sync import _del_dotted
    data: dict = {"hotkey": {"combination": "alt"}}
    _del_dotted(data, "audio.device")  # should not raise
    assert data == {"hotkey": {"combination": "alt"}}


# ---- Task 5: _strip_deny ----

def _make_config_with_overrides(**overrides: object):
    """Build a Config with selected non-default fields. Returns the Config."""
    from soyle.core.config import (
        AudioConfig,
        BehaviorConfig,
        CloudSyncConfig,
        Config,
        HotkeyConfig,
        PostProcessConfig,
        UIConfig,
        WhisperConfig,
    )
    cfg = Config(
        hotkey=HotkeyConfig(**overrides.get("hotkey", {})),
        audio=AudioConfig(**overrides.get("audio", {})),
        whisper=WhisperConfig(**overrides.get("whisper", {})),
        postprocess=PostProcessConfig(**overrides.get("postprocess", {})),
        ui=UIConfig(**overrides.get("ui", {})),
        behavior=BehaviorConfig(**overrides.get("behavior", {})),
        cloud_sync=CloudSyncConfig(**overrides.get("cloud_sync", {})),
    )
    return cfg


def test_strip_deny_removes_all_listed_dotted_paths() -> None:
    from soyle.core.cloud_sync import _strip_deny

    cfg = _make_config_with_overrides(
        audio={"device": "MyMic"},
        whisper={"model": "large-v3", "device": "cuda", "compute_type": "float16"},
        behavior={"autostart": True, "inject_method": "keystroke"},
        ui={"theme": "light"},
    )
    stripped = _strip_deny(cfg)

    assert "version" not in stripped
    assert "device" not in stripped.get("audio", {})
    assert "model" not in stripped.get("whisper", {})
    assert "device" not in stripped.get("whisper", {})
    assert "compute_type" not in stripped.get("whisper", {})
    assert "autostart" not in stripped.get("behavior", {})
    assert "inject_method" not in stripped.get("behavior", {})
    assert "theme" not in stripped.get("ui", {})
    assert "cloud_sync" not in stripped


def test_strip_deny_preserves_synced_fields() -> None:
    from soyle.core.cloud_sync import _strip_deny

    cfg = _make_config_with_overrides(
        hotkey={"combination": "ctrl+shift"},
        postprocess={"mode": "rewrite", "model": "google/gemini-2.5-flash"},
        ui={"sound_enabled": False},
    )
    stripped = _strip_deny(cfg)

    assert stripped["hotkey"]["combination"] == "ctrl+shift"
    assert stripped["postprocess"]["mode"] == "rewrite"
    assert stripped["postprocess"]["model"] == "google/gemini-2.5-flash"
    assert stripped["ui"]["sound_enabled"] is False


def test_strip_deny_returns_dict_not_pydantic_model() -> None:
    """Returns a plain dict (Pydantic dump shape) suitable for TOML serialize."""
    from soyle.core.cloud_sync import _strip_deny
    cfg = _make_config_with_overrides()
    stripped = _strip_deny(cfg)
    assert isinstance(stripped, dict)


# ---- Task 6: _merge_config ----

def test_merge_config_remote_wins_when_remote_mtime_newer() -> None:
    from soyle.core.cloud_sync import _merge_config

    local = _make_config_with_overrides(hotkey={"combination": "alt"})
    remote = _make_config_with_overrides(hotkey={"combination": "ctrl"})
    local_mtime = datetime(2026, 5, 22, 10, 0, 0, tzinfo=UTC)
    remote_mtime = datetime(2026, 5, 22, 11, 0, 0, tzinfo=UTC)

    merged = _merge_config(local, remote, local_mtime, remote_mtime)
    assert merged.hotkey.combination == "ctrl"


def test_merge_config_local_wins_when_local_mtime_newer() -> None:
    from soyle.core.cloud_sync import _merge_config

    local = _make_config_with_overrides(hotkey={"combination": "alt"})
    remote = _make_config_with_overrides(hotkey={"combination": "ctrl"})
    local_mtime = datetime(2026, 5, 22, 11, 0, 0, tzinfo=UTC)
    remote_mtime = datetime(2026, 5, 22, 10, 0, 0, tzinfo=UTC)

    merged = _merge_config(local, remote, local_mtime, remote_mtime)
    assert merged.hotkey.combination == "alt"


def test_merge_config_preserves_deny_list_from_local_when_remote_wins() -> None:
    """Even when remote wins on mtime, deny-list fields stay local."""
    from soyle.core.cloud_sync import _merge_config

    local = _make_config_with_overrides(
        whisper={"model": "small"},
        hotkey={"combination": "alt"},
    )
    remote = _make_config_with_overrides(
        whisper={"model": "large-v3"},
        hotkey={"combination": "ctrl"},
    )
    local_mtime = datetime(2026, 5, 22, 10, 0, 0, tzinfo=UTC)
    remote_mtime = datetime(2026, 5, 22, 11, 0, 0, tzinfo=UTC)

    merged = _merge_config(local, remote, local_mtime, remote_mtime)
    assert merged.hotkey.combination == "ctrl"
    assert merged.whisper.model == "small"


def test_merge_config_preserves_cloud_sync_section_from_local() -> None:
    """The entire cloud_sync section stays local — per-device state."""
    from soyle.core.cloud_sync import _merge_config

    local = _make_config_with_overrides(
        cloud_sync={"last_synced_at": datetime(2026, 5, 22, 12, tzinfo=UTC)},
    )
    remote = _make_config_with_overrides(
        cloud_sync={"last_synced_at": datetime(2020, 1, 1, tzinfo=UTC)},
    )
    local_mtime = datetime(2026, 5, 22, 10, 0, 0, tzinfo=UTC)
    remote_mtime = datetime(2026, 5, 22, 11, 0, 0, tzinfo=UTC)

    merged = _merge_config(local, remote, local_mtime, remote_mtime)
    assert merged.cloud_sync.last_synced_at == datetime(
        2026, 5, 22, 12, tzinfo=UTC,
    )


def test_merge_config_version_stays_local() -> None:
    """version is in deny-list — local schema version is authoritative."""
    from soyle.core.cloud_sync import _merge_config

    local = _make_config_with_overrides()
    remote = _make_config_with_overrides()
    merged = _merge_config(
        local, remote,
        datetime(2026, 5, 22, 10, tzinfo=UTC),
        datetime(2026, 5, 22, 11, tzinfo=UTC),
    )
    assert merged.version == local.version
